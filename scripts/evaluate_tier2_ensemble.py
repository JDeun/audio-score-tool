"""Compare two recorded AMT candidates and their consensus on identical references.

This script never downloads private audio and never treats prediction agreement as
accuracy. It does not select a commercial default engine or compute human editing
time: those require the separately governed Tier 2 release approval process.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import time
from dataclasses import asdict
from pathlib import Path
from statistics import mean

from audio_score_tool.metrics import evaluate_midi_files, midi_notes
from audio_score_tool.tier2_experiment_record import validate_tier2_experiment_record
from audio_score_tool.tier2_benchmark import case_fingerprint, load_manifest, resolve_locator
from audio_score_tool.tier2_prediction import load_tier2_prediction_provenance
# Direct script invocation puts ./scripts on sys.path, while pytest imports
# this module as scripts.evaluate_tier2_ensemble from the repository root.
if __package__:
    from scripts.ensemble_amt_predictions import ensemble
else:
    from ensemble_amt_predictions import ensemble

_SAFE_CASE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")
_METRICS = (
    "note_precision",
    "note_recall",
    "note_f1",
    "onset_mae_ms",
    "offset_mae_ms",
    "instrument_precision",
    "instrument_recall",
    "instrument_f1",
)


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _average(values: list[float | None]) -> float | None:
    good = [float(value) for value in values if value is not None]
    return round(mean(good), 8) if good else None


def _identity(root: Path, *, corpus_version: str, case_ids: tuple[str, ...]) -> dict:
    version, engine, ids, _payload = load_tier2_prediction_provenance(root)
    if version != corpus_version or ids != case_ids:
        raise ValueError("ensemble source provenance does not match the exact corpus and case order")
    return asdict(engine)


def _midi(path: Path, *, label: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} MIDI not found: {path.name}")
    return path


def evaluate_ensemble_candidates(
    manifest_path: Path,
    *,
    corpus_root: Path,
    first_root: Path,
    second_root: Path,
    output_root: Path,
    onset_tolerance: float = 0.09,
    min_overlap: float = 0.35,
    metric_onset_tolerance: float = 0.05,
) -> dict:
    for name, value in (
        ("onset_tolerance", onset_tolerance),
        ("min_overlap", min_overlap),
        ("metric_onset_tolerance", metric_onset_tolerance),
    ):
        if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be finite and positive")
    if min_overlap > 1:
        raise ValueError("min_overlap must not exceed 1")

    corpus_version, cases = load_manifest(manifest_path)
    ids = tuple(case.id for case in cases)
    if not all(_SAFE_CASE.fullmatch(cid) and ".." not in cid for cid in ids):
        raise ValueError("ensemble case IDs must be safe path components")
    first_root = first_root.expanduser().resolve()
    second_root = second_root.expanduser().resolve()
    output_root = output_root.expanduser().resolve()
    if len({first_root, second_root, output_root}) != 3:
        raise ValueError("ensemble source and output directories must differ")
    if any(output_root == parent or output_root in parent.parents for parent in (first_root, second_root)):
        raise ValueError("ensemble output must not be an ancestor of a source directory")

    # The matrix's independent provenance verifier ensures the predictions
    # still match their recorded hashes and the entire corpus manifest bytes.
    validate_tier2_experiment_record(first_root, manifest_path=manifest_path)
    validate_tier2_experiment_record(second_root, manifest_path=manifest_path)
    first_identity = _identity(first_root, corpus_version=corpus_version, case_ids=ids)
    second_identity = _identity(second_root, corpus_version=corpus_version, case_ids=ids)
    if first_identity["id"] == second_identity["id"]:
        raise ValueError("ensemble candidates must have distinct engine IDs")

    # Validate the complete corpus *before* writing any result.
    source_midi = []
    for case in cases:
        if not case.reference_midi:
            raise ValueError(f"missing independent reference MIDI: {case.id}")
        reference = _midi(
            resolve_locator(case.reference_midi, corpus_root=corpus_root),
            label=f"{case.id}.reference",
        )
        a = _midi(first_root / f"{case.id}.mid", label=f"{case.id}.first")
        b = _midi(second_root / f"{case.id}.mid", label=f"{case.id}.second")
        source_midi.append((case.id, reference, a, b))
    output_root.mkdir(parents=True, exist_ok=True)
    consensus_dir = output_root / "consensus"
    consensus_dir.mkdir(parents=True, exist_ok=True)

    entries = []
    per_candidate: dict[str, list[dict]] = {name: [] for name in ("first", "second", "consensus")}
    empty = {name: 0 for name in per_candidate}
    for case_id, reference, a, b in source_midi:
        destination = consensus_dir / f"{case_id}.mid"
        started = time.perf_counter()
        consensus_result = ensemble(
            a, b, destination,
            onset_tolerance=onset_tolerance,
            min_overlap=min_overlap,
        )
        consensus_seconds = round(time.perf_counter() - started, 6)

        results = {}
        notes = {}
        for label, source in (("first", a), ("second", b), ("consensus", destination)):
            count = len(midi_notes(source))
            notes[label] = count
            empty[label] += count == 0
            metrics = evaluate_midi_files(
                source, reference,
                onset_tolerance_seconds=metric_onset_tolerance,
            ).as_dict()
            results[label] = {key: metrics.get(key) for key in _METRICS}
            per_candidate[label].append(results[label])
        entries.append({
            "case_id": case_id,
            "reference_sha256": _file_hash(reference),
            "prediction_sha256": {
                "first": _file_hash(a),
                "second": _file_hash(b),
                "consensus": _file_hash(destination),
            },
            "notes": notes,
            "consensus_runtime_seconds": consensus_seconds,
            "consensus_matching": consensus_result,
            "metrics": results,
        })
    summary = {}
    for label, records in per_candidate.items():
        summary[label] = {
            "case_count": len(records),
            "empty_output_cases": empty[label],
            "empty_output_rate": round(empty[label] / len(records), 8),
            **{f"mean_{metric}": _average([item[metric] for item in records])
               for metric in _METRICS},
        }

    report = {
        "schema_version": "1",
        "report_type": "tier2_ensemble_evaluation",
        "corpus_version": corpus_version,
        "manifest_sha256": _file_hash(manifest_path),
        "case_fingerprint": case_fingerprint(ids),
        "case_count": len(ids),
        "source_candidates": {"first": first_identity, "second": second_identity},
        "consensus": {
            "method": "pitch_program_onset_overlap_consensus",
            "onset_tolerance_seconds": onset_tolerance,
            "min_overlap": min_overlap,
            "metric_onset_tolerance_seconds": metric_onset_tolerance,
            "total_consensus_runtime_seconds": round(
                sum(item["consensus_runtime_seconds"] for item in entries), 6
            ),
        },
        "cases": entries,
        "summary": summary,
        "model_inference_runtime_seconds": None,
        "human_publish_metrics": None,
        "commercial_baseline_approved": False,
        "notes": (
            "Metrics use independent MIDI references, not agreement between model predictions; "
            "runtime covers only consensus fusion, not AMT inference or human correction."
        ),
    }
    target = output_root / "ensemble-evaluation.json"
    temp = target.with_suffix(".json.tmp")
    try:
        temp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate two Tier 2 AMT candidates vs consensus")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--first-root", type=Path, required=True)
    parser.add_argument("--second-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--onset-tolerance", type=float, default=0.09)
    parser.add_argument("--min-overlap", type=float, default=0.35)
    parser.add_argument("--metric-onset-tolerance", type=float, default=0.05)
    args = parser.parse_args()
    report = evaluate_ensemble_candidates(
        args.manifest,
        corpus_root=args.corpus_root,
        first_root=args.first_root,
        second_root=args.second_root,
        output_root=args.output_root,
        onset_tolerance=args.onset_tolerance,
        min_overlap=args.min_overlap,
        metric_onset_tolerance=args.metric_onset_tolerance,
    )
    print(json.dumps({
        "case_count": report["case_count"],
        "candidate_ids": [
            report["source_candidates"]["first"]["id"],
            report["source_candidates"]["second"]["id"],
        ],
        "summary": report["summary"],
        "result": str(args.output_root / "ensemble-evaluation.json"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

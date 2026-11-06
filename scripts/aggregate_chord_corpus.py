"""Offline multi-song chord benchmark aggregation with leakage and rights guards.

The manifest references only private, operator-reviewed local files. Results
contain metrics, SHA-256 and non-identifying case/dataset IDs, never source
audio, private file paths, or an unsupported claim of model quality. Independent
reference evaluation is delegated to compare_chord_playalong.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import re
from pathlib import Path
from statistics import mean
from typing import Any

if __package__:
    from scripts.compare_chord_playalong import compare_chord_predictions
else:
    from compare_chord_playalong import compare_chord_predictions

ROOT = Path(__file__).resolve().parents[1]
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_TASKS = frozenset({"chord", "chord_beat"})
_ALLOWED_STATUSES = frozenset({"annotation_import_supported", "verified_for_evaluation"})
_SPLITS = frozenset({"validation", "test"})
_METRICS = (
    "root", "majmin", "thirds", "triads", "sevenths",
    "beat_f1", "downbeat_f1", "chord_boundary_f1_mean", "no_chord_recall_mean",
)
_LIMIT = 128


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def _read_json(path: Path) -> dict:
    if not path.is_file() or path.is_symlink():
        raise ValueError("a required JSON file is missing or is a symbolic link")
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise ValueError("each JSON input must contain an object")
    return result


def _text(entry: dict, field: str) -> str:
    value = entry.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")
    return value.strip()


def _private_file(root: Path, relative: str) -> Path:
    if (not relative or "\\" in relative or "%" in relative or relative.startswith("/")
            or any(part in {"", ".", ".."} for part in relative.split("/"))):
        raise ValueError("unsafe private file locator")
    candidate = root.joinpath(*relative.split("/"))
    if not candidate.resolve().is_relative_to(root):
        raise ValueError("private source locator escapes corpus root")
    if any(item.is_symlink() for item in (candidate, *candidate.parents) if item != root):
        raise ValueError("source cannot use symbolic links")
    if not candidate.is_file() or candidate.suffix.lower() != ".json":
        raise ValueError("private source must be an existing JSON file")
    return candidate


def _finite_metric(value: Any, *, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError(f"{name} metric must be numeric or absent")
    numeric = float(value)
    if not math.isfinite(numeric) or not 0 <= numeric <= 1:
        raise ValueError(f"{name} metric must be finite and within 0..1")
    return numeric


def _metrics(report: dict, candidate: str) -> dict[str, float | None]:
    entry = report["by_model"][candidate]
    chords = entry["chords"]["mean_by_metric"]
    values = {name: chords[name] if name in chords else entry.get(name) for name in _METRICS}
    return {name: _finite_metric(value, name=name) for name, value in values.items()}


def _percentile(sorted_values: list[float], q: float) -> float:
    pos = (len(sorted_values) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] * (1.0 - (pos - lo)) + sorted_values[hi] * (pos - lo)


def _summarize(cases: list[dict], *, seed: int) -> dict:
    """Macro-average **songs**, never frames or annotation count.

    A track with multiple annotators contributes one vote. Missing optional
    beat references are excluded rather than imputed as failure/success.
    """
    stats: dict[str, dict] = {}
    for name in ("manual", "sheetsage2"):
        metrics = {}
        for metric in _METRICS:
            values = [case["metrics"][name][metric] for case in cases]
            valid = [float(v) for v in values if v is not None]
            item: dict[str, Any] = {
                "song_count": len(valid),
                "macro_mean": float(mean(valid)) if valid else None,
                "song_bootstrap_ci95": None,
            }
            if len(valid) >= 2:
                rng = random.Random(f"{seed}:{name}:{metric}")
                samples = sorted(
                    mean(rng.choice(valid) for _ in valid) for _ in range(1000)
                )
                item["song_bootstrap_ci95"] = [
                    float(_percentile(samples, 0.025)), float(_percentile(samples, 0.975)),
                ]
            metrics[metric] = item
        stats[name] = metrics
    return {
        "song_count": len(cases),
        "macro_average_unit": "song",
        "bootstrap_resamples": 1000,
        "bootstrap_seed": seed,
        "by_candidate": stats,
    }


def evaluate_corpus(
    manifest: dict, registry: dict, *,
    corpus_root: Path, manifest_sha256: str | None = None,
    registry_sha256: str | None = None, seed: int = 20261106,
) -> dict:
    """Evaluate only independently referenced, rights-reviewed private pairs."""
    root = corpus_root.expanduser().resolve()
    if not root.is_dir() or root.is_relative_to(ROOT):
        raise ValueError("corpus_root must be an existing private directory outside the repository")
    cases = manifest.get("cases")
    if (manifest.get("schema_version") != 1 or not isinstance(cases, list)
            or not 1 <= len(cases) <= _LIMIT):
        raise ValueError("manifest requires between 1 and 128 chord cases")
    entries = registry.get("datasets")
    if registry.get("schema_version") != 1 or not isinstance(entries, list):
        raise ValueError("dataset registry schema is invalid")
    sources = {e.get("id"): e for e in entries if isinstance(e, dict) and isinstance(e.get("id"), str)}
    if len(sources) != len(entries):
        raise ValueError("source dataset IDs must be distinct and valid")

    case_ids: set[str] = set()
    recording_splits: dict[str, str] = {}
    seen_fingerprints: set[str] = set()
    report_cases: list[dict] = []
    for entry in cases:
        if not isinstance(entry, dict):
            raise ValueError("chord case must be an object")
        case_id = _text(entry, "id")
        dataset_id = _text(entry, "dataset_id")
        split = _text(entry, "split")
        sha = _text(entry, "recording_sha256")
        rights = entry.get("rights_reviewed")
        license_value = _text(entry, "license").lower()
        if not _ID.fullmatch(case_id) or case_id in case_ids:
            raise ValueError("duplicate or unsafe chord case ID")
        if not _HASH.fullmatch(sha):
            raise ValueError("recording_sha256 must be lowercase hex")
        if split not in _SPLITS:
            raise ValueError("chord evaluation accepts validation/test splits, never train")
        if sha in recording_splits and recording_splits[sha] != split:
            raise ValueError("cross-split audio identity overlap detected")
        if sha in seen_fingerprints:
            raise ValueError("duplicate recording SHA-256 in chord evaluation")
        if rights is not True:
            raise ValueError("every source needs an explicit operator rights review")
        source = sources.get(dataset_id)
        if source is None or source.get("task") not in _ALLOWED_TASKS:
            raise ValueError("chord dataset is missing or wrong evaluation task")
        if source.get("status") not in _ALLOWED_STATUSES:
            raise ValueError("dataset is not registered for annotation evaluation")
        registered_license = _text(source, "license").lower()
        if (license_value != registered_license
                or any(flag in license_value for flag in ("unknown", "verify", "per_source"))):
            raise ValueError("source license is unresolved or contradicts registry")
        case_ids.add(case_id)
        seen_fingerprints.add(sha)
        recording_splits[sha] = split

        paths = {
            name: _private_file(root, _text(entry, name))
            for name in ("reference", "manual", "sheetsage2")
        }
        if len(set(paths.values())) != 3:
            raise ValueError("reference and predictions must be independent files")
        inputs = {name: _digest(path) for name, path in paths.items()}
        reference = _read_json(paths["reference"])
        manual = _read_json(paths["manual"])
        sheetsage = _read_json(paths["sheetsage2"])
        if reference.get("dataset") != dataset_id:
            raise ValueError("reference dataset does not match case registry")
        if str(reference.get("license", "")).lower() != license_value:
            raise ValueError("reference license does not match operator/registry")
        if reference.get("recording_sha256") != sha:
            raise ValueError("reference recording SHA-256 differs from the case")
        if reference.get("rights_reviewed_by_operator_only") is not True:
            raise ValueError("reference rights review attestation is missing")
        if reference.get("commercial_model_approved") is not False:
            raise ValueError("reference must not claim model commercial approval")
        score = compare_chord_predictions(
            reference, manual, sheetsage, inputs=inputs,
        )
        report_cases.append({
            "case_id": case_id,
            "dataset_id": dataset_id,
            "split": split,
            "recording_sha256": sha,
            "license": license_value,
            "duration_seconds": score["duration_seconds"],
            "independent_annotators": score["independent_annotators"],
            "input_sha256": inputs,
            "metrics": {
                "manual": _metrics(score, "manual"),
                "sheetsage2": _metrics(score, "sheetsage2"),
            },
            "inter_model_agreement_not_accuracy": score["inter_model_agreement_not_accuracy"],
            "source_rights_independently_verified": False,
            "audio_reference_alignment_independently_verified": False,
        })

    # Preserve manifest order in the cases, but use a stable sorted order for
    # confidence intervals independent of the order supplied by the caller.
    groups: dict[str, list[dict]] = {}
    for case in report_cases:
        groups.setdefault(case["dataset_id"], []).append(case)
    return {
        "schema_version": 1,
        "purpose": "evaluation_only",
        "comparison_type": "licensed_operator_supplied_independent_chord_reference",
        "case_count": len(report_cases),
        "manifest_sha256": manifest_sha256,
        "registry_sha256": registry_sha256,
        "cases": report_cases,
        "overall": _summarize(sorted(report_cases, key=lambda x: x["case_id"]), seed=seed),
        "by_dataset": {
            name: _summarize(sorted(entries, key=lambda x: x["case_id"]), seed=seed)
            for name, entries in sorted(groups.items())
        },
        "limitations": [
            "audio and reference identity provided by operator, not independently certified",
            "training/test leakage may exist in model checkpoints beyond these evaluated files",
            "multi-annotator reference scores are averaged within song before macro-aggregation",
            "no rights to redistribute third-party audio or annotations are granted by the tool",
        ],
        "source_media_included": False,
        "model_inference_performed": False,
        "commercial_model_approved": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Private multi-song chord metric aggregation")
    parser.add_argument("manifest", type=Path, help="Private case manifest JSON")
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-csv", type=Path)
    parser.add_argument("--seed", type=int, default=20261106)
    args = parser.parse_args()

    files = (args.manifest, args.registry)
    inputs = [_read_json(x) for x in files]
    output = evaluate_corpus(
        inputs[0], inputs[1], corpus_root=args.corpus_root,
        manifest_sha256=_digest(files[0]), registry_sha256=_digest(files[1]),
        seed=args.seed,
    )
    output_paths = [args.output_json] + ([args.output_csv] if args.output_csv else [])
    root = args.corpus_root.resolve()
    for path in output_paths:
        dst = path.expanduser().resolve()
        if dst.is_relative_to(ROOT) or dst == ROOT:
            raise ValueError("source-derived benchmark outputs must remain outside the repository")
        if dst in {f.resolve() for f in files}:
            raise ValueError("cannot overwrite the manifest or source registry")
        if dst in {root.joinpath(*_text(e, key).split("/")).resolve()
                   for e in inputs[0]["cases"] for key in ("reference", "manual", "sheetsage2")}:
            raise ValueError("cannot overwrite source reference or prediction")
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n",
                                encoding="utf-8")
    if args.output_csv:
        args.output_csv.parent.mkdir(parents=True, exist_ok=True)
        with args.output_csv.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["case_id", "dataset_id", "split", "candidate", *_METRICS])
            for case in output["cases"]:
                for candidate, values in case["metrics"].items():
                    writer.writerow([
                        case["case_id"], case["dataset_id"], case["split"], candidate,
                        *(values[name] for name in _METRICS),
                    ])
    print(json.dumps({"case_count": output["case_count"],
                      "datasets": sorted(output["by_dataset"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

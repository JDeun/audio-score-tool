"""Measure direct-mix AMT against all estimated Demucs stems on identical audio.

This is an engine-level experiment, not the selected-part product assembly.
Raw note multisets are scored without MIDI merging, de-duplication, reference
alignment, instrument relabelling, or choosing a favourable subset of stems.
MusicXML/PDF fidelity and source-separation SDR are NOT measured here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from importlib.metadata import version
from pathlib import Path
from statistics import mean
from typing import Any

from audio_score_tool.metrics import midi_notes
from audio_score_tool.stem_ablation import METHOD_ID, score_note_events
from audio_score_tool.tier2_benchmark import resolve_locator
from scripts import fetch_pinned_mrmt3_checkpoint as mr
from scripts import fetch_pinned_yourmt3_checkpoint as your
from scripts.prepare_cocochorales_official_sample import SAMPLE_BLOBS
from scripts.prepare_cocochorales_pairs import official_split
from scripts.score_cocochorales_tiny import _source_receipt
from scripts.separate_benchmark_stems import run_separation
from scripts.validate_tier2_dataset_pairs import validate_pairs

ROOT = Path(__file__).resolve().parents[1]
METRICS = ("onset", "onset_offset", "instrument_onset_offset")
_INFER = (
    "import random,numpy,torch;random.seed(0);numpy.random.seed(0);"
    "torch.manual_seed(0);torch.set_num_threads(2);"
    "from audio_score_tool.mt3_program_midi import main;raise SystemExit(main())"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _new_private_directory(path: Path) -> Path:
    path = path.expanduser().absolute()
    if path.exists() or path.is_symlink() or path.resolve().is_relative_to(ROOT):
        raise ValueError("Experiment work must be a new private directory outside git")
    path.mkdir(parents=True)
    return path.resolve()


def model_identity(model: str, checkpoint_root: Path) -> dict[str, Any]:
    if model not in {"mr_mt3", "yourmt3"}:
        raise ValueError("Unsupported pinned AMT model")
    source = mr if model == "mr_mt3" else your
    relative = (
        Path("mr_mt3") / mr.CHECKPOINT_NAME if model == "mr_mt3"
        else Path("yourmt3") / your.MODEL_VARIANT / "last.ckpt"
    )
    checkpoint = checkpoint_root / relative
    if (checkpoint.is_symlink() or not checkpoint.is_file()
            or sha256(checkpoint) != source.CHECKPOINT_SHA256):
        raise ValueError("AMT checkpoint bytes do not match the pinned model")
    expected = {
        "mt3-infer": "0.2.0", "torch": "2.7.1", "torchaudio": "2.7.1",
        "transformers": "4.57.6" if model == "mr_mt3" else "4.44.2",
        "demucs": "4.0.1",
    }
    actual = {name: version(name) for name in expected}
    if any(actual[key].split("+")[0] != value for key, value in expected.items()):
        raise ValueError(f"Experiment requires pinned model runtimes: {expected}; got {actual}")
    return {
        "model": model, "checkpoint_sha256": source.CHECKPOINT_SHA256,
        "checkpoint_source_revision": source.MODEL_REVISION,
        "runtime_versions": actual, "python": platform.python_version(),
        "entrypoint": "audio_score_tool.mt3_program_midi.main",
        "mr_program_preservation": model == "mr_mt3", "seed": 0,
        "torch_threads": 2, "checkpoint_auto_download": False,
    }


def infer_raw_midi(
    audio: Path, output: Path, *, model: str, checkpoint_root: Path, device: str,
) -> tuple[list, dict[str, Any]]:
    """Use the app's exact AMT bridge; a valid empty MIDI is a measured zero.

    The app's engine also converts MIDI to MusicXML. That conversion rejects
    empty stems, so invoke its unchanged raw-MIDI bridge and keep every stem,
    including zero-note predictions. This prevents successful-stem selection.
    """
    output.mkdir(parents=True, exist_ok=False)
    midi = output / "prediction.mid"
    before = sha256(audio)
    env = {
        **os.environ, "MT3_CHECKPOINT_DIR": str(checkpoint_root.resolve()),
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "HF_DATASETS_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1",
        "PYTHONHASHSEED": "0", "PYTHONIOENCODING": "utf-8",
        "OMP_NUM_THREADS": "2", "MKL_NUM_THREADS": "2",
    }
    started = time.perf_counter()
    with (output / "inference.log").open("w", encoding="utf-8") as log:
        result = subprocess.run(
            [sys.executable, "-c", _INFER, "transcribe", str(audio), "-o", str(midi),
             "-m", model, "--device", device, "--no-download"],
            env=env, stdout=log, stderr=subprocess.STDOUT, timeout=1200, check=False,
        )
    elapsed = time.perf_counter() - started
    if result.returncode != 0:
        diagnostic = (output / "inference.log").read_text(encoding="utf-8", errors="replace")[-2400:]
        raise RuntimeError(f"AMT process failed ({result.returncode}): {diagnostic}")
    if sha256(audio) != before:
        raise ValueError("Inference input changed during the experiment")
    if midi.is_symlink() or not midi.is_file():
        raise ValueError("AMT did not produce a regular MIDI file")
    notes = midi_notes(midi)
    return notes, {
        "audio_sha256": before, "prediction_midi_sha256": sha256(midi),
        "inference_seconds": round(elapsed, 6), "predicted_note_count": len(notes),
        "status": "scored", "empty_prediction": not notes,
    }


def run_experiment(
    pairs: dict, registry: dict, source_proof: dict, *, corpus_root: Path,
    work_root: Path, model: str, checkpoint_root: Path, separator: str = "htdemucs_6s",
    device: str = "cpu",
) -> dict[str, Any]:
    verified, _manifest = validate_pairs(pairs, registry, corpus_root=corpus_root)
    records = pairs["cases"]
    if any(
        row["dataset_id"] != "cocochorales" or row["recording_id"] not in SAMPLE_BLOBS
        or row["split"] != official_split(row["recording_id"])
        for row in records
    ):
        raise ValueError("This experiment supports the pinned author train examples only")
    _source_receipt(source_proof, split="train", paired=pairs)
    identity = model_identity(model, checkpoint_root)
    work = _new_private_directory(work_root)
    report: dict[str, Any] = {
        "schema_version": 1, "purpose": "same-source-mix-vs-estimated-stems-amt",
        "model_identity": identity, "device": device, "separator": separator,
        "evaluation_method": METHOD_ID,
        "source_code_revision": os.getenv("GITHUB_SHA"),
        "source_proof_sha256": hashlib.sha256(json.dumps(
            source_proof, sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest(),
        "paired_fingerprint": verified["recording_pairs_fingerprint"],
        "protocol": {
            "audio_crop": "entire original recording; no trim, shift, or alignment search",
            "stem_selection": "all separator outputs; no energy threshold or reference selection",
            "stem_combination": "raw note multiset union in seconds; no MIDI reserialization",
            "duplicate_notes_removed": False, "programs_relabelled": False,
            "failure_policy": "any failed stem makes the separated arm incomplete",
            "empty_prediction_policy": "valid empty MIDI counts as zero, never as a skipped stem",
            "same_amt_checkpoint_and_runtime_for_both_arms": True,
        },
        "cases": [], "all_samples_in_train_split": True,
        "heldout_generalization_measured": False, "source_separation_sdr_measured": False,
        "ground_truth_stem_control_measured": False, "musicxml_pdf_quality_measured": False,
        "human_editing_time_measured": False, "release_quality_approved": False,
        "commercial_default_selected": False, "model_redistribution_approved": False,
        "source_media_published": False,
    }
    for record in records:
        track = record["recording_id"]
        audio = resolve_locator(record["audio"]["locator"], corpus_root=corpus_root)
        reference = resolve_locator(record["reference_midi"]["locator"], corpus_root=corpus_root)
        reference_notes = midi_notes(reference)
        row: dict[str, Any] = {
            "track_id": track, "split": record["split"],
            "source_proof_sha256": report["source_proof_sha256"],
            "paired_fingerprint": report["paired_fingerprint"],
            "audio_sha256": record["audio"]["sha256"],
            "reference_midi_sha256": record["reference_midi"]["sha256"],
            "reference_note_count": len(reference_notes),
        }
        print(f"{model}/{track}: direct mixture", flush=True)
        try:
            notes, receipt = infer_raw_midi(
                audio, work / track / "direct", model=model,
                checkpoint_root=checkpoint_root, device=device,
            )
            row["direct_mix"] = {**receipt, "metrics": score_note_events(notes, reference_notes)}
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            row["direct_mix"] = {"status": "failed", "error": str(exc)}
        print(f"{model}/{track}: separate all stems with {separator}", flush=True)
        separated: dict[str, Any] = {"status": "failed", "stems": {}}
        row["estimated_stems"] = separated
        try:
            stems, separation = run_separation(
                audio, work / track / "separation", model=separator, device=device, seed=0,
            )
            separated["separation"] = separation
            if separation["input"]["sha256"] != row["audio_sha256"]:
                raise ValueError("Separator receipt describes a different input recording")
            all_notes = []
            for name, stem in stems.items():
                print(f"{model}/{track}: transcribe {name}", flush=True)
                try:
                    notes, receipt = infer_raw_midi(
                        stem, work / track / f"amt-{name}", model=model,
                        checkpoint_root=checkpoint_root, device=device,
                    )
                    separated["stems"][name] = receipt
                    all_notes.extend(notes)
                except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                    separated["stems"][name] = {"status": "failed", "error": str(exc)}
            if all(value["status"] == "scored" for value in separated["stems"].values()):
                separated.update({
                    "status": "scored", "metrics": score_note_events(all_notes, reference_notes),
                    "predicted_note_count": len(all_notes),
                    "inference_seconds": round(sum(
                        value["inference_seconds"] for value in separated["stems"].values()
                    ), 6),
                })
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            separated["error"] = str(exc)
        if (sha256(audio) != row["audio_sha256"]
                or sha256(reference) != row["reference_midi_sha256"]):
            raise ValueError("Original audio/reference changed after validation")
        row["both_scored"] = all(
            row[arm]["status"] == "scored" for arm in ("direct_mix", "estimated_stems")
        )
        row["stems_minus_mix_f1"] = {
            metric: round(
                separated["metrics"][metric]["f1"] - row["direct_mix"]["metrics"][metric]["f1"], 8,
            ) for metric in METRICS
        } if row["both_scored"] else None
        report["cases"].append(row)
    report["all_cases_complete"] = all(row["both_scored"] for row in report["cases"])
    return report


def aggregate_reports(reports: list[dict]) -> dict:
    """Keep every planned track; never rank only the stems that succeeded."""
    if not reports:
        raise ValueError("No stem-ablation reports")
    first = reports[0]
    cases = []
    separator_identity = None
    for report in reports:
        for field in (
            "purpose", "model_identity", "device", "separator", "protocol",
            "evaluation_method", "source_code_revision",
        ):
            if report.get(field) != first.get(field):
                raise ValueError(f"Cannot combine different ablation conditions: {field}")
        for case in report["cases"]:
            actual_complete = all(
                case[arm]["status"] == "scored" for arm in ("direct_mix", "estimated_stems")
            )
            if case["both_scored"] != actual_complete:
                raise ValueError("Case completion flag differs from observed arm status")
            separation = case["estimated_stems"].get("separation")
            if separation is not None:
                identity = separation.get("identity")
                if not isinstance(identity, dict) or not identity:
                    raise ValueError("Missing actual separator checkpoint and option identity")
                if separator_identity is not None and identity != separator_identity:
                    raise ValueError("Cannot combine different separator checkpoint or options")
                separator_identity = identity
            if actual_complete and separation is None:
                raise ValueError("Scored separated arm has no actual separation receipt")
            cases.append(case)
    if len(cases) != len(SAMPLE_BLOBS) or {r["track_id"] for r in cases} != set(SAMPLE_BLOBS):
        raise ValueError("Aggregate requires all four distinct planned author examples")
    complete = all(row["both_scored"] for row in cases)
    return {
        **{key: value for key, value in first.items() if key not in {
            "cases", "source_proof_sha256", "paired_fingerprint", "all_cases_complete",
        }},
        "cases": cases, "all_cases_complete": complete,
        "complete_paired_case_count": sum(row["both_scored"] for row in cases),
        "macro_f1": {
            arm: {metric: round(mean(row[arm]["metrics"][metric]["f1"] for row in cases), 8)
                  for metric in METRICS}
            for arm in ("direct_mix", "estimated_stems")
        } if complete else None,
        "macro_stems_minus_mix_f1": {
            metric: round(mean(row["stems_minus_mix_f1"][metric] for row in cases), 8)
            for metric in METRICS
        } if complete else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", type=Path)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--source-proof", type=Path)
    parser.add_argument("--corpus-root", type=Path)
    parser.add_argument("--work-root", type=Path)
    parser.add_argument("--checkpoint-root", type=Path)
    parser.add_argument("--model", choices=("mr_mt3", "yourmt3"))
    parser.add_argument("--separator", choices=("htdemucs", "htdemucs_6s"), default="htdemucs_6s")
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--aggregate", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink() or args.output.resolve().is_relative_to(ROOT):
        parser.error("Use a new metadata report outside the repository")
    def read(path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))
    if args.aggregate:
        report = aggregate_reports([read(path) for path in args.aggregate])
    else:
        required = ("pairs", "registry", "source_proof", "corpus_root", "work_root", "model", "checkpoint_root")
        if any(getattr(args, field) is None for field in required):
            parser.error("Provide pairs/registry/source-proof/corpus/work/model/checkpoint paths")
        report = run_experiment(
            read(args.pairs), read(args.registry), read(args.source_proof),
            corpus_root=args.corpus_root, work_root=args.work_root, model=args.model,
            checkpoint_root=args.checkpoint_root, separator=args.separator, device=args.device,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    return 0 if report["all_cases_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

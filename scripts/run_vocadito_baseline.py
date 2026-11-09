"""Private, fixed-corpus vocal AMT evaluation against BOTH human annotators.

Source: Bittner et al., vocadito v3, doi:10.5281/zenodo.5578807 (CC BY 4.0).
No five-song acceptance audio, tuning, reference pitch rounding, or model promotion.
Requires the separate pinned model environment and optional mir_eval==0.8.2.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import platform
import subprocess
import wave
import zipfile
from importlib.metadata import version
from pathlib import Path
from statistics import mean

from scripts import fetch_pinned_mrmt3_checkpoint as mr
from scripts import fetch_pinned_yourmt3_checkpoint as your
from scripts.run_cocochorales_stem_ablation import (
    _new_private_directory,
    infer_raw_midi,
    sha256,
)
from scripts.vocadito_reference import read_notes, score_annotations

SOURCE_URL = "https://zenodo.org/records/5578807"
ARCHIVE_MD5 = "dea40fd18f14d899643c4ba221b33a46"
ARCHIVE_BYTES = 58_492_257
CASE_IDS = tuple(f"vocadito_{index}" for index in range(1, 41))


def run(archive: Path, checkpoint_root: Path, output: Path, *, model: str) -> dict:
    if (archive.is_symlink() or archive.stat().st_size != ARCHIVE_BYTES
            or hashlib.md5(archive.read_bytes()).hexdigest() != ARCHIVE_MD5):
        raise ValueError("Vocadito archive does not match the original v3 checksum")
    source = mr if model == "mr_mt3" else your
    checkpoint = checkpoint_root / (
        Path("mr_mt3") / mr.CHECKPOINT_NAME if model == "mr_mt3"
        else Path("yourmt3") / your.MODEL_VARIANT / "last.ckpt"
    )
    if checkpoint.is_symlink() or sha256(checkpoint) != source.CHECKPOINT_SHA256:
        raise ValueError("Checkpoint does not match the pinned model")
    expected = {
        "mt3-infer": "0.2.0", "torch": "2.7.1", "torchaudio": "2.7.1",
        "transformers": "4.57.6" if model == "mr_mt3" else "4.44.2",
        "mir-eval": "0.8.2",
    }
    actual = {name: version(name) for name in expected}
    if actual != expected:
        raise ValueError(f"Pinned experiment runtime required: {expected}; got {actual}")
    work = _new_private_directory(output)
    report = {
        "schema_version": 1, "dataset": "vocadito-v3", "source_url": SOURCE_URL,
        "archive_sha256": sha256(archive), "archive_md5_verified": True,
        "model": model, "checkpoint_sha256": source.CHECKPOINT_SHA256,
        "model_revision": source.MODEL_REVISION, "runtime": actual,
        "python": platform.python_version(), "device": "cpu", "seed": 0,
        "torch_threads": 2, "planned_case_ids": CASE_IDS, "cases": [],
        "onset_tolerance_seconds": 0.05, "pitch_tolerance_cents": 50,
        "offset_tolerance": "max(50ms, 20% of reference duration)",
        "training_overlap": "unknown", "human_editing_time_measured": False,
        "commercial_release_quality_approved": False, "five_acceptance_songs_used": False,
    }
    with zipfile.ZipFile(archive) as package:
        for case_id in CASE_IDS:
            audio_bytes = package.read(f"Audio/{case_id}.wav")
            with wave.open(io.BytesIO(audio_bytes)) as audio:
                duration = audio.getnframes() / audio.getframerate()
            annotations = {
                name: package.read(f"Annotations/Notes/{case_id}_notes{name}.csv")
                for name in ("A1", "A2")
            }
            # Validate both references before inference and never choose the easier one.
            for raw in annotations.values():
                read_notes(raw)
            path = work / f"{case_id}.wav"
            path.write_bytes(audio_bytes)
            row = {
                "id": case_id, "audio_sha256": sha256(path), "duration_seconds": duration,
                "reference_sha256": {k: hashlib.sha256(v).hexdigest() for k, v in annotations.items()},
            }
            try:
                notes, receipt = infer_raw_midi(
                    path, work / case_id, model=model, checkpoint_root=checkpoint_root, device="cpu",
                )
                row.update(receipt)
                row["annotators"] = {name: score_annotations(notes, raw) for name, raw in annotations.items()}
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                row.update(status="failed", error_type=type(exc).__name__)
            report["cases"].append(row)
            report["all_cases_complete"] = (
                len(report["cases"]) == len(CASE_IDS)
                and all(r["status"] == "scored" for r in report["cases"])
            )
            if report["all_cases_complete"]:
                report["macro_f1"] = {
                    metric: round(mean(
                        r["annotators"][name][metric] for r in report["cases"] for name in ("A1", "A2")
                    ), 8) for metric in ("onset_f1", "onset_offset_f1")
                }
            (work / "report.json").write_text(json.dumps(report, indent=2) + "\n")
            print(f"{model}: {case_id} {row['status']} ({len(report['cases'])}/40)", flush=True)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--checkpoint-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", choices=("mr_mt3", "yourmt3"), required=True)
    args = parser.parse_args()
    return 0 if run(args.archive, args.checkpoint_root, args.output, model=args.model)["all_cases_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

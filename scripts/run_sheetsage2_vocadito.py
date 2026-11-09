"""Official pinned SheetSage2 on all 40 original vocal clips; no final-song tuning."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import random
import time
import zipfile
from importlib.metadata import version
from pathlib import Path
from statistics import mean

from scripts.sheetsage2_infer_adapter import load_native_model, normalize_native_result
from scripts.vocadito_reference import score_annotations


def run(archive: Path, snapshot: Path, output: Path):
    import numpy as np
    import soundfile as sf
    import torch

    from audio_score_tool.metrics import midi_notes

    if (archive.stat().st_size != 58_492_257 or hashlib.md5(archive.read_bytes()).hexdigest()
            != "dea40fd18f14d899643c4ba221b33a46"):
        raise ValueError("Unverified vocadito v3 archive")
    if output.exists() or output.is_symlink() or output.resolve().is_relative_to(Path(__file__).resolve().parents[1]):
        raise ValueError("Use a new private output directory outside the Git repository")
    output.mkdir(parents=True)
    random.seed(0)
    np.random.seed(0)
    torch.manual_seed(0)
    torch.set_num_threads(4)
    model = load_native_model(snapshot / "model", snapshot / "mert")
    report = {
        "schema_version": 1, "model": "sheetsage2", "dataset": "vocadito-v3",
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "runtime": {k: version(k) for k in ("torch", "torchaudio", "transformers", "numpy", "mir-eval")},
        "python": platform.python_version(), "device": "cpu", "dtype": "float32",
        "seed": 0, "threads": 4, "preset": "default", "window_seconds": 300,
        "training_overlap": "unknown", "five_acceptance_songs_used": False,
        "commercial_release_quality_approved": False, "cases": [],
    }
    with zipfile.ZipFile(archive) as package:
        for index in range(1, 41):
            case_id = f"vocadito_{index}"
            work = output / case_id
            work.mkdir()
            audio_bytes = package.read(f"Audio/{case_id}.wav")
            source = work / "source.wav"
            source.write_bytes(audio_bytes)
            references = {ann: package.read(f"Annotations/Notes/{case_id}_notes{ann}.csv") for ann in ("A1", "A2")}
            row = {"id": case_id, "audio_sha256": hashlib.sha256(audio_bytes).hexdigest(),
                   "reference_sha256": {ann: hashlib.sha256(raw).hexdigest() for ann, raw in references.items()}}
            started = time.perf_counter()
            try:
                audio, rate = sf.read(source, dtype="float32", always_2d=True)
                result = model.transcribe(audio.T, sampling_rate=rate, output_dir=work,
                                          dtype="fp32", preset="default")
                normalized = normalize_native_result(result)
                (work / "normalized.json").write_text(json.dumps(normalized, indent=2) + "\n")
                notes = midi_notes(work / "melody_vocal.mid")
                row.update(status="scored", predicted_note_count=len(notes),
                           abc_error=result.get("abc_error"),
                           annotators={ann: score_annotations(notes, raw) for ann, raw in references.items()})
            except (ValueError, RuntimeError, OSError) as exc:
                row.update(status="failed", error_type=type(exc).__name__)
                (work / "failure.txt").write_text(str(exc))
            row["inference_seconds"] = time.perf_counter() - started
            report["cases"].append(row)
            report["all_cases_complete"] = len(report["cases"]) == 40 and all(c["status"] == "scored" for c in report["cases"])
            if report["all_cases_complete"]:
                report["macro_f1"] = {metric: round(mean(c["annotators"][ann][metric] for c in report["cases"] for ann in ("A1", "A2")), 8) for metric in ("onset_f1", "onset_offset_f1")}
            (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
            print(f"SheetSage2 {case_id}: {row['status']} ({index}/40)", flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    return 0 if run(args.archive, args.snapshot, args.output)["all_cases_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

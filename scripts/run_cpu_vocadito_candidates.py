"""CPU-only, credential-free vocadito research; note AMT and F0 are separate tasks.

Reuse the existing original-Hz/A1+A2 note scorer, never an oracle octave shift.
Only metadata reports may leave the runner; audio, predictions and weights stay private.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import platform
import random
import time
import warnings
import zipfile
from importlib.metadata import distributions, version
from pathlib import Path
from statistics import mean

import numpy as np

CANDIDATES = ("mr_mt3", "yourmt3", "basic_pitch", "yin", "pyin", "torchcrepe_tiny", "torchcrepe_full")
CASE_IDS = tuple(f"vocadito_{i}" for i in range(1, 41))
ARCHIVE_MD5 = "dea40fd18f14d899643c4ba221b33a46"
ARCHIVE_BYTES = 58_492_257
NOTE_MODELS = frozenset(CANDIDATES[:3])
ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def verified_asset(path: Path, blob: str, size: int) -> dict:
    """Check upstream Git blob identity BEFORE deserializing public model weights."""
    if path.is_symlink() or not path.is_file() or path.stat().st_size != size:
        raise ValueError("Pinned model asset size/path mismatch")
    h = hashlib.sha1(f"blob {size}\0".encode())
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    if h.hexdigest() != blob:
        raise ValueError("Pinned upstream model asset Git blob mismatch")
    return {"git_blob": blob, "sha256": digest(path), "bytes": size}


def validate_f0(raw: bytes) -> tuple[np.ndarray, np.ndarray]:
    values = np.loadtxt(io.BytesIO(raw), delimiter=",", ndmin=2)
    if (values.shape[1] != 2 or len(values) < 2 or not np.isfinite(values).all()
            or np.any(values[:, 0] < 0) or np.any(np.diff(values[:, 0]) <= 0)
            or np.any(values[:, 1] < 0)):
        raise ValueError("Invalid original vocadito F0 annotation")
    return values[:, 0], values[:, 1]


def f0_metrics(raw: bytes, times: np.ndarray, hz: np.ndarray) -> dict:
    """Full annotated timeline, including silence and unobserved frames; no shifting."""
    import mir_eval.melody as melody

    ref_time, ref_hz = validate_f0(raw)
    if (times.ndim != 1 or times.shape != hz.shape or len(times) < 2
            or not np.isfinite(times).all() or not np.isfinite(hz).all()
            or np.any(times < 0) or np.any(np.diff(times) <= 0) or np.any(hz < 0)):
        raise ValueError("Invalid predicted F0 timeline")
    # Nearest-frame resampling does not invent intermediate pitches across octave jumps.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Estimated melody has no voiced frames.*",
                                category=UserWarning, module="mir_eval.melody")
        scores = melody.evaluate(ref_time, ref_hz, times, hz, cent_tolerance=50, kind="nearest")
    rv, rc, ev, ec = melody.to_cent_voicing(ref_time, ref_hz, times, hz, kind="nearest")
    diff = ec - rc
    octave = ((rv > 0) & (ev > 0) & (np.abs(diff) >= 1150)
              & (np.abs(diff - 1200 * np.round(diff / 1200)) < 50))
    return {
        **{key: float(value) for key, value in scores.items()},
        "octave_errors_per_reference_voiced_frame": float(octave.sum() / max(1, (rv > 0).sum())),
        "reference_voiced_frames": int((rv > 0).sum()),
        "reference_voiced_outside_55_880_hz": int(((ref_hz > 0) & ((ref_hz < 55) | (ref_hz > 880))).sum()),
        "predicted_voiced_fraction": float((ev > 0).mean()),
    }


def complete_macro(cases: list[dict], task: str) -> dict | None:
    """Never emit a successful-subset score as the planned forty-recording result."""
    if (len(cases) != 40 or {row["id"] for row in cases} != set(CASE_IDS)
            or any(row.get("status") != "scored" for row in cases)):
        return None
    if task == "note_amt":
        return {metric: round(mean(row["annotators"][ann][metric]
                                  for row in cases for ann in ("A1", "A2")), 8)
                for metric in ("onset_f1", "onset_offset_f1")}
    keys = ("Raw Pitch Accuracy", "Raw Chroma Accuracy", "Overall Accuracy",
            "Voicing Recall", "Voicing False Alarm", "octave_errors_per_reference_voiced_frame",
            "predicted_voiced_fraction")
    return {key: round(mean(row["f0_metrics"][key] for row in cases), 8) for key in keys}


def prepare(candidate: str, work: Path):
    """Return predictor and explicit identity. No credentials or GPU are consulted."""
    if candidate in {"mr_mt3", "yourmt3"}:
        from scripts import fetch_pinned_mrmt3_checkpoint as mr
        from scripts import fetch_pinned_yourmt3_checkpoint as your
        from scripts.run_cocochorales_stem_ablation import infer_raw_midi

        expected_transformers = "4.57.6" if candidate == "mr_mt3" else "4.44.2"
        for package, expected in {"torch": "2.7.1", "torchaudio": "2.7.1",
                                  "mt3-infer": "0.2.0", "transformers": expected_transformers}.items():
            if version(package).split("+")[0] != expected:
                raise ValueError(f"Runtime version mismatch: {package}")
        source = mr if candidate == "mr_mt3" else your
        weights = source.fetch_pinned_checkpoint(work / "checkpoints", cache_dir=work / "hub")

        def predict(audio, output):
            notes, receipt = infer_raw_midi(audio, output, model=candidate,
                                           checkpoint_root=work / "checkpoints", device="cpu")
            return notes, receipt

        return predict, {"weights": weights, "model_lifecycle": "fresh process per recording"}

    if candidate == "basic_pitch":
        import basic_pitch
        import onnxruntime as ort
        from basic_pitch.inference import Model
        from basic_pitch.inference import predict as bp_predict

        from audio_score_tool.metrics import midi_notes

        if version("basic-pitch") != "0.4.0" or version("onnxruntime") != "1.20.1":
            raise ValueError("Pinned Basic Pitch/ONNX runtime required")
        asset = Path(basic_pitch.__file__).parent / "saved_models/icassp_2022/nmp.onnx"
        proof = verified_asset(asset, "c30e5f9438e798604b7177aa26be1fe64482f767", 230444)
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        # Preserve upstream Model.predict and all upstream note decoding unchanged.
        model = Model.__new__(Model)
        model.model_type = Model.MODEL_TYPES.ONNX
        model.model = ort.InferenceSession(str(asset), sess_options=options,
                                           providers=["CPUExecutionProvider"])

        def predict(audio, output):
            output.mkdir()
            raw, midi, _events = bp_predict(audio, model, onset_threshold=0.5,
                                            frame_threshold=0.3, minimum_note_length=127.7,
                                            multiple_pitch_bends=False, melodia_trick=True)
            target = output / "prediction.mid"
            midi.write(str(target))
            np.savez_compressed(output / "raw.npz", **raw)
            notes = midi_notes(target)
            return notes, {"prediction_midi_sha256": digest(target),
                           "raw_output_sha256": digest(output / "raw.npz"),
                           "predicted_note_count": len(notes), "empty_prediction": not notes}

        return predict, {"weights": proof, "weights_source_revision": "fa5997af0a8210982619003269994a1be25eddf3",
                         "backend": "onnx-cpu", "intra_threads": 2, "inter_threads": 1,
                         "thresholds": {"onset": 0.5, "frame": 0.3, "minimum_note_ms": 127.7},
                         "pitch_bends_scored": False, "instrument_identity_predicted": False,
                         "model_lifecycle": "resident model; preparation time reported separately"}

    identity = {"fmin": 55, "fmax": 880, "frame_hop_seconds": 0.01,
                "note_segmentation": False, "reference_boundary_used_for_prediction": False}
    if candidate.startswith("torchcrepe_"):
        import torch
        import torchcrepe

        torch.manual_seed(0)
        torch.set_num_threads(2)
        capacity = candidate.split("_")[1]
        blob, size = (("18d881163b9f7ddf8daf0709c75cf204f5570da5", 1962363) if capacity == "tiny"
                      else ("ddd8a2eb75a1eadb073e5f5bb5bee45d4d8d1323", 88991291))
        identity.update(weights=verified_asset(Path(torchcrepe.__file__).parent / "assets" / f"{capacity}.pth", blob, size),
                        weights_source_revision="19e2ec3d494c0797a5ff2a11408ec5838fba6681",
                        decoder="viterbi", periodicity_threshold=0.21, silence_db=-60,
                        model_lifecycle="lazy load on first recording; retained afterwards")
    elif candidate == "yin":
        identity.update(frame_hop_seconds=256 / 11025, implementation="existing vocal_pitch_track unchanged")

    def predict(audio, output):
        import librosa

        output.mkdir()
        if candidate == "yin":
            from audio_score_tool.vocal_evidence import vocal_pitch_track

            times, midi_pitch = vocal_pitch_track(audio, ffmpeg_cmd="ffmpeg")
            hz = np.where(np.isfinite(midi_pitch), 440 * 2 ** ((midi_pitch - 69) / 12), 0.0)
        else:
            samples, sr = librosa.load(str(audio), sr=16000, mono=True)
            if candidate == "pyin":
                hz, voiced, _prob = librosa.pyin(samples, sr=sr, fmin=55, fmax=880,
                                                frame_length=2048, hop_length=160, center=True)
                hz = np.where(voiced & np.isfinite(hz), hz, 0.0)
            else:
                tensor = torch.tensor(samples, dtype=torch.float32).unsqueeze(0)
                with torch.inference_mode():
                    pitch, periodicity = torchcrepe.predict(
                        tensor, sr, 160, 55, 880, capacity, decoder=torchcrepe.decode.viterbi,
                        return_periodicity=True, batch_size=128, device="cpu", pad=True,
                    )
                    periodicity = torchcrepe.threshold.Silence(-60)(periodicity, tensor, sr, 160)
                pitch, periodicity = pitch[0].cpu().numpy(), periodicity[0].cpu().numpy()
                hz = np.where((periodicity >= 0.21) & np.isfinite(pitch), pitch, 0.0)
            times = np.arange(len(hz), dtype=float) * 0.01
        np.savez_compressed(output / "prediction.npz", times=times, hz=hz)
        return (times, hz), {"prediction_f0_sha256": digest(output / "prediction.npz")}

    return predict, identity


def run(candidate: str, archive: Path, work: Path, report_path: Path) -> dict:
    if (candidate not in CANDIDATES or work.exists() or work.is_symlink()
            or work.resolve().is_relative_to(ROOT) or report_path.exists() or report_path.is_symlink()
            or archive.is_symlink() or archive.stat().st_size != ARCHIVE_BYTES
            or hashlib.md5(archive.read_bytes()).hexdigest() != ARCHIVE_MD5):
        raise ValueError("Invalid candidate, private workspace or pinned vocadito v3 archive")
    if version("mir-eval") != "0.8.2":
        raise ValueError("Original scorer requires mir_eval 0.8.2")
    if os.getenv("HF_TOKEN") or os.getenv("HUGGING_FACE_HUB_TOKEN"):
        raise ValueError("Credential-free experiment refuses supplied model tokens")
    work.mkdir(parents=True, mode=0o700)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    random.seed(0)
    np.random.seed(0)
    task = "note_amt" if candidate in NOTE_MODELS else "f0_tracking"
    report = {"schema_version": 1, "candidate": candidate, "task": task,
              "dataset": "vocadito-v3", "archive_sha256": digest(archive),
              "source_revision": os.getenv("GITHUB_SHA"), "planned_case_ids": list(CASE_IDS),
              "platform": platform.platform(), "python": platform.python_version(),
              "machine": platform.machine(), "cpu_count": os.cpu_count(),
              "runtime": {d.metadata["Name"]: d.version for d in distributions() if d.metadata["Name"]},
              "script_sha256": digest(Path(__file__)),
              "note_scorer_sha256": digest(ROOT / "scripts/vocadito_reference.py"),
              "device": "cpu", "seed": 0, "cases": [], "all_cases_complete": False,
              "macro": None, "quality_approved": False, "training_overlap": "unknown",
              "policy": {"original_hz": True, "onset_seconds": 0.05, "pitch_cents": 50,
                         "offset": "max(50ms, reference duration * 0.2)", "octave_folding": False,
                         "source_media_published": False, "model_weights_published": False,
                         "timing_is_controlled_speed_ranking": False}}

    def save():
        temporary = report_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        temporary.replace(report_path)

    save()
    started = time.perf_counter()
    try:
        with (work / "prepare.log").open("w") as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            predictor, identity = prepare(candidate, work)
        report["identity"] = identity
        report["preparation_seconds"] = round(time.perf_counter() - started, 6)
    except Exception as exc:
        report.update(status="preparation_failed", error_type=type(exc).__name__)
        save()
        raise
    with zipfile.ZipFile(archive) as package:
        for case in CASE_IDS:
            audio_bytes = package.read(f"Audio/{case}.wav")
            note_refs = {a: package.read(f"Annotations/Notes/{case}_notes{a}.csv") for a in ("A1", "A2")}
            f0_ref = package.read(f"Annotations/F0/{case}_f0.csv")
            from scripts.vocadito_reference import read_notes, score_annotations

            for value in note_refs.values():
                read_notes(value)
            validate_f0(f0_ref)
            audio = work / f"{case}.wav"
            audio.write_bytes(audio_bytes)
            row = {"id": case, "audio_sha256": digest(audio),
                   "reference_sha256": {a: hashlib.sha256(value).hexdigest() for a, value in note_refs.items()},
                   "f0_reference_sha256": hashlib.sha256(f0_ref).hexdigest()}
            started = time.perf_counter()
            try:
                with (work / f"{case}.log").open("w") as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                    prediction, receipt = predictor(audio, work / case)
                row.update(receipt, elapsed_seconds=round(time.perf_counter() - started, 6))
                if task == "note_amt":
                    row["annotators"] = {a: score_annotations(prediction, value) for a, value in note_refs.items()}
                else:
                    row["f0_metrics"] = f0_metrics(f0_ref, *prediction)
                if digest(audio) != row["audio_sha256"]:
                    raise ValueError("Input audio changed during inference")
                row["status"] = "scored"
            except Exception as exc:
                # No exception message/audio/notes are published to public artifacts.
                row.update(status="failed", error_type=type(exc).__name__)
            report["cases"].append(row)
            report["macro"] = complete_macro(report["cases"], task)
            report["all_cases_complete"] = report["macro"] is not None
            save()
            print(f"{candidate}: {case}: {row['status']}", flush=True)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", choices=CANDIDATES, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    return 0 if run(args.candidate, args.archive, args.work, args.report)["all_cases_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

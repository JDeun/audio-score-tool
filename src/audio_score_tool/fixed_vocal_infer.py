"""Pinned CPU Demucs/YourMT3 runtime for the fixed vocal recipe."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import random
import sys
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from audio_score_tool.fixed_lead_recipe import (
    BEAT_RUNTIME,
    DEMUCS_SHA256,
    SEPARATOR_RUNTIME,
    YOUR_CHECKPOINT,
    YOUR_RUNTIME,
    YOUR_SHA256,
    require_runtime,
    verify_separator,
    verify_weight,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["separate", "vocal", "pitch", "pitch-preflight", "beat"])
    parser.add_argument("audio", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args()
    pitch_stage = args.stage in {"pitch", "pitch-preflight"}
    expected = (BEAT_RUNTIME if args.stage == "beat" else
                {**YOUR_RUNTIME, "torchcrepe": "0.0.24", "resampy": "0.4.3", "librosa": "0.11.0"}
                if pitch_stage else {**YOUR_RUNTIME, **(SEPARATOR_RUNTIME if args.stage == "separate" else {})})
    actual = require_runtime(expected)
    checkpoint = args.snapshot / "checkpoints" / YOUR_CHECKPOINT
    if pitch_stage:
        import torchcrepe
        weight = Path(torchcrepe.__file__).parent / "assets" / "tiny.pth"
        verify_weight(weight, "d4993eea36ed1a0ad9ac549c740dae5265b049ce72004f00c2f59e01c0be8432")
        if args.stage == "pitch-preflight":
            return 0
    elif args.stage == "beat":
        weight = args.snapshot / "beat-this/final0.ckpt"
        verify_weight(weight, "8c328b45f59d8dd3dff219253ff6a8d6482be57d0133a29140e2febbf8eb8331")
    elif args.stage == "separate":
        verify_separator(args.snapshot / "demucs")
    else:
        verify_weight(checkpoint, YOUR_SHA256)
    os.environ.update(MT3_CHECKPOINT_DIR=str((args.snapshot / "checkpoints").resolve()),
                      HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_DATASETS_OFFLINE="1",
                      HF_HUB_DISABLE_TELEMETRY="1")
    import numpy as np
    import torch
    random.seed(0)
    np.random.seed(0)
    torch.manual_seed(0)
    threads = 4 if args.stage == "separate" else 2
    torch.set_num_threads(threads)
    if args.stage == "beat":
        import beat_this
        import madmom
        import soundfile as sf
        from beat_this.inference import Audio2Frames
        from beat_this.model.postprocessor import Postprocessor
        from madmom import models

        def tree_digest():
            root = Path(beat_this.__file__).parent
            h = hashlib.sha256()
            for path in sorted(root.rglob("*.py")):
                h.update(str(path.relative_to(root)).encode() + b"\0")
                h.update(path.read_bytes())
            return h.hexdigest()

        expected_tree = "3f8d310da05e5b26fb455645dfcad5b835570b23a511003e351ce0f33b45fd04"
        if tree_digest() != expected_tree:
            raise ValueError("BeatThis source tree mismatch")
        def madmom_digest():
            root = Path(madmom.__file__).parent
            h = hashlib.sha256()
            for path in sorted(p for p in root.rglob("*") if p.is_file() and p.suffix in {".py", ".so"}):
                h.update(str(path.relative_to(root)).encode() + b"\0")
                h.update(path.read_bytes())
            return h.hexdigest()

        expected_madmom = "43edae0d91e5813ccea423d9fe0693f315514e3139616c9d1d37f05e9dc4a995"
        if (madmom_digest() != expected_madmom or models.DOWNBEATS_BLSTM or models.BEATS_BLSTM
                or list(Path(madmom.__file__).parent.rglob("*.pkl"))):
            raise ValueError("Unexpected madmom code or pretrained weights")
        adapter_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        source_sha = hashlib.sha256(args.audio.read_bytes()).hexdigest()
        samples, rate = sf.read(args.audio, dtype="float32")
        model = Audio2Frames(checkpoint_path=str(weight), device="cpu")
        beat_logits, downbeat_logits = model(samples, rate)
        if (beat_logits.ndim != 1 or downbeat_logits.shape != beat_logits.shape
                or not torch.isfinite(beat_logits).all() or not torch.isfinite(downbeat_logits).all()):
            raise ValueError("Invalid BeatThis logits")
        beats, downbeats = Postprocessor(type="dbn")(beat_logits, downbeat_logits)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        beat_logits, downbeat_logits = beat_logits.cpu().numpy(), downbeat_logits.cpu().numpy()
        np.savez_compressed(args.output, beats=np.asarray(beats), downbeats=np.asarray(downbeats),
                            beat_logits=beat_logits, downbeat_logits=downbeat_logits)
        verify_weight(weight, "8c328b45f59d8dd3dff219253ff6a8d6482be57d0133a29140e2febbf8eb8331")
        if (tree_digest() != expected_tree or madmom_digest() != expected_madmom
                or hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != adapter_sha
                or hashlib.sha256(args.audio.read_bytes()).hexdigest() != source_sha):
            raise ValueError("BeatThis source or audio changed during inference")
        args.output.with_suffix(".runtime.json").write_text(json.dumps({
            "provider": "beat-this", "model": "final0", "source_sha256": source_sha,
            "prediction_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
            "beat_logits_sha256": hashlib.sha256(beat_logits.tobytes()).hexdigest(),
            "downbeat_logits_sha256": hashlib.sha256(downbeat_logits.tobytes()).hexdigest(),
            "checkpoint_sha256": "8c328b45f59d8dd3dff219253ff6a8d6482be57d0133a29140e2febbf8eb8331",
            "source_revision": "b95c8ab0c58c2d9fcfd40508ae8dffbc05ac4f5c", "source_tree_sha256": expected_tree,
            "runtime": actual, "python": platform.python_version(),
            "adapter_sha256": adapter_sha,
            "madmom_source_revision": "27f032e8947204902c675e5e341a3faf5dc86dae",
            "madmom_tree_sha256": expected_madmom, "madmom_pretrained_weights": False,
            "device": "cpu", "threads": 2, "seed": 0, "dbn": True,
            "dbn_parameters": {"fps": 50, "beats_per_bar": [3, 4], "min_bpm": 55.0,
                               "max_bpm": 215.0, "transition_lambda": 100},
        }, indent=2) + "\n")
        return 0
    if args.stage == "pitch":
        import librosa

        source_sha = hashlib.sha256(args.audio.read_bytes()).hexdigest()
        samples, sr = librosa.load(str(args.audio), sr=16000, mono=True)
        tensor = torch.tensor(samples, dtype=torch.float32).unsqueeze(0)
        os.environ["TORCH_FORCE_WEIGHTS_ONLY_LOAD"] = "1"
        with torch.inference_mode():
            pitch, periodicity = torchcrepe.predict(
                tensor, sr, 160, 55, 880, "tiny", decoder=torchcrepe.decode.viterbi,
                return_periodicity=True, batch_size=128, device="cpu", pad=True)
            periodicity = torchcrepe.threshold.Silence(-60)(periodicity, tensor, sr, 160)
        pitch, periodicity = pitch[0].cpu().numpy(), periodicity[0].cpu().numpy()
        hz = np.where((periodicity >= .21) & np.isfinite(pitch), pitch, 0.0)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(args.output, times=np.arange(len(hz), dtype=float) * .01, hz=hz)
        verify_weight(weight, "d4993eea36ed1a0ad9ac549c740dae5265b049ce72004f00c2f59e01c0be8432")
        if hashlib.sha256(args.audio.read_bytes()).hexdigest() != source_sha:
            raise ValueError("Vocal source changed during pitch inference")
        args.output.with_suffix(".runtime.json").write_text(json.dumps({
            "provider": "torchcrepe", "model": "tiny", "source_sha256": source_sha,
            "prediction_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
            "checkpoint_sha256": "d4993eea36ed1a0ad9ac549c740dae5265b049ce72004f00c2f59e01c0be8432",
            "runtime": actual, "python": platform.python_version(),
            "adapter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "weights_source_revision": "19e2ec3d494c0797a5ff2a11408ec5838fba6681",
            "device": "cpu", "threads": 2, "seed": 0,
            "sample_rate": 16000, "hop": 160, "fmin": 55, "fmax": 880,
            "decoder": "viterbi", "batch_size": 128, "pad": True,
            "periodicity_threshold": .21, "silence_db": -60,
        }, indent=2) + "\n")
        return 0
    if args.stage == "separate":
        from fractions import Fraction

        from demucs.htdemucs import HTDemucs
        from demucs.separate import main as separate

        os.environ["TORCH_FORCE_WEIGHTS_ONLY_LOAD"] = "1"
        # The SHA-verified legacy checkpoint still needs these types under weights_only=True.
        with torch.serialization.safe_globals([
            HTDemucs, Fraction, np.dtype, (np._core.multiarray.scalar, "numpy.core.multiarray.scalar"),
            np.dtypes.Float64DType, np.dtypes.Float32DType,
        ]):
            separate(["-n", "htdemucs", "--repo", str(args.snapshot / "demucs"),
                      "--two-stems", "vocals", "--shifts", "0", "--float32", "--clip-mode", "rescale",
                      "-d", "cpu", "-o", str(args.output), str(args.audio)])
        verify_separator(args.snapshot / "demucs")
        receipt = args.output / "runtime.json"
    else:
        from mt3_infer import transcribe
        from mt3_infer.utils.audio import load_audio

        audio, rate = load_audio(str(args.audio))
        midi = transcribe(audio, model="yourmt3", sr=rate, device="cpu", auto_download=False)
        verify_weight(checkpoint, YOUR_SHA256)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        midi.save(str(args.output))
        receipt = args.output.with_suffix(".runtime.json")
    receipt.write_text(json.dumps({
        "checkpoint_sha256": DEMUCS_SHA256 if args.stage == "separate" else YOUR_SHA256,
        "runtime": actual, "python": platform.python_version(),
        "seed": 0, "threads": threads, "device": "cpu", "auto_download": False,
        "adapter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

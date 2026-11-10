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
    parser.add_argument("stage", choices=["separate", "vocal"])
    parser.add_argument("audio", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args()
    expected = {**YOUR_RUNTIME, **(SEPARATOR_RUNTIME if args.stage == "separate" else {})}
    actual = require_runtime(expected)
    checkpoint = args.snapshot / "checkpoints" / YOUR_CHECKPOINT
    if args.stage == "separate":
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

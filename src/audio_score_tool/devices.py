from __future__ import annotations

import platform
import shutil
import subprocess

from .models import DevicePlan


def _nvidia_available() -> bool:
    executable = shutil.which("nvidia-smi")
    if not executable:
        return False
    try:
        proc = subprocess.run(
            [executable, "-L"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
            check=False,
        )
        return proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _apple_silicon() -> bool:
    return platform.system() == "Darwin" and platform.machine().lower() in {"arm64", "aarch64"}


def detect_device_plan() -> DevicePlan:
    """Choose the best available backend without making torch a hard dependency.

    Detection first asks torch when it is installed in the application environment.
    If model tools live in isolated environments, it falls back to system-level
    NVIDIA detection and Apple Silicon architecture detection.

    MuScriptor supports CUDA/MPS/CPU. WhisperX currently documents CUDA or CPU,
    so Apple Silicon uses MPS for MuScriptor and CPU for WhisperX/Demucs.
    """
    torch_cuda = False
    torch_mps = False
    try:
        import torch

        torch_cuda = bool(torch.cuda.is_available())
        mps = getattr(torch.backends, "mps", None)
        torch_mps = bool(mps is not None and mps.is_available())
    except ImportError:
        pass

    if torch_cuda or _nvidia_available():
        return DevicePlan(
            torch_device="cuda",
            muscriptor_device="cuda",
            demucs_device="cuda",
            whisperx_device="cuda",
            whisperx_compute_type="float16",
        )

    if torch_mps or _apple_silicon():
        return DevicePlan(
            torch_device="mps",
            muscriptor_device="mps",
            demucs_device="cpu",
            whisperx_device="cpu",
            whisperx_compute_type="int8",
        )

    return DevicePlan(
        torch_device="cpu",
        muscriptor_device="cpu",
        demucs_device="cpu",
        whisperx_device="cpu",
        whisperx_compute_type="int8",
    )

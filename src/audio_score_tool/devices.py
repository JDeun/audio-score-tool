from __future__ import annotations

from .models import DevicePlan


def detect_device_plan() -> DevicePlan:
    """Choose the best available backend without making torch a hard dependency.

    MuScriptor supports CUDA/MPS/CPU.
    WhisperX currently documents CUDA or CPU; macOS therefore falls back to CPU.
    Demucs is kept on CUDA/CPU for portability.
    """
    try:
        import torch
    except ImportError:
        return DevicePlan(
            torch_device="cpu",
            muscriptor_device="cpu",
            demucs_device="cpu",
            whisperx_device="cpu",
            whisperx_compute_type="int8",
        )

    if torch.cuda.is_available():
        return DevicePlan(
            torch_device="cuda",
            muscriptor_device="cuda",
            demucs_device="cuda",
            whisperx_device="cuda",
            whisperx_compute_type="float16",
        )

    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available():
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

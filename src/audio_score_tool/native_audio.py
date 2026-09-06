from __future__ import annotations

from pathlib import Path

from .native_model import NativeModelConfig, require_torch


def load_log_mel(path: Path, config: NativeModelConfig, device: str = "cpu"):
    torch, _nn = require_torch()
    try:
        import torchaudio
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("AudioScore Native requires torchaudio. Install the `native` extra.") from exc

    waveform, sample_rate = torchaudio.load(str(path))
    if waveform.shape[0] > 1:
        waveform = waveform.mean(dim=0, keepdim=True)
    if sample_rate != config.sample_rate:
        waveform = torchaudio.functional.resample(waveform, sample_rate, config.sample_rate)
    transform = torchaudio.transforms.MelSpectrogram(
        sample_rate=config.sample_rate,
        n_fft=config.n_fft,
        hop_length=config.hop_length,
        n_mels=config.n_mels,
        power=2.0,
    )
    mel = transform(waveform)
    mel = torch.log1p(mel)
    mean = mel.mean(dim=(-2, -1), keepdim=True)
    std = mel.std(dim=(-2, -1), keepdim=True).clamp_min(1e-5)
    mel = (mel - mean) / std
    return mel.to(device)

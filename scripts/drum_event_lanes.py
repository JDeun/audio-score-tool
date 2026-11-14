"""Frozen coarse-role drum lane ablation; no reference or metadata inputs.

This is a two-role DSP mechanism study, not a nine-class drum recognizer.
The 10 ms refractory arms retain a 10 ms hop and 64 ms analysis window.
Strict local maxima cannot occupy adjacent frames, so a 10 ms refractory
setting is not a promise of 10 ms onset resolution.
"""
from __future__ import annotations

import numpy as np

from scripts import gmd_audio_range_probe as historical

ARMS = ("global85", "global10", "independent85", "independent10")
SETTINGS = {
    "sample_rate": 16000, "nfft": 1024, "hop": 160,
    "low_band_hz": [45, 210], "high_band_hz": [400, 6000],
    "normalization_percentile": 99.0, "minimum_scale": 1e-9,
    "floor_minimum": .14, "floor_median_weight": .45,
    "floor_percentile": 85, "global_kick_ratio": 1.25,
    "refractory_seconds": [0.085, 0.01],
    "threshold_scope": "same global combined floor for every arm and lane",
    "timestamp": "(frame_start_for_positive_difference + nfft/2) / sr",
    "reference_time_shift_seconds": 0.0,
    "velocity_estimated": False,
}


def novelty_features(samples, sr=16000):
    """Rebuild the historical features exactly, without a classifier or truth."""
    samples = np.asarray(samples)
    nfft, hop = 1024, 160
    if (sr != 16000 or samples.ndim != 1 or samples.dtype.kind not in "fiu"
            or len(samples) < nfft + hop or not np.isfinite(samples).all()):
        raise ValueError("finite mono 16 kHz waveform required")
    window = np.hanning(nfft)
    starts = np.arange(0, len(samples) - nfft, hop)
    frames = np.stack([samples[p:p+nfft] for p in starts])
    mag = np.abs(np.fft.rfft(frames * window, axis=1))
    freq = np.fft.rfftfreq(nfft, 1 / sr)
    novelty = np.maximum(0, mag[1:] - mag[:-1])
    low = novelty[:, (freq >= 45) & (freq <= 210)].sum(axis=1)
    high = novelty[:, (freq >= 400) & (freq <= 6000)].sum(axis=1)
    scaled = []
    for arr in (low, high):
        cap = max(float(np.percentile(arr, 99.0)), 1e-9)
        scaled.append(np.clip(arr / cap, 0, 1))
    low, high = scaled
    combined = np.maximum(low, high)
    floor = max(0.14, float(np.median(combined) + .45 *
                            (np.percentile(combined, 85) - np.median(combined))))
    times = (starts[1:] + nfft / 2) / sr
    return times, low, high, floor


def _select_peaks(times, low, high, floor, *, independent, refractory):
    """Only lane coupling and the exclusion interval vary between arms."""
    combined = np.maximum(low, high)
    lanes = (("kick", low), ("backbeat", high)) if independent else ((None, combined),)
    result = []
    for lane_role, values in lanes:
        peaks = []
        for i in range(1, len(values) - 1):
            if (values[i] < floor or values[i] < values[i - 1]
                    or values[i] <= values[i + 1]):
                continue
            role = lane_role or ("kick" if low[i] >= 1.25 * high[i] else "backbeat")
            event = (float(times[i]), role, float(values[i]))
            if peaks and event[0] - peaks[-1][0] < refractory:
                if values[i] > peaks[-1][2]:
                    peaks[-1] = event
                continue
            peaks.append(event)
        result.extend(peaks)
    return sorted(result, key=lambda row: (row[0], row[1]))


def detect_all_arms(samples, sr=16000):
    """Return chronological (seconds, role, normalized strength) predictions.

    Strength is relative spectral novelty, not probability or MIDI velocity.
    Every arm receives the same waveform and global threshold. No timing shift,
    quantization, reference class, recording identity, tempo or meter is used.
    """
    times, low, high, floor = novelty_features(samples, sr)
    baseline = [(float(time), role, float(strength))
                for time, role, strength in historical.detect_audio_roles(samples, sr)]
    rebuilt = _select_peaks(times, low, high, floor, independent=False, refractory=.085)
    if baseline != rebuilt:
        raise ValueError("historical global85 parity failed before comparison")
    return {
        "global85": baseline,
        "global10": _select_peaks(times, low, high, floor, independent=False, refractory=.01),
        "independent85": _select_peaks(times, low, high, floor, independent=True, refractory=.085),
        "independent10": _select_peaks(times, low, high, floor, independent=True, refractory=.01),
    }

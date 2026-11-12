"""Fixed waveform descriptors for source-boundary observability research.

Reference MIDI conditions a spectral measurement; it is never an inferred pitch
or a detected release. A complete Hann window must lie inside each requested
time interval. No padding, clipping, silence threshold, or offset fitting occurs.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from numbers import Integral, Real

import numpy as np

SAMPLE_RATE = 44100
FRAME_SAMPLES = 2048
HOP_SAMPLES = 441
CHUNK_FRAMES = 256
BAND_HZ = (80.0, 8000.0)
HARMONICS = 8
CENTS_RADIUS = 50.0
WINDOW = np.hanning(FRAME_SAMPLES)
WINDOW.setflags(write=False)


def _readonly(values):
    values.setflags(write=False)
    return values


def _periodograms(frames):
    """One-sided powers whose full-band sum obeys windowed Parseval energy."""
    transformed = np.fft.rfft(frames * WINDOW, axis=1)
    powers = transformed.real ** 2 + transformed.imag ** 2
    powers[:, 1:-1] *= 2.0  # DC and the even-length Nyquist bin occur only once.
    powers /= FRAME_SAMPLES * float(np.sum(WINDOW ** 2))
    return powers


@dataclass(frozen=True, eq=False)
class PitchFeatures:
    """Private per-frame measurements; NaN denotes an undefined silent ratio."""

    midi: int
    target_band_energy: np.ndarray
    target_fraction: np.ndarray
    target_bin_count: int
    harmonic_count: int


@dataclass(frozen=True, eq=False)
class FeatureBank:
    """Immutable frame geometry/powers plus a lazily populated pitch cache.

    Starts are 0, 441, 882, ... samples, and each end is start + 2048.
    Supports are half-open sample intervals, reported in seconds. A frequency
    bin belongs to a target if its center is in any declared harmonic band.
    """

    sample_rate: int
    sample_count: int
    centers: np.ndarray
    start_supports: np.ndarray
    end_supports: np.ndarray
    total_band_energy: np.ndarray
    _frequencies: np.ndarray = field(repr=False)
    _powers: np.ndarray = field(repr=False)
    _pitch_cache: dict[int, PitchFeatures] = field(default_factory=dict, repr=False)

    @property
    def duration_s(self) -> float:
        return self.sample_count / self.sample_rate

    def for_pitch(self, midi: int) -> PitchFeatures:
        """Union eight harmonic bands, each at least one FFT bin in radius.

        The bounds are the outer hull of true +/-50 cents and +/-one bin.
        Centers above 8000 Hz are excluded. Remaining bands are intersected
        with analysis-bin centers in 80..8000 Hz. Bins are never counted twice;
        this fixed descriptor does not claim to contain all Hann leakage.
        """
        if not isinstance(midi, Integral) or isinstance(midi, (bool, np.bool_)) or not 0 <= midi <= 127:
            raise ValueError('integral MIDI in 0..127 required')
        midi = int(midi)
        if midi not in self._pitch_cache:
            fundamental = 440.0 * 2.0 ** ((midi - 69) / 12.0)
            ratio = 2.0 ** (CENTS_RADIUS / 1200.0)
            bin_width = self.sample_rate / FRAME_SAMPLES
            selected = np.zeros(len(self._frequencies), dtype=bool)
            count = 0
            for harmonic in range(1, HARMONICS + 1):
                center = harmonic * fundamental
                if center > BAND_HZ[1]:
                    continue
                count += 1
                low = min(center / ratio, center - bin_width)
                high = max(center * ratio, center + bin_width)
                selected |= (self._frequencies >= low) & (self._frequencies <= high)
            energy = self._powers[:, selected].sum(axis=1)
            fraction = np.full(len(energy), np.nan)
            np.divide(energy, self.total_band_energy, out=fraction,
                      where=self.total_band_energy > 0)
            self._pitch_cache[midi] = PitchFeatures(
                midi, _readonly(energy), _readonly(fraction), int(selected.sum()), count)
        return self._pitch_cache[midi]


def extract_features(samples, sr: int, *, chunk_frames: int = CHUNK_FRAMES) -> FeatureBank:
    """Extract fixed 44.1 kHz mono descriptors with bounded temporary FFT memory.

    Samples must be normalized PCM values in [-1, 1]. Short positive recordings
    yield an empty bank. Only the 80..8000 Hz periodograms are retained, and the
    input is neither changed nor retained. chunk_frames changes resources only.
    """
    values = np.asarray(samples, dtype=np.float64)
    if (values.ndim != 1 or not len(values) or not np.isfinite(values).all()
            or np.any(np.abs(values) > 1)
            or not isinstance(sr, Integral) or isinstance(sr, (bool, np.bool_))
            or sr != SAMPLE_RATE):
        raise ValueError('nonempty finite normalized mono PCM at 44100 Hz required')
    if (not isinstance(chunk_frames, Integral) or isinstance(chunk_frames, (bool, np.bool_))
            or not 1 <= chunk_frames <= 1024):
        raise ValueError('FFT chunk must contain 1..1024 frames')
    count = max(0, 1 + (len(values) - FRAME_SAMPLES) // HOP_SAMPLES)
    starts = np.arange(count, dtype=np.int64) * HOP_SAMPLES
    frequencies = np.fft.rfftfreq(FRAME_SAMPLES, 1 / SAMPLE_RATE)
    selected = (frequencies >= BAND_HZ[0]) & (frequencies <= BAND_HZ[1])
    powers = np.empty((count, int(selected.sum())), dtype=np.float64)
    offsets = np.arange(FRAME_SAMPLES)
    for left in range(0, count, int(chunk_frames)):
        right = min(count, left + int(chunk_frames))
        frames = values[starts[left:right, None] + offsets]
        powers[left:right] = _periodograms(frames)[:, selected]
    return FeatureBank(
        SAMPLE_RATE, len(values), _readonly((starts + FRAME_SAMPLES / 2) / SAMPLE_RATE),
        _readonly(starts / SAMPLE_RATE), _readonly((starts + FRAME_SAMPLES) / SAMPLE_RATE),
        _readonly(powers.sum(axis=1)), _readonly(frequencies[selected]), _readonly(powers))


def _dbfs(power):
    return 10 * math.log10(power) if power > 0 else None


def summarize_window(bank: FeatureBank, midi: int | None, start: float, end: float) -> dict:
    """Summarize whole frames within a fully observed requested interval.

    full_coverage/audio_interval_supported describe audio availability, not a
    claim that FFT frames cover every endpoint. A short in-audio window can have
    full_coverage=True and available=False. Out-of-audio windows are not clipped.
    Means are in linear power; dB follows averaging. target_fraction is sum of
    target powers / sum of total powers, never the mean of per-frame ratios.
    MIDI None requests only broadband measurements (for source rest intervals).
    """
    if not isinstance(bank, FeatureBank):
        raise ValueError('FeatureBank required')
    if (any(not isinstance(value, Real) or isinstance(value, (bool, np.bool_))
            or not math.isfinite(value) for value in (start, end)) or end <= start):
        raise ValueError('positive finite time interval required')
    pitch = bank.for_pitch(midi) if midi is not None else None
    full = bool(0 <= start < end <= bank.duration_s)
    result = dict(
        frame_count=0, available=False, reason=None, full_coverage=full,
        audio_interval_supported=full,
        target_bin_count=pitch.target_bin_count if pitch is not None else None,
        harmonic_count=pitch.harmonic_count if pitch is not None else None,
        mean_target_band_power=None, mean_total_band_power=None,
        target_band_dbfs=None, total_band_dbfs=None, target_fraction=None,
        zero_target_frames=None, zero_total_frames=None,
        first_frame_start_offset_s=None, last_frame_end_offset_s=None,
    )
    if not full:
        result['reason'] = 'window_outside_audio'
        return result
    selected = np.flatnonzero((bank.start_supports >= start) & (bank.end_supports <= end))
    if not len(selected):
        result['reason'] = 'no_complete_frame'
        return result
    total = bank.total_band_energy[selected]
    mean_total = float(total.mean())
    result.update(
        frame_count=len(selected), available=True,
        mean_total_band_power=mean_total, total_band_dbfs=_dbfs(mean_total),
        zero_total_frames=int(np.count_nonzero(total == 0)),
        first_frame_start_offset_s=float(bank.start_supports[selected[0]] - start),
        last_frame_end_offset_s=float(bank.end_supports[selected[-1]] - start),
    )
    if pitch is not None:
        if not pitch.target_bin_count:
            result.update(available=False, reason='target_pitch_has_no_analysis_bins')
            return result
        target = pitch.target_band_energy[selected]
        mean_target = float(target.mean())
        result.update(mean_target_band_power=mean_target, target_band_dbfs=_dbfs(mean_target),
                      target_fraction=float(target.sum() / total.sum()) if mean_total > 0 else None,
                      zero_target_frames=int(np.count_nonzero(target == 0)))
    return result


def synthetic_controls() -> dict:
    """Report fixed signal controls without source recordings or event arrays."""
    time = np.arange(int(.6 * SAMPLE_RATE)) / SAMPLE_RATE
    split = .3
    tone = .25 * np.sin(2 * np.pi * 440 * time)
    signals = {
        'hard_release': np.where(time < split, tone, 0.0),
        'same_pitch_sustain': tone,
        'quiet_nonzero_tail': np.where(time < split, tone, .05 * tone),
        'detuned_two_semitones': .25 * np.sin(2 * np.pi * 440 * 2 ** (2 / 12) * time),
        'seeded_noise': np.random.default_rng(0).normal(0, .02, len(time)),
    }
    cases = {}
    for name, signal in signals.items():
        bank = extract_features(signal, SAMPLE_RATE)
        before = summarize_window(bank, 69, split - .1, split - .02)
        after = summarize_window(bank, 69, split + .02, split + .1)
        cases[name] = {'before': before, 'after': after,
                       'target_delta_db': (after['target_band_dbfs'] - before['target_band_dbfs']
                                           if after['target_band_dbfs'] is not None
                                           and before['target_band_dbfs'] is not None else None)}
    sustain = cases['same_pitch_sustain']
    tail = cases['quiet_nonzero_tail']
    hard = cases['hard_release']
    checks = {
        'all_side_intervals_observed': all(row[side]['available'] for row in cases.values()
                                          for side in ('before', 'after')),
        'hard_release_has_zero_post_energy': hard['after']['mean_total_band_power'] == 0,
        'zero_has_no_fabricated_db_or_fraction': hard['after']['target_band_dbfs'] is None
                                               and hard['after']['target_fraction'] is None,
        'sustain_has_nonzero_post_energy': sustain['after']['mean_target_band_power'] > 0,
        'sustain_delta_within_point01_db': abs(sustain['target_delta_db']) < .01,
        'quiet_tail_remains_nonzero': 0 < tail['after']['mean_target_band_power']
                                       < tail['before']['mean_target_band_power'],
        'detuning_reduces_conditioned_fraction': cases['detuned_two_semitones']['after']['target_fraction']
                                                < sustain['after']['target_fraction'],
        'noise_is_not_mislabeled_silence': cases['seeded_noise']['after']['mean_total_band_power'] > 0,
    }
    return {'status': 'passed' if all(checks.values()) else 'failed', 'checks': checks,
            'cases': cases, 'source_audio_used': False, 'estimated_note_or_release': False}

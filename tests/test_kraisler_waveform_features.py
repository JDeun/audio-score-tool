"""Independent synthetic contracts for fixed boundary spectral measurements."""
import json
import math

import numpy as np
import pytest

from scripts.kraisler_waveform_features import (
    FRAME_SAMPLES,
    HOP_SAMPLES,
    SAMPLE_RATE,
    WINDOW,
    _periodograms,
    extract_features,
    summarize_window,
    synthetic_controls,
)


def tone(frequency=440.0, amplitude=.25, duration=.6):
    time = np.arange(int(duration * SAMPLE_RATE)) / SAMPLE_RATE
    return amplitude * np.sin(2 * np.pi * frequency * time)


def test_parseval_normalization_for_dc_nyquist_and_random_samples():
    rng = np.random.default_rng(103)
    frames = np.vstack([np.full(FRAME_SAMPLES, .4),
                        .4 * (-1.) ** np.arange(FRAME_SAMPLES),
                        rng.uniform(-.4, .4, FRAME_SAMPLES)])
    measured = _periodograms(frames).sum(axis=1)
    # Time-domain expectation checks one-sided multiplicity and FFT scaling.
    expected = ((frames * WINDOW) ** 2).sum(axis=1) / (WINDOW ** 2).sum()
    np.testing.assert_allclose(measured, expected, rtol=1e-14, atol=1e-16)
    np.testing.assert_allclose(measured[:2], [.16, .16], rtol=1e-14)


def test_chunking_changes_no_energy_or_frame_geometry_and_input_is_untouched():
    original = tone() + tone(873.2, .07)
    before = original.copy()
    one = extract_features(original, SAMPLE_RATE, chunk_frames=1)
    many = extract_features(original, SAMPLE_RATE, chunk_frames=37)
    np.testing.assert_array_equal(original, before)
    for name in ('centers', 'start_supports', 'end_supports', 'total_band_energy'):
        np.testing.assert_array_equal(getattr(one, name), getattr(many, name))
        assert not getattr(one, name).flags.writeable
    np.testing.assert_array_equal(one.for_pitch(69).target_band_energy,
                                  many.for_pitch(69).target_band_energy)
    assert one.for_pitch(69) is one.for_pitch(np.int64(69))
    assert one.start_supports[0] == 0
    assert one.start_supports[1] == HOP_SAMPLES / SAMPLE_RATE
    assert one.centers[0] == FRAME_SAMPLES / (2 * SAMPLE_RATE)
    assert one.end_supports[-1] <= one.duration_s


def test_positive_short_audio_has_no_padded_frame():
    bank = extract_features(np.zeros(FRAME_SAMPLES - 1), SAMPLE_RATE)
    assert len(bank.centers) == 0
    result = summarize_window(bank, 69, 0, bank.duration_s)
    assert result['full_coverage'] and not result['available']
    assert result['reason'] == 'no_complete_frame'
    assert result['mean_total_band_power'] is None


def test_full_frame_support_inclusive_edges_and_one_sample_exclusions():
    bank = extract_features(tone(), SAMPLE_RATE)
    left, right = bank.start_supports[10], bank.end_supports[10]
    result = summarize_window(bank, 69, left, right)
    assert result['frame_count'] == 1 and result['available']
    assert result['first_frame_start_offset_s'] == 0
    assert result['last_frame_end_offset_s'] == right - left
    assert summarize_window(bank, 69, left + 1 / SAMPLE_RATE, right)['frame_count'] == 0
    assert summarize_window(bank, 69, left, right - 1 / SAMPLE_RATE)['frame_count'] == 0


def test_twenty_ms_guard_cannot_include_a_frame_crossing_the_boundary():
    samples = tone()
    boundary = .303
    samples[int(boundary * SAMPLE_RATE):] = 0
    bank = extract_features(samples, SAMPLE_RATE)
    left = summarize_window(bank, 69, boundary - .1, boundary - .02)
    right = summarize_window(bank, 69, boundary + .02, boundary + .1)
    assert 3 <= left['frame_count'] <= 4 and 3 <= right['frame_count'] <= 4
    assert left['mean_target_band_power'] > 0
    assert right['mean_total_band_power'] == 0
    # A center-only rule admits a frame whose support crosses the boundary.
    nearest = int(np.argmin(abs(bank.centers - (boundary + .02))))
    assert bank.centers[nearest] >= boundary + .02
    assert bank.start_supports[nearest] < boundary < bank.end_supports[nearest]


def test_out_of_audio_window_is_unavailable_without_partial_clipping():
    bank = extract_features(tone(), SAMPLE_RATE)
    for left, right in ((-.01, .1), (.5, bank.duration_s + .001)):
        result = summarize_window(bank, 69, left, right)
        assert not result['available'] and not result['full_coverage']
        assert result['reason'] == 'window_outside_audio'
        assert result['frame_count'] == 0 and result['target_band_dbfs'] is None


def test_zero_power_is_explicit_without_log_floor_or_fabricated_fraction():
    bank = extract_features(np.zeros(SAMPLE_RATE // 2), SAMPLE_RATE)
    result = summarize_window(bank, 69, .1, .2)
    assert result['available']
    assert result['mean_target_band_power'] == result['mean_total_band_power'] == 0
    assert result['target_band_dbfs'] is result['total_band_dbfs'] is result['target_fraction'] is None
    assert result['zero_total_frames'] == result['zero_target_frames'] == result['frame_count']
    json.dumps(result, allow_nan=False)


def test_amplitude_scaling_covariance_and_fraction_invariance():
    samples = tone() + tone(710.3, .1)
    full = summarize_window(extract_features(samples, SAMPLE_RATE), 69, .2, .28)
    half = summarize_window(extract_features(samples / 2, SAMPLE_RATE), 69, .2, .28)
    for name in ('target', 'total'):
        assert half[f'mean_{name}_band_power'] == pytest.approx(full[f'mean_{name}_band_power'] / 4)
        assert half[f'{name}_band_dbfs'] - full[f'{name}_band_dbfs'] == pytest.approx(20 * math.log10(.5))
    assert half['target_fraction'] == pytest.approx(full['target_fraction'], abs=1e-14)


def test_fraction_is_ratio_of_summed_powers_not_average_of_ratios():
    samples = tone(amplitude=.4)
    samples[:SAMPLE_RATE // 4] = tone(710.3, .025, .25)
    bank = extract_features(samples, SAMPLE_RATE)
    selected = (bank.start_supports >= .1) & (bank.end_supports <= .4)
    pitch = bank.for_pitch(69)
    result = summarize_window(bank, 69, .1, .4)
    expected = pitch.target_band_energy[selected].sum() / bank.total_band_energy[selected].sum()
    assert result['target_fraction'] == expected
    assert abs(result['target_fraction'] - pitch.target_fraction[selected].mean()) > .1


def test_overlapping_harmonic_bands_are_union_not_multiply_counted():
    # For low MIDI, neighboring centers are closer than two one-bin radii.
    bank = extract_features(tone(82.4), SAMPLE_RATE)
    pitch = bank.for_pitch(24)
    fundamental = 440 * 2 ** ((24 - 69) / 12)
    frequencies = np.fft.rfftfreq(FRAME_SAMPLES, 1 / SAMPLE_RATE)
    frequencies = frequencies[(frequencies >= 80) & (frequencies <= 8000)]
    width = SAMPLE_RATE / FRAME_SAMPLES
    bins = [set(np.flatnonzero((frequencies >= min(h * fundamental / 2 ** (50 / 1200),
                                                   h * fundamental - width))
                              & (frequencies <= max(h * fundamental * 2 ** (50 / 1200),
                                                    h * fundamental + width))))
            for h in range(1, 9)]
    assert len(set().union(*bins)) < sum(map(len, bins))
    assert pitch.target_bin_count == len(set().union(*bins))
    assert np.all(pitch.target_band_energy <= bank.total_band_energy + 1e-16)


def test_no_target_harmonic_in_analysis_band_and_broadband_only_rest_summary():
    bank = extract_features(tone(), SAMPLE_RATE)
    missing = summarize_window(bank, 127, .1, .2)
    assert not missing['available'] and missing['reason'] == 'target_pitch_has_no_analysis_bins'
    assert missing['mean_target_band_power'] is None and missing['mean_total_band_power'] > 0
    rest = summarize_window(bank, None, .1, .2)
    assert rest['available'] and rest['mean_total_band_power'] > 0
    assert rest['mean_target_band_power'] is rest['target_fraction'] is None


@pytest.mark.parametrize('samples,sr', [([], SAMPLE_RATE), ([[0.]], SAMPLE_RATE),
                                       ([np.nan], SAMPLE_RATE), ([np.inf], SAMPLE_RATE),
                                       ([32767], SAMPLE_RATE), ([0.], 22050), ([0.], True)])
def test_invalid_waveforms_are_rejected(samples, sr):
    with pytest.raises(ValueError):
        extract_features(samples, sr)


@pytest.mark.parametrize('midi', [-1, 128, 69.0, True, None, '69'])
def test_invalid_pitch_is_rejected(midi):
    with pytest.raises(ValueError):
        extract_features(tone(), SAMPLE_RATE).for_pitch(midi)


@pytest.mark.parametrize('start,end', [(0, 0), (.2, .1), (0, np.inf), (np.nan, 1), (True, 2)])
def test_invalid_intervals_are_rejected(start, end):
    with pytest.raises(ValueError):
        summarize_window(extract_features(tone(), SAMPLE_RATE), 69, start, end)


@pytest.mark.parametrize('chunk', [0, -1, 1025, 1.5, True])
def test_invalid_chunks_are_rejected(chunk):
    with pytest.raises(ValueError):
        extract_features(tone(), SAMPLE_RATE, chunk_frames=chunk)


def test_standalone_synthetic_controls_pass_and_are_json_safe():
    report = synthetic_controls()
    assert report['status'] == 'passed' and all(report['checks'].values())
    assert not report['source_audio_used'] and not report['estimated_note_or_release']
    assert set(report['cases']) == {'hard_release', 'same_pitch_sustain', 'quiet_nonzero_tail',
                                   'detuned_two_semitones', 'seeded_noise'}
    tail = report['cases']['quiet_nonzero_tail']
    assert tail['target_delta_db'] == pytest.approx(20 * math.log10(.05), abs=.01)
    json.dumps(report, allow_nan=False)

import itertools
import math

import numpy as np
import pytest

from scripts.dsp_note_probe import DT, FRAME, HOP, MIN_SECONDS, Note
from scripts.note_state_hmm import (
    ARMS,
    ATTACK,
    PAPER_DT,
    PITCHES,
    SETTINGS,
    SILENT,
    STABLE,
    UNVOICED_VOICED_MASS,
    centered_rms,
    decode_state_path,
    infer_note_states,
    notes_from_state_path,
    observation_log_weights,
    rms_silence_path,
    transition_probabilities,
)


def hz(pitch):
    return 440 * 2 ** ((np.asarray(pitch) - 69) / 12)


def state(pitch, phase=STABLE):
    return int(round((pitch - 33) * 3)) * 3 + phase


def dense_decode(frequency, grid):
    """Intentionally dense reference recurrence independent of the sparse decoder."""
    transition = transition_probabilities(grid)
    with np.errstate(divide='ignore'):
        log_transition = np.log(transition)
    initial = np.zeros(3 * len(grid))
    initial[ATTACK::3] = initial[SILENT::3] = .5 / len(grid)
    with np.errstate(divide='ignore'):
        score = np.log(initial) + observation_log_weights(frequency[0], grid)
    back = []
    for observation in frequency[1:]:
        candidates = score[:, None] + log_transition
        predecessors = candidates.argmax(axis=0)
        back.append(predecessors)
        score = candidates[predecessors, np.arange(len(score))]
        score += observation_log_weights(observation, grid)
    path = [int(score.argmax())]
    for predecessors in reversed(back):
        path.append(int(predecessors[path[-1]]))
    return np.asarray(path[::-1]), float(score.max())


def path_weight(path, frequency, grid):
    transition = transition_probabilities(grid)
    first = path[0]
    if first % 3 == STABLE:
        return -np.inf
    score = math.log(.5 / len(grid))
    for i, (node, observation) in enumerate(zip(path, frequency)):
        score += observation_log_weights(observation, grid)[node]
        if i:
            probability = transition[path[i - 1], node]
            if probability == 0:
                return -np.inf
            score += math.log(probability)
    return score


def test_frozen_grid_and_duration_rescaled_self_transitions():
    assert len(PITCHES) == 145
    assert PITCHES[0] == 33 and PITCHES[-1] == 81
    np.testing.assert_allclose(np.diff(PITCHES), 1 / 3)
    assert not PITCHES.flags.writeable
    transition = transition_probabilities()
    expected = np.array([.9, .99, .9999]) ** (DT / PAPER_DT)
    np.testing.assert_allclose(np.diag(transition).reshape(-1, 3), np.tile(expected, (145, 1)))
    np.testing.assert_allclose(SETTINGS['self_probabilities'], expected)
    paper_transition = transition_probabilities([60., 61.], dt=PAPER_DT)
    np.testing.assert_allclose(np.diag(paper_transition), [.9, .99, .9999] * 2)


def test_transition_rows_and_phase_structure_are_exact():
    transition = transition_probabilities()
    np.testing.assert_allclose(transition.sum(axis=1), 1., rtol=0, atol=3e-16)
    assert np.all(transition >= 0)
    for pitch_index in (0, 30, 144):
        a, s, u = np.arange(3) + pitch_index * 3
        assert np.flatnonzero(transition[a]).tolist() == [a, s]
        assert np.flatnonzero(transition[s]).tolist() == [s, u]
        destinations = np.flatnonzero(transition[u])
        assert all(node == u or node % 3 == ATTACK for node in destinations)


def test_jump_constraints_and_exp_kernel_are_source_row_normalized():
    transition = transition_probabilities()
    exit_probability = 1 - .9999 ** (DT / PAPER_DT)
    for source in (0, 72, 144):
        jumps = transition[source * 3 + SILENT, ATTACK::3]
        distance = np.abs(PITCHES - PITCHES[source])
        allowed = ((distance < 1e-10) | (distance >= 2 / 3 - 1e-10)) & (distance <= 13 + 1e-10)
        weights = np.zeros(len(PITCHES))
        weights[allowed] = np.exp(-distance[allowed] / 2)
        weights /= weights.sum()
        np.testing.assert_allclose(jumps, exit_probability * weights)
        assert jumps[source] > 0
        for neighbor in (source - 1, source + 1):
            if 0 <= neighbor < len(PITCHES):
                assert jumps[neighbor] == 0
    assert transition[2, 0] != transition[72 * 3 + SILENT, 72 * 3]


@pytest.mark.parametrize('pitch', [33., 33.25, 57., 69., 80.75, 81.])
def test_positive_observation_emission_mass_and_gaussian_ratio(pitch):
    values = np.exp(observation_log_weights(hz(pitch)))
    assert values.sum() == pytest.approx(1.)
    assert values[SILENT::3].sum() == pytest.approx(.5)
    assert (values[ATTACK::3].sum() + values[STABLE::3].sum()) == pytest.approx(.5)
    np.testing.assert_allclose(values[SILENT::3], .5 / len(PITCHES))
    index = int(np.argmin(np.abs(PITCHES - pitch)))
    delta = pitch - PITCHES[index]
    expected_ratio = ((.9 / 5) * np.exp(-.5 * (delta / 5)**2 + .5 * (delta / .9)**2))**.1
    assert values[index * 3] / values[index * 3 + 1] == pytest.approx(expected_ratio)


def test_unvoiced_emission_is_uniform_with_explicit_tiny_voiced_mass():
    weights = np.exp(observation_log_weights(0.))
    np.testing.assert_allclose(weights[ATTACK::3], UNVOICED_VOICED_MASS / (2 * 145))
    np.testing.assert_allclose(weights[STABLE::3], UNVOICED_VOICED_MASS / (2 * 145))
    assert weights[SILENT::3].sum() == pytest.approx(1 - UNVOICED_VOICED_MASS)
    assert weights.sum() == pytest.approx(1.)


@pytest.mark.parametrize('frequency', [
    [0., 0., 0., 0.],
    hz([60., 60., 60., 60.]),
    np.r_[hz([60., 61.]), 0., hz(62.)],
])
def test_sparse_viterbi_matches_dense_and_exhaustive_small_grid(frequency):
    grid = np.array([60., 61., 62.])
    sparse = decode_state_path(frequency, pitches=grid)
    dense, score = dense_decode(frequency, grid)
    np.testing.assert_array_equal(sparse, dense)
    # Enumerate every path, including impossible transitions and Stable initial states.
    all_scores = [path_weight(path, frequency, grid)
                  for path in itertools.product(range(9), repeat=len(frequency))]
    assert path_weight(sparse, frequency, grid) == pytest.approx(max(all_scores), abs=1e-12)
    assert score == pytest.approx(max(all_scores), abs=1e-12)


def test_sparse_viterbi_matches_dense_on_longer_mixed_synthetic_contour():
    grid = np.array([60., 61., 62., 73.])
    frequency = np.r_[hz(np.full(30, 60.)), np.zeros(4), hz(np.full(40, 62.)),
                      np.zeros(3), hz(np.full(20, 73.))]
    sparse = decode_state_path(frequency, pitches=grid)
    dense, _ = dense_decode(frequency, grid)
    np.testing.assert_array_equal(sparse, dense)
    transition = transition_probabilities(grid)
    assert np.all(transition[sparse[:-1], sparse[1:]] > 0)


def test_exact_silent_ties_choose_smallest_state_id():
    np.testing.assert_array_equal(decode_state_path(np.zeros(40)), np.full(40, SILENT))
    assert decode_state_path([0.], pitches=[50., 60., 70.]).tolist() == [SILENT]


def test_empty_and_silent_contours_have_no_notes():
    result = infer_note_states([], 0., rms=[])
    assert result['arms'] == dict.fromkeys(ARMS, [])
    assert result['phase_path'].dtype == np.int16
    assert result['phase_path'].size == 0
    assert infer_note_states(np.zeros(101), 1.)['arms'][ARMS[0]] == []


@pytest.mark.parametrize('pitch', [33., 57., 69., 81.])
def test_constant_valid_pitch_and_last_padding_frame(pitch):
    result = infer_note_states(np.full(101, hz(pitch)), 1.)
    assert result['arms'][ARMS[0]] == [Note(int(pitch), 0., 1.)]
    assert result['phase_path'].dtype == np.int16
    assert np.all((result['phase_path'] >= 0) & (result['phase_path'] < 435))


def test_vibrato_and_same_pitch_repeated_notes():
    vibrato = 69 + .25 * np.sin(2 * np.pi * 5 * np.arange(201) * DT)
    assert infer_note_states(hz(vibrato), 2.)['arms'][ARMS[0]] == [Note(69, 0., 2.)]
    repeated = np.r_[np.full(100, 440.), np.zeros(20), np.full(100, 440.)]
    assert infer_note_states(repeated, 2.2)['arms'][ARMS[0]] == [
        Note(69, 0., 1.), Note(69, 1.2, 2.2)]


def test_state_readout_joins_attack_stable_and_preserves_same_pitch_silent_boundary():
    path = np.r_[np.full(3, state(69, ATTACK)), np.full(7, state(69)),
                 [state(69, SILENT)], np.full(4, state(69, ATTACK)), np.full(6, state(69))]
    notes, diagnostics = notes_from_state_path(path, np.full(len(path), 440.), .21)
    assert notes == [Note(69, 0., .1), Note(69, .11, .21)]
    assert diagnostics['raw_voiced_decoded_silent_frames'] == 1
    assert diagnostics['segments_before_filter'] == 2


def test_state_readout_uses_raw_median_and_does_not_apply_raw_voicing_split():
    path = np.full(20, state(60), dtype=np.int16)
    observations = np.r_[hz(np.full(9, 69.6)), [0., 0.], hz(np.full(9, 69.6))]
    notes, diagnostics = notes_from_state_path(path, observations, .2)
    assert notes == [Note(70, 0., .2)]
    assert diagnostics['decoded_voiced_over_raw_unvoiced_frames'] == 2
    assert diagnostics['emitted_notes_with_raw_unvoiced_frames'] == 1
    assert diagnostics['emitted_raw_unvoiced_frames'] == 2


def test_minimum_duration_boundary_and_missing_voiced_support_are_counted():
    for frames, expected in [(7, []), (8, [Note(69, 0., MIN_SECONDS)])]:
        notes, diagnostics = notes_from_state_path(np.full(frames, state(69)),
                                                  np.full(frames, 440.), frames * DT)
        assert notes == expected
        assert diagnostics['short_segments_discarded'] == int(frames == 7)
    notes, diagnostics = notes_from_state_path(np.full(20, state(69)), np.zeros(20), .2)
    assert notes == []
    assert diagnostics['segments_without_raw_voiced_support'] == 1
    notes, diagnostics = notes_from_state_path(
        np.r_[np.full(8, state(69, SILENT)), state(69, ATTACK)], np.full(9, 440.), .08)
    assert notes == []
    assert diagnostics['zero_duration_segments'] == 1


@pytest.mark.parametrize('sample_count', [1, 159, 160, 161, 2048, 3231])
def test_centered_rms_matches_direct_windows_and_frame_clock(sample_count):
    audio = np.random.default_rng(1).normal(0, .1, sample_count)
    original = audio.copy()
    padded = np.pad(audio, (FRAME // 2, FRAME // 2))
    expected = [np.sqrt(np.mean(padded[i:i + FRAME]**2))
                for i in range(0, sample_count + 1, HOP)]
    measured = centered_rms(audio)
    assert measured.shape == (sample_count // HOP + 1,)
    np.testing.assert_allclose(measured, expected, rtol=1e-14)
    np.testing.assert_array_equal(audio, original)


def test_rms_local_summation_preserves_quiet_tail_after_loud_audio():
    audio = np.r_[np.ones(4096), np.full(4096, 1e-10)]
    measured = centered_rms(audio)
    assert measured[-10] == pytest.approx(1e-10, rel=1e-12, abs=0)


def test_rms_rise_removes_i_minus_two_and_preserves_original_path():
    path = np.full(40, state(69), dtype=np.int16)
    energy = np.r_[np.ones(20), np.full(20, 2.)]
    original_path, original_energy = path.copy(), energy.copy()
    edited, diagnostics = rms_silence_path(path, energy)
    # i=19 and i=20 satisfy the rise condition, so j=17 and j=18 become Silent.
    assert np.flatnonzero(edited % 3 == SILENT).tolist() == [17, 18]
    assert diagnostics == {'rms_rise_candidates': 2, 'rms_frames_changed_to_silent': 2,
                           'rms_candidates_already_silent': 0}
    notes, _ = notes_from_state_path(edited, np.full(40, 440.), .4)
    assert notes == [Note(69, 0., .17), Note(69, .19, .4)]
    np.testing.assert_array_equal(path, original_path)
    np.testing.assert_array_equal(energy, original_energy)
    assert np.all((edited % 3 == SILENT) | (path % 3 != SILENT))


def test_rms_early_rise_can_delete_short_fragment_and_counts_existing_silence():
    path = np.full(20, state(69), dtype=np.int16)
    path[2] = state(69, SILENT)
    energy = np.r_[np.ones(5), np.full(15, 2.)]
    edited, diagnostics = rms_silence_path(path, energy)
    assert np.flatnonzero(edited % 3 == SILENT).tolist() == [2, 3]
    assert diagnostics['rms_rise_candidates'] == 2
    assert diagnostics['rms_frames_changed_to_silent'] == 1
    assert diagnostics['rms_candidates_already_silent'] == 1
    notes, filtered = notes_from_state_path(edited, np.full(20, 440.), .2)
    assert notes == [Note(69, .04, .2)]
    assert filtered['segments_before_filter'] == 2
    assert filtered['short_segments_discarded'] == 1
    assert filtered['short_segments_discarded_seconds'] == pytest.approx(.02)


def test_rms_boundary_floor_and_strict_threshold():
    path = np.full(4, state(69), dtype=np.int16)
    for energy in ([1., .7, 1., 1.], [0., 0., 0., 1e-12], [0., 0., 0., 0.]):
        edited, diagnostics = rms_silence_path(path, energy)
        np.testing.assert_array_equal(edited, path)
        assert diagnostics['rms_rise_candidates'] == 0
    edited, _ = rms_silence_path(path, [1., .69, 1., 1.])
    assert np.flatnonzero(edited % 3 == SILENT).tolist() == [0]
    for frames in range(4):
        short_path = path[:frames]
        np.testing.assert_array_equal(rms_silence_path(short_path, np.ones(frames))[0], short_path)


def test_infer_decodes_once_reuses_path_and_returns_scalar_diagnostics(monkeypatch):
    import scripts.note_state_hmm as model

    original_decode, calls = model._decode, []

    def counted_decode(*args):
        calls.append(1)
        return original_decode(*args)

    monkeypatch.setattr(model, '_decode', counted_decode)
    frequency = np.full(100, 440.)
    energy = np.r_[np.ones(50), np.full(50, 2.)]
    result = infer_note_states(frequency, 1., rms=energy)
    assert len(calls) == 1
    assert set(result['arms']) == set(ARMS)
    expected_path, _ = rms_silence_path(result['phase_path'], energy)
    np.testing.assert_array_equal(result['rms_phase_path'], expected_path)
    assert len(result['arms'][ARMS[0]]) == 1
    assert len(result['arms'][ARMS[1]]) == 2
    assert result['diagnostics']['rms']['rms_frames_changed_to_silent'] == 2
    for arm in ARMS:
        assert all(np.isscalar(value) for value in result['diagnostics']['arms'][arm].values())
    np.testing.assert_array_equal(frequency, np.full(100, 440.))


@pytest.mark.parametrize('frequency', [[np.nan], [np.inf], [-1.], [[440.]],
                                      [hz(32.99)], [hz(81.01)]])
def test_invalid_and_fractional_out_of_range_f0_fail_closed(frequency):
    with pytest.raises(ValueError):
        infer_note_states(frequency, .01)


@pytest.mark.parametrize('duration', [-.1, np.nan, np.inf, .07, .11])
def test_invalid_duration_or_frame_clock_mismatch_fail_closed(duration):
    with pytest.raises(ValueError):
        infer_note_states(np.full(10, 440.), duration)


def test_empty_nonzero_duration_and_invalid_path_fail_closed():
    with pytest.raises(ValueError):
        infer_note_states([], .01)
    for path in ([435], [-1], [1.0], [[1]], [1, 2]):
        with pytest.raises(ValueError):
            notes_from_state_path(path, [440.], .01)


@pytest.mark.parametrize('rms', [[1.], [1., np.nan], [1., np.inf], [1., -1.], [[1., 1.]]])
def test_invalid_rms_fails_closed(rms):
    with pytest.raises(ValueError):
        infer_note_states([440., 440.], .02, rms=rms)


@pytest.mark.parametrize('samples', [[], [[0.]], [np.nan], [np.inf], [1e308]])
def test_invalid_audio_for_rms_fails_closed(samples):
    with pytest.raises(ValueError):
        centered_rms(samples)

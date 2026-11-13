import json
import math
from dataclasses import FrozenInstanceError, asdict, replace

import numpy as np
import pytest

from scripts import note_state_factors as factors
from scripts import note_state_hmm as legacy

ALL_CONFIGS = (factors.LEGACY_CONFIG, *factors.CONFIGS.values())
CONFIG_IDS = ('legacy', *factors.FACTOR_ARMS)


def hz(pitch):
    return 440 * 2 ** ((np.asarray(pitch) - 69) / 12)


def independent_dense_oracle(frequency, grid, config):
    """Build probabilities and dense DP without the candidate's math helpers."""
    count = len(grid)
    self_probs = np.array([.9, .99, config.paper_silent_self])
    if config.rescale_hop:
        self_probs **= .01 / (256 / 44100)
    transition = np.zeros((3 * count, 3 * count))
    for i, source in enumerate(grid):
        transition[3 * i, 3 * i] = self_probs[0]
        transition[3 * i, 3 * i + 1] = 1 - self_probs[0]
        transition[3 * i + 1, 3 * i + 1] = self_probs[1]
        transition[3 * i + 1, 3 * i + 2] = 1 - self_probs[1]
        transition[3 * i + 2, 3 * i + 2] = self_probs[2]
        jumps = []
        for target in grid:
            distance = abs(target - source)
            permitted = (distance < 1e-10 or distance >= 2 / 3 - 1e-10) and distance <= 13 + 1e-10
            jumps.append(math.exp(-distance / 2) if permitted else 0.)
        transition[3 * i + 2, ::3] = (1 - self_probs[2]) * np.asarray(jumps) / sum(jumps)
    with np.errstate(divide='ignore'):
        log_transition = np.log(transition)
    observations = []
    for value in frequency:
        weights = np.empty(3 * count)
        if value == 0:
            weights[0::3] = weights[1::3] = math.log(1e-12 / (2 * count))
            weights[2::3] = math.log((1 - 1e-12) / count)
        else:
            midi = 69 + 12 * math.log2(value / 440)
            a = config.gaussian_exponent * np.array([
                -math.log(5 * math.sqrt(2 * math.pi)) - (midi - p)**2 / (2 * 5**2)
                for p in grid])
            s = config.gaussian_exponent * np.array([
                -math.log(.9 * math.sqrt(2 * math.pi)) - (midi - p)**2 / (2 * .9**2)
                for p in grid])
            if config.balance_phases:
                weights[0::3] = math.log(config.positive_voiced_mass / 2) + a - np.logaddexp.reduce(a)
                weights[1::3] = math.log(config.positive_voiced_mass / 2) + s - np.logaddexp.reduce(s)
            else:
                normalization = np.logaddexp.reduce(np.r_[a, s])
                weights[0::3] = math.log(config.positive_voiced_mass) + a - normalization
                weights[1::3] = math.log(config.positive_voiced_mass) + s - normalization
            weights[2::3] = math.log((1 - config.positive_voiced_mass) / count)
        observations.append(weights)
    initial = np.full(3 * count, -np.inf)
    initial[0::3] = initial[2::3] = math.log(.5 / count)
    score = initial + observations[0]
    back = []
    for observation in observations[1:]:
        candidates = score[:, None] + log_transition
        previous = candidates.argmax(axis=0)
        back.append(previous)
        score = candidates[previous, np.arange(len(score))] + observation
    path = [int(score.argmax())]
    for previous in reversed(back):
        path.append(int(previous[path[-1]]))
    return np.asarray(path[::-1], dtype=np.int16), float(score.max())


def test_configs_are_fixed_and_each_factor_changes_exactly_one_field():
    expected_changes = {
        'gaussian_exponent_1': {'gaussian_exponent': 1.},
        'phase_balanced': {'balance_phases': True},
        'positive_voicing_08': {'positive_voiced_mass': .8},
        'silent_self_099': {'paper_silent_self': .99},
        'hop_unscaled': {'rescale_hop': False},
    }
    assert tuple(factors.CONFIGS) == factors.FACTOR_ARMS == tuple(expected_changes)
    baseline = asdict(factors.LEGACY_CONFIG)
    for name, config in factors.CONFIGS.items():
        changed = {key: value for key, value in asdict(config).items() if value != baseline[key]}
        assert changed == expected_changes[name]
    with pytest.raises(FrozenInstanceError):
        factors.CONFIGS['gaussian_exponent_1'].gaussian_exponent = .2
    with pytest.raises(TypeError):
        factors.CONFIGS['extra'] = factors.LEGACY_CONFIG


def test_settings_are_deeply_readonly_and_json_serializable():
    serialized = json.dumps(factors.SETTINGS, sort_keys=True, allow_nan=False)
    restored = json.loads(serialized)
    assert restored['factor_arms'] == list(factors.FACTOR_ARMS)
    with pytest.raises(TypeError):
        factors.SETTINGS['model'] = 'changed'
    with pytest.raises(TypeError):
        factors.SETTINGS['factor_configs']['phase_balanced']['balance_phases'] = False
    with pytest.raises(TypeError):
        factors.SETTINGS['legacy_base_settings']['self_probabilities'][0] = .1
    with pytest.raises(TypeError):
        factors.SETTINGS.update({'new': 'setting'})
    assert json.dumps(factors.SETTINGS, sort_keys=True, allow_nan=False) == serialized


@pytest.mark.parametrize('config', ALL_CONFIGS, ids=CONFIG_IDS)
def test_transition_rows_topology_and_jump_bounds(config):
    transition = factors.transition_probabilities(config)
    np.testing.assert_allclose(transition.sum(axis=1), 1., rtol=0, atol=2e-15)
    assert np.all(transition >= 0)
    for pitch_index in (0, 72, 144):
        a, s, u = np.arange(3) + pitch_index * 3
        assert np.flatnonzero(transition[a]).tolist() == [a, s]
        assert np.flatnonzero(transition[s]).tolist() == [s, u]
        for destination in np.flatnonzero(transition[u]):
            if destination == u:
                continue
            assert destination % 3 == legacy.ATTACK
            distance = abs(legacy.PITCHES[destination // 3] - legacy.PITCHES[pitch_index])
            assert distance < 1e-10 or 2 / 3 - 1e-10 <= distance <= 13 + 1e-10


def test_transition_factors_have_no_unintended_emission_or_topology_changes():
    old_transition = legacy.transition_probabilities()
    np.testing.assert_array_equal(factors.transition_probabilities(), old_transition)
    for name in factors.FACTOR_ARMS[:3]:
        np.testing.assert_array_equal(factors.transition_probabilities(factors.CONFIGS[name]), old_transition)
    changed = factors.transition_probabilities(factors.CONFIGS['silent_self_099'])
    np.testing.assert_array_equal(changed[0::3], old_transition[0::3])
    np.testing.assert_array_equal(changed[1::3], old_transition[1::3])
    np.testing.assert_allclose(np.diag(changed)[2::3], .99 ** (legacy.DT / legacy.PAPER_DT))
    for row in range(2, 435, 3):
        np.testing.assert_allclose(changed[row, ::3] / changed[row, ::3].sum(),
                                   old_transition[row, ::3] / old_transition[row, ::3].sum())
    unscaled = factors.transition_probabilities(factors.CONFIGS['hop_unscaled'])
    np.testing.assert_array_equal(np.diag(unscaled), np.tile([.9, .99, .9999], 145))
    for name in ('silent_self_099', 'hop_unscaled'):
        np.testing.assert_array_equal(factors.log_emissions(hz(57), factors.CONFIGS[name]),
                                      legacy.observation_log_weights(hz(57)))


@pytest.mark.parametrize('config', ALL_CONFIGS, ids=CONFIG_IDS)
@pytest.mark.parametrize('pitch', [33., 57.125, 81.])
def test_voiced_and_silent_masses_are_normalized(config, pitch):
    emission = np.exp(factors.log_emissions(hz(pitch), config))
    assert emission.sum() == pytest.approx(1.)
    assert emission[2::3].sum() == pytest.approx(1 - config.positive_voiced_mass)
    assert emission[0::3].sum() + emission[1::3].sum() == pytest.approx(config.positive_voiced_mass)
    np.testing.assert_allclose(emission[2::3], (1 - config.positive_voiced_mass) / 145)
    if config.balance_phases:
        assert emission[0::3].sum() == pytest.approx(.25)
        assert emission[1::3].sum() == pytest.approx(.25)


def test_gaussian_exponent_1_is_ordinary_pdf_and_voicing_factor_preserves_shape():
    q = 57.
    exponent_config = factors.CONFIGS['gaussian_exponent_1']
    weights = np.exp(factors.log_emissions(hz(q), exponent_config))
    a = np.exp(-.5 * ((q - legacy.PITCHES) / 5)**2) / (5 * np.sqrt(2 * np.pi))
    s = np.exp(-.5 * ((q - legacy.PITCHES) / .9)**2) / (.9 * np.sqrt(2 * np.pi))
    total = a.sum() + s.sum()
    np.testing.assert_allclose(weights[::3], .5 * a / total, atol=1e-16)
    np.testing.assert_allclose(weights[1::3], .5 * s / total, atol=1e-16)
    center = int(round((q - 33) * 3))
    assert weights[3 * center] / weights[3 * center + 1] == pytest.approx(.9 / 5)
    old = np.exp(legacy.observation_log_weights(hz(q)))
    voiced = np.exp(factors.log_emissions(hz(q), factors.CONFIGS['positive_voicing_08']))
    np.testing.assert_allclose(voiced[::3], old[::3] * 1.6)
    np.testing.assert_allclose(voiced[1::3], old[1::3] * 1.6)
    np.testing.assert_allclose(voiced[2::3], old[2::3] * .4)
    balanced = np.exp(factors.log_emissions(hz(q), factors.CONFIGS['phase_balanced']))
    for phase in (0, 1):
        np.testing.assert_allclose(balanced[phase::3], old[phase::3] * .25 / old[phase::3].sum())


@pytest.mark.parametrize('config', ALL_CONFIGS, ids=CONFIG_IDS)
def test_zero_hz_emissions_are_unchanged_in_every_factor(config):
    np.testing.assert_array_equal(factors.log_emissions(0., config), legacy.observation_log_weights(0.))


@pytest.mark.parametrize('config', ALL_CONFIGS, ids=CONFIG_IDS)
def test_sparse_path_matches_independent_dense_oracle(config):
    grid = np.arange(33., 82., 4.)
    frequency = np.r_[np.zeros(5), hz(np.full(80, 45.)), np.zeros(4),
                      hz(57 + .1 * np.sin(np.arange(90))), np.zeros(5)]
    expected, score = independent_dense_oracle(frequency, grid, config)
    actual = factors.decode_state_path(frequency, config, pitches=grid)
    np.testing.assert_array_equal(actual, expected)
    # Check the returned score separately from the path, using the same contract input.
    midi = np.full(len(frequency), np.nan)
    positive = frequency > 0
    midi[positive] = 69 + 12 * np.log2(frequency[positive] / 440)
    private_path, actual_score = factors._decode(midi, grid, config)
    np.testing.assert_array_equal(private_path, actual)
    assert actual_score == pytest.approx(score, abs=1e-10)
    assert len(np.unique(actual % 3)) == 3


@pytest.mark.parametrize('config', ALL_CONFIGS, ids=CONFIG_IDS)
def test_exact_ties_choose_lowest_state_and_stable_cannot_be_initial(config):
    np.testing.assert_array_equal(factors.decode_state_path(np.zeros(12), config),
                                  np.full(12, legacy.SILENT))
    first = factors.decode_state_path([hz(57)], config)[0]
    assert first % 3 != legacy.STABLE


@pytest.mark.parametrize('frequency', [
    np.zeros(17), np.full(31, 440.),
    np.r_[np.zeros(3), hz(np.full(80, 57.)), np.zeros(4), hz(np.full(80, 69.))],
    hz(57 + .2 * np.sin(np.arange(100))),
])
def test_legacy_configuration_matches_frozen_decoder_bit_for_bit(frequency):
    old = legacy.infer_note_states(frequency, len(frequency) * legacy.DT)
    new_path = factors.decode_state_path(frequency)
    np.testing.assert_array_equal(new_path, old['phase_path'])
    notes, counts = legacy.notes_from_state_path(new_path, frequency, len(frequency) * legacy.DT)
    assert notes == old['arms']['note_state_hmm']
    assert counts == old['diagnostics']['arms']['note_state_hmm']
    for value in (0., hz(33), hz(57.125), hz(81)):
        np.testing.assert_array_equal(factors.log_emissions(value), legacy.observation_log_weights(value))


def test_infer_api_uses_original_readout_and_one_decode_per_factor(monkeypatch):
    calls = []
    original = factors._decode

    def recorded(midi, grid, config):
        calls.append(config)
        return original(midi, grid, config)

    monkeypatch.setattr(factors, '_decode', recorded)
    frequency = np.full(101, 440.)
    before = frequency.copy()
    result = factors.infer_factors(frequency, 1.)
    assert set(result) == {'arms', 'paths', 'diagnostics'}
    assert calls == list(factors.CONFIGS.values())
    for mapping in result.values():
        assert tuple(mapping) == factors.FACTOR_ARMS
    for name in factors.FACTOR_ARMS:
        path = result['paths'][name]
        assert path.dtype == np.int16 and path.shape == frequency.shape
        assert np.all((path >= 0) & (path < 435))
        expected_notes, expected_counts = legacy.notes_from_state_path(path, frequency, 1.)
        assert result['arms'][name] == expected_notes
        diagnostics = result['diagnostics'][name]
        assert {key: value for key, value in diagnostics.items()
                if key != 'viterbi_path_log_weight'} == expected_counts
        assert all(np.isscalar(value) for value in diagnostics.values())
        assert math.isfinite(diagnostics['viterbi_path_log_weight'])
        assert all(note.offset <= 1. for note in expected_notes)
    np.testing.assert_array_equal(frequency, before)
    assert len({id(path) for path in result['paths'].values()}) == len(factors.FACTOR_ARMS)


def test_empty_inputs_preserve_all_five_arm_keys():
    result = factors.infer_factors([], 0.)
    assert result['arms'] == dict.fromkeys(factors.FACTOR_ARMS, [])
    for name in factors.FACTOR_ARMS:
        assert result['paths'][name].dtype == np.int16
        assert result['paths'][name].size == 0
        assert result['diagnostics'][name]['frames'] == 0
        assert result['diagnostics'][name]['viterbi_path_log_weight'] == 0


def test_emission_factorial_is_analysis_only_and_has_four_combinations():
    before = tuple(factors.CONFIGS)
    rows = factors.emission_factorial_diagnostics(hz(57))
    assert {(row['gaussian_exponent'], row['balance_phases']) for row in rows} == {
        (.1, False), (.1, True), (1., False), (1., True)}
    for row in rows:
        assert row['attack_total_mass'] + row['stable_total_mass'] == pytest.approx(.5)
        assert row['silent_total_mass'] == pytest.approx(.5)
        assert all(np.isscalar(value) for value in row.values())
    assert tuple(factors.CONFIGS) == before
    assert len(factors.FACTOR_ARMS) == 5


@pytest.mark.parametrize('frequency', [[np.nan], [np.inf], [-1.], [[440.]],
                                      [hz(32.99)], [hz(81.01)]])
def test_invalid_f0_is_rejected_before_decode(frequency, monkeypatch):
    def forbidden(*args):
        raise AssertionError('invalid observations reached decoder')

    monkeypatch.setattr(factors, '_decode', forbidden)
    with pytest.raises(ValueError):
        factors.infer_factors(frequency, .01)


@pytest.mark.parametrize('duration', [-.1, np.nan, np.inf, .07, .11])
def test_duration_contract_matches_original_clock(duration):
    with pytest.raises(ValueError):
        factors.infer_factors(np.full(10, 440.), duration)


@pytest.mark.parametrize('config', [
    replace(factors.LEGACY_CONFIG, gaussian_exponent=0),
    replace(factors.LEGACY_CONFIG, gaussian_exponent=np.inf),
    replace(factors.LEGACY_CONFIG, positive_voiced_mass=1),
    replace(factors.LEGACY_CONFIG, paper_silent_self=0),
    replace(factors.LEGACY_CONFIG, balance_phases=1),
    replace(factors.LEGACY_CONFIG, rescale_hop=1),
])
def test_invalid_factor_configuration_fails_closed(config):
    with pytest.raises(ValueError):
        factors.decode_state_path([440.], config)
    with pytest.raises(ValueError):
        factors.log_emissions(440., config)
    with pytest.raises(ValueError):
        factors.transition_probabilities(config)

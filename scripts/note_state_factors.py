"""Frozen one-factor diagnostics of the legacy research note-state HMM.

Each reported candidate changes exactly one setting of note_state_hmm.py. The
failed legacy model stays untouched and is evaluated by its original module.
These are conditional sensitivity checks, not an upstream Tony reproduction.
The Gaussian-exponent factor uses an ordinary Gaussian; it does not claim to
recover pYIN's missing candidate probabilities from a decoded F0 contour.

No CLI, annotation input, parameter search, RMS edit, or score rhythm enters
this module. The original event readout is reused without alteration.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace
from functools import lru_cache
from types import MappingProxyType

import numpy as np

from scripts import note_state_hmm as legacy

FACTOR_ARMS = (
    'gaussian_exponent_1', 'phase_balanced', 'positive_voicing_08',
    'silent_self_099', 'hop_unscaled',
)


@dataclass(frozen=True)
class FactorConfig:
    gaussian_exponent: float = .1
    balance_phases: bool = False
    positive_voiced_mass: float = .5
    paper_silent_self: float = .9999
    rescale_hop: bool = True


LEGACY_CONFIG = FactorConfig()
CONFIGS = MappingProxyType({
    FACTOR_ARMS[0]: replace(LEGACY_CONFIG, gaussian_exponent=1.),
    FACTOR_ARMS[1]: replace(LEGACY_CONFIG, balance_phases=True),
    FACTOR_ARMS[2]: replace(LEGACY_CONFIG, positive_voiced_mass=.8),
    FACTOR_ARMS[3]: replace(LEGACY_CONFIG, paper_silent_self=.99),
    FACTOR_ARMS[4]: replace(LEGACY_CONFIG, rescale_hop=False),
})


class _FrozenDict(dict):
    """Read-only dict that remains directly serializable by json.dumps."""

    def _immutable(self, *args, **kwargs):
        raise TypeError('experiment settings are immutable')

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = _immutable
    __ior__ = _immutable


def _freeze(value):
    if isinstance(value, dict):
        return _FrozenDict((key, _freeze(item)) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


SETTINGS = _freeze({
    'model': 'fixed_one_factor_note_state_diagnostics',
    'factor_arms': FACTOR_ARMS,
    'legacy_config': asdict(LEGACY_CONFIG),
    'factor_configs': {name: asdict(config) for name, config in CONFIGS.items()},
    'legacy_base_settings': legacy.SETTINGS,
    'legacy_settings_overrides': 'only the single differing FactorConfig field per arm',
    'phase_balanced_emission': 'A and S normalized separately to v/2 each; U total 1-v',
    'zero_hz_handling': 'unchanged legacy 1e-12 total voiced mass, uniform across 2N states',
    'event_readout': 'unchanged scripts.note_state_hmm.notes_from_state_path',
    'rms_postprocess': False,
    'primary_factor': FACTOR_ARMS[0],
    'analysis_factorial': 'Gaussian exponent {.1,1} x phase balance {False,True}; emissions only',
    'upstream_reproduction': False,
})


def _validate_config(config):
    if (not isinstance(config, FactorConfig)
            or not math.isfinite(config.gaussian_exponent) or config.gaussian_exponent <= 0
            or not math.isfinite(config.positive_voiced_mass)
            or not 0 < config.positive_voiced_mass < 1
            or not math.isfinite(config.paper_silent_self) or not 0 < config.paper_silent_self < 1
            or type(config.balance_phases) is not bool or type(config.rescale_hop) is not bool):
        raise ValueError('invalid note-state factor configuration')


def _pitch_grid(pitches):
    grid = np.asarray(pitches, dtype=float)
    if (grid.ndim != 1 or not len(grid) or len(grid) > 10922
            or not np.isfinite(grid).all() or np.any(np.diff(grid) <= 0)
            or grid[0] < 0 or grid[-1] > 127):
        raise ValueError('invalid pitch-state grid')
    return grid


def _frequencies(hz, grid):
    values = np.asarray(hz, dtype=float)
    if values.ndim != 1 or not np.isfinite(values).all() or np.any(values < 0):
        raise ValueError('invalid F0 observations')
    voiced = values > 0
    midi = np.full(values.shape, np.nan)
    midi[voiced] = 69 + 12 * np.log2(values[voiced] / 440.)
    if (np.any(midi[voiced] < grid[0] - 1e-10)
            or np.any(midi[voiced] > grid[-1] + 1e-10)):
        raise ValueError('fractional F0 outside note-state pitch range')
    return values, midi


def _validate_duration(duration, frames):
    if not math.isfinite(duration) or duration < 0:
        raise ValueError('invalid audio duration')
    if frames == 0:
        if duration != 0:
            raise ValueError('empty F0 requires zero audio duration')
    elif not (max(0., (frames - 1) * legacy.DT) - 1e-10
              <= duration <= frames * legacy.DT + 1e-10):
        raise ValueError('duration is inconsistent with the centered F0 frame clock')


@lru_cache(maxsize=16)
def _model(pitch_tuple, config):
    _validate_config(config)
    grid = _pitch_grid(pitch_tuple)
    count = len(grid)
    self_probs = np.array([.9, .99, config.paper_silent_self])
    if config.rescale_hop:
        self_probs = self_probs ** (legacy.DT / legacy.PAPER_DT)
    distance = np.abs(grid[:, None] - grid[None, :])
    allowed = ((distance < 1e-10) | (distance >= 2 / 3 - 1e-10))
    allowed &= distance <= 13 + 1e-10
    jump = np.where(allowed, np.exp(-distance / 2), 0.)
    jump /= jump.sum(axis=1, keepdims=True)
    width = int(allowed.sum(axis=0).max())
    sources = np.zeros((count, width), dtype=np.int16)
    log_jump = np.full((count, width), -np.inf)
    for destination in range(count):
        indexes = np.flatnonzero(allowed[:, destination])
        sources[destination, :len(indexes)] = 3 * indexes + legacy.SILENT
        log_jump[destination, :len(indexes)] = (
            np.log1p(-self_probs[legacy.SILENT]) + np.log(jump[indexes, destination]))
    initial = np.full(3 * count, -np.inf)
    initial[legacy.ATTACK::3] = initial[legacy.SILENT::3] = math.log(.5 / count)
    for array in (self_probs, jump, sources, log_jump, initial):
        array.setflags(write=False)
    return self_probs, jump, sources, log_jump, initial


def transition_probabilities(config=LEGACY_CONFIG, *, pitches=legacy.PITCHES):
    """Dense audit matrix at the fixed 10 ms observation hop."""
    _validate_config(config)
    grid = _pitch_grid(pitches)
    self_probs, jump, _, _, _ = _model(tuple(grid), config)
    count = len(grid)
    result = np.zeros((3 * count, 3 * count))
    indexes = np.arange(count) * 3
    result[indexes, indexes] = self_probs[legacy.ATTACK]
    result[indexes, indexes + legacy.STABLE] = 1 - self_probs[legacy.ATTACK]
    result[indexes + legacy.STABLE, indexes + legacy.STABLE] = self_probs[legacy.STABLE]
    result[indexes + legacy.STABLE, indexes + legacy.SILENT] = 1 - self_probs[legacy.STABLE]
    result[indexes + legacy.SILENT, indexes + legacy.SILENT] = self_probs[legacy.SILENT]
    result[legacy.SILENT::3, legacy.ATTACK::3] = (1 - self_probs[legacy.SILENT]) * jump
    return result


def _log_emissions_midi(midi, grid, config):
    count = len(grid)
    result = np.empty(3 * count)
    if math.isnan(midi):
        result[legacy.ATTACK::3] = result[legacy.STABLE::3] = math.log(
            legacy.UNVOICED_VOICED_MASS / (2 * count))
        result[legacy.SILENT::3] = math.log((1 - legacy.UNVOICED_VOICED_MASS) / count)
        return result
    delta = midi - grid
    attack = config.gaussian_exponent * (
        -math.log(5.) - .5 * math.log(2 * math.pi) - .5 * (delta / 5.)**2)
    stable = config.gaussian_exponent * (
        -math.log(.9) - .5 * math.log(2 * math.pi) - .5 * (delta / .9)**2)
    if config.balance_phases:
        for phase, logs in ((legacy.ATTACK, attack), (legacy.STABLE, stable)):
            maximum = float(logs.max())
            normalizer = maximum + math.log(float(np.exp(logs - maximum).sum()))
            result[phase::3] = math.log(config.positive_voiced_mass / 2) + logs - normalizer
    else:
        maximum = max(float(attack.max()), float(stable.max()))
        normalizer = maximum + math.log(float(
            np.exp(attack - maximum).sum() + np.exp(stable - maximum).sum()))
        result[legacy.ATTACK::3] = math.log(config.positive_voiced_mass) + attack - normalizer
        result[legacy.STABLE::3] = math.log(config.positive_voiced_mass) + stable - normalizer
    result[legacy.SILENT::3] = math.log((1 - config.positive_voiced_mass) / count)
    return result


def log_emissions(hz, config=LEGACY_CONFIG, *, pitches=legacy.PITCHES):
    """Normalized log weights for one F0 observation, with all 3N state IDs."""
    _validate_config(config)
    grid = _pitch_grid(pitches)
    _, midi = _frequencies([hz], grid)
    return _log_emissions_midi(float(midi[0]), grid, config)


def _decode(midi, grid, config):
    count, frames = len(grid), len(midi)
    if frames == 0:
        return np.empty(0, dtype=np.int16), 0.
    self_probs, _, sources, jump_log, initial = _model(tuple(grid), config)
    log_self, log_exit = np.log(self_probs), np.log1p(-self_probs)
    attack_ids = np.arange(count, dtype=np.int16) * 3
    stable_ids, silent_ids = attack_ids + legacy.STABLE, attack_ids + legacy.SILENT
    rows = np.arange(count)
    back = np.empty((frames, 3 * count), dtype=np.int16)
    back[0] = -1
    previous = initial + _log_emissions_midi(float(midi[0]), grid, config)
    for frame in range(1, frames):
        incoming = previous[sources] + jump_log
        positions = np.argmax(incoming, axis=1)
        jump_scores = incoming[rows, positions]
        jump_sources = sources[rows, positions]
        self_scores = previous[attack_ids] + log_self[legacy.ATTACK]
        use_self = ((self_scores > jump_scores)
                    | ((self_scores == jump_scores) & (attack_ids < jump_sources)))
        current = np.empty_like(previous)
        current[legacy.ATTACK::3] = np.where(use_self, self_scores, jump_scores)
        back[frame, legacy.ATTACK::3] = np.where(use_self, attack_ids, jump_sources)

        attack_scores = previous[attack_ids] + log_exit[legacy.ATTACK]
        stable_scores = previous[stable_ids] + log_self[legacy.STABLE]
        from_attack = attack_scores >= stable_scores
        current[legacy.STABLE::3] = np.where(from_attack, attack_scores, stable_scores)
        back[frame, legacy.STABLE::3] = np.where(from_attack, attack_ids, stable_ids)

        stable_scores = previous[stable_ids] + log_exit[legacy.STABLE]
        silent_scores = previous[silent_ids] + log_self[legacy.SILENT]
        from_stable = stable_scores >= silent_scores
        current[legacy.SILENT::3] = np.where(from_stable, stable_scores, silent_scores)
        back[frame, legacy.SILENT::3] = np.where(from_stable, stable_ids, silent_ids)
        previous = current + _log_emissions_midi(float(midi[frame]), grid, config)
    final_state = int(np.argmax(previous))
    score = float(previous[final_state])
    path = np.empty(frames, dtype=np.int16)
    path[-1] = final_state
    for frame in range(frames - 1, 0, -1):
        path[frame - 1] = back[frame, path[frame]]
    return path, score


def decode_state_path(hz, config=LEGACY_CONFIG, *, pitches=legacy.PITCHES):
    """Config-aware sparse Viterbi; custom grids are for oracle contract tests."""
    _validate_config(config)
    grid = _pitch_grid(pitches)
    _, midi = _frequencies(hz, grid)
    return _decode(midi, grid, config)[0]


def infer_factors(hz, duration):
    """Return the five fixed candidate arms, private paths, and scalar diagnostics."""
    values, midi = _frequencies(hz, legacy.PITCHES)
    _validate_duration(duration, len(values))
    arms, paths, diagnostics = {}, {}, {}
    for name in FACTOR_ARMS:
        path, score = _decode(midi, legacy.PITCHES, CONFIGS[name])
        notes, counts = legacy.notes_from_state_path(path, values, duration)
        counts['viterbi_path_log_weight'] = score
        arms[name], paths[name], diagnostics[name] = notes, path, counts
    return {'arms': arms, 'paths': paths, 'diagnostics': diagnostics}


def emission_factorial_diagnostics(hz):
    """Four analytic emission summaries only; the fourth combination is not an arm.

    This exposes the exponent/phase-normalization interaction without running a
    decoder, introducing an additional corpus candidate, or selecting a setting.
    """
    rows = []
    for exponent in (.1, 1.):
        for balanced in (False, True):
            config = replace(LEGACY_CONFIG, gaussian_exponent=exponent, balance_phases=balanced)
            log_weights = log_emissions(hz, config)
            weights = np.exp(log_weights)
            rows.append({
                'gaussian_exponent': exponent, 'balance_phases': balanced,
                'attack_total_mass': float(weights[legacy.ATTACK::3].sum()),
                'stable_total_mass': float(weights[legacy.STABLE::3].sum()),
                'silent_total_mass': float(weights[legacy.SILENT::3].sum()),
                'attack_peak_mass': float(weights[legacy.ATTACK::3].max()),
                'stable_peak_mass': float(weights[legacy.STABLE::3].max()),
                'silent_each_mass': float(weights[legacy.SILENT]),
                'stable_peak_over_silent_log_ratio': float(
                    log_weights[legacy.STABLE::3].max() - log_weights[legacy.SILENT]),
            })
    return tuple(rows)

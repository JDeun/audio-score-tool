"""Strict gate replay guard allowing only decision-inert scalar roundoff."""
from __future__ import annotations

import math
from numbers import Real

import numpy as np

from scripts.audio_gate_rest import SETTINGS

SCALAR_KEYS = ('reference_db', 'close_db', 'open_db')
ABSOLUTE_TOLERANCE = 1e-12


def _archived_threshold_mask(levels: np.ndarray, close: float, opening: float) -> np.ndarray:
    """Frozen start-closed, backdated-hold gate using archived thresholds."""
    quiet = np.ones(len(levels), dtype=bool)
    if float(levels.max()) <= -239:
        return quiet
    hold = int(round(SETTINGS['hold_seconds'] / SETTINGS['hop_seconds']))
    opened, low_start = False, None
    for i, value in enumerate(levels):
        if not opened:
            if value >= opening:
                opened, low_start = True, None
                quiet[i] = False
        else:
            quiet[i] = False
            if value < close:
                if low_start is None:
                    low_start = i
                if i - low_start + 1 >= hold:
                    quiet[low_start:i + 1] = True
                    opened, low_start = False, None
            else:
                low_start = None
    return quiet


def verify_gate_replay(levels, quiet, settings, expected_gate_dict) -> dict:
    """Require exact counts/mask and at most 1e-12 absolute scalar roundoff.

    The archived close/open scalars are reapplied to the same current levels.
    Every resulting cell must equal the current mask. Relative tolerance is zero;
    this guard cannot authorize a changed decision, event hash, or musical score.
    Input arrays and dictionaries are never mutated.
    """
    levels = np.asarray(levels)
    quiet = np.asarray(quiet)
    if (levels.ndim != 1 or not len(levels) or levels.dtype.kind not in 'fiu'
            or not np.isfinite(levels).all()):
        raise ValueError('gate replay requires nonempty finite numeric levels')
    if quiet.ndim != 1 or quiet.dtype.kind != 'b' or len(quiet) != len(levels):
        raise ValueError('gate replay mask length/type mismatch')
    if (not isinstance(settings, dict) or set(settings) != set(SCALAR_KEYS)
            or not isinstance(expected_gate_dict, dict)
            or not set(SCALAR_KEYS + ('total_frames', 'quiet_frames')) <= set(expected_gate_dict)):
        raise ValueError('gate replay settings/receipt fields malformed')
    current, archived, deltas = {}, {}, {}
    for key in SCALAR_KEYS:
        actual, expected = settings[key], expected_gate_dict[key]
        if any(not isinstance(value, Real) or isinstance(value, (bool, np.bool_))
               or not math.isfinite(value) for value in (actual, expected)):
            raise ValueError(f'gate replay scalar {key} malformed: actual={actual!r} expected={expected!r}')
        current[key], archived[key] = float(actual), float(expected)
        deltas[key] = current[key] - archived[key]
        if abs(deltas[key]) > ABSOLUTE_TOLERANCE:
            raise ValueError(f'gate replay scalar {key} mismatch: actual={actual!r} '
                             f'expected={expected!r} delta={deltas[key]!r} atol=1e-12 rtol=0')
    if current['close_db'] >= current['open_db'] or archived['close_db'] >= archived['open_db']:
        raise ValueError('gate replay requires close_db below open_db')
    counts = {'total_frames': len(levels), 'quiet_frames': int(quiet.sum())}
    for key, actual in counts.items():
        expected = expected_gate_dict[key]
        if type(expected) is not int or expected < 0:
            raise ValueError(f'gate replay {key} malformed: actual={actual} expected={expected!r}')
        if actual != expected:
            raise ValueError(f'gate replay {key} mismatch: actual={actual} expected={expected} '
                             f'delta={actual - expected} scalar_deltas={deltas!r}')
    archived_mask = _archived_threshold_mask(levels, archived['close_db'], archived['open_db'])
    if not np.array_equal(quiet, archived_mask):
        indices = np.flatnonzero(quiet != archived_mask)
        first = int(indices[0])
        raise ValueError(f'archived threshold mask mismatch: frames={len(indices)} first_index={first} '
                         f'actual={bool(quiet[first])} expected={bool(archived_mask[first])} '
                         f'scalar_deltas={deltas!r}')
    return {**counts, 'scalar_deltas': deltas,
            'max_abs_scalar_delta': max(abs(delta) for delta in deltas.values()),
            'scalars_exact': all(delta == 0. for delta in deltas.values()),
            'archived_threshold_mask_equal': True}

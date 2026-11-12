"""Replay guard contracts; no source outcome or new threshold selection."""
from __future__ import annotations

import copy

import numpy as np
import pytest

from scripts.audio_gate_replay import verify_gate_replay
from scripts.audio_gate_rest import gate_levels


def _case(levels):
    levels = np.asarray(levels, dtype=float)
    quiet, settings = gate_levels(levels, 'relative')
    expected = {**settings, 'total_frames': len(levels), 'quiet_frames': int(quiet.sum())}
    return levels, quiet, settings, expected


@pytest.mark.parametrize('levels', [
    [-240.] * 10,
    [-20.] + [-60.] * 5 + [-40.] + [-60.] * 6 + [-40.] + [-20.],
    [-30.] * 5 + [-90.] * 6 + [-50.] * 3 + [-20.],
])
def test_exact_silence_hold_and_hysteresis_replay(levels):
    inputs = _case(levels)
    before = copy.deepcopy(inputs)
    diagnostic = verify_gate_replay(*inputs)
    assert diagnostic['scalars_exact'] is True
    assert diagnostic['max_abs_scalar_delta'] == 0.
    assert diagnostic['archived_threshold_mask_equal'] is True
    assert np.array_equal(inputs[0], before[0])
    assert np.array_equal(inputs[1], before[1])
    assert inputs[2:] == before[2:]


def test_small_scalar_roundoff_accepted_when_full_mask_is_identical():
    levels, quiet, settings, expected = _case([-20.] * 10 + [-80.] * 10 + [-20.] * 10)
    settings = {key: value + 1e-14 for key, value in settings.items()}
    result = verify_gate_replay(levels, quiet, settings, expected)
    assert result['scalars_exact'] is False
    assert 0. < result['max_abs_scalar_delta'] <= 1e-12
    assert result['archived_threshold_mask_equal'] is True
    assert result['scalar_deltas'] == {key: settings[key] - expected[key] for key in settings}


@pytest.mark.parametrize('key', ['reference_db', 'close_db', 'open_db'])
def test_larger_scalar_change_rejected_even_if_gate_would_be_unchanged(key):
    levels, quiet, settings, expected = _case([-20.] * 10 + [-80.] * 10)
    settings[key] += 1e-8
    with pytest.raises(ValueError, match=r'actual=.*expected=.*delta=.*atol=1e-12 rtol=0'):
        verify_gate_replay(levels, quiet, settings, expected)


def test_tiny_open_threshold_change_affecting_one_frame_is_rejected():
    levels = np.array([-39., -20.])
    archived = {'reference_db': -15., 'close_db': -45., 'open_db': -39.,
                'total_frames': 2, 'quiet_frames': 0}
    current = {key: archived[key] for key in ('reference_db', 'close_db', 'open_db')}
    current['open_db'] += 1e-14
    quiet = np.array([True, False])
    with pytest.raises(ValueError, match='quiet_frames mismatch'):
        verify_gate_replay(levels, quiet, current, archived)
    # Even a receipt claiming the new count cannot bypass full-mask equality.
    archived['quiet_frames'] = 1
    with pytest.raises(ValueError, match=r'mask mismatch: frames=1 first_index=0'):
        verify_gate_replay(levels, quiet, current, archived)


def test_equal_frame_counts_cannot_hide_different_decisions():
    levels = np.array([-60., -20.])
    quiet = np.array([False, True])
    settings = {'reference_db': -15., 'close_db': -45., 'open_db': -39.}
    expected = {**settings, 'total_frames': 2, 'quiet_frames': 1}
    with pytest.raises(ValueError, match=r'mask mismatch: frames=2'):
        verify_gate_replay(levels, quiet, settings, expected)


@pytest.mark.parametrize('field', ['total_frames', 'quiet_frames'])
def test_counts_must_match_exactly(field):
    levels, quiet, settings, expected = _case([-20.] * 10 + [-80.] * 10)
    expected[field] += 1
    with pytest.raises(ValueError, match=field + ' mismatch: actual=.*expected=.*delta='):
        verify_gate_replay(levels, quiet, settings, expected)


@pytest.mark.parametrize('defect', [
    'empty', 'levels_shape', 'levels_nan', 'levels_text', 'mask_length',
    'mask_shape', 'mask_numeric', 'missing_scalar', 'extra_scalar',
    'missing_count', 'scalar_nan', 'scalar_inf', 'scalar_bool', 'scalar_text',
    'receipt_scalar_nan', 'negative_count', 'bool_count', 'float_count',
    'settings_not_dict', 'receipt_not_dict', 'inverted_thresholds',
])
def test_malformed_nonfinite_or_inconsistent_inputs_fail_closed(defect):
    levels, quiet, settings, expected = _case([-20.] * 10 + [-80.] * 10)
    if defect == 'empty':
        levels, quiet = np.array([]), np.array([], dtype=bool)
    elif defect == 'levels_shape':
        levels = levels.reshape(2, 10)
    elif defect == 'levels_nan':
        levels[0] = np.nan
    elif defect == 'levels_text':
        levels = levels.astype(str)
    elif defect == 'mask_length':
        quiet = quiet[:-1]
    elif defect == 'mask_shape':
        quiet = quiet.reshape(2, 10)
    elif defect == 'mask_numeric':
        quiet = quiet.astype(int)
    elif defect == 'missing_scalar':
        settings.pop('close_db')
    elif defect == 'extra_scalar':
        settings['unused'] = 0
    elif defect == 'missing_count':
        expected.pop('quiet_frames')
    elif defect in ('scalar_nan', 'scalar_inf', 'scalar_bool', 'scalar_text'):
        settings['close_db'] = {'scalar_nan': np.nan, 'scalar_inf': np.inf,
                                'scalar_bool': True, 'scalar_text': '-50'}[defect]
    elif defect == 'receipt_scalar_nan':
        expected['close_db'] = np.nan
    elif defect in ('negative_count', 'bool_count', 'float_count'):
        expected['quiet_frames'] = {'negative_count': -1, 'bool_count': True,
                                   'float_count': 10.}[defect]
    elif defect == 'settings_not_dict':
        settings = []
    elif defect == 'receipt_not_dict':
        expected = []
    elif defect == 'inverted_thresholds':
        settings['close_db'] = settings['open_db']
        expected['close_db'] = expected['open_db']
    with pytest.raises(ValueError):
        verify_gate_replay(levels, quiet, settings, expected)

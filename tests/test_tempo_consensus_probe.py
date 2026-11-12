"""Tempo consensus correctness checks; controlled signals are not song accuracy."""
from __future__ import annotations

import inspect

import numpy as np
import pytest
from scipy.signal import correlate

from scripts.tempo_consensus_probe import (
    BPMS,
    METHODS,
    PRIOR,
    RATE,
    estimate,
    rank,
    score,
    selection,
    validate,
    window_scores,
)


def pulses(seconds=24, period=.5, shift=.15):
    env = np.zeros(int(seconds * RATE) + 1)
    for t in np.arange(shift, seconds, period):
        env[int(round(t * RATE))] += 1
    return np.convolve(env, [.25, .5, .25], mode='same')


def reference_earlier_curve(env):
    # Independent verbatim mathematical implementation of #255, also replayed
    # against actual scripts.tempo_pattern_probe._acf_curve on every remote case.
    length = min(len(env), 800)
    starts = list(range(0, len(env) - length + 1, 400))
    if starts[-1] != len(env) - length:
        starts.append(len(env) - length)
    scores = []
    for start in starts:
        centered = env[start:start + length] - float(env[start:start + length].mean())
        if np.dot(centered, centered) < 1e-10:
            continue
        maximum = min(length - 2, 600)
        numerator = correlate(centered, centered, mode='full', method='fft')[length - 1:]
        cumulative = np.r_[0., np.cumsum(centered ** 2)]
        lag = np.arange(maximum + 1)
        den = np.sqrt((cumulative[length] - cumulative[lag]) * cumulative[length - lag])
        curve = np.clip(np.divide(numerator[:maximum + 1], den,
                                  out=np.zeros(maximum + 1), where=den > 1e-10), 0, 1)
        target = 6000 / BPMS
        scores.append(sum(w * np.interp(k * target, np.arange(len(curve)), curve,
                                        left=0, right=0)
                          for k, w in zip((1, 2, 4), (1., .5, .25))) / 1.75)
    return np.mean(scores, axis=0) if scores else np.zeros_like(BPMS)


@pytest.mark.parametrize('seconds', [4, 5, 8, 12, 24, 60])
def test_old_baseline_is_exactly_reproduced(seconds):
    env = pulses(seconds)
    original = reference_earlier_curve(env) * PRIOR
    result, _ = estimate(env)
    assert result[METHODS[0]]['candidates'] == rank(original)


def test_no_reference_meter_or_phase_interface():
    assert list(inspect.signature(estimate).parameters) == ['env']
    assert list(inspect.signature(selection).parameters) == ['scores', 'records']


def test_ambiguous_bar_start_does_not_block_bpm():
    result, _ = estimate(pulses())
    assert result[METHODS[0]]['bpm'] == 120
    assert result[METHODS[1]]['bpm'] == 120


def test_no_input_mutation_and_determinism():
    env = pulses()
    before = env.copy()
    a, da = estimate(env)
    b, db = estimate(env)
    assert np.array_equal(env, before)
    assert a == b and da == db


def test_shifted_pulses_keep_same_tempo():
    a, _ = estimate(pulses(shift=.15))
    b, _ = estimate(pulses(shift=.65))
    assert a[METHODS[0]]['bpm'] == b[METHODS[0]]['bpm'] == 120
    assert a[METHODS[1]]['bpm'] == b[METHODS[1]]['bpm'] == 120


@pytest.mark.parametrize('env,status', [(np.zeros(500), 'no_periodic_evidence'),
                                        (np.ones(300), 'too_short')])
def test_unavailable_cases_are_not_reported_as_120(env, status):
    results, _ = estimate(env)
    assert all(r['status'] == status and r['bpm'] is None for r in results.values())


@pytest.mark.parametrize('env', [np.array([float('nan')]), np.array([-1.]), np.zeros((2, 3))])
def test_invalid_data_rejected(env):
    with pytest.raises(ValueError):
        validate(env)


def test_selective_does_not_call_abstention_correct():
    result, _ = estimate(pulses(4))
    r = result['consensus_selective']
    assert r['bpm'] is None and 'insufficient_multiwindow_context' in r['reasons']
    measured = score(r, 120)
    assert not measured['within_4pct'] and measured['alias'] == 'unavailable'
    assert r['diagnostic_winner_not_deployed_if_abstained'] == 120


def test_half_double_candidates_remain_errors():
    assert score({'status': 'estimated', 'bpm': 150, 'candidates': []}, 75)['alias'] == 'half_double'
    assert not score({'status': 'estimated', 'bpm': 150, 'candidates': []}, 75)['within_4pct']
    assert score({'status': 'estimated', 'bpm': 105, 'candidates': []}, 157)['alias'] == 'other'


def test_near_alias_scores_trigger_explicit_abstention():
    scores = np.full(len(BPMS), .01)
    scores[80 - 40], scores[160 - 40] = 1., .9
    records = [{'scale': scale, 'scores': scores.copy()} for scale in [4, 8, 12]]
    result = selection(scores, records)
    assert result['bpm'] is None and 'half_double_ambiguity' in result['reasons']
    assert result['diagnostic_winner_not_deployed_if_abstained'] == 80


def test_flat_sustained_activity_not_strong_rhythmic_evidence():
    result, diagnostic = estimate(np.ones(2400))
    assert all(r['bpm'] is None for r in result.values())
    assert diagnostic['informative_scale_count'] == 0


def test_window_report_has_all_attempted_windows_including_silence():
    env = pulses()
    env[800:2000] = 0
    rows = window_scores(env, 4)
    assert any(r['scores'] is None for r in rows)
    result, diagnostic = estimate(env)
    assert len(diagnostic['windows']) >= len(rows)
    assert set(result) == set(METHODS)


def test_no_best_candidate_is_relabelled_as_final_accuracy():
    x = {'status': 'estimated', 'bpm': 150, 'candidates': [{'bpm': 75}]}
    measured = score(x, 75)
    assert measured['candidate_recall_at3'] and not measured['within_4pct']

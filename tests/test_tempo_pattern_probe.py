"""Tempo-only contracts: no downbeat/meter gating, no label-aware selection."""
from __future__ import annotations

import inspect

import numpy as np
import pytest

from scripts.tempo_pattern_probe import (
    ENV_RATE,
    METHODS,
    audio_flux,
    estimate,
    event_envelope,
    score_tempo,
    select_audio,
    summarize,
)


def pulses(period=.5, duration=12., subdivisions=1, shift=0.):
    return [(float(t + shift), 1.) for t in np.arange(0, duration, period / subdivisions)
            if t + shift < duration]


def test_no_meter_downbeat_or_truth_bpm_parameter():
    assert set(inspect.signature(estimate).parameters) == {'env', 'unique_hit_count', 'duration'}
    assert set(inspect.signature(audio_flux).parameters) == {'samples', 'sr'}


def test_half_bar_phase_ambiguity_does_not_block_bpm():
    env, count = event_envelope(pulses(), 12.)
    result = estimate(env, unique_hit_count=count, duration=12.)
    assert result['acf_prior120']['status'] == 'estimated'
    assert abs(result['acf_prior120']['bpm'] - 120) <= 2


def test_shifted_rhythm_keeps_rate_without_barline():
    a, na = event_envelope(pulses(shift=.15), 12.)
    b, nb = event_envelope(pulses(shift=.65), 12.)
    pa = estimate(a, unique_hit_count=na, duration=12.)
    pb = estimate(b, unique_hit_count=nb, duration=12.)
    assert abs(pa['acf_prior120']['bpm'] - pb['acf_prior120']['bpm']) <= 2


def test_more_hits_is_not_ground_truth_faster_tempo():
    a, na = event_envelope(pulses(subdivisions=1), 12.)
    b, nb = event_envelope(pulses(subdivisions=2), 12.)
    assert nb == 2 * na
    pa = estimate(a, unique_hit_count=na, duration=12.)
    pb = estimate(b, unique_hit_count=nb, duration=12.)
    assert pb['count_negative_control']['bpm'] == 2 * pa['count_negative_control']['bpm']
    assert any(abs(v['bpm'] / 120 - 1) <= .04 for v in pb['acf_prior120']['candidates'])


def test_event_coincidence_is_not_counted_as_two_time_instants():
    _, count = event_envelope([(0.5, 1.), (0.5, .7), (1., 1.)], 4.)
    assert count == 2


@pytest.mark.parametrize('env', [np.zeros(800), np.zeros(80)])
def test_absent_or_short_evidence_is_not_fabricated_as_120(env):
    result = estimate(env, unique_hit_count=0, duration=len(env) / ENV_RATE)
    assert set(result) == set(METHODS)
    assert all(v['bpm'] is None for v in result.values())


@pytest.mark.parametrize('env', [np.array([np.nan] * 800), -np.ones(800), np.ones((2, 800))])
def test_invalid_envelope_fails_closed(env):
    with pytest.raises(ValueError):
        estimate(env, unique_hit_count=1, duration=8.)


def test_algorithms_do_not_mutate_input():
    env, count = event_envelope(pulses(), 12.)
    original = env.copy()
    estimate(env, unique_hit_count=count, duration=12.)
    assert np.array_equal(env, original)


def test_aliases_and_candidate_oracle_are_separate_metrics():
    result = {'status': 'estimated', 'bpm': 60., 'candidates': [{'bpm': 120.}]}
    score = score_tempo(result, 120.)
    assert score['alias'] == 'half_double'
    assert not score['within_4pct']
    assert score['candidate_recall_at_3']
    assert score_tempo({'status': 'estimated', 'bpm': 124., 'candidates': []}, 120.)['within_4pct']
    assert not score_tempo({'status': 'estimated', 'bpm': 126., 'candidates': []}, 120.)['within_4pct']


def test_audio_envelope_runs_without_instrument_or_reference_inputs():
    t = np.arange(16000 * 5) / 16000
    y = np.sin(2 * np.pi * 120 * t) * (np.mod(t, .5) < .05)
    env = audio_flux(y)
    assert env.ndim == 1 and np.isfinite(env).all() and env.min() >= 0
    assert len(env) > 400
    assert np.count_nonzero(audio_flux(np.zeros_like(y))) == 0


def test_audio_selection_is_deterministic_disjoint_and_metadata_only():
    old = {'id': 'old', 'split': 'validation', 'time_signature': '3-4',
           'beat_type': 'beat', 'duration': '80'}
    rows = [old] + [{'id': f'b{i}', 'split': 'test', 'time_signature': '4-4',
                    'beat_type': 'beat', 'duration': '20'} for i in range(10)]
    rows += [{'id': f'f{i}', 'split': 'test', 'time_signature': '4-4',
              'beat_type': 'fill', 'duration': '7'} for i in range(4)]
    first = select_audio(rows, ['old'])
    second = select_audio(list(reversed(rows)), ['old'])
    assert first == second and len(first) == 9
    assert len({r['id'] for r, _ in first}) == 9
    assert first[0][1] == 'previous_audio_cases'
    assert all(cohort == 'additional_test_audio' for _, cohort in first[1:])


def scored_row(name):
    return {'id': name, 'cohort': 'test', 'status': 'scored', 'representations': {
        'hits': {'methods': {m: {'evaluation': score_tempo(
            {'status': 'estimated', 'bpm': 120., 'candidates': []}, 120.)} for m in METHODS}}}}


def test_missing_and_duplicated_cases_refuse_full_summary():
    row = scored_row('a')
    assert summarize([row], ['a', 'b']) is None
    assert summarize([row, row], ['a', 'b']) is None


def test_failures_keep_all_planned_denominator():
    rows = [scored_row('a'), {'id': 'b', 'cohort': 'test', 'status': 'failed'}]
    summary = summarize(rows, ['a', 'b'])
    assert not summary['all_cases_evaluated']
    for row in summary['groups']['test/hits'].values():
        assert row['planned'] == 2 and row['within_4pct'] == 1
        assert row['within_4pct_rate_all_planned'] == .5
        assert row['unavailable_or_failed'] == 1

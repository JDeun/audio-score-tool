"""No-reference selector contracts, not performance-based parameter tuning."""
from __future__ import annotations

import inspect
import math

import pytest

from scripts.tempo_unit_selector import (
    METHODS,
    SETTINGS,
    SPELLINGS,
    choose,
    coordinate_seconds,
    duration_costs,
    evaluate,
    identifiability_control,
    infer_units,
    notation_cost,
    pulse_coordinate,
    split_span,
)


def example():
    pulses = tuple(i * .5 for i in range(41))
    events = tuple((i * .25 + .01, 'kick' if i % 2 == 0 else 'backbeat')
                   for i in range(80))
    return pulses, events


def test_interface_has_no_reference_or_meter_input():
    assert tuple(inspect.signature(infer_units).parameters) == ('pulses', 'events')


def test_interval_spelling_dp_is_exact_against_direct_recurrence():
    costs = duration_costs()
    expected = [0.]
    for size in range(1, 97):
        expected.append(min(expected[size - d] + c for d, c in SPELLINGS if d <= size))
    assert costs == tuple(expected)
    assert costs[24] == 1.
    assert costs[12] == 1.15


@pytest.mark.parametrize('bar,phase,start,end', [(72, 0, -10, 210), (96, 24, 3, 304),
                                               (96, 0, 0, 96), (72, 30, 20, 21)])
def test_partition_preserves_total_exactly(bar, phase, start, end):
    result = split_span(start, end, bar, phase)
    assert sum(result) == end - start
    assert all(0 < x <= bar for x in result)


@pytest.mark.parametrize('t', [0., .12, .5, 2.8, 6.5])
def test_pulse_coordinate_roundtrip_even_with_jitter_or_extrapolation(t):
    pulses = (0.1, .58, 1.13, 1.61, 2.10, 2.61, 3.14)
    assert coordinate_seconds(pulse_coordinate(t, pulses), pulses) == pytest.approx(t)


def test_units_share_exactly_the_same_seconds_grid():
    pulses, events = example()
    for t, _ in events:
        p = round(pulse_coordinate(t, pulses) * 12) / 12
        expected = coordinate_seconds(p, pulses)
        for unit in (.5, 1., 2.):
            q = p * unit
            assert coordinate_seconds(q / unit, pulses) == pytest.approx(expected)


def test_inference_does_not_mutate_or_reorder_observations():
    pulses, events = example()
    first = infer_units(pulses, events)
    assert first == infer_units(pulses, events)
    assert first['input_event_count'] == len(events)
    assert set(first['methods']) == set(METHODS)
    assert [r['unit'] for r in first['candidates']] == [.5, 1., 2.]
    assert [r['qpm'] for r in first['candidates']] == [60., 120., 240.]


def test_shift_invariance_without_a_given_downbeat():
    pulses, events = example()
    a = infer_units(pulses, events)
    b = infer_units(tuple(x + 3 for x in pulses), tuple((t + 3, r) for t, r in events))
    assert a['methods'] == b['methods']
    assert a['candidates'] == b['candidates']


def test_known_role_streams_are_not_concatenated_in_time():
    a = [(i * 12, 'kick') for i in range(10)]
    b = sorted(a + [(t, 'backbeat') for t, _ in a])
    left, right = notation_cost(a, 1.), notation_cost(b, 1.)
    assert left['cost'] == right['cost']
    assert right['positive_spans'] == 2 * left['positive_spans']


def test_collisions_are_counted_not_claimed_corrected():
    x = notation_cost([(0, 'all'), (0, 'all'), (12, 'all'), (24, 'all')], 1.)
    assert x['snapped_collisions'] == 1


def test_exact_ties_abstain_without_first_candidate_bias():
    rows = [{'unit': u, 'qpm': 120 * u, 'cost': 1.} for u in (.5, 1., 2.)]
    assert choose(rows, 'cost')['status'] == 'abstained'
    assert choose(rows[::-1], 'cost') == choose(rows, 'cost')


def test_margin_does_not_turn_ambiguous_scores_into_confidence():
    rows = [{'unit': u, 'qpm': 120 * u, 'cost': c}
            for u, c in ((.5, 1.0), (1., 1.05), (2., 2.))]
    assert choose(rows, 'cost')['unit'] == .5
    assert choose(rows, 'cost', .1)['unit'] is None


def test_empty_events_are_unavailable_not_falsely_accurate():
    pulses, _ = example()
    result = infer_units(pulses, ())
    assert all(result['methods'][m]['status'] == 'insufficient_context' for m in METHODS[2:])


@pytest.mark.parametrize('pulses,events', [((0, 1, 1, 2), ()),
                                         ((0, 1, math.nan, 3), ()),
                                         ((0, 1, 2, 3), ((1, 'unknown'),)),
                                         ((0, 1, 2, 3), ((2, 'kick'), (1, 'kick')))])
def test_bad_observations_rejected(pulses, events):
    with pytest.raises(ValueError):
        infer_units(pulses, events)


def test_identical_observations_cannot_recover_two_different_units():
    control = identifiability_control()
    for method in METHODS:
        a = control['evaluation_only']['75.0'][method]
        b = control['evaluation_only']['150.0'][method]
        assert not (a['correct'] and b['correct'])


def test_reference_is_only_in_evaluator_and_boundaries_are_inclusive():
    assert evaluate({'qpm': 124.8}, 120)['correct']
    assert evaluate({'qpm': 240.}, 120)['error_type'] == 'half_double'
    assert not evaluate({'qpm': None}, 120)['selected']
    assert SETTINGS['reference_or_meter_input'] is False

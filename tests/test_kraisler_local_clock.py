"""Synthetic support boundaries; never load the real six-recording cohort."""
from __future__ import annotations

import copy
import json
from dataclasses import FrozenInstanceError
from fractions import Fraction as Q
from types import SimpleNamespace as NS

import pytest

from scripts.kraisler_local_clock import build_local_clocks


def measure(start, end, meter, *, pickup=False, final=False):
    return NS(part='P1', onset_q=Q(start), end_q=Q(end), time_signature=meter,
              nominal_duration_q=Q(4 * meter[0], meter[1]), pickup=pickup,
              short_final=final)


def score(n=5):
    return NS(admissible_for_alignment=True, measures=(measure(0, n, (n, 4)),))


def beats(times, meter):
    return tuple(NS(time=t, kind='db' if i == 0 else 'b', meter=meter)
                 for i, t in enumerate(times))


def match(points, *, admitted=True):
    return NS(strict_score_consistency=admitted,
              anchors=tuple(NS(q=Q(q), time=t) for q, t in points))


def build(points=None, times=None, n=5):
    times = tuple(i / 2 for i in range(n)) if times is None else tuple(times)
    points = tuple(enumerate(times)) if points is None else points
    s = score(n)
    return build_local_clocks(s, s, match(points), beats(times, (n, 4)))


def test_monotone_source_support_is_observed_span_not_whole_score():
    b, p, audit = build()
    assert audit['status'] == 'admitted'
    assert audit['beat_cells'] == audit['supported_beat_cells'] == 4
    assert audit['unsupported_beat_cells'] == 0 and audit['support_components'] == 1
    assert audit['observed_score_quarters'] == audit['supported_score_quarters'] == 4
    assert audit['whole_score_quarters'] == 5
    assert audit['support_denominator'] == 'observed structural beat range'
    assert audit['supported_score_quarters_exact'] == '4'
    for c in (b, p):
        assert c.time_at(Q(3, 2)) == .75
        assert c.supports_interval(0, 4)
        assert not c.supports_interval(0, 5)
        assert c.supports_time_band(2, 1.)
        assert not c.supports_time_band(2, 1.000001)
        assert c.time_at(-1) is None and c.time_at(Q(41, 10)) is None
    assert b.candidate_time_at(4) == 2.
    assert b.candidate_time_at(Q(41, 10)) is None
    assert b.period_at(0) == b.period_at(4) == .5


@pytest.mark.parametrize('right_time,reverse,equal', [(1.5, 1, 0), (1.6, 0, 1)])
def test_nonincreasing_edge_quarantines_both_nodes_and_all_incident_edges(right_time, reverse, equal):
    points = [(0, 0.), (1, .5), (2, 1.6), (3, right_time),
              (4, 2.), (5, 2.5), (6, 3.), (7, 3.5)]
    b, p, audit = build(points, n=8)
    assert audit['piano_nonincreasing_edges'] == 1
    assert audit['piano_reversal_edges'] == reverse
    assert audit['piano_equal_time_edges'] == equal
    assert audit['piano_quarantined_anchor_groups'] == 2
    assert audit['piano_trusted_edges'] == 4
    assert audit['piano_edge_rejection_counts'] == {'quarantined_anchor_incident': 3}
    assert audit['supported_beat_cells'] == 4 and audit['unsupported_beat_cells'] == 3
    assert audit['support_components'] == 2
    for c in (b, p):
        assert c.time_at(2) is None and c.time_at(3) is None
        assert c.time_at(Q(3, 2)) is None and c.time_at(Q(7, 2)) is None
        assert c.time_at(Q(1, 2)) == .25 and c.time_at(Q(9, 2)) == 2.25
        assert not c.supports_interval(Q(1, 2), Q(9, 2))
        assert not c.supports_time_band(2, 0)
        assert c.supports_time_band(Q(1, 2), .25)
    # Unsupported source attacks remain visible to the caller's competitor graph.
    assert b.candidate_time_at(2) == 1. and b.period_at(2) == .5


def test_unsupported_fraction_boundaries_cannot_be_revived_by_float_rounding():
    b, p, _ = build([(0, 0.), (1, .5), (2, 1.6), (3, 1.5),
                     (4, 2.), (5, 2.5), (6, 3.), (7, 3.5)], n=8)
    tiny = Q(1, 10**30)
    for c in (b, p):
        assert c.time_at(Q(1) + tiny) is None
        assert c.time_at(Q(4) - tiny) is None
        assert c.time_at(2) is None
        assert not c.supports_interval(Q(1) - tiny, Q(1) + tiny)
        assert not c.supports_time_band(1, 1e-30)
        assert not c.supports_time_band(4, 1e-30)
        assert c.supports_time_band(1, 0)


def test_large_piano_quarter_gap_does_not_bridge_to_retained_anchors():
    b, p, audit = build([(0, 0.), (5, 2.5), (6, 3.), (7, 3.5)], n=8)
    assert audit['piano_edge_rejection_counts'] == {'piano_quarter_gap': 1}
    assert audit['supported_beat_cells'] == 2
    assert audit['supported_score_quarters'] == 2
    for c in (b, p):
        assert c.time_at(0) is None  # Isolated exact anchor is not interval support.
        assert c.time_at(3) is None
        assert c.time_at(6) == 3.
        assert not c.supports_interval(0, 7)
    assert b.candidate_time_at(3) == 1.5


def test_large_piano_seconds_gap_rejects_even_shorter_individual_beat_cells():
    times = (0., 2., 4., 4.5, 5.)
    b, p, audit = build([(0, 0.), (2, 4.), (3, 4.5), (4, 5.)], times)
    assert audit['piano_edge_rejection_counts'] == {'piano_seconds_gap': 1}
    assert audit['beat_cell_rejection_counts'] == {'piano_interval_unsupported': 2}
    assert audit['supported_beat_cells'] == 2
    assert b.time_at(1) is p.time_at(1) is None
    assert b.candidate_time_at(1) == 2.


def test_large_beat_gap_is_unsupported_even_with_fully_trusted_piano_edges():
    times = (0., .5, 4.5, 5., 5.5)
    points = [(0, 0.), (1, .5), (Q(3, 2), 2.5), (2, 4.5), (3, 5.), (4, 5.5)]
    b, p, audit = build(points, times)
    assert audit['piano_trusted_edges'] == 5
    assert audit['beat_cell_rejection_counts'] == {'beat_seconds_gap': 1}
    assert audit['support_components'] == 2
    assert b.time_at(Q(3, 2)) is p.time_at(Q(3, 2)) is None
    assert b.candidate_time_at(Q(3, 2)) == 2.5
    assert b.period_at(Q(3, 2)) == 4.
    for c in (b, p):
        assert c.time_at(1) == .5 and c.time_at(2) == 4.5
        assert not c.supports_interval(1, 2)
        assert not c.supports_time_band(1, .01)
        assert not c.supports_time_band(2, .01)


def test_gap_boundaries_are_inclusive_without_adding_extra_gap_tolerance():
    b, p, audit = build([(0, 0.), (4, 3.)], (0., .75, 1.5, 2.25, 3.))
    assert audit['supported_beat_cells'] == 4
    assert b.supports_interval(0, 4) and p.supports_interval(0, 4)
    b, p, audit = build([(0, 0.), (Q(4) + Q(1, 10**20), 3.)], n=6)
    assert b is p is None
    assert audit['piano_edge_rejection_counts']['piano_quarter_gap'] == 1
    b, p, audit = build([(0, 0.), (4, 3.000000001)], n=5)
    assert b is p is None
    assert audit['piano_edge_rejection_counts']['piano_seconds_gap'] == 1


def test_interior_piano_breakpoint_disagreement_rejects_matching_endpoint_cell():
    points = [(0, 0.), (1, .5), (Q(3, 2), .95), (2, 1.), (3, 1.5), (4, 2.)]
    b, p, audit = build(points)
    assert audit['piano_quarantined_anchor_groups'] == 0
    assert audit['beat_cell_rejection_counts'] == {'clock_disagreement': 1}
    assert audit['support_components'] == 2 and audit['supported_beat_cells'] == 3
    assert audit['maximum_compared_clock_disagreement_seconds'] == pytest.approx(.2)
    for c in (b, p):
        assert c.time_at(1) == .5 and c.time_at(2) == 1.
        assert c.time_at(Q(3, 2)) is None
        assert not c.supports_interval(1, 2)
    assert b.candidate_time_at(Q(3, 2)) == .75


@pytest.mark.parametrize('shift,admitted', [(.1, True), (.10000001, False)])
def test_fixed_clock_agreement_limit_is_not_enlarged_by_future_note_window(shift, admitted):
    b, p, audit = build([(i, i / 2 + shift) for i in range(5)])
    assert (audit['status'] == 'admitted') is admitted
    if not admitted:
        assert b is p is None
        assert audit['beat_cell_rejection_counts'] == {'clock_disagreement': 4}


def test_period_uses_actual_pulse_and_smaller_neighbor_at_exact_boundary():
    b, _, _ = build(times=(0., .6, 1., 1.8), n=4)
    assert b.period_at(0) == pytest.approx(.6)
    assert b.period_at(Q(1, 2)) == pytest.approx(.6)
    assert b.period_at(1) == pytest.approx(.4)
    assert b.period_at(2) == pytest.approx(.4)
    assert b.period_at(Q(5, 2)) == pytest.approx(.8)
    assert b.period_at(3) == pytest.approx(.8)
    assert b.period_at(-1) is None and b.period_at(Q(31, 10)) is None


def test_compound_meter_period_is_dotted_pulse_not_quarter_seconds():
    s = NS(admissible_for_alignment=True,
           measures=(measure(0, 3, (6, 8)), measure(3, 6, (6, 8))))
    observed = (NS(time=0., kind='db', meter=(6, 8)), NS(time=.6, kind='b', meter=(6, 8)),
                NS(time=1.2, kind='db', meter=(6, 8)), NS(time=1.8, kind='b', meter=(6, 8)))
    m = match([(0, 0.), (Q(3, 2), .6), (3, 1.2), (Q(9, 2), 1.8)])
    b, p, audit = build_local_clocks(s, s, m, observed)
    assert audit['observed_score_quarters'] == audit['supported_score_quarters'] == 4.5
    assert b.period_at(Q(3, 2)) == pytest.approx(.6)
    assert b.time_at(Q(3, 4)) == p.time_at(Q(3, 4)) == .3


def test_short_pickup_never_gets_an_invented_beat_or_extrapolated_support():
    s = NS(admissible_for_alignment=True,
           measures=(measure(0, Q(1, 4), (2, 4), pickup=True),
                     measure(Q(1, 4), Q(9, 4), (2, 4))))
    b, p, audit = build_local_clocks(
        s, s, match([(Q(1, 4), .2), (Q(5, 4), .8)]), beats((.2, .8), (2, 4)))
    assert audit['observed_score_quarters'] == 1
    assert audit['whole_score_quarters'] == 2.25
    assert b.candidate_time_at(0) is None and b.period_at(0) is None
    assert b.time_at(0) is p.time_at(0) is None
    assert b.time_at(Q(1, 4)) == .2


def test_structural_ambiguity_is_not_resolved_using_the_better_timing_candidate():
    s = NS(admissible_for_alignment=True,
           measures=(measure(0, 4, (4, 4)), measure(4, 8, (4, 4))))
    b, p, audit = build_local_clocks(s, s, match([(i, i / 2) for i in range(8)]),
                                    beats((0., .5, 1., 1.5), (4, 4)))
    assert b is p is None and audit['structural_candidate_count'] == 2
    assert audit['observed_score_quarters'] is None
    assert audit['supported_score_quarters'] == 0
    assert audit['unsupported_beat_cells'] == 3


def test_no_structural_sequence_returns_clear_unmapped_denominator():
    s = score()
    b, p, audit = build_local_clocks(s, s, match([(0, 0.), (4, 2.)]),
                                    beats((0., .5, 1.), (3, 4)))
    assert b is p is None and audit['structural_candidate_count'] == 0
    assert audit['observed_score_quarters'] is None
    assert audit['support_components'] == 0


@pytest.mark.parametrize('failure', ['match', 'score', 'piano', 'measure', 'two_parts'])
def test_unadmitted_symbolic_sources_never_receive_local_clock(failure):
    s, piano, m = score(), score(), match([(i, i / 2) for i in range(5)])
    if failure == 'match':
        m.strict_score_consistency = False
    elif failure == 'score':
        s.admissible_for_alignment = False
    elif failure == 'piano':
        piano.admissible_for_alignment = False
    elif failure == 'measure':
        piano.measures[0].pickup = True
    else:
        piano.measures += (NS(**{**vars(piano.measures[0]), 'part': 'P2'}),)
    b, p, audit = build_local_clocks(s, piano, m, beats((0., .5, 1., 1.5, 2.), (5, 4)))
    assert b is p is None and audit['status'] == 'unadmitted'
    assert audit['supported_beat_cells'] == 0


def test_duplicate_quarter_anchors_use_unchanged_median_without_removing_notes():
    points = [(0, 0.), (0, .1), (1, .5), (2, 1.), (3, 1.5), (4, 2.)]
    b, p, audit = build(points)
    assert p.time_at(0) == .05 and b.time_at(0) == 0.
    assert audit['eligible_piano_anchor_notes'] == 6 and audit['piano_anchor_groups'] == 5
    assert audit['coincident_group_max_spread_seconds'] == .1
    assert audit['deleted_anchor_bridging'] is False


@pytest.mark.parametrize('points', [[], [(0, 0.)], [(0, 0.), (0, .1)]])
def test_too_few_distinct_piano_positions_are_unadmitted(points):
    b, p, audit = build(points)
    assert b is p is None
    assert audit['supported_beat_cells'] == 0
    assert audit['observed_score_quarters'] == 4


def test_whole_recording_ninety_percent_rule_is_not_reapplied_to_local_support():
    b, p, audit = build([(0, 0.), (6, 3.), (7, 3.5)], n=8)
    assert b is not None and p is not None and audit['status'] == 'admitted'
    assert audit['supported_beat_cells'] == 1 and audit['beat_cells'] == 7
    assert audit['supported_fraction_of_observed_score'] == pytest.approx(1 / 7)


def test_band_must_use_its_score_component_even_when_component_times_overlap():
    times = (0., .4, .45, .5, .55, .6, 1.)
    points = [(0, 0.), (1, .5), (2, .8), (3, .1), (4, .45), (5, .5), (6, .9)]
    b, p, audit = build(points, times, n=7)
    assert audit['support_components'] == 2
    assert p.time_at(1) == .5 and p.time_at(4) == .45
    # A global union of performance ranges would incorrectly pass these.
    assert not p.supports_time_band(1, .01)
    assert not p.supports_time_band(4, .01)
    assert not b.supports_interval(Q(1, 2), Q(9, 2))
    assert not p.supports_interval(Q(1, 2), Q(9, 2))


@pytest.mark.parametrize('bad', [-.1, float('nan'), float('inf'), True, None])
def test_malformed_clock_values_are_rejected(bad):
    with pytest.raises(ValueError):
        build([(0, bad), (1, .5), (2, 1.), (3, 1.5), (4, 2.)])
    with pytest.raises(ValueError):
        build(times=(bad, .5, 1., 1.5, 2.))


def test_nonincreasing_observed_beats_are_malformed_not_repaired():
    with pytest.raises(ValueError, match='strictly increasing'):
        build(times=(0., .5, .5, 1.5, 2.))
    with pytest.raises(ValueError, match='strictly increasing'):
        build(times=(0., .5, .4, 1.5, 2.))


@pytest.mark.parametrize('bad', [-.1, float('nan'), float('inf'), True, None])
def test_invalid_band_width_is_rejected_instead_of_extending_support(bad):
    b, p, _ = build()
    for c in (b, p):
        with pytest.raises(ValueError):
            c.supports_time_band(2, bad)


def test_interval_order_and_outside_queries_are_conservative():
    b, p, _ = build()
    for c in (b, p):
        assert not c.supports_interval(2, 2)
        assert not c.supports_interval(3, 2)
        assert not c.supports_time_band(-1, 0)
        with pytest.raises(ValueError):
            c.time_at(float('nan'))
        with pytest.raises(ValueError):
            c.time_at(True)


def test_inputs_and_clocks_are_immutable_and_public_audit_has_no_arrays():
    s, m, observed = score(), match([(i, i / 2) for i in range(5)]), beats((0., .5, 1., 1.5, 2.), (5, 4))
    before = copy.deepcopy((s, m, observed))
    b, p, audit = build_local_clocks(s, s, m, observed)
    assert (s, m, observed) == before
    with pytest.raises(FrozenInstanceError):
        b.new_value = 1
    with pytest.raises(FrozenInstanceError):
        p._points = ()
    assert repr(b) == 'LocalBeatClock()' and repr(p) == 'LocalClock()'
    assert all(not isinstance(v, (list, tuple)) for v in audit.values())
    assert all(len(value) == 64 for key, value in audit.items() if key.endswith('_sha256'))
    json.dumps(audit, allow_nan=False)


def test_anchor_hash_is_input_order_independent_but_detects_changed_source_times():
    points = [(0, 0.), (1, .5), (2, 1.), (3, 1.5), (4, 2.)]
    _, _, a = build(points)
    _, _, b = build(list(reversed(points)))
    assert a == b
    points[2] = (2, 1.01)
    _, _, c = build(points)
    assert c['piano_original_anchors_sha256'] != a['piano_original_anchors_sha256']
    assert c['piano_median_anchors_sha256'] != a['piano_median_anchors_sha256']
    assert c['accepted_components_sha256'] == a['accepted_components_sha256']

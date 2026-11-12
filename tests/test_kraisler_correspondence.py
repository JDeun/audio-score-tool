"""Meaningful source-clock, ambiguity, and immutable-ledger contracts."""
from __future__ import annotations

import copy
import hashlib
from fractions import Fraction as Q
from types import SimpleNamespace as NS

import pytest

from scripts import kraisler_correspondence as c


def event(q, pitch=60, *, ident='n0', grace=False, ornaments=(), articulations=()):
    return NS(onset_q=Q(q), end_q=Q(q) + (0 if grace else Q(1, 2)), midi=pitch,
              id=ident, grace=grace, ornaments=ornaments, articulations=articulations)


def measure(start=0, end=4, meter=(4, 4), *, pickup=False, final=False):
    return NS(part='P1', onset_q=Q(start), end_q=Q(end), time_signature=meter,
              nominal_duration_q=Q(4 * meter[0], meter[1]), pickup=pickup, short_final=final)


def score(events=(), measures=None, rests=()):
    return NS(admissible_for_alignment=True, measures=tuple(measures or [measure()]),
              events=tuple(events), attacks=tuple(events), rests=tuple(rests),
              global_rests=tuple(rests), unknown_intervals=(), counts={'events': len(events)},
              warnings=(), unsupported=())


def clock():
    return c.Clock(((Q(0), 0.), (Q(2), 2.), (Q(4), 4.)))


def source_beats(times=(0., 1., 2., 3.)):
    return tuple(c.Beat(t, 'db' if i == 0 else 'b', (4, 4), True, True)
                 for i, t in enumerate(times))


def test_clock_refuses_repairs_extrapolation_and_unsupported_gap():
    with pytest.raises(ValueError, match='strictly increasing'):
        c.Clock(((Q(0), 1.), (Q(1), .9)))
    with pytest.raises(ValueError, match='strictly increasing'):
        c.Clock(((Q(0), 0.), (Q(0), 1.)))
    ordinary = clock()
    assert ordinary.time_at(Q(1, 2)) == .5
    assert ordinary.time_at(Q(-1)) is None
    assert ordinary.time_at(Q(5)) is None
    gap = c.Clock(((Q(0), 0.), (Q(5), 2.), (Q(6), 3.)))
    assert gap.time_at(Q(1)) is None
    assert gap.time_at(Q(5)) == 2.
    assert not gap.supports_interval(Q(0), Q(6))
    slow = c.Clock(((Q(0), 0.), (Q(1), 4.)))
    assert slow.time_at(Q(1, 2)) is None


def test_piano_median_does_not_hide_nonmonotone_group_sequence():
    anchors = (NS(q=Q(0), time=0.), NS(q=Q(0), time=.02), NS(q=Q(1), time=1.))
    value, audit = c.piano_clock(NS(strict_score_consistency=True, anchors=anchors))
    assert value.time_at(Q(0)) == .01
    assert audit['eligible_note_anchors'] == 3
    assert audit['coincident_group_max_spread_s'] == .02
    with pytest.raises(ValueError, match='symbolic consistency'):
        c.piano_clock(NS(strict_score_consistency=False, anchors=anchors))


def test_symbolic_grid_preserves_fractional_pickup_and_compound_meter():
    pickup = score(measures=[measure(0, Q(1, 4), (2, 4), pickup=True),
                             measure(Q(1, 4), Q(9, 4), (2, 4))])
    assert c.symbolic_beats(pickup) == ((Q(1, 4), 'db', (2, 4)), (Q(5, 4), 'b', (2, 4)))
    compound = score(measures=[measure(0, 3, (6, 8)), measure(3, 5, (2, 4))])
    assert c.symbolic_beats(compound) == ((Q(0), 'db', (6, 8)), (Q(3, 2), 'b', (6, 8)),
                                        (Q(3), 'db', (2, 4)), (Q(4), 'b', (2, 4)))
    pickup3 = score(measures=[measure(0, 1, (3, 4), pickup=True), measure(1, 4, (3, 4))])
    assert c.symbolic_beats(pickup3)[0] == (Q(0), 'b', (3, 4))


def test_beat_map_never_fits_a_constant_shift_to_pass():
    s = score()
    result, audit = c.align_beats(s, s, source_beats(), clock())
    assert audit['status'] == 'admitted'
    assert result.time_at(Q(1, 2)) == .5
    result, audit = c.align_beats(s, s, source_beats((.2, 1.2, 2.2, 3.2)), clock())
    assert result is None
    assert audit['candidates'][0]['residuals']['median_s'] == pytest.approx(.2)
    assert 'median_s exceeds fixed bound or unavailable' in audit['candidates'][0]['rejection_reasons']


def test_beat_map_refuses_different_score_bars_and_missing_support():
    s = score()
    other = score(measures=[measure(0, 1, (4, 4), pickup=True)])
    assert c.align_beats(s, other, source_beats(), clock())[0] is None
    late = c.Clock(((Q(2), 2.), (Q(4), 4.)))
    _, audit = c.align_beats(s, s, source_beats(), late)
    assert audit['status'] == 'unadmitted'
    assert audit['candidates'][0]['supported_fraction'] == .5


def test_two_passing_structural_candidates_are_ambiguous_not_ranked():
    s = score(measures=[measure(0, 4), measure(4, 8)])
    compressed = c.Clock(((Q(0), 0.), (Q(4), .1), (Q(8), .2)))
    observed = source_beats((.1, .125, .15, .175))
    result, audit = c.align_beats(s, s, observed, compressed)
    assert result is None
    assert audit['structural_candidate_count'] == 2
    assert all(row['admitted'] for row in audit['candidates'])
    assert audit['reason'] == 'multiple candidates passed'


def test_mutual_uniqueness_rejects_repeated_pitch_ambiguity():
    refs = (c.Reference(.5, .9, 60),)
    s = score((event(Q(1, 2)), event(Q(3, 5), ident='n1')))
    pairs, result = c.pair_references(refs, s, clock(), clock(), 100)
    assert pairs == {}
    assert result['unresolved_reasons'] == {'reference_has_multiple_candidates': 1}
    pairs, result = c.pair_references(refs, s, clock(), clock(), 50)
    assert pairs == {0: 0}
    assert result['memberships']['unmarked'] == '1'


def test_mutual_uniqueness_rejects_multiple_references_for_one_attack():
    refs = (c.Reference(.48, .7, 60), c.Reference(.52, .9, 60))
    pairs, result = c.pair_references(refs, score((event(Q(1, 2)),)), clock(), clock(), 100)
    assert not pairs
    assert result['unresolved_reasons'] == {'score_attack_has_multiple_references': 2}


def test_pair_requires_same_identity_under_both_clocks():
    refs = (c.Reference(.5, .8, 60),)
    s = score((event(Q(1, 2)), event(Q(3, 4), ident='n1')))
    changed = c.Clock(((Q(0), 0.), (Q(3), 2.)))
    pairs, result = c.pair_references(refs, s, clock(), changed, 50)
    assert not pairs
    assert result['unresolved_reasons'] == {'clocks_disagree_on_identity': 1}


@pytest.mark.parametrize('kind', ['trill', 'tremolo', 'grace_context'])
def test_ornaments_and_grace_context_are_uniformly_excluded(kind):
    notes = [event(Q(1, 2), ornaments=() if kind == 'grace_context' else (kind,))]
    if kind == 'grace_context':
        notes.append(event(Q(1, 2), pitch=62, ident='g', grace=True))
    pairs, result = c.pair_references((c.Reference(.5, .9, 60),), score(notes), clock(), clock(), 100)
    assert not pairs
    assert result['unresolved_reasons'] == {'ornament_or_grace_context': 1}


def test_reference_offsets_cannot_select_correspondence():
    s = score((event(Q(1, 2), articulations=('staccato',)),))
    a, first = c.pair_references((c.Reference(.5, .6, 60),), s, clock(), clock(), 100)
    b, second = c.pair_references((c.Reference(.5, 3., 60),), s, clock(), clock(), 100)
    assert a == b == {0: 0}
    assert first == second
    assert first['memberships']['staccato'] == '1'


def test_rest_projection_preserves_note_overlap_and_shared_guard():
    rest = NS(onset_q=Q(1), end_q=Q(2))
    s = score(rests=(rest,))
    context = c.rest_context(s, (c.Reference(1.5, 2.5, 60),), clock(), clock())
    assert context['projected_rest_intervals'] == 1
    assert context['projections']['global_beats']['duration_s'] == 1.
    assert context['projections']['global_beats']['annotated_note_overlap_s'] == .5
    assert context['projections']['guarded_shared_core']['duration_s'] == pytest.approx(.8)
    assert context['projections']['guarded_shared_core']['annotated_note_overlap_s'] == pytest.approx(.4)
    assert context['written_rest_accuracy_measured'] is False


def test_rest_projection_does_not_bridge_an_unsupported_clock_gap():
    s = score(rests=(NS(onset_q=Q(0), end_q=Q(6)),))
    long_clock = c.Clock(((Q(0), 0.), (Q(5), 2.), (Q(6), 3.)))
    context = c.rest_context(s, (), long_clock, long_clock)
    assert context['projected_rest_intervals'] == 0
    assert context['unprojectable_rest_intervals'] == 1


@pytest.mark.parametrize('raw', [b'onset,offset,midi,velocity\n0,1,60,127\n0,1,60,127\n',
                               b'onset,offset,midi,velocity\n0,2,60,127\n',
                               b'onset,offset,midi,velocity\n0,1,nan,127\n',
                               b'onset,offset,midi,velocity\n.2,.1,60,127\n'])
def test_invalid_reference_rows_fail_without_clipping(raw):
    with pytest.raises(ValueError):
        c.read_notes(raw, 1.)


def test_beat_meter_must_be_established_and_times_must_increase():
    header = 'beat_time,beat_type,time_signature,piano,violin\n'
    for body in ('0,db,,True,True\n', '1,db,4/4,True,True\n1,b,,True,True\n',
                 '0,db,4/4,maybe,True\n'):
        with pytest.raises(ValueError):
            c.read_beats((header + body).encode(), 5.)


def ledger_fixture():
    memberships = {name: '000' for name in c.CATEGORIES}
    memberships.update(staccato='100', unmarked='010', unresolved='001')
    analysis = {'reference_count': 3, 'source_sha256': {'notes': 'n', 'beats': 'b'},
                'correspondence': {'windows': {'100': {'memberships': memberships}},
                                   'stable_across_windows': {'memberships': memberships}}}
    prior = {'status': 'scored', 'reference_sha256': 'n', 'beats_sha256': 'b', 'bases': {}}
    for base in c.BASES:
        prior['bases'][base] = {'arms': {}}
        for arm in c.ARMS:
            after = '101' if arm == 'raw' else '011'
            metrics = {'reference_note_count': 3, 'transition': {}}
            for metric in ('onset', 'onset_offset'):
                metrics[metric + '_reference_mask'] = after
                metrics[metric + '_f1'] = round(4 / 6, 8)
                metrics['transition'][metric] = {'gained': 0 if arm == 'raw' else 1,
                                                  'damaged': 0 if arm == 'raw' else 1}
            prior['bases'][base]['arms'][arm] = {'count': 3, 'metrics': metrics}
    return prior, analysis


def test_conditional_ledger_conserves_damage_and_unresolved_population():
    prior, analysis = ledger_fixture()
    result = c.attribute_previous_case(prior, analysis)
    groups = result['scopes']['primary_100ms']
    assert sum(g['reference_notes'] for g in groups.values()) == 3
    assert groups['staccato']['bases']['onset065']['tail_only']['onset_offset']['damaged'] == 1
    assert groups['unmarked']['bases']['onset065']['tail_only']['onset_offset']['gained'] == 1
    assert groups['unresolved']['bases']['onset065']['tail_only']['onset_offset']['matched'] == 1
    assert result['new_f1_computed'] is False
    assert result['prediction_false_positives_classified'] is False


@pytest.mark.parametrize('failure', ['source', 'partition', 'transition', 'count'])
def test_previous_identity_partition_and_arithmetic_mismatches_fail(failure):
    prior, analysis = ledger_fixture()
    if failure == 'source':
        prior['reference_sha256'] = 'changed'
    elif failure == 'partition':
        analysis['correspondence']['windows']['100']['memberships']['unmarked'] = '110'
    elif failure == 'transition':
        prior['bases']['default']['arms']['tail_only']['metrics']['transition']['onset']['gained'] = 2
    else:
        prior['bases']['default']['arms']['tail_only']['count'] = 4
    with pytest.raises(ValueError):
        c.attribute_previous_case(prior, analysis)


def test_exact_previous_receipt_is_reused_and_tampering_is_rejected(tmp_path):
    original = c.read_previous_receipt()
    assert original['summary']['scored_conditions'] == 48
    assert original['completed_recording_inferences'] == 6
    altered = bytearray(c.PRIOR_PATH.read_bytes())
    altered[-1] ^= 1
    dest = tmp_path / 'report.zip'
    dest.write_bytes(altered)
    with pytest.raises(ValueError, match='digest'):
        c.read_previous_receipt(dest)


def test_analysis_runs_source_only_and_keeps_all_unadmitted_references():
    notes = b'onset,offset,midi,velocity\n.5,.9,60,127\n'
    beats = b'beat_time,beat_type,time_signature,piano,violin\n0,db,4/4,True,True\n1,b,,True,True\n2,b,,True,True\n3,b,,True,True\n'
    s = score((event(Q(1, 2)),))
    match = NS(strict_score_consistency=False, diagnostics={'unverified_rows': 1}, anchors=())
    result = c.analyze_correspondence(s, s, match, beats, notes, 5.)
    assert result['source_sha256']['notes'] == hashlib.sha256(notes).hexdigest()
    for window in c.WINDOWS_MS:
        row = result['correspondence']['windows'][str(window)]
        assert row['matched_pairs'] == 0
        assert row['memberships']['unresolved'] == '1'
    assert result['new_model_inferences'] == 0


def test_stable_intersection_removes_pair_ambiguous_only_at_200ms():
    notes = b'onset,offset,midi,velocity\n.5,.9,60,127\n'
    beats = b'beat_time,beat_type,time_signature,piano,violin\n0,db,4/4,True,True\n1,b,,True,True\n2,b,,True,True\n3,b,,True,True\n'
    s = score((event(Q(1, 2)), event(Q(13, 20), ident='n1')))
    match = NS(strict_score_consistency=True, diagnostics={},
               anchors=tuple(NS(q=q, time=t) for q, t in clock().points))
    result = c.analyze_correspondence(s, s, match, beats, notes, 5.)
    rows = result['correspondence']['windows']
    assert rows['50']['matched_pairs'] == rows['100']['matched_pairs'] == 1
    assert rows['200']['matched_pairs'] == 0
    assert result['correspondence']['stable_across_windows']['matched_pairs'] == 0
    assert result['correspondence']['stable_across_windows']['memberships']['unresolved'] == '1'


def test_summary_requires_every_fixed_recording_and_conserves_categories():
    prior, analysis = ledger_fixture()
    analysis.update(beat_alignment={'status': 'unadmitted'},
                    rest_context={'status': 'source_clock_unadmitted', 'explicit_rest_elements': 1,
                                  'instrument_wide_rest_intervals': 1, 'unknown_score_intervals': 0,
                                  'projected_rest_intervals': 0, 'unprojectable_rest_intervals': 1})
    for window in c.WINDOWS_MS:
        analysis['correspondence']['windows'][str(window)] = {
            **copy.deepcopy(analysis['correspondence']['windows']['100']), 'matched_pairs': 2}
    analysis['correspondence']['stable_across_windows']['matched_pairs'] = 2
    cases = [{'id': tid, 'status': 'analyzed', 'analysis': copy.deepcopy(analysis),
              'attribution': c.attribute_previous_case(prior, analysis)} for tid in c.PLANNED_IDS]
    result = c.summarize_cases(cases)
    assert result['reference_notes'] == 18
    assert result['windows']['100']['matched_pairs'] == 12
    assert result['conditional_ledger']['primary_100ms']['unresolved']['reference_notes'] == 6
    assert c.summarize_cases(cases[:-1]) is None
    cases[-1]['id'] = cases[0]['id']
    assert c.summarize_cases(cases) is None

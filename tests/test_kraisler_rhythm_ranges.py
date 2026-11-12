"""Synthetic duration/range contracts; never reads recordings or cohort results."""
import json
import math
from dataclasses import dataclass, field, replace
from fractions import Fraction as F

import pytest

from scripts.kraisler_correspondence import CATEGORIES, Reference
from scripts.kraisler_rhythm_ranges import (
    duration_context,
    rest_range_context,
    source_expression_metadata,
    synthetic_controls,
)
from scripts.kraisler_score import parse_score


def note(q=1, *, pitch='C', chord=False, rest=False, articulations='', grace=False):
    ticks = F(q) * 120
    assert ticks.denominator == 1
    body = '<rest/>' if rest else f'<pitch><step>{pitch}</step><octave>4</octave></pitch>'
    return ('<note>' + ('<chord/>' if chord else '') + ('<grace/>' if grace else '') + body
            + ('' if grace else f'<duration>{ticks.numerator}</duration>')
            + f'<notations><articulations>{articulations}</articulations></notations></note>')


def xml(body, meter=(4, 4), extra=''):
    return ('<score-partwise><part id="P1"><measure number="1"><attributes><divisions>120</divisions>'
            f'<time><beats>{meter[0]}</beats><beat-type>{meter[1]}</beat-type></time></attributes>'
            + extra + body + '</measure></part></score-partwise>').encode()


def score(body, meter=(4, 4)):
    return parse_score(xml(body, meter))


@dataclass
class Clock:
    scale: float = 1.
    shift: float = 0.
    spans: tuple = ((F(0), F(4)),)
    period: float | None = 1.
    band_calls: list = field(default_factory=list)

    def time_at(self, q):
        return float(q) * self.scale + self.shift if any(a <= q <= b for a, b in self.spans) else None

    def supports_interval(self, start, end):
        return any(a <= start < end <= b for a, b in self.spans)

    def supports_time_band(self, q, width):
        self.band_calls.append((q, width))
        return any(a <= q <= b and float(a) * self.scale + self.shift <= self.time_at(q) - width
                   and self.time_at(q) + width <= float(b) * self.scale + self.shift
                   for a, b in self.spans)

    def period_at(self, q):
        return self.period


def test_duration_categories_quantiles_and_all_reference_denominators():
    symbolic = score(note(articulations='<staccato/>')
                     + note(pitch='D', chord=True)
                     + note(pitch='E', chord=True, articulations='<accent/>')
                     + note(pitch='F', chord=True, articulations='<tenuto/><staccato/>'), (1, 4))
    refs = tuple(Reference(0., d, p) for d, p in ((.5, 60), (1.1, 62), (1.8, 64), (.85, 65)))
    refs += (Reference(2., 3., 67),)
    out = duration_context(symbolic, refs, {i: i for i in range(4)}, Clock(), Clock(scale=1.2))
    assert out['reference_notes'] == 5 and out['paired_notes'] == 4 and out['unpaired_notes'] == 1
    assert out['supported_pairs'] == 4 and out['unsupported_pairs'] == 0
    assert out['band_counts'] == dict(inside_both=1, shorter_both=1, longer_both=1, clock_dependent=1)
    assert set(out['by_category']) == set(CATEGORIES)
    assert sum(x['reference_notes'] for x in out['by_category'].values()) == 5
    assert sum(x['paired_notes'] for x in out['by_category'].values()) == 4
    assert out['by_category']['unresolved']['unpaired_notes'] == 1
    assert out['by_category']['unresolved']['supported_pairs'] == 0
    assert out['by_category']['staccato']['band_counts']['shorter_both'] == 1
    assert out['by_category']['mixed_articulation']['band_counts']['clock_dependent'] == 1
    stats = out['ratios']['global_beats']
    assert stats == pytest.approx(dict(count=4, sum=4.25, mean=1.0625, min=.5,
                                      p10=.605, median=.975, p90=1.59, max=1.8))
    assert out['ratios']['piano']['sum'] == pytest.approx(4.25 / 1.2)
    assert out['performed_duration_s_sum'] == pytest.approx(4.25)
    assert out['projected_duration_s_sum'] == pytest.approx(dict(global_beats=4., piano=4.8))
    assert out['by_category']['tenuto']['ratios']['global_beats'] == {
        'count': 0, 'sum': 0., 'mean': None, 'min': None, 'p10': None,
        'median': None, 'p90': None, 'max': None}
    assert not out['identity_uses_duration'] and not out['musical_correctness_measured']


@pytest.mark.parametrize('projected,performed,side', [
    (1., .8, 'inside_both'), (1., 1.2, 'inside_both'),
    (1., .799, 'shorter_both'), (1., 1.201, 'longer_both'),
    (.1, .05, 'inside_both'), (.1, .15, 'inside_both'),
    (.1, .049, 'shorter_both'), (.1, .151, 'longer_both'),
])
def test_duration_diagnostic_boundaries_include_the_50ms_floor(projected, performed, side):
    symbolic = score(note(), (1, 4))
    out = duration_context(symbolic, (Reference(0., performed, 60),), {0: 0},
                           Clock(scale=projected), Clock(scale=projected))
    assert out['band_counts'][side] == 1
    assert sum(out['band_counts'].values()) == 1


def test_duration_requires_the_entire_interval_and_preserves_unsupported_pairs():
    symbolic = score(note() + note(2, pitch='D') + note(pitch='E'))
    refs = (Reference(0., 1., 60), Reference(1., 3., 62), Reference(3., 4., 64))
    hole = Clock(spans=((F(0), F(3, 2)), (F(2), F(4))))
    assert hole.time_at(F(1)) is not None and hole.time_at(F(3)) is not None
    out = duration_context(symbolic, refs, {0: 0, 1: 1, 2: 2}, Clock(), hole)
    assert out['paired_notes'] == 3 and out['supported_pairs'] == 2 and out['unsupported_pairs'] == 1
    assert out['unsupported_reasons'] == {'interval_not_supported_by_both_clocks': 1}
    assert out['ratios']['global_beats']['count'] == out['ratios']['piano']['count'] == 2
    assert out['by_category']['unmarked']['unsupported_pairs'] == 1


@pytest.mark.parametrize('mode,reason', [('clock', 'source_clock_unavailable'),
                                      ('score', 'score_structure_unadmitted'),
                                      ('grace', 'nonpositive_score_interval')])
def test_unavailable_source_reasons_remain_in_duration_population(mode, reason):
    symbolic = score(note(grace=True) + note(), (1, 4)) if mode == 'grace' else score(note(), (1, 4))
    if mode == 'score':
        symbolic = replace(symbolic, unsupported=('synthetic unsupported structure',))
    out = duration_context(symbolic, (Reference(0., .5, 60),), {0: 0},
                           None if mode == 'clock' else Clock(), Clock())
    assert out['unsupported_reasons'] == {reason: 1}
    assert out['supported_pairs'] == 0 and out['unsupported_pairs'] == 1
    assert out['ratios']['piano']['mean'] is None


@pytest.mark.parametrize('end', [None, 0., math.nan, math.inf])
def test_invalid_projected_duration_is_unavailable_not_a_ratio(end):
    clock = Clock()
    clock.time_at = lambda q: 0. if q == 0 else end
    out = duration_context(score(note(), (1, 4)), (Reference(0., .5, 60),), {0: 0}, Clock(), clock)
    assert out['unsupported_reasons'] == {'nonpositive_or_unavailable_projection': 1}
    assert out['ratios']['piano']['count'] == 0


@pytest.mark.parametrize('pairs', [{1: 0}, {0: 1}, {True: 0}, {0: -1}, {0: '0'}, {0: [0]}])
def test_malformed_pair_identity_is_rejected(pairs):
    with pytest.raises(ValueError):
        duration_context(score(note(), (1, 4)), (Reference(0., 1., 60),), pairs, Clock(), Clock())


def test_reused_score_identity_or_changed_pitch_is_rejected():
    symbolic = score(note(), (1, 4))
    with pytest.raises(ValueError, match='uniquely'):
        duration_context(symbolic, (Reference(0., .5, 60), Reference(.2, .6, 60)),
                         {0: 0, 1: 0}, Clock(), Clock())
    with pytest.raises(ValueError, match='pitch'):
        duration_context(symbolic, (Reference(0., .5, 62),), {0: 0}, Clock(), Clock())


def test_rest_envelope_core_boundary_partition_and_annotation_overlap():
    symbolic = score(note() + note(rest=True) + note(2))
    refs = (Reference(.9, 1.1, 60), Reference(1.6, 1.9, 62), Reference(2., 2.1, 64))
    out = rest_range_context(symbolic, refs, Clock(), Clock(shift=.1))
    assert out['projected_rest_intervals'] == 1 and out['unprojectable_rest_intervals'] == 0
    assert out['collapsed_core_intervals'] == 0
    expected = {'envelope': (1.5, .6), 'core': (.5, .2), 'boundary_uncertain': (1., .4)}
    for name, (duration, overlap) in expected.items():
        row = out['projections'][name]
        assert row['duration_s'] == pytest.approx(duration)
        assert row['annotated_note_overlap_s'] == pytest.approx(overlap)
        assert row['uncovered_by_note_annotations_s'] == pytest.approx(duration - overlap)
    assert out['expanded_boundary_support_widths_s']['mean'] == pytest.approx(.3)
    assert out['boundary_guards_s']['count'] == 2
    assert not out['written_rest_accuracy_measured'] and not out['acoustic_silence_verified']


def test_rest_union_avoids_double_counting_overlapping_reference_notes():
    symbolic = score(note() + note(rest=True) + note(2))
    refs = (Reference(.9, 1.6, 60), Reference(1.4, 2.1, 62))
    out = rest_range_context(symbolic, refs, Clock(), Clock(shift=.1))
    assert out['projections']['envelope']['annotated_note_overlap_s'] == pytest.approx(1.2)
    assert out['projections']['core']['annotated_note_overlap_s'] == pytest.approx(.5)
    assert out['projections']['boundary_uncertain']['annotated_note_overlap_s'] == pytest.approx(.7)


def test_collapsed_cores_and_overlapping_envelopes_keep_source_counts_and_union_seconds():
    symbolic = score(note() + note(F(1, 5), rest=True) + note(F(1, 10))
                     + note(F(1, 5), rest=True) + note(F(5, 2)))
    out = rest_range_context(symbolic, (), Clock(), Clock())
    assert out['instrument_wide_rest_intervals'] == out['projected_rest_intervals'] == 2
    assert out['collapsed_core_intervals'] == 2 and out['nonempty_core_source_intervals'] == 0
    assert out['projections']['envelope']['interval_count'] == 1
    assert out['projections']['envelope']['duration_s'] == pytest.approx(.9)
    assert out['projections']['core']['duration_s'] == 0
    assert out['projections']['boundary_uncertain']['duration_s'] == pytest.approx(.9)


def test_rest_expanded_hull_must_be_supported_in_both_clocks_without_clipping():
    symbolic = score(note() + note(rest=True) + note(2))
    spans = ((F(3, 4), F(9, 4)),)
    bclock, pclock = Clock(spans=spans), Clock(shift=.2, spans=spans)
    assert all(clock.supports_time_band(q, .2) for clock in (bclock, pclock) for q in (F(1), F(2)))
    out = rest_range_context(symbolic, (), bclock, pclock)
    assert out['projected_rest_intervals'] == 0 and out['unprojectable_rest_intervals'] == 1
    assert out['unprojectable_reasons'] == {'expanded_boundary_band_not_supported_by_both_clocks': 1}
    assert bclock.band_calls[-1][1] == pytest.approx(.4)
    assert out['projections']['envelope']['duration_s'] == 0
    assert not out['clipping_performed'] and not out['extrapolation']


def test_rest_boundary_at_component_edge_fails_positive_symmetric_support():
    symbolic = score(note(rest=True) + note(3))
    out = rest_range_context(symbolic, (), Clock(), Clock())
    assert out['unprojectable_rest_intervals'] == 1
    assert out['unprojectable_reasons'] == {'expanded_boundary_band_not_supported_by_both_clocks': 1}


def test_rest_hole_is_not_bridged_despite_supported_endpoints():
    symbolic = score(note() + note(rest=True) + note(2))
    clock = Clock(spans=((F(0), F(7, 5)), (F(8, 5), F(4))))
    assert clock.time_at(1) is not None and clock.time_at(2) is not None
    out = rest_range_context(symbolic, (), Clock(), clock)
    assert out['unprojectable_reasons'] == {'interval_not_supported_by_both_clocks': 1}


@pytest.mark.parametrize('period,guard', [(.1, .05), (.5, .1), (2., .2)])
def test_rest_primary_guard_uses_observed_pulse_with_fixed_floor_and_cap(period, guard):
    symbolic = score(note() + note(rest=True) + note(2))
    clock = Clock(scale=period, period=period)
    out = rest_range_context(symbolic, (), clock, clock)
    assert out['projected_rest_intervals'] == 1
    assert out['boundary_guards_s']['min'] == pytest.approx(guard)
    assert out['boundary_guards_s']['max'] == pytest.approx(guard)


@pytest.mark.parametrize('period', [None, 0., -1., math.nan, math.inf])
def test_rest_unavailable_pulse_is_not_replaced_with_a_guessed_guard(period):
    symbolic = score(note() + note(rest=True) + note(2))
    out = rest_range_context(symbolic, (), Clock(period=period), Clock())
    assert out['unprojectable_reasons'] == {'boundary_pulse_period_unavailable': 1}
    assert out['boundary_guards_s']['count'] == 0


def test_all_unknown_source_time_stays_unknown_not_rest():
    symbolic = score('<forward><duration>120</duration></forward>' + note(3))
    assert len(symbolic.unknown_intervals) == 1
    out = rest_range_context(symbolic, (), Clock(), Clock())
    assert out['unknown_score_intervals'] == 1
    assert out['instrument_wide_rest_intervals'] == out['projected_rest_intervals'] == 0


@pytest.mark.parametrize('mode,reason', [('clock', 'source_clock_unavailable'),
                                      ('score', 'score_structure_unadmitted')])
def test_rest_unavailable_sources_preserve_the_whole_interval_denominator(mode, reason):
    symbolic = score(note() + note(rest=True) + note(2))
    if mode == 'score':
        symbolic = replace(symbolic, unsupported=('synthetic unsupported structure',))
    out = rest_range_context(symbolic, (), None if mode == 'clock' else Clock(), Clock())
    assert out['unprojectable_reasons'] == {reason: 1}
    assert out['projected_rest_intervals'] + out['unprojectable_rest_intervals'] == 1


def test_expression_metadata_counts_tags_and_attributes_without_applying_swing():
    body = note().replace('<note>', '<note attack="-2" release="3">')
    raw = xml(body, (1, 4), '<direction><sound><swing><first>2</first><second>1</second>'
              '</swing></sound></direction>')
    notes = b'onset,offset,midi,velocity\n0,0.5,60,127\n0.6,1,62,127\n'
    out = source_expression_metadata(raw, notes)
    assert out['explicit_swing_elements'] == 1 and out['explicit_straight_elements'] == 0
    assert out['note_attack_attributes'] == out['note_release_attributes'] == 1
    assert out['reference_notes'] == 2
    assert out['velocity_counts'] == {'127': 2} and out['velocity_unique_count'] == 1
    assert out['velocity_all_127'] and out['velocity_is_constant']
    assert out['swing_status'] == 'unestablished'
    assert not out['real_data_swing_applied'] and not out['attack_release_modifications_applied']
    assert not out['violin_dynamics_measured']


def test_absent_swing_or_variable_velocity_is_not_a_performance_truth_claim():
    raw = xml(note(), (1, 4), '<direction><direction-type><words>swing</words></direction-type></direction>')
    out = source_expression_metadata(raw, b'onset,offset,midi,velocity\n0,.4,60,40\n.6,1,62,80\n')
    assert out['explicit_swing_elements'] == 0
    assert out['velocity_counts'] == {'40': 1, '80': 1}
    assert not out['velocity_is_constant'] and not out['velocity_all_127']
    assert not out['absence_of_swing_tags_establishes_straight_performance']
    assert out['swing_status'] == 'unestablished' and not out['violin_dynamics_measured']


def test_metadata_namespace_and_explicit_straight_are_only_counted():
    raw = xml(note(), (1, 4), '<direction><sound><swing><straight/></swing></sound></direction>')
    raw = raw.replace(b'<score-partwise>', b'<score-partwise xmlns="urn:synthetic-musicxml">')
    out = source_expression_metadata(raw, b'onset,offset,midi,velocity\n0,.5,60,127\n')
    assert out['explicit_straight_elements'] == out['explicit_swing_elements'] == 1
    assert out['swing_status'] == 'unestablished'


@pytest.mark.parametrize('notes', [b'', b'onset,offset,midi,velocity\n',
                                 b'onset,offset,midi,velocity\n0,1,60,nan\n',
                                 b'onset,offset,midi,velocity\n0,1,60,128\n',
                                 b'onset,offset,midi,velocity\n0,1,60,127.5\n',
                                 b'onset,offset,midi,velocity\n1,0,60,127\n',
                                 b'onset,offset,midi,velocity\n0,1,60,127\n0,1,60,127\n'])
def test_expression_note_metadata_uses_bounded_strict_reference_validation(notes):
    with pytest.raises(ValueError):
        source_expression_metadata(xml(note(), (1, 4)), notes)


@pytest.mark.parametrize('raw', [b'', b'<!DOCTYPE x [<!ENTITY y "unsafe">]><score-partwise/>',
                               xml(note(), (1, 4)).replace(b'<note>', b'<note attack="NaN">')])
def test_expression_score_metadata_rejects_unsafe_or_nonfinite_source(raw):
    with pytest.raises(ValueError):
        source_expression_metadata(raw, b'onset,offset,midi,velocity\n0,1,60,127\n')


def test_deterministic_synthetic_controls_distinguish_expression_and_broad_band_failure():
    out = synthetic_controls()
    assert out == synthetic_controls()
    assert out['status'] == 'completed' and out['expected_behavior_observed'] and out['illustrative_only']
    assert out['real_recordings_used'] == out['model_inferences'] == 0
    assert not out['human_acceptability_benchmark'] and not out['thresholds_selected_from_results']
    assert out['straight_with_microtiming']['correct_identity_pairs'] == 4
    swing = out['known_two_to_one_swing']
    assert swing['oracle_map']['correct_identity_pairs'] == 4
    assert swing['straight_map']['correct_identity_pairs'] == 2
    wrong = out['incorrect_subdivision']
    assert wrong['narrow']['wrong_identity_pairs'] == 0
    assert wrong['broad']['wrong_identity_pairs'] == 1
    assert wrong['broad_with_competing_correct_candidate']['admitted_pairs'] == 0
    staccato = out['staccato_short_release']
    assert staccato['same_written_quarter_note_intent']
    assert staccato['duration_diagnostic']['band_counts']['shorter_both'] == 1
    assert staccato['duration_diagnostic']['ratios']['global_beats']['mean'] == pytest.approx(.4)
    assert not staccato['short_duration_implies_musical_error']
    serialized = json.dumps(out, allow_nan=False)
    assert 'raw_notes' not in serialized and '<score-partwise' not in serialized


@pytest.mark.parametrize('ref', [Reference(-1., 1., 60), Reference(0., math.inf, 60),
                               Reference(1., 1., 60), Reference(0., 1., True)])
def test_invalid_reference_intervals_or_pitch_cannot_enter_range_summaries(ref):
    symbolic = score(note(), (1, 4))
    with pytest.raises(ValueError):
        duration_context(symbolic, (ref,), {}, Clock(), Clock())
    with pytest.raises(ValueError):
        rest_range_context(symbolic, (ref,), Clock(), Clock())

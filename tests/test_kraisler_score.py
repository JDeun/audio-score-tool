"""Synthetic admission regressions; no downloaded score or model output needed."""
from dataclasses import FrozenInstanceError
from fractions import Fraction as F

import pytest

from scripts.kraisler_score import parse_score


def note(duration='12', *, pitch='C', octave=4, alter=None, voice='1', staff='1',
         rest=False, chord=False, grace=False, kind=None, dots=0, tie=(), extra='',
         notations='', measure_rest=False, xml_id=''):
    if rest:
        body = '<rest measure="yes"/>' if measure_rest else '<rest/>'
    else:
        accidental = '' if alter is None else f'<alter>{alter}</alter>'
        body = f'<pitch><step>{pitch}</step>{accidental}<octave>{octave}</octave></pitch>'
    return (f'<note id="{xml_id}">' + ('<grace/>' if grace else '')
            + ('<chord/>' if chord else '') + body
            + ('' if duration is None else f'<duration>{duration}</duration>')
            + ''.join(f'<tie type="{value}"/>' for value in tie)
            + f'<voice>{voice}</voice><staff>{staff}</staff>'
            + ('' if kind is None else f'<type>{kind}</type>') + '<dot/>' * dots
            + extra + f'<notations>{notations}</notations></note>')


def attributes(numerator=4, denominator=4, divisions='12'):
    return (f'<attributes><divisions>{divisions}</divisions>'
            f'<time><beats>{numerator}</beats><beat-type>{denominator}</beat-type></time>'
            '</attributes>')


def measure(body, number='1', attrs=''):
    return f'<measure number="{number}" {attrs}>{body}</measure>'


def document(*measures, part='P1'):
    return (f'<score-partwise><part id="{part}">' + ''.join(measures)
            + '</part></score-partwise>').encode()


def one(body, numerator=1, denominator=4, divisions='12'):
    return document(measure(attributes(numerator, denominator, divisions) + body))


def intervals(values):
    return tuple((v.onset_q, v.end_q) for v in values)


def test_generated_ids_do_not_depend_on_source_ids_or_display_numbers():
    raw = document(measure(attributes(2, 4) + note(xml_id='same') + note(rest=True), '7'),
                   measure(note(xml_id='same') + note(pitch='D'), '7'))
    score = parse_score(raw)
    assert [e.id for e in score.events] == ['P1/m0000/n0000', 'P1/m0001/n0000', 'P1/m0001/n0001']
    assert score.rests[0].id == 'P1/m0000/n0001'
    assert [m.number for m in score.measures] == ['7', '7']
    assert all(e.source_ids == (e.id,) for e in score.events)
    assert score == parse_score(raw.replace(b'id="same"', b'id="different"'))
    with pytest.raises(FrozenInstanceError):
        score.events[0].midi = 61
    with pytest.raises(TypeError):
        score.counts['events'] = 99
    assert score.counts['note_elements'] == 4
    assert score.admissible_for_alignment


@pytest.mark.parametrize('meter,pickup', [((3, 4), F(1)), ((2, 4), F(1, 4)), ((4, 4), F(2))])
def test_unmarked_pickup_is_actual_extent_without_first_measure_padding(meter, pickup):
    full = F(4 * meter[0], meter[1])
    score = parse_score(document(
        measure(attributes(*meter) + note(str(pickup * 12))),
        measure(note(str(full * 12)), '2')))
    assert score.measures[0].pickup and not score.measures[0].implicit
    assert score.measures[0].duration_q == pickup
    assert score.measures[1].onset_q == pickup
    assert score.duration_q == pickup + full
    assert not score.measures[-1].short_final
    assert score.admissible_for_alignment


def test_short_final_has_evidence_and_no_padding():
    score = parse_score(document(measure(attributes() + note('48')),
                                 measure(note('6'), '2')))
    assert score.measures[-1].short_final and not score.measures[-1].pickup
    assert score.duration_q == F(9, 2)
    assert score.admissible_for_alignment


@pytest.mark.parametrize('body', [note('12'), note('60'), ''])
def test_internal_short_overfull_and_empty_bars_fail_admission(body):
    score = parse_score(document(measure(attributes() + note('48')),
                                 measure(body, '2'), measure(note('48'), '3')))
    assert not score.admissible_for_alignment
    assert any('overfull, empty, or internal underfull' in s for s in score.unsupported)


def test_meter_denominator_and_boundary_changes_are_exact():
    score = parse_score(document(
        measure(attributes(3, 2) + note('72')),
        measure(attributes(4, 4) + note('48'), '2'),
        measure(attributes(6, 8) + note('36'), '3'),
        measure(attributes(2, 2) + note('48'), '4')))
    assert [m.time_signature for m in score.measures] == [(3, 2), (4, 4), (6, 8), (2, 2)]
    assert [m.duration_q for m in score.measures] == [F(6), F(4), F(3), F(4)]
    assert [m.onset_q for m in score.measures] == [F(0), F(6), F(10), F(13)]
    assert score.admissible_for_alignment


def test_mid_measure_meter_change_fails_without_rewriting_earlier_meter():
    score = parse_score(one(note() + attributes(2, 4) + note(), numerator=2))
    assert not score.admissible_for_alignment
    assert any('mid-measure' in s for s in score.unsupported)


@pytest.mark.parametrize('time', [
    '<time><beats>3+2</beats><beat-type>8</beat-type></time>',
    '<time><senza-misura/></time>',
    '<time number="1"><beats>1</beats><beat-type>4</beat-type></time>',
    '<time><beats>1</beats><beat-type>3</beat-type></time>',
    '',
])
def test_unhandled_meter_never_silently_defaults_to_four_four(time):
    score = parse_score(document(measure('<attributes><divisions>12</divisions>'
                                         + time + '</attributes>' + note())))
    assert not score.admissible_for_alignment


def test_backup_chords_and_cross_staff_notes_do_not_advance_chord_cursor():
    body = (note('48') + note('48', pitch='E', chord=True, staff='2')
            + '<backup><duration>48</duration></backup>'
            + note('24', voice='2', rest=True) + note('24', pitch='G', voice='2'))
    score = parse_score(one(body, numerator=4))
    assert intervals(score.events) == ((F(0), F(4)), (F(0), F(4)), (F(2), F(4)))
    assert score.counts['chord_events'] == 1
    assert score.counts['voices'] == 2 and score.counts['staffs'] == 2
    assert not score.global_rests and not score.unknown_intervals
    assert score.admissible_for_alignment


def test_global_rest_subtracts_any_sounding_voice_and_staff():
    body = (note('48', rest=True) + '<backup><duration>48</duration></backup>'
            + '<forward><duration>12</duration><voice>2</voice></forward>'
            + note(voice='2', staff='2') + '<forward><duration>24</duration></forward>')
    score = parse_score(one(body, numerator=4))
    assert intervals(score.rests) == ((F(0), F(4)),)
    assert intervals(score.global_rests) == ((F(0), F(1)), (F(2), F(4)))
    assert not score.unknown_intervals
    assert score.admissible_for_alignment


def test_forward_holes_are_unknown_instead_of_fabricated_rests():
    score = parse_score(one('<forward><duration>12</duration></forward>' + note()
                            + '<forward><duration>24</duration></forward>', numerator=4))
    assert not score.rests and not score.global_rests
    assert intervals(score.unknown_intervals) == ((F(0), F(1)), (F(2), F(4)))
    assert any('unknown' in warning for warning in score.warnings)


def test_events_preserve_xml_order_attacks_have_stable_score_order():
    score = parse_score(one(note() + note(pitch='D')
                            + '<backup><duration>24</duration></backup>'
                            + note('24', pitch='E', voice='2'), numerator=2))
    assert [e.midi for e in score.events] == [60, 62, 64]
    assert [e.midi for e in score.attacks] == [60, 64, 62]


def test_grace_and_grace_chords_have_zero_duration_without_advancing_cursor():
    score = parse_score(one(note(None, grace=True, kind='eighth')
                            + note(None, grace=True, chord=True, pitch='E', kind='eighth')
                            + note(None, grace=True, pitch='D', kind='16th')
                            + note(kind='quarter')))
    assert intervals(score.events) == ((F(0), F(0)),) * 3 + ((F(0), F(1)),)
    assert score.counts['grace_events'] == 3 and len(score.attacks) == 4
    assert not score.unknown_intervals
    assert any('grace' in warning for warning in score.warnings)
    assert score.admissible_for_alignment


def test_tuplets_keep_written_duration_and_do_not_apply_ratio_twice():
    modification = ('<time-modification><actual-notes>3</actual-notes>'
                    '<normal-notes>2</normal-notes></time-modification>')
    score = parse_score(one(''.join(note('4', pitch=p, kind='eighth', extra=modification)
                                    for p in ['C', 'D', 'E'])))
    assert [e.duration_q for e in score.events] == [F(1, 3)] * 3
    assert [e.written_duration_q for e in score.events] == [F(1, 2)] * 3
    assert [e.tuplet_ratio for e in score.events] == [F(2, 3)] * 3
    assert score.duration_q == 1 and score.admissible_for_alignment


def test_dotted_notes_and_decimal_divisions_are_exact_fractions():
    dotted = parse_score(one(note('18', kind='quarter', dots=1)
                             + note('18', kind='quarter', dots=1), numerator=6, denominator=8))
    assert dotted.events[0].written_duration_q == F(3, 2)
    assert dotted.admissible_for_alignment
    decimal = parse_score(one(note('2.5', kind='quarter'), divisions='2.5'))
    assert decimal.events[0].duration_q == 1 and decimal.admissible_for_alignment


def test_written_duration_disagreement_fails_except_explicit_measure_rest():
    score = parse_score(one(note('24', kind='quarter'), numerator=2))
    assert not score.admissible_for_alignment
    assert any('written type/tuplet' in s for s in score.unsupported)
    rest = parse_score(one(note('36', rest=True, measure_rest=True, kind='whole'), numerator=3))
    assert rest.admissible_for_alignment and rest.rests[0].measure_rest


def test_contiguous_enharmonic_ties_collapse_and_keep_segment_evidence():
    score = parse_score(one(
        note(alter=1, kind='quarter', tie=('start',),
             notations='<tied type="start"/><articulations><staccato/></articulations>')
        + note(pitch='D', alter=-1, kind='quarter', tie=('stop', 'start'),
               notations='<tied type="stop"/><tied type="start"/>'
                         '<articulations><tenuto/></articulations>')
        + note(alter=1, kind='quarter', tie=('stop',),
               notations='<tied type="stop"/><articulations><accent/></articulations>'),
        numerator=3))
    assert len(score.events) == 3 and len(score.attacks) == 1
    attack = score.attacks[0]
    assert attack.midi == 61 and intervals(score.attacks) == ((F(0), F(3)),)
    assert attack.source_ids == tuple(e.id for e in score.events)
    assert attack.articulations == ('staccato', 'tenuto', 'accent')
    assert attack.written_duration_q == 3
    assert score.events[0].end_q == 1 and score.events[0].articulations == ('staccato',)
    assert score.admissible_for_alignment


def test_tie_identity_includes_voice_and_staff_across_measures():
    def bar(tie):
        return (note(tie=(tie,)) + '<backup><duration>12</duration></backup>'
                + note(voice='2', tie=(tie,)) + '<backup><duration>12</duration></backup>'
                + note(staff='2', tie=(tie,)))
    score = parse_score(document(measure(attributes(1, 4) + bar('start')),
                                 measure(bar('stop'), '2')))
    assert len(score.events) == 6 and len(score.attacks) == 3
    assert intervals(score.attacks) == ((F(0), F(2)),) * 3
    assert score.admissible_for_alignment


@pytest.mark.parametrize('voice,staff', [('2', '1'), ('1', '2'), ('2', '2')])
def test_unique_contiguous_tie_can_change_voice_or_staff_with_warning(voice, staff):
    score = parse_score(document(measure(attributes(1, 4) + note(tie=('start',))),
                                 measure(note(voice=voice, staff=staff, tie=('stop',)), '2')))
    assert score.admissible_for_alignment and len(score.attacks) == 1
    assert intervals(score.attacks) == ((F(0), F(2)),)
    assert score.attacks[0].source_ids == tuple(e.id for e in score.events)
    assert score.warnings == ('P1/m0001/n0000: cross_voice_or_staff_tie',)


def test_cross_voice_tie_continuation_moves_active_identity_without_leaving_open_parent():
    score = parse_score(one(note(tie=('start',))
                            + note(voice='2', tie=('stop', 'start'))
                            + note(voice='3', tie=('stop',)), numerator=3))
    assert score.admissible_for_alignment and len(score.attacks) == 1
    assert intervals(score.attacks) == ((F(0), F(3)),)
    assert len(score.warnings) == 2


def test_cross_voice_tie_with_two_contiguous_parents_remains_ambiguous():
    first = (attributes(1, 4) + note(tie=('start',))
             + '<backup><duration>12</duration></backup>' + note(voice='2', tie=('start',)))
    score = parse_score(document(measure(first), measure(note(voice='3', tie=('stop',)), '2')))
    assert not score.admissible_for_alignment and len(score.attacks) == 3
    assert any('ambiguous cross-voice/staff tie' in s for s in score.unsupported)


def test_exact_voice_and_staff_tie_parent_wins_over_other_contiguous_candidates():
    first = (attributes(1, 4) + note(tie=('start',))
             + '<backup><duration>12</duration></backup>' + note(voice='2', tie=('start',)))
    second = (note(tie=('stop',)) + '<backup><duration>12</duration></backup>'
              + note(voice='2', tie=('stop',)))
    score = parse_score(document(measure(first), measure(second, '2')))
    assert score.admissible_for_alignment and len(score.attacks) == 2
    assert not score.warnings
    assert [a.source_ids for a in score.attacks] == [
        ('P1/m0000/n0000', 'P1/m0001/n0000'), ('P1/m0000/n0001', 'P1/m0001/n0001')]


@pytest.mark.parametrize('body,reason', [
    (note(tie=('stop',)), 'orphan tie stop'),
    (note(tie=('start',)), 'open tie'),
    (note(tie=('start',)) + note(rest=True) + note(tie=('stop',)), 'noncontiguous tie'),
    (note(tie=('start',)) + note() + note(tie=('stop',)), 'interrupted or ambiguous tie'),
    (note(tie=('stop',), notations='<tied type="start"/>'), 'ties disagree'),
    (note(None, grace=True, tie=('start',)) + note(), 'grace tie'),
    (note(notations='<tied type="continue"/>'), 'unsupported tie type'),
])
def test_ambiguous_or_incomplete_ties_fail_admission(body, reason):
    score = parse_score(one(body, numerator=3))
    assert not score.admissible_for_alignment
    assert any(reason in s for s in score.unsupported)


def test_local_ornaments_are_preserved_as_unresolved_warning():
    score = parse_score(one(note(notations='<ornaments><tremolo type="single">1</tremolo>'
                                            '<trill-mark/></ornaments>')))
    assert score.events[0].ornaments == ('tremolo', 'trill-mark')
    assert any('nonliteral attacks' in warning for warning in score.warnings)
    assert score.admissible_for_alignment


@pytest.mark.parametrize('instruction', [
    '<barline><repeat direction="backward"/></barline>',
    '<barline><ending number="1" type="start"/></barline>',
    '<direction><direction-type><segno/></direction-type></direction>',
    '<direction><sound dalsegno="segno"/></direction>',
    '<direction><direction-type><words>D.C. al Fine</words></direction-type></direction>',
    '<direction><direction-type><words>D.S. al Coda</words></direction-type></direction>',
    '<attributes><transpose><chromatic>-2</chromatic></transpose></attributes>',
    '<direction><direction-type><octave-shift type="up" size="8"/></direction-type></direction>',
    '<attributes><measure-style><measure-repeat type="start"/></measure-style></attributes>',
])
def test_navigation_and_transposition_fail_closed_without_expansion(instruction):
    score = parse_score(one(note() + instruction))
    assert not score.admissible_for_alignment
    assert len(score.events) == 1 and score.duration_q == 1


def test_multiple_rest_is_validated_display_compression_not_extra_bars():
    marking = '<attributes><measure-style><multiple-rest>2</multiple-rest></measure-style></attributes>'
    score = parse_score(document(measure(attributes() + marking + note('48', rest=True)),
                                 measure(note('48', rest=True), '2'),
                                 measure(note('48'), '3')))
    assert score.duration_q == 12 and len(score.measures) == 3
    assert intervals(score.global_rests) == ((F(0), F(8)),)
    assert score.admissible_for_alignment
    incomplete = parse_score(document(measure(attributes() + marking + note('48', rest=True))))
    assert any('incomplete multiple-rest' in s for s in incomplete.unsupported)


def test_multiple_rest_cannot_hide_a_note_in_another_voice():
    marking = '<attributes><measure-style><multiple-rest>1</multiple-rest></measure-style></attributes>'
    score = parse_score(one(marking + note(rest=True)
                            + '<backup><duration>12</duration></backup>' + note(voice='2')))
    assert any('pitched note inside multiple-rest' in s for s in score.unsupported)


def test_unpitched_sound_blocks_global_rest_and_alignment():
    unpitched = ('<note><unpitched><display-step>C</display-step><display-octave>4</display-octave>'
                 '</unpitched><duration>12</duration><voice>2</voice></note>')
    score = parse_score(one(note(rest=True) + '<backup><duration>12</duration></backup>' + unpitched))
    assert not score.global_rests and not score.admissible_for_alignment
    assert score.counts['nonpitch_events'] == 1 and score.counts['note_elements'] == 2


def test_part_rest_scope_is_explicit_and_disagreeing_part_grids_fail():
    left = '<part id="P1">' + measure(attributes() + note('48', rest=True)) + '</part>'
    right = '<part id="P2">' + measure(attributes() + note('48')) + '</part>'
    score = parse_score(('<score-partwise>' + left + right + '</score-partwise>').encode())
    assert [r.part for r in score.global_rests] == ['P1']
    assert score.admissible_for_alignment
    changed = parse_score(('<score-partwise>' + left + right.replace('<duration>48', '<duration>12')
                           + '</score-partwise>').encode())
    assert 'part measure grids disagree' in changed.unsupported


@pytest.mark.parametrize('body', [
    note(None), note('0'), note('-1'), note('NaN'), note('inf'),
    '<backup><duration>1</duration></backup>' + note(),
    note(chord=True), note() + note(chord=True, voice='2'),
    note(None, grace=True, rest=True), note(grace=True),
    note(octave=20), note(alter='0.5'), note(voice=''),
    note(tie=('start',), rest=True),
    note().replace('</pitch>', '</pitch><rest/>'),
    note().replace('</duration>', '</duration><duration>12</duration>'),
    note(extra='<time-modification><actual-notes>0</actual-notes><normal-notes>2</normal-notes>'
               '</time-modification>'),
])
def test_malformed_note_or_cursor_is_rejected(body):
    with pytest.raises(ValueError):
        parse_score(one(body))


@pytest.mark.parametrize('raw', [
    b'', 'not bytes', b'<score-partwise>', b'<score-timewise/>',
    b'<score-partwise><part id="P1"/><part id="P1"/></score-partwise>',
    b'<!DOCTYPE score-partwise [<!ENTITY e "bad">]><score-partwise/>',
    b'<!DOCTYPE score-partwise [ ]><score-partwise/>', b'\x00', b'\xff',
    b'a' * 4_000_001,
    document(measure(attributes(divisions='0') + note())),
    document(measure(note())),
])
def test_unsafe_malformed_or_unbounded_input_is_rejected(raw):
    with pytest.raises(ValueError):
        parse_score(raw)


def test_external_doctype_needs_no_download_and_consistent_namespaces_are_supported():
    raw = one(note())
    doctype = b'<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" "https://invalid.example/partwise.dtd">'
    assert parse_score(doctype + raw).admissible_for_alignment
    namespaced = raw.replace(b'<score-partwise>', b'<score-partwise xmlns="urn:musicxml:test">')
    assert parse_score(namespaced) == parse_score(raw)
    mixed = raw.replace(b'<pitch>', b'<pitch xmlns="urn:foreign">')
    with pytest.raises(ValueError, match='mixed MusicXML namespaces'):
        parse_score(mixed)

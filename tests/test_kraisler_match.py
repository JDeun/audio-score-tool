"""Match/source-clock contracts from synthetic metadata, without data downloads."""
import hashlib
import json
from dataclasses import FrozenInstanceError
from fractions import Fraction as F

import pytest

from scripts.kraisler_match import parse_piano_match
from scripts.kraisler_score import parse_score


def note(q=1, *, step='C', voice='1', staff='1', grace=False, rest=False,
         tie=(), ornaments=''):
    body = '<rest/>' if rest else f'<pitch><step>{step}</step><octave>4</octave></pitch>'
    return ('<note>' + ('<grace/>' if grace else '') + body
            + ('' if grace else f'<duration>{F(q) * 12}</duration>')
            + f'<voice>{voice}</voice><staff>{staff}</staff>'
            + ''.join(f'<tie type="{value}"/>' for value in tie)
            + (f'<notations><ornaments>{ornaments}</ornaments></notations>' if ornaments else '')
            + '</note>')


def attributes(numerator, denominator):
    return ('<attributes><divisions>12</divisions>'
            f'<time><beats>{numerator}</beats><beat-type>{denominator}</beat-type></time>'
            '</attributes>')


def score(*bodies, meter=(1, 4)):
    measures = ''.join(f'<measure number="{i + 1}">'
                       + (attributes(*meter) if i == 0 else '') + body + '</measure>'
                       for i, body in enumerate(bodies))
    return parse_score(('<score-partwise><part id="P1">' + measures
                        + '</part></score-partwise>').encode())


def row(identity='s1', *, step='C', measure=1, beat=1, offset='0', duration='1/4',
        onset='0', end='1', attrs='v1,staff1', performance_id='n1', pitch=60,
        tick=960, end_tick=None, deleted=False):
    symbolic = (f'snote({identity},[{step},n],4,{measure}:{beat},{offset},{duration},'
                f'{onset},{end},[{attrs}])')
    if deleted:
        return symbolic + '-deletion.'
    return (symbolic + f'-note({performance_id},{pitch},{tick},'
            f'{tick + 480 if end_tick is None else end_tick},90,0,0).')


def match(*rows, units=480, rate=500000):
    return ('\n'.join(('info(matchFileVersion,1.1.0).',
                       f'info(midiClockUnits,{units}).',
                       f'info(midiClockRate,{rate}).', *rows)) + '\n').encode()


def test_original_tick_clock_and_nonmonotonic_performance_are_not_fitted():
    symbolic = score(note() + note(step='D'), meter=(2, 4))
    raw = match(row(tick=1440), row('s2', step='D', beat=2, onset='1', end='2',
                                  performance_id='n2', pitch=62, tick=960))
    audit = parse_piano_match(raw, symbolic)
    assert audit.strict_score_consistency
    assert [(a.q, a.time) for a in audit.anchors] == [(F(0), 1.5), (F(1), 1.0)]
    assert audit.diagnostics['seconds_per_tick'] == '1/960'
    assert not audit.diagnostics['clock_fitted']
    assert not audit.diagnostics['isotonic_repair']
    assert not audit.diagnostics['extrapolation']
    assert audit.diagnostics['match_sha256'] == hashlib.sha256(raw).hexdigest()
    with pytest.raises(FrozenInstanceError):
        audit.anchors[0].time = 99
    # Public diagnostics contain summaries/hashes, not the source note records.
    serialized = json.dumps(audit.diagnostics)
    assert 'snote(' not in serialized and 'P1/m' not in serialized


def test_compound_meter_match_unit_is_denominator_not_csv_dotted_pulse():
    symbolic = score(note(F(7, 4), rest=True) + note(F(1, 4)) + note(1, rest=True),
                     meter=(6, 8))
    audit = parse_piano_match(match(row(beat=4, offset='1/16', duration='1/16',
                                       onset='3.5', end='4')), symbolic)
    assert audit.strict_score_consistency
    assert [(a.q, a.score_end_q) for a in audit.anchors] == [(F(7, 4), F(2))]


def test_meter_changes_accumulate_denominator_beats_not_quarters():
    symbolic = score(note(6), attributes(4, 4) + note(4, step='D'), meter=(3, 2))
    raw = match(row(duration='3/2', end='3'),
                row('s2', step='D', measure=2, duration='1', onset='3', end='7',
                    performance_id='n2', pitch=62))
    audit = parse_piano_match(raw, symbolic)
    assert audit.strict_score_consistency
    assert [a.q for a in audit.anchors] == [F(0), F(6)]
    bad = parse_piano_match(raw.replace(b',3,7,[', b',6,10,['), symbolic)
    assert not bad.strict_score_consistency
    assert bad.diagnostics['source_beat_coordinate_errors'] == 1


@pytest.mark.parametrize('meter,pickup,beat,offset,start', [
    ((3, 4), F(1), 3, '0', '-1'),
    ((2, 4), F(1, 4), 2, '3/16', '-0.25'),
    ((4, 4), F(2), 3, '0', '-2'),
])
def test_pickup_measure_zero_uses_terminal_nominal_measure(meter, pickup, beat, offset, start):
    full = F(4 * meter[0], meter[1])
    symbolic = score(note(pickup), note(full, step='D'), meter=meter)
    raw = match(row(measure=0, beat=beat, offset=offset, duration=str(pickup / 4),
                    onset=start, end='0'),
                row('s2', step='D', measure=1, duration=str(full / 4), onset='0',
                    end=str(meter[0]), performance_id='n2', pitch=62))
    audit = parse_piano_match(raw, symbolic)
    assert audit.strict_score_consistency
    assert [a.q for a in audit.anchors] == [F(0), pickup]
    assert audit.diagnostics['pickup_measure_zero']


def test_sixteenth_rest_pickup_with_property_coordinate_and_no_piano_attack():
    symbolic = score(note(F(1, 4), rest=True), note(2), meter=(2, 4))
    raw = match('scoreprop(timeSignature,2/4,0:2,3/16,-0.25).',
                row(duration='1/2', end='2'))
    audit = parse_piano_match(raw, symbolic)
    assert audit.strict_score_consistency
    assert audit.anchors[0].q == F(1, 4)


def test_tie_collapsed_duration_matches_single_score_alignment_row():
    symbolic = score(note(tie=('start',)), note(tie=('stop',)))
    audit = parse_piano_match(match(row(duration='1/2', end='2')), symbolic)
    assert audit.strict_score_consistency
    assert len(audit.anchors) == 1 and audit.anchors[0].score_end_q == 2
    assert audit.diagnostics['xml_attack_count'] == 1
    assert audit.diagnostics['symbolic_note_rows'] == 1


@pytest.mark.parametrize('xml_ornament,match_flag', [('<tremolo>3</tremolo>', ''),
                                                  ('', ',tremolo')])
def test_grace_and_either_ornament_source_are_uniformly_excluded(xml_ornament, match_flag):
    symbolic = score(note(grace=True) + note() + note(step='D', ornaments=xml_ornament),
                     meter=(2, 4))
    raw = match(row('grace', duration='0', end='0', attrs='v1,staff1,grace', performance_id='ng'),
                row(), row('s2', step='D', beat=2, onset='1', end='2',
                           attrs='v1,staff1' + match_flag, performance_id='n2', pitch=62))
    audit = parse_piano_match(raw, symbolic)
    assert audit.strict_score_consistency
    assert [a.score_id for a in audit.anchors] == ['s1']
    assert audit.diagnostics['matched_notes'] == 3
    assert audit.diagnostics['excluded_grace'] == 1
    assert audit.diagnostics['excluded_ornament'] == 1
    assert audit.diagnostics['excluded_unverified'] == 0


def test_excluded_grace_duration_disagreement_is_still_reported():
    symbolic = score(note(grace=True) + note())
    raw = match(row('grace', attrs='v1,staff1,grace', performance_id='ng'), row())
    audit = parse_piano_match(raw, symbolic)
    assert not audit.strict_score_consistency
    assert audit.diagnostics['excluded_grace'] == 1
    assert audit.diagnostics['score_attack_disagreements'] == 1
    assert audit.diagnostics['contradictory_score_rows'] == 1
    assert audit.diagnostics['missing_xml_attack_rows'] == 1
    assert audit.diagnostics['excess_match_score_rows'] == 1
    assert len(audit.anchors) == 1


def test_nonanchor_rows_preserved_and_zero_duration_insertion_is_valid_metadata():
    symbolic = score(note() + note(step='D'), meter=(2, 4))
    raw = match(row(), row('s2', step='D', beat=2, onset='1', end='2', deleted=True),
                'insertion-note(inserted,67,1000,1000,40,0,0).',
                'virtualSnote(s1,[])-virtualPnote(n1,).', 'sustain(100,127).', 'soft(200,0).')
    audit = parse_piano_match(raw, symbolic)
    assert audit.strict_score_consistency
    assert len(audit.anchors) == 1
    for key, value in {'matched_notes': 1, 'deleted_score_notes': 1,
                       'verified_deleted_score_notes': 1, 'inserted_notes': 1,
                       'zero_duration_inserted_notes': 1, 'virtual_pairs': 1,
                       'pedal_events': 2}.items():
        assert audit.diagnostics[key] == value


def test_deleted_score_disagreement_cannot_be_silently_ignored():
    audit = parse_piano_match(match(row(step='D', deleted=True)), score(note()))
    assert not audit.strict_score_consistency
    assert audit.diagnostics['deleted_score_notes'] == 1
    assert audit.diagnostics['verified_deleted_score_notes'] == 0
    assert audit.diagnostics['score_attack_disagreements'] == 1
    assert audit.diagnostics['contradictory_score_rows'] == 1
    assert audit.anchors == ()


def test_zero_duration_matched_note_preserves_original_onset_and_is_counted():
    audit = parse_piano_match(match(row(tick=960, end_tick=960)), score(note()))
    assert audit.strict_score_consistency
    assert audit.anchors[0].time == 1
    assert audit.diagnostics['zero_duration_matched_notes'] == 1


@pytest.mark.parametrize('changes,diagnostic', [
    ({'measure': 2}, 'source_position_errors'),
    ({'step': 'D', 'pitch': 62}, 'score_attack_disagreements'),
    ({'duration': '1/8', 'end': '0.5'}, 'score_attack_disagreements'),
    ({'onset': '0.001'}, 'source_beat_coordinate_errors'),
    ({'end': '0.999'}, 'source_beat_coordinate_errors'),
    ({'pitch': 61}, 'matched_pitch_disagreements'),
    ({'attrs': 'v2,staff1'}, 'voice_staff_disagreements'),
])
def test_coordinate_pitch_duration_and_voice_contradictions_fail_consistency(changes, diagnostic):
    audit = parse_piano_match(match(row(**changes)), score(note()))
    assert not audit.strict_score_consistency
    assert audit.diagnostics[diagnostic] == 1


def test_missing_score_rows_and_duplicate_coordinate_rows_fail_complete_inventory():
    symbolic = score(note() + note(step='D'), meter=(2, 4))
    missing = parse_piano_match(match(row()), symbolic)
    assert not missing.strict_score_consistency
    assert missing.diagnostics['missing_xml_attack_rows'] == 1
    duplicate = parse_piano_match(match(row(), row('duplicate', performance_id='another')),
                                  score(note()))
    assert not duplicate.strict_score_consistency
    assert duplicate.diagnostics['excess_match_score_rows'] == 1


def test_identical_symbolic_positions_keep_all_performances_and_report_identity_ambiguity():
    symbolic = score(note() + '<backup><duration>12</duration></backup>' + note(voice='2'))
    raw = match(row(), row('s2', attrs='v2,staff1', performance_id='n2', tick=1000))
    audit = parse_piano_match(raw, symbolic)
    assert audit.strict_score_consistency
    assert len(audit.anchors) == 2 and len({a.time for a in audit.anchors}) == 2
    assert audit.diagnostics['non_unique_xml_identity_matches'] == 2
    assert audit.diagnostics['anchor_positions'] == 1
    assert all(len(a.score_support_ids) == 2 for a in audit.anchors)


def test_four_decimal_export_rounding_does_not_round_symbolic_fractions():
    symbolic = score(note(F(1, 3)) + note(F(1, 3), step='D') + note(F(1, 3), step='E'))
    raw = match(row(duration='1/12', end='0.3333'),
                row('s2', step='D', offset='1/12', duration='1/12', onset='0.3333',
                    end='0.6667', performance_id='n2', pitch=62),
                row('s3', step='E', offset='1/6', duration='1/12', onset='0.6667',
                    end='1', performance_id='n3', pitch=64))
    audit = parse_piano_match(raw, symbolic)
    assert audit.strict_score_consistency
    assert [a.q for a in audit.anchors] == [F(0), F(1, 3), F(2, 3)]
    bad = parse_piano_match(raw.replace(b'0.3333', b'0.3334'), symbolic)
    assert not bad.strict_score_consistency
    assert bad.diagnostics['source_beat_coordinate_errors'] == 2


def test_unsupported_symbolic_structure_prevents_false_strict_claim():
    symbolic = score(note(tie=('stop',)))
    assert not symbolic.admissible_for_alignment
    audit = parse_piano_match(match(row()), symbolic)
    assert not audit.strict_score_consistency
    assert audit.diagnostics['xml_unsupported_count'] == 1
    assert audit.diagnostics['score_attack_disagreements'] == 0


@pytest.mark.parametrize('extra', [row(), row('s2'), 'unknown(1).', 'sustain(-1,0).',
                                 'soft(1,128).', 'virtualSnote(x,[foo])-virtualPnote(y,).'])
def test_duplicate_id_and_unknown_or_malformed_row_classes_fail_closed(extra):
    with pytest.raises(ValueError):
        parse_piano_match(match(row(), extra), score(note()))


@pytest.mark.parametrize('changes', [
    {'end_tick': 959}, {'duration': '0'}, {'offset': '-1/4'}, {'offset': '1/0'},
    {'onset': 'NaN'}, {'end': 'Infinity'}, {'attrs': 'v1,[staff1'}, {'attrs': 'x()'},
])
def test_invalid_numeric_or_structural_fields_are_rejected(changes):
    with pytest.raises(ValueError):
        parse_piano_match(match(row(**changes)), score(note()))


@pytest.mark.parametrize('raw', [b'', 'not bytes', b'info(matchFileVersion,1.1.0).\n',
                               match(row()).replace(b'1.1.0', b'0.5.0'),
                               match(row(), units=0), match(row(), rate=-1),
                               match(row()).replace(b').\n', b')\n', 1),
                               match(row()) + b'\xff'])
def test_missing_or_invalid_header_and_encoding_are_rejected(raw):
    with pytest.raises(ValueError):
        parse_piano_match(raw, score(note()))


@pytest.mark.parametrize('property_line', ['scoreprop(timeSignature,2/4,1:1,0,0).',
                                          'scoreprop(timeSignature,1/4,1:1,0,0.1).'])
def test_time_signature_and_property_coordinate_mismatch_is_not_ignored(property_line):
    with pytest.raises(ValueError):
        parse_piano_match(match(property_line, row()), score(note()))

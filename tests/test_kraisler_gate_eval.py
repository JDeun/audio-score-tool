"""Synthetic evaluator contracts; no KRAISLER audio outcomes or source redistribution."""
from __future__ import annotations

import copy
import json

import numpy as np
import pytest

from scripts.audio_gate_attribution import ARMS, make_attribution_arms
from scripts.audio_gate_rest import scored_notes
from scripts.kraisler_gate_eval import (
    BASES,
    evaluate_arms,
    read_reference,
    score_context_audit,
    summarize,
)
from scripts.vocadito_reference import read_notes
from scripts.vocal_recovery import Event

HEADER = 'onset,offset,midi,velocity\n'
REFERENCE = (HEADER + '0.1,0.5,69,127\n0.7,1.1,72,90\n').encode()
PLANNED = ('02', '19', '08', '12', '05', '06')
BEATS = (b'beat_time,beat_type,time_signature,piano,violin\n'
         b'0,db,4/4,True,True\n0.5,b,,False,True\n1,b,3/2,True,False\n')
XML = b'''<score-partwise><part-list/><part id="P1"><measure number="1">
<attributes><divisions>4</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
<note id="n1"><pitch><step>A</step><octave>4</octave></pitch><duration>4</duration><voice>1</voice>
<notations><articulations><staccato/><accent/></articulations></notations><tie type="start"/></note>
<note id="n2"><chord/><pitch><step>C</step><octave>5</octave></pitch><duration>4</duration><voice>1</voice></note>
<backup><duration>4</duration></backup><note><rest/><duration>4</duration><voice>2</voice></note>
<note id="g1"><grace/><pitch><step>B</step><octave>4</octave></pitch><voice>2</voice></note>
</measure><measure number="2"><note id="n1"><pitch><step>A</step><octave>4</octave></pitch>
<duration>4</duration><voice>1</voice><tie type="stop"/></note></measure></part></score-partwise>'''


def _evaluation():
    edges = np.arange(151) / 100
    quiet = np.zeros(150, dtype=bool)
    quiet[50:70] = True
    quiet[110:] = True
    raw = [Event(69, .1, .6), Event(72, .7, 1.1)]
    predictions = make_attribution_arms(raw, edges, quiet)
    return predictions, edges, evaluate_arms(predictions, REFERENCE, edges)


def _cases():
    _, _, entries = _evaluation()
    context = score_context_audit(XML, BEATS, REFERENCE)
    return [{'id': ident, 'status': 'scored',
             'bases': {base: {'arms': copy.deepcopy(entries)} for base in BASES},
             'score_context': copy.deepcopy(context)} for ident in PLANNED]


def test_reference_preserves_original_seconds_pitch_and_velocity():
    value = read_reference(REFERENCE, 1.5)
    intervals, hz = read_notes(value.equivalent_hz_csv)
    assert value.note_count == 2
    assert value.intervals == ((.1, .5), (.7, 1.1))
    assert value.midi == (69, 72) and value.velocities == (127, 90)
    assert np.array_equal(intervals, np.array(value.intervals))
    assert hz[0] == 440.
    assert hz[1] == pytest.approx(440 * 2 ** (3 / 12))


def test_chords_and_overlapping_notes_are_preserved_not_declared_monophonic():
    raw = (HEADER + '.1,.8,69,127\n.1,.8,72,127\n.5,1.0,76,127\n').encode()
    value = read_reference(raw, 1.1)
    assert value.note_count == 3
    assert value.intervals[0] == value.intervals[1]
    audit = score_context_audit(XML, BEATS, raw)
    assert audit['overlapping_reference_note_pairs'] == 3
    assert audit['max_simultaneous_reference_notes'] == 3


@pytest.mark.parametrize('body', [
    '', '0.2,0.1,69,127\n', '-.1,.2,69,127\n', '0,.2,128,127\n',
    '0,.2,-1,127\n', '0,.2,69.5,127\n', '0,.2,69,128\n',
    '0,.2,69,-1\n', '0,.2,69,2.5\n', 'nan,.2,69,127\n',
    '0,inf,69,127\n', '0,.2,nan,127\n', '0,.2,69,inf\n',
    '0,.2,69\n', '0,.2,69,127,extra\n', '0,.2,69,127\n\n',
    '.2,.3,69,127\n.1,.2,72,127\n',
    '0,.2,69,127\n0,.2,69,90\n',
])
def test_invalid_reference_rows_fail_without_clipping_dropping_or_sorting(body):
    with pytest.raises(ValueError):
        read_reference((HEADER + body).encode(), 2.)


@pytest.mark.parametrize('header', ['onset,offset,pitch,velocity', 'offset,onset,midi,velocity',
                                    'onset,offset,midi,velocity,', ''])
def test_only_declared_csv_schema_is_accepted(header):
    with pytest.raises(ValueError, match='header'):
        read_reference((header + '\n0,.2,69,127\n').encode())


@pytest.mark.parametrize('duration', [0., -1., np.inf, np.nan, True, '2.0'])
def test_invalid_audio_duration_rejected(duration):
    with pytest.raises(ValueError):
        read_reference(REFERENCE, duration)


def test_reference_outside_observed_audio_is_rejected_not_truncated():
    with pytest.raises(ValueError, match='beyond observed audio'):
        read_reference(REFERENCE, 1.09)
    assert read_reference(REFERENCE, 1.1).note_count == 2


def test_evaluation_reuses_unchanged_scoring_and_correct_gain_masks():
    predictions, edges, entries = _evaluation()
    reference = read_reference(REFERENCE)
    for arm in ARMS:
        expected = scored_notes(predictions[arm][0], reference.equivalent_hz_csv, edges)
        value = entries[arm]['metrics']
        assert {key: value[key] for key in expected} == expected
    assert entries['raw']['metrics']['onset_f1'] == 1.
    assert entries['raw']['metrics']['onset_offset_f1'] == .5
    assert entries['tail_only']['metrics']['onset_f1'] == 1.
    assert entries['tail_only']['metrics']['onset_offset_f1'] == 1.
    assert entries['tail_only']['metrics']['transition']['onset_offset'] == {'gained': 1, 'damaged': 0}


def test_empty_predictions_are_valid_zero_metrics_with_visible_missed_note_time():
    edges = np.arange(151) / 100
    entries = evaluate_arms(make_attribution_arms([], edges, np.zeros(150, bool)), REFERENCE, edges)
    for entry in entries.values():
        assert entry['count'] == 0
        assert entry['metrics']['onset_f1'] == entry['metrics']['onset_offset_f1'] == 0.
        assert entry['metrics']['onset_reference_mask'] == '00'
        assert entry['metrics']['occupancy']['lost_note_s'] == pytest.approx(.8)


@pytest.mark.parametrize('change', ['count', 'onset', 'pitch', 'program', 'extension'])
def test_tail_only_invariants_are_checked_before_scoring(change):
    predictions, edges, _ = _evaluation()
    children, diagnostics = predictions['tail_only']
    children = list(children)
    if change == 'count':
        children.pop()
    else:
        values = {'onset': Event(69, .2, .5), 'pitch': Event(70, .1, .5),
                  'program': Event(69, .1, .5, program=40), 'extension': Event(69, .1, .8)}
        children[0] = values[change]
    predictions['tail_only'] = children, diagnostics
    with pytest.raises(ValueError, match='tail-only changed'):
        evaluate_arms(predictions, REFERENCE, edges)


def test_scoring_rejects_drums_and_does_not_mutate_source_predictions():
    predictions, edges, _ = _evaluation()
    before = copy.deepcopy(predictions)
    evaluate_arms(predictions, REFERENCE, edges)
    assert predictions == before
    notes, diagnostic = predictions['non_tail_only']
    predictions['non_tail_only'] = [Event(69, .1, .5, is_drum=True), *notes[1:]], diagnostic
    with pytest.raises(ValueError, match='non-drum'):
        evaluate_arms(predictions, REFERENCE, edges)


@pytest.mark.parametrize('defect', ['missing', 'duplicate', 'failed', 'base', 'arm',
                                   'planned_five', 'planned_duplicate'])
def test_only_complete_six_by_two_by_four_cohort_has_summary(defect):
    cases, planned = _cases(), PLANNED
    if defect == 'missing':
        cases.pop()
    elif defect == 'duplicate':
        cases[-1] = cases[0]
    elif defect == 'failed':
        cases[-1]['status'] = 'failed'
    elif defect == 'base':
        cases[-1]['bases'].pop('default')
    elif defect == 'arm':
        cases[-1]['bases']['default']['arms'].pop('tail_only')
    elif defect == 'planned_five':
        planned = planned[:-1]
    else:
        planned = (*planned[:-1], planned[0])
    assert summarize(cases, planned) is None


def test_summary_is_six_recording_macro_and_single_reference_time_totals():
    cases = _cases()
    result = summarize(cases, PLANNED)
    assert result['recordings'] == 6
    assert result['scored_conditions'] == 48
    assert result['aggregation'] == 'six-recording macro'
    tail = result['bases']['onset065']['tail_only']
    assert tail['onset_offset_f1'] == 1.
    assert tail['delta_vs_raw']['onset_offset_f1'] == .5
    assert tail['paired_recordings'] == {'improved': 6, 'worsened': 0, 'equal': 0}
    assert tail['onset_offset_transition'] == {'gained': 6, 'damaged': 0}
    assert tail['output_notes'] == tail['reference_notes'] == 12
    assert tail['changed_parents'] == 6
    assert tail['occupancy_seconds_totals']['reference_note_s'] == pytest.approx(4.8)
    assert [row['id'] for row in tail['per_recording']] == list(PLANNED)
    assert result['score_context']['aligned_recordings'] == 0
    assert result['score_context']['unaligned_recordings'] == 6
    assert result['score_context']['xml_count_totals']['explicit_rests'] == 6
    assert result['score_context']['articulation_tag_totals']['staccato'] == 6
    assert not result['explicit_written_rest_f1_evaluated']
    serialized = json.dumps(result)
    assert HEADER.strip() not in serialized
    assert '<score-partwise>' not in serialized


@pytest.mark.parametrize('defect', ['nan_f1', 'negative_time', 'reference_count', 'mask', 'transition'])
def test_invalid_metric_or_population_ledger_cannot_be_aggregated(defect):
    cases = _cases()
    value = cases[-1]['bases']['onset065']['arms']['tail_only']['metrics']
    if defect == 'nan_f1':
        value['onset_f1'] = np.nan
    elif defect == 'negative_time':
        value['occupancy']['lost_note_s'] = -1.
    elif defect == 'reference_count':
        value['reference_note_count'] += 1
    elif defect == 'mask':
        value['onset_reference_mask'] = 'x1'
    else:
        value['transition']['onset_offset']['gained'] += 1
    with pytest.raises(ValueError):
        summarize(cases, PLANNED)


def test_xml_audit_counts_structure_without_inventing_alignment():
    result = score_context_audit(XML, BEATS, REFERENCE)
    assert result['status'] == 'audited'
    assert result['alignment_status'] == 'unaligned'
    assert result['xml_counts']['explicit_rests'] == 1
    assert result['xml_counts']['pitched_notes'] == 4
    assert result['xml_counts']['chord_members'] == 1
    assert result['xml_counts']['grace_notes'] == 1
    assert result['xml_counts']['duplicate_note_ids'] == 1
    assert result['voice_count'] == 2
    assert result['articulation_tags'] == {'staccato': 1, 'accent': 1}
    assert result['beat_count'] == 3
    assert result['beat_time_signature_sequence'] == ['4/4', '3/2']
    assert result['xml_time_signatures'] == ['4/4']
    assert result['reference_note_count'] == 2
    assert not result['explicit_written_rest_f1_evaluated']
    assert 'rest_f1' not in result


@pytest.mark.parametrize('xml', [b'bad XML', b'<score-timewise/>',
                                 b'<!DOCTYPE x [<!ENTITY e "x">]><score-partwise/>'])
def test_unsupported_xml_is_visible_and_never_aligned(xml):
    value = score_context_audit(xml, BEATS, REFERENCE)
    assert value['status'] == 'unsupported'
    assert value['alignment_status'] == 'unaligned'
    assert 'reason' in value
    assert not value['explicit_written_rest_f1_evaluated']


@pytest.mark.parametrize('body', [
    '0,b,,True,True\n0,b,,True,True\n', 'nan,b,,True,True\n',
    '-1,b,,True,True\n', '0,guess,4/4,True,True\n',
    '0,db,0/4,True,True\n', '0,b,,maybe,True\n',
])
def test_malformed_beat_table_stays_unsupported(body):
    beat_header = b'beat_time,beat_type,time_signature,piano,violin\n'
    result = score_context_audit(XML, beat_header + body.encode(), REFERENCE)
    assert result['status'] == 'unsupported'
    assert result['alignment_status'] == 'unaligned'


def test_missing_structural_context_is_reported_separately_from_note_population():
    cases = _cases()
    cases[0].pop('score_context')
    cases[1]['score_context'] = {'status': 'unsupported', 'alignment_status': 'unaligned'}
    result = summarize(cases, PLANNED)
    assert result['recordings'] == 6
    assert result['score_context']['audited_recordings'] == 4
    assert result['score_context']['unsupported_or_missing_recordings'] == 2
    assert result['score_context']['aligned_recordings'] == 0

"""Small owned contracts for all-or-nothing G parent preservation."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

import numpy as np
import pytest

from scripts import note_boundary_parent_guard as guard
from scripts import note_boundary_readout as split
from scripts import note_state_hmm as frozen
from scripts.dsp_note_probe import Note, fingerprint


def frequencies(pitches):
    return np.array([0. if pitch is None else 440. * 2 ** ((pitch - 69) / 12)
                     for pitch in pitches], dtype=float)


def state(pitch=60, phase=frozen.STABLE):
    return int(round((pitch - 33) * 9)) + phase


def run(pitches, *, path=None, duration=None):
    hz = frequencies(pitches)
    path = np.full(len(hz), state(), dtype=np.int16) if path is None else path
    duration = len(hz) * .01 if duration is None else duration
    originals, old_diagnostics = frozen.notes_from_state_path(path, hz, duration)
    old_hz, old_path = hz.copy(), path.copy()
    notes, diagnostics, trace = guard.notes_from_state_path(
        path, hz, duration, original_notes=originals)
    assert np.array_equal(hz, old_hz) and np.array_equal(path, old_path)
    assert diagnostics['baseline'] == old_diagnostics
    assert diagnostics['readout']['emitted_notes'] == len(notes)
    assert diagnostics['trace_sha256'] == fingerprint(trace)
    assert diagnostics['output_interval_union_preserved'] is True
    assert guard.interval_union(notes) == guard.interval_union(originals)
    assert diagnostics['baseline_interval_union_sha256'] == diagnostics['output_interval_union_sha256']
    assert diagnostics['nonemitted_parents_resurrected'] == 0
    assert diagnostics['originally_emitted_parents_all_children_pruned'] == 0
    return notes, diagnostics, trace, originals


def test_fixed_single_factor_settings():
    assert guard.ARM == 'gaussian_raw_hysteresis_parent_guard'
    assert guard.BASE_ARM == split.BASE_ARM
    assert guard.SPLIT_ARM == split.ARM
    assert guard.SETTINGS['change_support_frames'] == 5
    assert guard.SETTINGS['minimum_note_seconds'] == .08
    for name in ('nonemitted_parent_resurrection', 'partial_cut_selection',
                 'raw_unvoiced_posthoc_split', 'reference_informed_cuts'):
        assert guard.SETTINGS[name] is False


def test_all_passing_children_accept_every_cut_and_keep_exact_interval_union():
    notes, diag, trace, old = run([60] * 10 + [61] * 10 + [62] * 10)
    assert notes == [Note(60, 0., .1), Note(61, .1, .2), Note(62, .2, .3)]
    assert all(note is not old[0] for note in notes)
    parent = trace['parents'][0]
    assert parent['decision'] == 'accepted'
    assert parent['proposed_cut_frames'] == parent['accepted_cut_frames'] == [10, 20]
    assert [c['prediction_index'] for c in parent['proposed_children']] == [0, 1, 2]
    assert all(c['passes_readout'] and c['emitted'] for c in parent['proposed_children'])
    assert all('passes_readout' not in c for c in parent['final_segments'])
    assert diag['proposed_cut_count'] == diag['accepted_cut_count'] == 2
    assert diag['accepted_child_count'] == 3


def test_one_short_middle_child_rejects_entire_proposal_not_a_greedy_subset():
    notes, diag, trace, old = run([60] * 10 + [61] * 5 + [62] * 10)
    assert notes == old and notes[0] is old[0]
    parent = trace['parents'][0]
    assert parent['decision'] == 'rejected'
    assert parent['proposed_cut_frames'] == [10, 15]
    assert parent['accepted_cut_frames'] == []
    assert parent['rejection_reasons'] == ['short']
    assert [c['passes_readout'] for c in parent['proposed_children']] == [True, False, True]
    assert all(c['emitted'] is False and c['prediction_index'] is None
               for c in parent['proposed_children'])
    assert diag['proposed']['short_segments_discarded'] == 1
    assert diag['proposed']['short_segments_discarded_seconds'] == pytest.approx(.05)
    assert diag['proposed']['emitted_notes'] == 2
    assert diag['readout']['short_segments_discarded'] == 0
    assert diag['restored_original_event_count'] == 1
    assert diag['emitted_seconds_change'] == 0.


def test_all_short_children_restore_original_event_bytes_and_object():
    notes, diag, trace, old = run([60] * 5 + [61] * 5)
    old_bytes = json.dumps([asdict(n) for n in old], indent=2).encode()
    new_bytes = json.dumps([asdict(n) for n in notes], indent=2).encode()
    assert hashlib.sha256(old_bytes).digest() == hashlib.sha256(new_bytes).digest()
    assert notes[0] is old[0]
    assert diag['proposed']['short_segments_discarded'] == 2
    assert diag['readout']['emitted_note_seconds'] == .1
    assert trace['parents'][0]['final_segments'][0]['prediction_index'] == 0


def test_four_frame_change_is_no_cut_and_reuses_original_note():
    notes, diag, trace, old = run([60] * 10 + [61] * 4 + [60] * 10)
    assert notes[0] is old[0]
    assert diag['readout'] == diag['baseline']
    assert diag['proposed_child_count'] == 0
    assert trace['candidate_cut_frames'] == []
    assert trace['parents'][0]['decision'] == 'no_cut'
    assert trace['parents'][0]['proposed_children'] == []


def test_nonemitted_short_parent_cannot_propose_or_resurrect():
    notes, diag, trace, old = run([60] * 2 + [61] * 5)
    assert notes == old == []
    assert trace['candidate_cut_frames'] == [2]
    parent = trace['parents'][0]
    assert parent['decision'] == 'nonemitted'
    assert parent['original']['discard_reason'] == 'short'
    assert parent['proposed_cut_frames'] == parent['proposed_children'] == []
    assert parent['final_segments'] == [parent['original']]
    assert diag['originally_nonemitted_parent_count'] == 1
    assert diag['baseline']['short_segments_discarded'] == 1
    assert diag['readout']['short_segments_discarded'] == 1
    assert diag['proposed']['short_segments_discarded'] == 0


def test_no_raw_support_parent_stays_in_denominator_without_resurrection():
    notes, diag, trace, old = run([None] * 10)
    assert notes == old == []
    assert trace['parents'][0]['original']['discard_reason'] == 'no_raw_support'
    assert trace['parents'][0]['decision'] == 'nonemitted'
    assert diag['readout']['segments_without_raw_voiced_support'] == 1
    assert diag['parent_segment_count'] == 1


@pytest.mark.parametrize('duration,decision', [(.16, 'accepted'), (.159, 'rejected'),
                                             (.16 - 5e-11, 'accepted'),
                                             (.16 - 2e-10, 'rejected')])
def test_clipped_child_uses_identical_frozen_80ms_comparison(duration, decision):
    notes, diag, trace, old = run([60] * 8 + [61] * 8, duration=duration)
    parent = trace['parents'][0]
    assert parent['decision'] == decision
    assert parent['proposed_children'][-1]['offset_seconds'] == duration
    if decision == 'rejected':
        assert notes[0] is old[0]
        assert diag['proposed']['short_segments_discarded'] == 1
    else:
        assert len(notes) == 2
        assert notes[-1].offset == duration
    assert diag['readout']['short_segments_discarded'] == 0


def test_zero_boundaries_leave_raw_bridging_and_original_note_unchanged():
    notes, diag, trace, old = run([60] * 10 + [None] * 2 + [61] * 10)
    assert notes[0] is old[0]
    assert trace['candidate_cut_frames'] == []
    assert diag['readout']['emitted_raw_unvoiced_frames'] == 2
    assert diag['readout']['decoded_voiced_over_raw_unvoiced_frames'] == 2


def test_global_hysteresis_does_not_restart_at_parent_boundary():
    path = np.array([state(phase=frozen.SILENT)] * 9 + [state()] * 11, dtype=np.int16)
    notes, diag, trace, old = run([60] * 6 + [61] * 14, path=path)
    assert notes[0] is old[0]
    assert trace['candidate_cut_frames'] == [6]
    assert diag['proposed_cut_count'] == 0


def test_original_pitch_and_silent_boundaries_are_never_removed():
    path = np.array([state()] * 10 + [state(61)] * 10
                    + [state(phase=frozen.SILENT)] * 2 + [state()] * 10, dtype=np.int16)
    notes, diag, _, old = run([60] * 32, path=path)
    assert all(a is b for a, b in zip(notes, old, strict=True))
    assert notes == [Note(60, 0., .1), Note(60, .1, .2), Note(60, .22, .32)]
    assert diag['parent_segment_count'] == 3
    assert guard.interval_union(notes) == [[0., .2], [.22, .32]]


def test_candidate_on_existing_boundary_is_not_an_added_cut():
    path = np.array([state()] * 10 + [state(61)] * 10, dtype=np.int16)
    notes, diag, trace, old = run([60] * 10 + [61] * 10, path=path)
    assert trace['candidate_cut_frames'] == [10]
    assert all(a is b for a, b in zip(notes, old, strict=True))
    assert diag['proposed_cut_count'] == 0


def test_silent_path_has_candidates_but_no_eligible_parent():
    path = np.full(20, state(phase=frozen.SILENT), dtype=np.int16)
    notes, diag, trace, _ = run([60] * 10 + [61] * 10, path=path)
    assert notes == [] and trace['candidate_cut_frames'] == [10]
    assert diag['parent_segment_count'] == diag['proposed_parent_count'] == 0


def test_terminal_clipping_never_admits_a_cut_at_audio_end():
    notes, diag, trace, old = run([60] * 20 + [61], duration=.2)
    assert notes[0] is old[0]
    assert diag['proposed_cut_count'] == 0
    assert trace['parents'][0]['final_segments'][0]['clipped'] is True


def test_mixed_accepted_rejected_and_nonemitted_parents_have_stable_indices():
    pitches = [60] * 10 + [61] * 10 + [None] + [60] * 5 + [61] * 5 + [None] + [60] * 3
    path = np.array([state()] * 20 + [state(phase=frozen.SILENT)] + [state()] * 10
                    + [state(phase=frozen.SILENT)] + [state()] * 3, dtype=np.int16)
    notes, diag, trace, old = run(pitches, path=path)
    assert [p['decision'] for p in trace['parents']] == ['accepted', 'rejected', 'nonemitted']
    assert [p['original']['prediction_index'] for p in trace['parents']] == [0, 1, None]
    assert notes[2] is old[1]
    assert [p['final_segments'][0]['prediction_index'] for p in trace['parents']] == [0, 2, None]
    assert [c['child_id'] for p in trace['parents'] for c in p['proposed_children']] == [0, 1, 2, 3]
    assert diag['readout']['short_segments_discarded'] == 1
    assert diag['proposed']['short_segments_discarded'] == 2


def test_standalone_api_constructs_the_same_events_and_trace_without_decode(monkeypatch):
    hz, path = frequencies([60] * 5 + [61] * 5), np.full(10, state(), dtype=np.int16)
    monkeypatch.setattr(frozen, 'decode_state_path', lambda *_: pytest.fail('must not decode'))
    old, _ = frozen.notes_from_state_path(path, hz, .1)
    actual = guard.notes_from_state_path(path, hz, .1)
    supplied = guard.notes_from_state_path(path, hz, .1, original_notes=old)
    assert actual == supplied
    assert supplied[0][0] is old[0]


@pytest.mark.parametrize('supplied', [[], [Note(61, 0., .1)], [Note(60, 0., .09)],
                                    [Note(60, 0., .1), Note(60, .1, .2)]])
def test_supplied_original_mismatch_is_rejected(supplied):
    with pytest.raises(ValueError, match='original G Note'):
        guard.notes_from_state_path(np.full(10, state(), dtype=np.int16),
                                    frequencies([60] * 10), .1, original_notes=supplied)


def test_empty_input_and_public_private_separation():
    notes, diag, trace, _ = run([])
    assert notes == [] and trace == {'schema_version': 1, 'candidate_cut_frames': [], 'parents': []}
    assert diag['proposed_child_seconds_summary']['count'] == 0
    assert diag['baseline_interval_union_seconds'] == diag['output_interval_union_seconds'] == 0
    for forbidden in ('parents', 'candidate_cut_frames', 'proposed_cut_frames',
                      'onset_seconds', 'offset_seconds', 'raw_positive_midi_median', 'pitch'):
        assert f'"{forbidden}"' not in json.dumps(diag)


@pytest.mark.parametrize('path,hz,duration', [
    ([244], [float('nan')], .01), ([244], [-1.], .01),
    ([244.], [440.], .01), ([99999], [440.], .01),
    ([244], [440.], .2), ([], [], .1), ([244], [440.], float('nan')),
])
def test_invalid_frozen_inputs_fail_before_readout(path, hz, duration):
    with pytest.raises(ValueError):
        guard.notes_from_state_path(np.asarray(path), hz, duration)

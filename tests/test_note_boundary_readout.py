"""Small owned controls for the frozen #296 segmentation contract."""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict

import numpy as np
import pytest

from scripts import note_boundary_readout as split
from scripts import note_state_hmm as frozen
from scripts.dsp_note_probe import Note, fingerprint, labels_from_hz


def frequencies(pitches):
    return np.array([0. if pitch is None else 440. * 2 ** ((pitch - 69) / 12)
                     for pitch in pitches], dtype=float)


def state(pitch=60, phase=frozen.STABLE):
    return int(round((pitch - 33) * 9)) + phase


def run(pitches, *, path=None, duration=None):
    hz = frequencies(pitches)
    path = np.full(len(hz), state(), dtype=np.int16) if path is None else path
    duration = len(hz) * .01 if duration is None else duration
    notes, diagnostics, trace = split.notes_from_state_path(path, hz, duration)
    old_notes, old_diagnostics = frozen.notes_from_state_path(path, hz, duration)
    assert diagnostics['baseline'] == old_diagnostics
    assert len(notes) == diagnostics['readout']['emitted_notes']
    assert len(trace['parents']) == diagnostics['parent_segment_count']
    assert sum(len(parent['children']) for parent in trace['parents']) == (
        diagnostics['child_segment_count'])
    return notes, diagnostics, trace, old_notes


def serialized(notes):
    return json.dumps([asdict(note) for note in notes], indent=2, allow_nan=False) + '\n'


def test_settings_are_the_predeclared_single_factor():
    assert split.ARM == 'gaussian_raw_hysteresis_split'
    assert split.BASE_ARM == 'gaussian_exponent_1'
    assert split.SETTINGS['change_support_frames'] == 5
    assert split.SETTINGS['minimum_note_seconds'] == .08
    assert split.SETTINGS['time_shift_seconds'] == 0
    assert split.SETTINGS['raw_unvoiced_posthoc_split'] is False


def test_sustained_change_is_backdated_to_first_evidence_and_uses_child_pitch():
    notes, diag, trace, old = run([60] * 10 + [61] * 10)
    assert notes == [Note(60, 0., .1), Note(61, .1, .2)]
    assert len(old) == 1
    assert trace['candidate_cut_frames'] == [10]
    assert trace['parents'][0]['applied_cut_frames'] == [10]
    assert diag['candidate_cut_count'] == diag['applied_cut_count'] == 1
    assert diag['affected_parent_count'] == diag['parent_segment_count'] == 1
    assert diag['child_segment_count'] == 2
    assert diag['emitted_seconds_change'] == 0.
    assert [child['prediction_index'] for child in trace['parents'][0]['children']] == [0, 1]
    assert trace['parents'][0]['original']['prediction_index'] == 0


def test_five_frame_confirmation_retains_a_short_child_in_the_pruning_denominator():
    notes, diag, trace, _ = run([60] * 10 + [61] * 5 + [60] * 10)
    assert notes == [Note(60, 0., .1), Note(60, .15, .25)]
    assert trace['candidate_cut_frames'] == [10, 15]
    children = trace['parents'][0]['children']
    assert [child['discard_reason'] for child in children] == [None, 'short', None]
    assert [child['prediction_index'] for child in children] == [0, None, 1]
    assert diag['readout']['short_segments_discarded'] == 1
    assert diag['readout']['short_segments_discarded_seconds'] == pytest.approx(.05)
    assert diag['originally_emitted_parents_with_short_children'] == 1
    assert diag['originally_emitted_parents_all_children_pruned'] == 0
    assert diag['child_segment_count'] == 3


def test_four_frame_change_does_not_cut_and_preserves_exact_event_bytes():
    notes, diag, trace, old = run([60] * 10 + [61] * 4 + [60] * 10)
    assert trace['candidate_cut_frames'] == []
    assert diag['applied_cut_count'] == 0
    assert notes == old
    assert serialized(notes) == serialized(old)
    assert hashlib.sha256(serialized(notes).encode()).hexdigest() == (
        hashlib.sha256(serialized(old).encode()).hexdigest())
    assert diag['readout'] == diag['baseline']


def test_pending_pitch_must_be_consecutive_and_resets_when_pitch_changes():
    _, _, trace, _ = run([60] * 10 + [61] * 4 + [62] * 8)
    assert trace['candidate_cut_frames'] == [14]
    assert trace['parents'][0]['children'][0]['stop_frame'] == 14


def test_zero_boundaries_do_not_cut_or_gate_the_original_decoded_support():
    notes, diag, trace, old = run([60] * 10 + [None] * 2 + [61] * 10)
    assert trace['candidate_cut_frames'] == []
    assert notes == old
    assert len(notes) == 1
    assert notes[0].onset == 0.
    assert notes[0].offset == .22
    assert diag['readout']['emitted_raw_unvoiced_frames'] == 2
    assert diag['readout']['decoded_voiced_over_raw_unvoiced_frames'] == 2
    assert diag['emitted_coverage_fraction'] == 1.


def test_raw_change_within_silent_support_is_only_a_candidate():
    pitches = [60] * 10 + [61] * 10
    path = np.full(20, state(phase=frozen.SILENT), dtype=np.int16)
    notes, diag, trace, old = run(pitches, path=path)
    assert notes == old == []
    assert trace['candidate_cut_frames'] == [10]
    assert diag['candidate_cut_count'] == 1
    assert diag['applied_cut_count'] == diag['parent_segment_count'] == 0
    assert diag['readout']['raw_voiced_decoded_silent_frames'] == 20


def test_original_decoded_pitch_boundaries_are_preserved_even_without_raw_changes():
    path = np.array([state(60)] * 10 + [state(61)] * 10, dtype=np.int16)
    notes, diag, trace, old = run([60] * 20, path=path)
    assert notes == old == [Note(60, 0., .1), Note(60, .1, .2)]
    assert diag['parent_segment_count'] == diag['child_segment_count'] == 2
    assert diag['applied_cut_count'] == 0
    assert [parent['state_pitch_index'] for parent in trace['parents']] == [81, 84]


def test_attack_to_stable_phase_change_is_not_an_extra_parent_boundary():
    path = np.array([state(phase=frozen.ATTACK)] * 5 + [state()] * 15, dtype=np.int16)
    notes, diag, _, old = run([60] * 20, path=path)
    assert notes == old == [Note(60, 0., .2)]
    assert diag['parent_segment_count'] == 1
    assert diag['baseline']['attack_only_segments'] == 0


def test_existing_silent_gap_survives_same_pitch_readout():
    path = np.array([state()] * 10 + [state(phase=frozen.SILENT)] * 2 + [state()] * 10,
                    dtype=np.int16)
    notes, diag, _, old = run([60] * 22, path=path)
    assert notes == old == [Note(60, 0., .1), Note(60, .12, .22)]
    assert diag['parent_segment_count'] == 2
    assert diag['readout']['raw_voiced_decoded_silent_frames'] == 2


def test_cut_on_existing_parent_boundary_does_not_duplicate_the_boundary():
    path = np.array([state(60)] * 10 + [state(61)] * 10, dtype=np.int16)
    notes, diag, trace, old = run([60] * 10 + [61] * 10, path=path)
    assert notes == old
    assert trace['candidate_cut_frames'] == [10]
    assert diag['applied_cut_count'] == 0
    assert all(not parent['applied_cut_frames'] for parent in trace['parents'])


def test_hysteresis_is_global_instead_of_restarted_at_each_parent():
    # Evidence starts while G is silent and is confirmed inside a voiced parent.
    # The backdated cut remains outside that parent and must not become a cut at 9.
    pitches = [60] * 6 + [61] * 14
    path = np.array([state(phase=frozen.SILENT)] * 9 + [state()] * 11, dtype=np.int16)
    notes, diag, trace, old = run(pitches, path=path)
    assert trace['candidate_cut_frames'] == [6]
    assert diag['applied_cut_count'] == 0
    assert notes == old == [Note(61, .09, .2)]


def test_short_children_can_delete_an_originally_emitted_parent():
    notes, diag, trace, old = run([60] * 5 + [61] * 5)
    assert old == [Note(60, 0., .1)]
    assert notes == []
    assert diag['baseline']['emitted_notes'] == 1
    assert diag['readout']['short_segments_discarded'] == 2
    assert diag['readout']['short_segments_discarded_seconds'] == .1
    assert diag['originally_emitted_parents_all_children_pruned'] == 1
    assert diag['originally_emitted_parents_with_short_children'] == 1
    assert diag['originally_emitted_parents_with_any_pruned_children'] == 1
    assert diag['baseline_emitted_coverage_fraction'] == 1.
    assert diag['emitted_coverage_fraction'] == 0.
    assert all(child['discard_reason'] == 'short' for child in trace['parents'][0]['children'])


def test_prefilter_short_parent_is_preserved_and_can_be_split():
    notes, diag, trace, old = run([60] * 2 + [61] * 5)
    assert notes == old == []
    assert diag['parent_segment_count'] == 1
    assert diag['baseline']['short_segments_discarded'] == 1
    assert diag['child_segment_count'] == 2
    assert diag['readout']['short_segments_discarded'] == 2
    assert diag['originally_emitted_parents_all_children_pruned'] == 0
    assert trace['parents'][0]['original']['prediction_index'] is None


@pytest.mark.parametrize('duration,emitted,reason', [(.08, True, None), (.079, False, 'short')])
def test_actual_audio_clipping_controls_the_frozen_minimum(duration, emitted, reason):
    notes, diag, trace, old = run([60] * 8, duration=duration)
    assert notes == old
    child = trace['parents'][0]['children'][0]
    assert child['emitted'] is emitted
    assert child['discard_reason'] == reason
    assert child['offset_seconds'] == duration
    assert child['clipped'] is (duration < .08)
    assert diag['clipped_child_count'] == int(duration < .08)


def test_terminal_observation_does_not_create_a_zero_duration_child():
    # A raw candidate at audio end is possible with support5 only if a caller
    # supplies later evidence; the centered clock rejects that shape. Here a
    # terminal new pitch has no confirmation and does not add any cut.
    notes, diag, trace, old = run([60] * 10 + [61], duration=.1)
    assert notes == old == [Note(60, 0., .1)]
    assert trace['candidate_cut_frames'] == []
    assert diag['child_segment_count'] == 1
    assert diag['clipped_child_count'] == 1
    assert diag['readout']['zero_duration_segments'] == 0


def test_zero_duration_original_parent_retains_support_and_reason():
    path = np.array([state(phase=frozen.SILENT)] * 10 + [state()], dtype=np.int16)
    notes, diag, trace, old = run([60] * 11, path=path, duration=.1)
    assert notes == old == []
    child = trace['parents'][0]['children'][0]
    assert child['raw_voiced_frames'] == 1
    assert child['pitch'] == 60
    assert child['discard_reason'] == 'zero_duration'
    assert diag['readout']['zero_duration_segments'] == 1
    assert diag['child_seconds_summary']['mean'] == 0.


def test_raw_positive_median_and_bankers_rounding_are_not_decoded_or_label_pitch():
    path = np.full(16, state(69), dtype=np.int16)
    notes, _, trace, old = run([60] * 8 + [61] * 8, path=path)
    assert old == [Note(60, 0., .16)]
    assert notes == [Note(60, 0., .08), Note(61, .08, .16)]
    assert trace['parents'][0]['original']['raw_positive_midi_median'] == 60.5
    assert trace['parents'][0]['original']['pitch'] == 60
    # A no-cut contour may round its median away from its dominant raw label.
    notes, _, trace, old = run([60.1, 60.9] * 8, path=path)
    assert notes == old == [Note(60, 0., .16)]
    assert trace['candidate_cut_frames'] == []


def test_all_raw_zero_parent_has_no_raw_support_before_short_filter():
    notes, diag, trace, old = run([None] * 5)
    assert notes == old == []
    child = trace['parents'][0]['children'][0]
    assert child['raw_positive_midi_median'] is None
    assert child['pitch'] is None
    assert child['discard_reason'] == 'no_raw_support'
    assert diag['readout']['segments_without_raw_voiced_support'] == 1
    assert diag['readout']['short_segments_discarded'] == 0
    assert diag['child_midi_median_summary']['count'] == 0


def test_zero_duration_precedes_no_raw_support():
    notes, diag, trace, old = run([None], duration=0.)
    assert notes == old == []
    assert trace['parents'][0]['children'][0]['discard_reason'] == 'zero_duration'
    assert diag['readout']['zero_duration_segments'] == 1
    assert diag['readout']['segments_without_raw_voiced_support'] == 0
    assert diag['emitted_coverage_fraction'] == 0.


def test_no_inputs_are_mutated_and_trace_hashes_are_canonical():
    hz = frequencies([60] * 10 + [61] * 10)
    path = np.full(20, state(), dtype=np.int16)
    saved_hz, saved_path = hz.copy(), path.copy()
    hz.setflags(write=False)
    path.setflags(write=False)
    _, diag, trace = split.notes_from_state_path(path, hz, .2)
    assert np.array_equal(hz, saved_hz)
    assert np.array_equal(path, saved_path)
    assert diag['trace_sha256'] == fingerprint(trace)
    assert diag['candidate_cut_frames_sha256'] == fingerprint([10])
    assert diag['applied_cut_frames_sha256'] == fingerprint([10])
    labels = labels_from_hz(hz, support=5)
    assert diag['raw_hysteresis_label_identity'] == {
        'dtype': str(labels.dtype), 'shape': [20],
        'sha256': hashlib.sha256(labels.tobytes()).hexdigest()}
    json.dumps(diag, allow_nan=False)
    json.dumps(trace, allow_nan=False)


def test_public_summary_contains_no_individual_event_or_parent_trace():
    _, diag, trace, _ = run([60] * 10 + [61] * 10)
    assert 'parents' not in diag
    assert 'candidate_cut_frames' not in diag
    assert 'children' not in diag
    assert diag['child_midi_median_summary'] == {
        'count': 2, 'min': 60., 'q25': 60.25, 'median': 60.5,
        'q75': 60.75, 'max': 61., 'mean': 60.5}
    mutated = copy.deepcopy(trace)
    mutated['parents'][0]['children'][0]['pitch'] += 1
    assert fingerprint(mutated) != diag['trace_sha256']


def test_empty_input_retains_empty_summary_denominators():
    notes, diag, trace, old = run([], path=np.empty(0, dtype=np.int16), duration=0.)
    assert notes == old == []
    assert trace == {'schema_version': 1, 'candidate_cut_frames': [], 'parents': []}
    assert diag['readout'] == diag['baseline']
    assert diag['parent_segment_count'] == diag['child_segment_count'] == 0
    assert diag['child_seconds_summary'] == {'count': 0, 'min': None,
        'q25': None, 'median': None, 'q75': None, 'max': None, 'mean': None}


@pytest.mark.parametrize('hz', [np.array([np.nan]), np.array([np.inf]), np.array([-1.]),
                              np.array([[440.]]), frequencies([32]), frequencies([82])])
def test_invalid_raw_observations_use_original_validation(hz):
    with pytest.raises(ValueError):
        split.notes_from_state_path(np.array([state()], dtype=np.int16), hz, .01)


@pytest.mark.parametrize('path', [np.array([325.]), np.array([-1]), np.array([435]),
                                np.array([[325]]), np.array([], dtype=np.int16)])
def test_invalid_state_paths_use_original_validation(path):
    with pytest.raises(ValueError, match='state path'):
        split.notes_from_state_path(path, np.array([440.]), .01)


@pytest.mark.parametrize('duration', [-.01, .02, np.nan, np.inf])
def test_invalid_clock_or_duration_is_rejected(duration):
    with pytest.raises(ValueError, match='duration'):
        split.notes_from_state_path(np.array([state()], dtype=np.int16),
                                    np.array([440.]), duration)


def test_nonzero_duration_with_empty_input_is_rejected():
    with pytest.raises(ValueError, match='empty F0'):
        split.notes_from_state_path(np.array([], dtype=np.int16), np.array([]), .01)

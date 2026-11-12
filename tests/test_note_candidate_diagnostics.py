from dataclasses import replace

import numpy as np
import pytest

from scripts.note_candidate_diagnostics import (
    Note,
    candidates,
    error_partition,
    fingerprint,
    metrics,
    validate,
    window_oracle,
    windows,
)
from scripts.run_note_candidate_diagnostics import aggregate


def test_generator_no_reference_input_and_does_not_mutate():
    raw = [Note(60, .5, 1), Note(60, 1.03, 1.5)]
    before = fingerprint(raw)
    out = candidates(raw, [.5, .8, 1.03], 0, 4)
    assert fingerprint(raw) == before
    assert out[0]['kind'] == 'keep'
    assert {'merge', 'split'} <= {c['kind'] for c in out}
    assert all({n.pitch for n in c['notes']} == {60} for c in out)
    with pytest.raises(TypeError):
        candidates(raw, [.5], 0, 4, reference='not allowed')


def test_real_reattack_and_syncopation_original_always_available():
    raw = [Note(60, .5, 1), Note(60, 1, 1.5)]
    out = candidates(raw, [.5, 1], 0, 4)
    assert out[0]['notes'] == tuple(raw)


def test_no_merge_different_pitch_or_program():
    for second in (Note(62, 1, 2), Note(60, 1, 2, program=25)):
        out = candidates([Note(60, .5, 1), second], [.5, 1], 0, 4)
        assert 'merge' not in {c['kind'] for c in out}


def test_overlapping_boundary_and_drum_not_flattened():
    for notes in ([Note(60, .5, 2), Note(64, 1, 2)], [Note(60, 3.5, 5)],
                  [Note(36, .5, 2, is_drum=True)]):
        assert len(candidates(notes, [.5, 1], 0, 4)) == 1


def test_short_split_not_generated_and_cap_is_enforced():
    raw = [Note(60, .5, .62)]
    assert 'split' not in {c['kind'] for c in candidates(raw, [.56], 0, 4)}
    assert len(candidates([Note(60, .5, 3)], np.arange(.5, 3, .1), 0, 4, 3)) == 3


@pytest.mark.parametrize('note', [Note(60, 1, 0), Note(129, 0, 1),
                                 Note(60, float('nan'), 1), Note(60.5, 0, 1)])
def test_invalid_events_rejected(note):
    with pytest.raises(ValueError):
        validate([note])


@pytest.mark.parametrize('peaks', [[1, 1], [float('nan')], [2, 1]])
def test_invalid_peaks_rejected(peaks):
    with pytest.raises(ValueError):
        candidates([], peaks, 0, 4)


def test_windows_fixed_without_reference():
    first = windows('recording', 24)
    assert first == windows('recording', 24)
    assert len(first) == 3 and all(hi - lo == 4 for lo, hi in first)
    assert windows('recording', 2) == []


def test_disjoint_partition_conserves_counts_and_keeps_octave_distinct():
    ref_i = np.array([[0, 1], [2, 3], [4, 5], [6, 7], [8, 9], [10, 11.]])
    ref_p = np.full(6, 440.)
    notes = [Note(69, 0, 1), Note(69, 2, 2.2), Note(69, 4.1, 5),
             Note(57, 6, 7), Note(70, 8, 9), Note(50, 20, 21)]
    out = error_partition(notes, ref_i, ref_p)
    for key in ('full_match', 'pitch_onset_offset_mismatch', 'same_pitch_150ms',
                'octave_at_50ms', 'other_pitch_at_50ms', 'unmatched_reference', 'unmatched_prediction'):
        assert out[key] == 1
    assert metrics([Note(57, 0, 1)], np.array([[0, 1.]]), np.array([440.]))['onset_f1'] == 0


def test_oracle_not_musical_policy_and_never_worse_than_keep():
    raw = [Note(69, .1, .5)]
    options = candidates(raw, [.16], 0, 4)
    result = window_oracle(options, np.array([[.16, .5]]), np.array([440.]))
    assert result['oracle']['onset_f1']['gain'] == 1
    assert result['oracle']['onset_f1']['edit_kind'] == 'onset'
    assert options[0]['notes'] == tuple(raw)


def test_empty_reference_not_perfect_oracle_score():
    out = window_oracle(candidates([], [], 0, 4), np.empty((0, 2)), np.array([]))
    assert not out['scorable'] and out['baseline']['onset_f1'] is None


def test_empty_prediction_counts_all_reference_as_unmatched():
    out = error_partition([], np.array([[0, 1.]]), np.array([440.]))
    assert out['unmatched_reference'] == 1 and out['prediction_count'] == 0


def row(name):
    return {'id': name, 'status': 'scored', 'arms': {'raw': {'annotators': {
        a: {'primary': {'onset_f1': .5, 'onset_offset_f1': .2}} for a in ('A1', 'A2')}}}}


def test_incomplete_duplicate_missing_arms_are_not_success():
    assert aggregate([row('a')], ('a', 'b'), ('raw',)) is None
    assert aggregate([row('a'), row('a')], ('a', 'b'), ('raw',)) is None
    assert aggregate([row('a')], ('a',), ('raw', 'onset_065')) is None
    assert aggregate([row('a')], ('a',), ('raw',))['raw']['onset_f1'] == .5


def test_split_can_create_reattack_without_changing_pitch_or_endpoints():
    raw = [Note(69, .5, 1.5)]
    split = next(c for c in candidates(raw, [1], 0, 4) if c['kind'] == 'split')
    assert split['notes'] == (replace(raw[0], offset=1), replace(raw[0], onset=1))
    assert split['source_indices'] == [0]

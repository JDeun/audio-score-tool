from dataclasses import replace

import numpy as np
import pytest

from scripts.vocal_recovery import (
    Event,
    aggregate,
    event_digest,
    events_from,
    matched_transition,
    octave_proposals,
    onset_proposals,
)


def track(pitch=57):
    times = np.arange(201) / 100
    return times, np.full(len(times), 440 * 2 ** ((pitch - 69) / 12))


def test_octave_change_preserves_count_time_identity_and_source():
    n = Event(69, 0.1, 1.0, 2, 40)
    raw = [n]
    digest = event_digest(raw)
    out = octave_proposals(raw, *track())
    assert out == [replace(n, pitch=57)]
    assert event_digest(raw) == digest


def test_real_octave_leap_is_not_normalized():
    raw = [Event(57, .1, .7), Event(69, 1, 1.7)]
    times, hz = track()
    hz[times >= .9] *= 2
    assert octave_proposals(raw, times, hz) == raw


@pytest.mark.parametrize('case', ['silence', 'unstable', 'polyphonic', 'short', 'semitone', 'drum'])
def test_ambiguous_pitch_abstains(case):
    notes = [Event(69, .1, 1.0)]
    times, hz = track()
    if case == 'silence':
        hz[:] = 0
    elif case == 'unstable':
        hz[::2] *= 2 ** (1 / 12)
    elif case == 'polyphonic':
        notes.append(Event(60, .2, .8))
    elif case == 'short':
        notes = [Event(69, .1, .16)]
    elif case == 'semitone':
        times, hz = track(68)
    else:
        notes = [replace(notes[0], is_drum=True)]
    assert octave_proposals(notes, times, hz) == notes


def test_onset_unique_peak_and_unchanged_offset():
    raw = [Event(60, 0.15, .5)]
    assert onset_proposals(raw, np.array([.12])) == [replace(raw[0], onset=.12)]
    assert onset_proposals(raw, np.array([.12, .17])) == raw
    assert onset_proposals(raw, np.array([.30])) == raw


def test_shared_peak_collision_and_new_overlap_are_rejected():
    raw = [Event(60, .10, .16), Event(62, .18, .3)]
    assert onset_proposals(raw, np.array([.14])) == raw
    raw = [Event(60, .01, .16), Event(62, .18, .3)]
    assert onset_proposals(raw, np.array([.15])) == raw


def test_invalid_events_and_observations():
    with pytest.raises(ValueError):
        events_from([Event(60, 1, .5)])
    with pytest.raises(ValueError):
        octave_proposals([], np.array([0., 0.]), np.array([440., 440.]))
    with pytest.raises(ValueError):
        onset_proposals([], np.array([float('nan')]))


def row(case, score=.5):
    return {'id': case, 'status': 'scored', 'arms': {
        'raw': {'annotators': {a: {'onset_f1': score, 'onset_offset_f1': score}
                               for a in ('A1', 'A2')}}}}


def test_incomplete_or_duplicate_cases_never_emit_macro():
    assert aggregate([row('a')], ('a', 'b'), ('raw',)) is None
    assert aggregate([row('a'), row('a')], ('a', 'b'), ('raw',)) is None
    failed = row('b')
    failed['status'] = 'failed'
    assert aggregate([row('a'), failed], ('a', 'b'), ('raw',)) is None


def test_paired_aggregate_and_lost_match_reporting():
    result = aggregate([row('a', .2), row('b', .8)], ('a', 'b'), ('raw',))
    assert result['raw']['onset_f1']['macro'] == .5
    assert result['raw']['onset_f1']['paired_recording_bootstrap_95'] == [0., 0.]
    assert matched_transition({0, 1}, {1, 2}) == {
        'matched_prediction_ids_gained': 1, 'matched_prediction_ids_lost': 1}


def test_diagnostics_do_not_replace_strict_octave_sensitive_score():
    pytest.importorskip("mir_eval")
    from scripts.run_vocal_recovery import score_with_diagnostics

    result, matched = score_with_diagnostics([Event(57, .1, .5)], b'0.1,440,0.4\n')
    assert result['onset_f1'] == 0.0
    assert result['diagnostic_pitch_class_50ms_f1'] == 1.0
    assert result['diagnostic_onset_only_50ms_f1'] == 1.0
    assert not matched


def test_late_onset_is_diagnostic_not_a_shifted_prediction():
    pytest.importorskip("mir_eval")
    from scripts.run_vocal_recovery import score_with_diagnostics

    notes = [Event(69, .18, .6)]
    before = event_digest(notes)
    result, _ = score_with_diagnostics(notes, b'0.1,440,0.5\n')
    assert result['onset_f1'] == 0.0
    assert result['diagnostic_onset_100ms_f1'] == 1.0
    assert event_digest(notes) == before


def test_empty_valid_prediction_scores_zero():
    pytest.importorskip("mir_eval")
    from scripts.run_vocal_recovery import score_with_diagnostics

    result, matched = score_with_diagnostics([], b'0.1,440,0.4\n')
    assert result['onset_f1'] == result['onset_offset_f1'] == 0
    assert not matched


def test_octave_diagnostic_keeps_fractional_pitch_at_wrap_boundary():
    pytest.importorskip("mir_eval")
    from scripts.run_vocal_recovery import score_with_diagnostics

    result, _ = score_with_diagnostics([Event(57, .1, .5)], b'0.1,439,0.4\n')
    assert result['diagnostic_pitch_class_50ms_f1'] == 1.
    assert result['onset_f1'] == 0.

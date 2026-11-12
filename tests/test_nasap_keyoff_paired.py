"""Offline regression contracts; no scientific parameters learned from outcomes."""
from __future__ import annotations

import io

import mido
import pytest

from scripts.audit_nasap_duration_source import midi_key_events
from scripts.nasap_duration_probe import VOCAB, Observation, fit, sha
from scripts.nasap_keyoff_paired import (
    FrozenReader,
    aggregate,
    load_previous,
    masks_for,
    match_key_releases,
    paired_counts,
    representation_check,
    same_grid,
)


def data():
    rows = [{'id': 'a', 'onset_sec': '.5', 'duration_sec': '1.5',
             'pitch': '60', 'channel': '0'},
            {'id': 'b', 'onset_sec': '2', 'duration_sec': '1',
             'pitch': '62', 'channel': '0'}]
    obs = [Observation('a', 60, .5, 1.5), Observation('b', 62, 2, 1)]
    notes = [{'onset': .5, 'offset': 1., 'pitch': 60, 'channel': 0},
             {'onset': 2., 'offset': 2.5, 'pitch': 62, 'channel': 0}]
    return rows, obs, notes


def test_key_release_only_changes_endpoints():
    r, o, k = data()
    answer, info = match_key_releases(r, o, k, [0., 1., 2., 3.], [0., 1., 2., 3.])
    same_grid(o, answer)
    assert [n.duration for n in answer] == [.5, .5]
    assert all(x['extended'] for x in info.values())
    assert [n.duration for n in o] == [1.5, 1.]


def test_slight_onset_rounding_keeps_csv_onset():
    r, o, k = data()
    k[0]['onset'] = .500001
    answer, info = match_key_releases(r, o, k, [0., 1., 2., 3.], [0., 1., 2., 3.])
    assert answer[0].onset == .5
    assert answer[0].duration == .5
    assert info['a']['onset_residual'] == pytest.approx(.000001)


def test_variable_clock_uses_endpoint_not_average_bpm():
    r, o, k = data()
    # First interval is one second/quarter; second interval two seconds/quarter.
    k[0]['offset'] = 2.
    answer, _ = match_key_releases(r[:1], o[:1], k[:1], [0., 1., 3.], [0., 1., 2.])
    assert answer[0].duration == 1.0


def test_no_new_notes_from_shorter_key_duration():
    r, o, k = data()
    answer, _ = match_key_releases(r, o[:1], k, [0., 1., 2., 3.], [0., 1., 2., 3.])
    assert [n.id for n in answer] == ['a']


@pytest.mark.parametrize('problem', ('missing', 'ambiguous', 'outside', 'nonpositive', 'nan'))
def test_bad_key_mapping_fails_whole_passage(problem):
    r, o, k = data()
    if problem == 'missing':
        k.pop(0)
    elif problem == 'ambiguous':
        k.append(dict(k[0]))
    else:
        k[0]['offset'] = {'outside': 3.1, 'nonpositive': .5, 'nan': float('nan')}[problem]
    with pytest.raises(ValueError):
        match_key_releases(r, o, k, [0., 1., 2., 3.], [0., 1., 2., 3.])


def test_same_midi_note_cannot_be_reused_for_two_ids():
    r, o, k = data()
    r[1] = {**r[0], 'id': 'b'}
    o[1] = Observation('b', 60, .5, 1.5)
    with pytest.raises(ValueError):
        match_key_releases(r, o, k, [0., 1., 2., 3.], [0., 1., 2., 3.])


def test_identity_change_is_rejected():
    with pytest.raises(ValueError):
        same_grid([Observation('x', 60, 0, 1)], [Observation('x', 61, 0, 1)])


def test_metric_masks_and_pairwise_damage_are_recomputable():
    truth = {'a': (0., 1.), 'b': (.5, .5)}
    a = masks_for({'a': (0., 1.), 'b': (.5, 1.)}, truth, ['a', 'b'])
    b = masks_for({'a': (0., .5), 'b': (.5, .5)}, truth, ['a', 'b'])
    assert a['duration_mask'] == '10'
    assert b['duration_mask'] == '01'
    assert a['onset_exact'] == b['onset_exact'] == 2
    assert paired_counts(a['duration_mask'], b['duration_mask']) == {
        'fixed': 1, 'damaged': 1, 'both_correct': 0, 'both_wrong': 0}


@pytest.mark.parametrize('a,b', (('1', '01'), ('x', '0')))
def test_invalid_masks_are_not_counted_as_success(a, b):
    with pytest.raises(ValueError):
        paired_counts(a, b)


def test_every_declared_candidate_survives_true_score_literal_test():
    truth = {str(i): (i*.5, duration) for i, (duration, _) in enumerate(VOCAB)}
    result = representation_check(truth, sorted(truth))
    assert set(result['exact_duration_vocab_mask']) == {'1'}
    assert result['literal_score_input']['pair_exact'] == len(truth)


def test_unsupported_target_remains_visible_not_deleted():
    truth = {'x': (0., .7), 'y': (.5, 1.)}
    result = representation_check(truth, ['x', 'y'])
    assert result['tolerant_duration_vocab_mask'] == '01'
    assert result['literal_score_input']['n'] == 2
    assert result['literal_score_input']['duration_exact'] == 1


def test_identical_input_has_identical_predictions_for_all_methods():
    for mode in ('literal', 'spelling', 'articulation'):
        notes = [Observation('x', 60, 0, .5)]
        assert fit(notes, mode=mode) == fit(list(notes), mode=mode)


def test_raw_midi_handles_multitrack_and_tempo_changes():
    f = mido.MidiFile(type=1, ticks_per_beat=480)
    clock = mido.MidiTrack()
    notes = mido.MidiTrack()
    f.tracks.extend([clock, notes])
    clock.extend([mido.MetaMessage('set_tempo', tempo=500000),
                  mido.MetaMessage('set_tempo', tempo=1000000, time=480)])
    notes.extend([mido.Message('note_on', note=60, velocity=90, time=0),
                  mido.Message('note_off', note=60, time=960),
                  mido.Message('note_on', note=60, velocity=80, time=0),
                  mido.Message('note_on', note=60, velocity=0, time=480)])
    stream = io.BytesIO()
    f.save(file=stream)
    parsed, _ = midi_key_events(stream.getvalue())
    assert len(parsed) == 2
    assert parsed[0]['offset'] == 1.5
    assert parsed[1]['onset'] == 1.5
    assert parsed[1]['offset'] == 2.5


def test_frozen_reader_rejects_unlisted_path_before_network():
    with pytest.raises(ValueError):
        FrozenReader({}).get('unlisted.csv')


def test_frozen_reader_verifies_bytes(monkeypatch):
    monkeypatch.setattr('scripts.nasap_keyoff_paired.Reader.get', lambda _s, _p: b'actual')
    assert FrozenReader({'a': {'sha256': sha(b'actual')}}).get('a') == b'actual'
    with pytest.raises(ValueError):
        FrozenReader({'a': {'sha256': sha(b'wrong')}}).get('a')


def test_corrupt_receipt_is_rejected(tmp_path):
    path = tmp_path / 'prior.zip'
    path.write_bytes(b'wrong bytes')
    with pytest.raises(ValueError):
        load_previous(path)


def test_exclusions_do_not_disappear_from_summary():
    result = aggregate([{'status': 'prior_not_evaluated'}, {'status': 'failed_pair'}])
    assert result['planned'] == 2
    assert result['paired_complete'] == 0
    assert result['matched_notes'] == 0


def test_aggregated_counts_equal_masks_and_pairwise_counts():
    truth = {'a': (0., 1.), 'b': (.5, .5)}
    old = masks_for({'a': (0., 1.), 'b': (.5, 1.)}, truth, ['a', 'b'])
    new = masks_for(truth, truth, ['a', 'b'])
    methods = ('literal', 'spelling', 'articulation')
    case = {'status': 'complete', 'observed_notes': 2, 'matched_notes': 2,
            'max_clock_roundtrip_seconds': 0.,
            'preflight': representation_check(truth, ['a', 'b']),
            'metrics': {'csv_sustain': {m: old for m in methods},
                        'key_release': {m: new for m in methods}},
            'paired_key_vs_csv': {m: paired_counts('10', '11') for m in methods}}
    result = aggregate([case, {'status': 'prior_not_evaluated'}])
    assert result['arms']['key_release/literal']['duration_micro'] == 1.
    assert result['arms']['csv_sustain/literal']['duration_macro'] == .5
    assert result['paired']['literal']['fixed'] == 1
    assert result['paired']['literal']['better_passages'] == 1
    assert result['preflight']['exact_duration_vocab_count'] == 2

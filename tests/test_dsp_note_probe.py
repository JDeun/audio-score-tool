from dataclasses import asdict

import numpy as np
import pytest

from scripts.dsp_note_probe import (
    ARMS,
    CASES,
    DT,
    Note,
    aggregate,
    fingerprint,
    harmonic_evidence,
    labels_from_hz,
    notes_from_labels,
    reattack_split,
)


def hz(p):
    return 440 * 2 ** ((np.asarray(p) - 69) / 12)


@pytest.mark.parametrize('pitch', [0, 57, 69, 81, 127])
def test_a440_absolute_midi_mapping(pitch):
    assert labels_from_hz(hz([pitch] * 10)).tolist() == [pitch] * 10


def test_silence_and_empty_are_not_notes():
    assert notes_from_labels(labels_from_hz(np.zeros(20)), .2) == []
    assert notes_from_labels(np.array([], dtype=int), 0) == []


def test_hysteresis_suppresses_short_flip_but_retains_octave_leap():
    source = hz([69] * 10 + [70] * 2 + [69] * 10 + [81] * 10)
    before = source.copy()
    assert labels_from_hz(source, 5).tolist() == [69] * 22 + [81] * 10
    np.testing.assert_array_equal(source, before)
    assert len(notes_from_labels(labels_from_hz(source, 5), .32)) == 2


def test_confirmed_change_backdates_and_does_not_move_clock():
    labels = labels_from_hz(hz([60] * 10 + [62] * 10), 5)
    assert notes_from_labels(labels, .2) == [Note(60, 0, .1), Note(62, .1, .2)]


def test_silence_gap_is_not_filled_or_merged():
    labels = labels_from_hz(np.r_[hz([69] * 10), [0, 0], hz([69] * 10)], 5)
    result = notes_from_labels(labels, .22)
    assert result == [Note(69, 0, .1), Note(69, .12, .22)]


def test_last_padding_frame_is_clamped_to_audio():
    result = notes_from_labels(np.full(101, 69), 1.)
    assert result == [Note(69, 0, 1.)]


def test_minimum_length_exact_boundary():
    assert notes_from_labels(np.full(7, 69), .07) == []
    assert notes_from_labels(np.full(8, 69), .08) == [Note(69, 0, .08)]


def test_reattack_split_preserves_coverage_and_inputs():
    original = [Note(69, 0, 1.)]
    before = fingerprint([asdict(n) for n in original])
    result = reattack_split(original, [.5], np.full(101, 440.), np.ones(101))
    assert result == [Note(69, 0, .5), Note(69, .5, 1.)]
    assert fingerprint([asdict(n) for n in original]) == before
    assert sum(n.offset-n.onset for n in result) == 1.


@pytest.mark.parametrize('condition', ['short', 'unvoiced', 'wrong_pitch', 'weak', 'unstable'])
def test_reattack_rejects_insufficient_evidence(condition):
    original = [Note(69, 0, 1.)]
    frequency, prob, attacks = np.full(101, 440.), np.ones(101), [.5]
    if condition == 'short':
        attacks = [.02, .98]
    elif condition == 'unvoiced':
        frequency[50] = 0
    elif condition == 'wrong_pitch':
        frequency[:] = 220
    elif condition == 'weak':
        prob[:] = .4
    else:
        frequency[50] = 880
    assert reattack_split(original, attacks, frequency, prob) == original


def test_vibrato_inside_semitone_is_one_note():
    pitch = 69 + .25 * np.sin(2*np.pi*np.arange(200)*DT*5)
    assert len(notes_from_labels(labels_from_hz(hz(pitch), 5), 2)) == 1


@pytest.mark.parametrize('values', [[float('nan')], [-1.], [float('inf')]])
def test_invalid_f0_refused(values):
    with pytest.raises(ValueError):
        labels_from_hz(values)


def test_duplicate_attack_refused():
    with pytest.raises(ValueError):
        reattack_split([], [.1, .1], np.ones(10), np.ones(10))


def test_stronger_second_harmonic_is_not_fundamental_evidence():
    t = np.arange(8000) / 16000
    x = .2*np.sin(2*np.pi*220*t)+np.sin(2*np.pi*440*t)+.5*np.sin(2*np.pi*660*t)
    spectrum = np.abs(np.fft.rfft(x*np.hanning(len(x))))
    peak = np.fft.rfftfreq(len(x), 1/16000)[spectrum.argmax()]
    assert peak == 440
    assert harmonic_evidence(x, 220)['periodicity'] > harmonic_evidence(x, 440)['periodicity']
    # A score is diagnostic, not a guarantee: integer subharmonics also repeat.
    assert harmonic_evidence(x, 110)['periodicity'] > .9


def test_zero_signal_has_no_spectral_confidence():
    assert harmonic_evidence(np.zeros(100), 440) == {'periodicity': 0., 'harmonic_sum': 0.}


def row(case):
    return {'id': case, 'status': 'scored', 'arms': {
        a: {'count': 1, 'annotators': {r: {'onset_f1': .5, 'onset_offset_f1': .3}
                                     for r in ('A1', 'A2')}} for a in ARMS}}


def test_incomplete_duplicate_and_failed_cases_never_emit_complete_mean():
    rows = [row(c) for c in CASES]
    assert aggregate(rows)['pitch_runs']['onset_f1']['macro'] == .5
    assert aggregate(rows[:-1]) is None
    assert aggregate(rows[:-1]+[rows[0]]) is None
    rows[-1]['status'] = 'failed'
    assert aggregate(rows) is None


def test_nonfinite_scores_fail_closed():
    rows = [row(c) for c in CASES]
    rows[0]['arms']['pitch_runs']['annotators']['A1']['onset_f1'] = float('nan')
    with pytest.raises(ValueError):
        aggregate(rows)

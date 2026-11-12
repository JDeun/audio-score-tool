"""Offline tests of the frozen gate and evaluation bookkeeping, not accuracy claims."""
from __future__ import annotations

import copy

import numpy as np
import pytest

from scripts.audio_gate_rest import (
    Event,
    apply_gate,
    gains_and_damage,
    gate_levels,
    mask_intervals,
    occupancy_score,
    rms_envelope,
)
from scripts.run_audio_gate_rest import summarize


@pytest.mark.parametrize('sr', [8000, 16000, 44100])
def test_rms_constant_and_native_duration(sr):
    edges, db = rms_envelope(np.full(sr, .1), sr)
    assert len(db) == 100
    assert edges[0] == 0 and edges[-1] == 1
    assert np.allclose(db, -20, atol=1e-8)


def test_stereo_antiphase_does_not_cancel_power():
    x = np.full((16000, 2), .1)
    x[:, 1] *= -1
    _, db = rms_envelope(x, 16000)
    assert np.allclose(db, -20, atol=1e-8)


@pytest.mark.parametrize('mode', ['absolute', 'relative'])
def test_exact_silence_closed(mode):
    _, db = rms_envelope(np.zeros(16000), 16000)
    quiet, _ = gate_levels(db, mode)
    assert quiet.all()


def test_hysteresis_and_hold():
    quiet, _ = gate_levels(np.array([-20.] + [-47.] * 5 + [-42.] + [-47.] * 6
                                    + [-42.] + [-38.]), 'absolute')
    assert not quiet[:7].any()
    assert quiet[7:14].all()
    assert not quiet[-1]


def test_close_threshold_is_strict():
    quiet, _ = gate_levels(np.array([-20.] + [-45.] * 20), 'absolute')
    assert not quiet.any()


@pytest.mark.parametrize('gain', [-12, 12])
def test_relative_gain_invariance(gain):
    rng = np.random.default_rng(11)
    samples = rng.normal(0, .001, 16000)
    samples[4000:12000] += .1 * np.sin(np.arange(8000) * .1)
    _, a = rms_envelope(samples, 16000)
    _, b = rms_envelope(samples * 10 ** (gain/20), 16000)
    assert np.array_equal(gate_levels(a, 'relative')[0], gate_levels(b, 'relative')[0])


def test_absolute_threshold_is_gain_sensitive():
    _, quiet_sound = rms_envelope(np.full(16000, .005), 16000)
    _, boosted = rms_envelope(np.full(16000, .005) * 10 ** (12/20), 16000)
    assert gate_levels(quiet_sound, 'absolute')[0].all()
    assert not gate_levels(boosted, 'absolute')[0].any()


def test_note_order_and_identity_preserved_when_gate_open():
    notes = [Event(62, .2, .7), Event(60, .1, .8)]
    unchanged = copy.deepcopy(notes)
    edges = np.arange(101)/100
    for method in ('hard', 'soft'):
        output, diag = apply_gate(notes, edges, np.zeros(100, bool), method)
        assert output == notes == unchanged
        assert diag['changed_parents'] == 0


def test_hard_splits_but_does_not_change_pitch():
    quiet = np.zeros(100, bool)
    quiet[40:60] = True
    output, diag = apply_gate([Event(60, 0, 1)], np.arange(101)/100, quiet, 'hard')
    assert [(n.pitch, n.onset, n.offset) for n in output] == [(60, 0, .4), (60, .6, 1)]
    assert diag['split_parents'] == 1
    assert diag['removed_seconds'] == pytest.approx(.2)


def test_soft_retains_small_boundary_edit():
    quiet = np.zeros(100, bool)
    quiet[94:] = True
    note = Event(60, 0, 1)
    hard, _ = apply_gate([note], np.arange(101)/100, quiet, 'hard')
    soft, _ = apply_gate([note], np.arange(101)/100, quiet, 'soft')
    assert hard[0].offset == .94
    assert soft == [note]


def test_hard_can_delete_real_quiet_note_and_soft_may_retain_it():
    edges = np.arange(101)/100
    note = Event(60, .1, .18)
    hard, _ = apply_gate([note], edges, np.ones(100, bool), 'hard')
    soft, _ = apply_gate([note], edges, np.ones(100, bool), 'soft')
    assert hard == []
    assert soft == [note]


def test_unknown_audio_tail_is_not_deleted():
    note = Event(60, .5, 1.2)
    out, diag = apply_gate([note], np.arange(101)/100, np.ones(100, bool), 'hard')
    assert out == [note] and diag['out_of_audio_unchanged'] == 1


def test_internal_evaluation_ignores_easy_leading_trailing_padding():
    reference = np.array([[.2, .4], [.6, .8]])
    value = occupancy_score([], reference, np.arange(101)/100)
    assert value['reference_note_s'] == pytest.approx(.4)
    assert value['reference_gap_s'] == pytest.approx(.2)
    assert value['lost_note_s'] == pytest.approx(.4)
    assert value['gap_recall'] == 1
    assert value['gap_precision'] == pytest.approx(1/3)


def test_false_rest_and_missing_rest_are_separate():
    reference = np.array([[.2, .4], [.6, .8]])
    value = occupancy_score([(.2, .8)], reference, np.arange(101)/100)
    assert value['filled_reference_gap_s'] == pytest.approx(.2)
    assert value['lost_note_s'] == 0


def test_mask_intervals_endpoints():
    assert mask_intervals(np.arange(5), [False, True, True, False]) == [(1, 3)]
    assert mask_intervals(np.arange(4), [True]*3) == [(0, 3)]


def test_ambiguous_notated_articulation_cannot_be_read_from_identical_waveform():
    x = np.zeros(16000)
    x[:4000] = .1 * np.sin(np.arange(4000)*.1)
    # Staccato quarter and eighth+rest may have identical sound: no score supplied.
    a = gate_levels(rms_envelope(x, 16000)[1], 'relative')[0]
    b = gate_levels(rms_envelope(x.copy(), 16000)[1], 'relative')[0]
    assert np.array_equal(a, b)


@pytest.mark.parametrize('samples,sr', [(np.array([]), 16000),
                                       (np.array([np.nan]*100), 16000),
                                       (np.ones(100), 0)])
def test_invalid_audio_rejected(samples, sr):
    with pytest.raises(ValueError):
        rms_envelope(samples, sr)


def test_invalid_gate_timeline_and_modes_rejected():
    with pytest.raises(ValueError):
        gate_levels(np.array([0.]), 'unknown')
    with pytest.raises(ValueError):
        mask_intervals([0, 0, 1], [True, True])
    with pytest.raises(ValueError):
        apply_gate([], [0, 1], [False], 'unknown')


def test_match_transition_counts_and_shape():
    assert gains_and_damage('1010', '1100') == {'gained': 1, 'damaged': 1}
    with pytest.raises(ValueError):
        gains_and_damage('00', '0')


def test_partial_or_duplicate_result_cannot_claim_full_macro():
    assert summarize([], ['x']) is None
    assert summarize([{'id': 'x', 'status': 'failed'}], ['x']) is None
    assert summarize([{'id': 'x', 'status': 'scored'}]*2, ['x', 'y']) is None

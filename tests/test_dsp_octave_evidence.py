from dataclasses import replace

import numpy as np
import pytest

from scripts.dsp_octave_evidence import (
    FRAME,
    SR,
    Note,
    anchored_transitions,
    fingerprint,
    frame_gate,
    freeze_notes,
    periodicity,
    propose,
    spectral_evidence,
    spectral_gate,
)
from scripts.run_dsp_octave_hybrid import aggregate


def wave(f, seconds=2):
    return np.sin(2*np.pi*f*np.arange(round(SR*seconds))/SR)


def track(hz):
    return np.full(201,hz,dtype=float),np.ones(201)


def test_fractional_period_and_missing_fundamental():
    x = wave(440,.128)+.5*wave(660,.128)
    assert periodicity(x,220) > .99
    assert periodicity(x,440) < .7
    target, raw = spectral_evidence(x,220),spectral_evidence(x,440)
    assert spectral_gate(raw,target,-12)


def test_pure_tone_has_subharmonic_period_but_no_odd_support():
    x = wave(440,.128)
    assert periodicity(x,220) > .99
    assert not spectral_gate(spectral_evidence(x,440),spectral_evidence(x,220),-12)
    assert spectral_gate(spectral_evidence(x,220),spectral_evidence(x,440),12)


def test_silence_has_zero_evidence():
    x = np.zeros(FRAME)
    assert spectral_evidence(x,440) == dict(coverage=0.,odd_energy=0.,periodicity=0.)


@pytest.mark.parametrize('f',[55.,110.,220.,440.,880.,1760.])
def test_fractional_lag_resolves_valid_pure_tones(f):
    assert periodicity(wave(f,.128),f) > .99


@pytest.mark.parametrize('value',[0.,float('nan'),float('inf'),-220.,2500.])
def test_bad_frequency_rejected(value):
    with pytest.raises(ValueError):
        spectral_evidence(np.ones(FRAME),value)


def test_downward_correction_changes_only_pitch():
    notes = [Note(69,.2,1.8,4,52)]
    original = fingerprint(notes)
    hz,prob = track(220)
    out, rows = propose(notes,wave(220),hz,prob)
    assert out['pyin_octave'] == [replace(notes[0],pitch=57)]
    assert out['corroborated_octave'] == out['pyin_octave']
    assert rows[0]['supporting_windows'] == 5
    assert fingerprint(notes) == original


def test_false_pyin_octave_blocked_by_actual_spectrum():
    notes = [Note(69,.2,1.8)]
    hz,prob = track(220)
    out,_ = propose(notes,wave(440),hz,prob)
    assert out['pyin_octave'][0].pitch == 57
    assert out['corroborated_octave'] == notes


def test_upward_correction_and_real_octave_leap_retained():
    notes = [Note(57,.2,1.8)]
    hz,prob = track(440)
    out,_ = propose(notes,wave(440),hz,prob)
    assert out['corroborated_octave'][0].pitch == 69
    hz[:100] = 220
    notes = [Note(57,.2,.8),Note(69,1.2,1.8)]
    y = np.r_[wave(220,1),wave(440,1)]
    out,_ = propose(notes,y,hz,prob)
    assert all(value == notes for value in out.values())


@pytest.mark.parametrize('reason',['short','drum','weak','unstable','edge','not_octave','overlap','silence'])
def test_uncertain_notes_are_not_changed(reason):
    n = Note(69,.2,1.8)
    notes = [n]
    hz,prob = track(220)
    if reason == 'short':
        notes = [replace(n,offset=.28)]
    elif reason == 'drum':
        notes = [replace(n,is_drum=True)]
    elif reason == 'weak':
        prob[:] = .2
    elif reason == 'unstable':
        hz[::2] *= 2**(2/12)
    elif reason == 'edge':
        hz[:] = 880
    elif reason == 'not_octave':
        hz[:] = 330
    elif reason == 'overlap':
        notes.append(Note(60,.5,1.4))
    else:
        hz[:] = 0
    out,_ = propose(notes,wave(220),hz,prob)
    assert all(value == notes for value in out.values())


def test_frame_gate_can_only_remove_voicing():
    hz,prob = track(440)
    before = hz.copy()
    prob[50:100] = 0
    gated = frame_gate(wave(440),hz,prob)
    assert np.array_equal(hz,before)
    assert np.all((gated == 0) | (gated == hz))
    assert np.all(gated[50:100] == 0)


def test_unique_temporal_anchor_reports_repair_and_damage():
    before = [Note(69,.1,.8),Note(57,1.,1.8)]
    after = [replace(before[0],pitch=57),replace(before[1],pitch=69)]
    counts = anchored_transitions(before,after,[(.1,.8),(1.,1.8)],np.array([220.,220.]))
    assert counts['repaired'] == counts['damaged'] == 1
    assert counts['changed_anchored'] == 2


def test_ambiguous_temporal_anchor_not_claimed_correct():
    before = [Note(69,.1,.8)]
    after = [replace(before[0],pitch=57)]
    counts = anchored_transitions(before,after,[(.1,.8),(.1,.8)],np.array([220.,220.]))
    assert counts['anchored'] == 0
    assert counts['changed_unanchored'] == 1


def test_no_pitch_or_reference_arguments_to_selector():
    import inspect
    assert list(inspect.signature(propose).parameters) == ['notes','samples','hz','probability']


def test_valid_event_copy_and_invalid_event_rejection():
    n = Note(69,.1,1)
    assert freeze_notes([n]) == [n]
    with pytest.raises(ValueError):
        freeze_notes([replace(n,onset=2)])


def test_empty_output_is_valid_and_preserved():
    hz,prob = track(0)
    out,rows = propose([],np.zeros(SR),hz,prob)
    assert out == dict(raw=[],pyin_octave=[],corroborated_octave=[])
    assert rows == []


def test_missing_or_duplicate_results_never_produce_macro():
    assert aggregate([],['x'],['default']) is None
    assert aggregate([{'id':'x','status':'failed'}],['x'],['default']) is None
    assert aggregate([{'id':'x','status':'scored','bases':{} }]*2,['x','y'],['default']) is None


def test_source_low_amplitude_does_not_validate_change():
    hz,prob = track(220)
    n = Note(69,.2,1.8)
    out,_ = propose([n],wave(220)*1e-5,hz,prob)
    assert out['pyin_octave'][0].pitch == 57
    assert out['corroborated_octave'] == [n]

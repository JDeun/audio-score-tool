from dataclasses import replace

import numpy as np
import pytest

from scripts.offset_tail_evidence import (
    ARMS,
    Event,
    aggregate,
    anchor_diagnostics,
    assert_offset_only,
    bar_times,
    checked_events,
    metrical_controls,
    propose,
)


def observations(release=.5, pitch=69):
    t = np.arange(201) * .01
    activation = np.zeros((len(t), 88))
    active = (t >= .1) & (t < release)
    activation[active, pitch - 21] = .8
    hz = np.where(active, 440 * 2 ** ((pitch - 69) / 12), 0.)
    prob = active.astype(float)
    return t, activation, 2., t.copy(), hz, prob


@pytest.mark.parametrize('offset', [.4, .6])
def test_tail_can_extend_or_shorten_without_other_mutation(offset):
    notes = [Event(69, .1, offset, 2, 40)]
    data = observations()
    saved = data[1].copy()
    arms, audit = propose(notes, *data)
    for arm in ARMS[1:]:
        assert arms[arm] == [replace(notes[0], offset=.5)]
    assert arms['raw'] == notes
    assert notes[0].offset == offset
    assert np.array_equal(saved, data[1])
    assert audit['screening'] == {'proposed': 1}


def test_corroboration_can_abstain_without_changing_frame_arm():
    data = list(observations())
    data[4][:] = 440
    data[5][:] = 1
    notes = [Event(69, .1, .6)]
    arms, audit = propose(notes, *data)
    assert arms['activation_tail'][0].offset == .5
    assert arms['activation_tail_pyin'] == notes
    assert audit['pyin_confirmation'] == {'not_corroborated': 1}


@pytest.mark.parametrize('kind', ['short', 'drum', 'overlap', 'range', 'no_seed',
                                  'no_release', 'too_far', 'already', 'source_outside'])
def test_abstention_reasons(kind):
    notes = [Event(69, .1, .6)]
    data = list(observations())
    if kind == 'short':
        notes = [Event(69, .1, .18)]
    elif kind == 'drum':
        notes = [replace(notes[0], is_drum=True)]
    elif kind == 'overlap':
        notes.append(Event(72, .2, .7))
    elif kind == 'range':
        notes = [replace(notes[0], pitch=15)]
    elif kind == 'no_seed':
        data[1][:] = 0
    elif kind == 'no_release':
        data[1][:, 48] = .8
    elif kind == 'too_far':
        notes = [replace(notes[0], offset=1.0)]
    elif kind == 'already':
        notes = [replace(notes[0], offset=.5)]
    else:
        notes = [replace(notes[0], offset=3.)]
    arms, audit = propose(notes, *data)
    assert arms['activation_tail'] == notes
    assert sum(audit['screening'].values()) == len(notes)


def test_new_overlap_is_rejected():
    notes = [Event(69, .1, .4), Event(72, .45, .7)]
    arms, audit = propose(notes, *observations())
    assert arms['activation_tail'] == notes
    assert audit['screening']['would_overlap_next_event'] == 1


def test_brief_activation_dip_is_not_release():
    data = list(observations())
    data[1][30:32, 48] = 0
    arms, _ = propose([Event(69, .1, .6)], *data)
    assert arms['activation_tail'][0].offset == .5


def test_empty_is_valid_and_silence_does_not_delete_notes():
    arms, _ = propose([], *observations())
    assert all(n == [] for n in arms.values())
    data = list(observations())
    data[1][:] = 0
    notes = [Event(69, .1, .6)]
    arms, _ = propose(notes, *data)
    assert all(n == notes for n in arms.values())


@pytest.mark.parametrize('field,value', [('pitch', 70), ('onset', .12), ('channel', 3),
                                        ('program', 5), ('offset', float('nan'))])
def test_contract_rejects_mutations(field, value):
    n = Event(69, .1, .6)
    with pytest.raises(ValueError):
        assert_offset_only([n], [replace(n, **{field: value})])


def test_invalid_observation_clock_and_events():
    data = list(observations())
    data[0][8] = data[0][7]
    with pytest.raises(ValueError):
        propose([Event(69, .1, .6)], *data)
    with pytest.raises(ValueError):
        checked_events([Event(69, .2, .1)])


def test_unique_anchor_repair_and_harm_are_separate():
    intervals = np.array([[.1, .5]])
    hz = np.array([440.])
    wrong, right = Event(69, .1, .65), Event(69, .1, .5)
    assert anchor_diagnostics([wrong], [right], intervals, hz)['repaired'] == 1
    assert anchor_diagnostics([right], [wrong], intervals, hz)['harmed'] == 1
    ambiguous = anchor_diagnostics([wrong, wrong], [right, wrong], intervals, hz)
    assert ambiguous['unassessable'] == 1
    assert ambiguous['unique_anchor'] == 0


def row(name, value=.5):
    arms = {arm: {'changed_offsets': 0, 'annotators': {
        ann: {'onset_f1': value, 'onset_offset_f1': value} for ann in ('A1', 'A2')}} for arm in ARMS}
    return {'id': name, 'status': 'scored', 'bases': {'base': {'arms': arms}}}


def test_incomplete_duplicate_or_failed_results_have_no_macro():
    assert aggregate([row('a')], ('a', 'b'), ('base',)) is None
    assert aggregate([row('a'), row('a')], ('a', 'b'), ('base',)) is None
    failed = row('b')
    failed['status'] = 'failed'
    assert aggregate([row('a'), failed], ('a', 'b'), ('base',)) is None
    partial = row('b')
    partial['bases']['base']['arms'].pop('raw')
    assert aggregate([row('a'), partial], ('a', 'b'), ('base',)) is None


def test_macro_and_pairing():
    result = aggregate([row('a', .2), row('b', .8)], ('a', 'b'), ('base',))
    assert result['base']['raw']['onset_f1']['macro'] == .5
    assert result['base']['raw']['onset_f1']['recording_bootstrap95'] == [0., 0.]


@pytest.mark.parametrize('n,d,bpm,unit,period', [(4, 4, 120, 1, 2.), (3, 4, 120, 1, 1.5),
                                             (6, 8, 60, 1.5, 2.), (6, 8, 60, 1, 3.)])
def test_meter_requires_explicit_bpm_unit(n, d, bpm, unit, period):
    assert bar_times(n, d, bpm, unit, 2., 3) == [2., 2. + period, 2. + 2 * period]


def test_first_note_not_necessarily_downbeat_and_constant_tempo_can_drift():
    report = metrical_controls()
    errors = {r['case']: r['maximum_same_index_error_s'] for r in report['cases']}
    assert errors['four_four_downbeat'] == 0
    assert errors['four_four_pickup_one_quarter'] == .5
    assert errors['four_four_rest_before_entry'] == 1.
    assert report['one_bpm_error_after_50_bars_s'] == pytest.approx(.82644628099)
    assert report['constant_tempo_error_at_end_s'] == pytest.approx(1.6)
    assert report['used_in_offset_experiment'] is False


def test_reference_free_proposal_api():
    import inspect
    parameters = str(inspect.signature(propose))
    assert 'reference' not in parameters and 'bpm' not in parameters


def test_offset_only_strict_onset_f1_invariance():
    mt = pytest.importorskip('mir_eval.transcription')
    reference = np.array([[.1, .5]])
    hz = np.array([440.])
    old = np.array([[.1, .65]])
    new = np.array([[.1, .5]])
    def score(intervals, ratio):
        return mt.precision_recall_f1_overlap(reference, hz, intervals, hz,
                                             offset_ratio=ratio)[2]
    assert score(old, None) == score(new, None) == 1
    assert score(old, .2) == 0
    assert score(new, .2) == 1

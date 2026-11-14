import copy
import hashlib
import json
from collections import Counter

import numpy as np
import pytest

from scripts import drum_lane_controls as controls


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def test_fixed_input_inventory_contains_no_reference_events_and_is_not_mutable_state():
    inventory = controls.control_inventory()
    assert len(inventory) == controls.CONTROL_COUNT == 100
    assert tuple(case['id'] for case in inventory) == controls.CONTROL_IDS
    assert len({case['id'] for case in inventory}) == 100
    assert Counter(case['category'] for case in inventory) == {
        'supported_singleton': 12, 'same_class_pair': 48, 'simultaneous_supported': 6,
        'simultaneous_with_unsupported': 18, 'unsupported_singleton': 12, 'silence': 4}
    assert all(set(case) == {'id', 'category', 'sample_rate', 'sample_count',
                            'duration_seconds', 'level', 'seed'} for case in inventory)
    assert fingerprint(inventory) == 'd76f07edac97ee9a9d400af69baec2b2682adf6eb5917dcbb3f6f6484fdccbe3'
    inventory[0]['category'] = 'changed'
    assert controls.control_inventory()[0]['category'] == 'supported_singleton'


def test_all_hundred_integer_pcm_inputs_have_exact_frozen_sample_identities():
    identities = []
    for case in controls.control_inventory():
        samples, digest = controls.synthesize_input(case)
        assert samples.dtype.str == '<f4'
        assert samples.shape == (case['sample_count'],)
        assert case['sample_rate'] == controls.SAMPLE_RATE == 16000
        assert case['duration_seconds'] == len(samples) / 16000
        assert samples.flags.c_contiguous and not samples.flags.writeable
        assert np.isfinite(samples).all()
        recovered_pcm = samples.astype(np.float64) * 32768
        assert np.array_equal(recovered_pcm, np.trunc(recovered_pcm))
        assert np.all((-32768 <= recovered_pcm) & (recovered_pcm <= 32767))
        assert digest == hashlib.sha256(samples.tobytes(order='C')).hexdigest()
        if case['category'] == 'silence':
            assert np.count_nonzero(samples) == 0
        else:
            assert np.count_nonzero(samples[:min(controls.LEADING_SILENCE_FRAMES)]) == 0
            assert np.count_nonzero(samples) > 0
        identities.append({'id': case['id'], 'sha256': digest,
                           'dtype': samples.dtype.str, 'shape': list(samples.shape)})
    assert fingerprint(identities) == '42747825e07ad407b0a3f3c629dc9414ef52319f98306649f7c1e7c29bc8349f'


def test_synthesis_never_accesses_reference_function_or_transcendental_generators(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('construction accessed reference or transcendental/RNG path')

    monkeypatch.setattr(controls, 'control_reference', forbidden)
    for name in ('sin', 'cos', 'exp', 'power', 'linspace', 'hanning'):
        monkeypatch.setattr(np, name, forbidden)
    monkeypatch.setattr(np.random, 'default_rng', forbidden)
    samples, digest = controls.synthesize_input('ctl067')
    assert digest == 'd2b75d799d696b3a01ed6fef22bd1a6c6231495df96ddec92b954c7e0a128d73'
    assert samples.shape == (16000,)


@pytest.mark.parametrize(('identifier', 'gap_frames'), [
    ('ctl013', 240), ('ctl019', 480), ('ctl025', 960), ('ctl031', 1440),
    ('ctl037', 240), ('ctl043', 480), ('ctl049', 960), ('ctl055', 1440),
])
def test_authored_pair_schedule_keeps_both_distinct_event_ids(identifier, gap_frames):
    events = controls.control_reference(identifier)
    assert len(events) == 2
    assert events[0]['role'] == events[1]['role']
    assert round((events[1]['time'] - events[0]['time']) * 16000) == gap_frames
    assert events[0]['event_id'] != events[1]['event_id']
    assert all(event['velocity'] is None for event in events)


def test_simultaneous_and_unsupported_reference_events_remain_explicit():
    events = controls.control_reference('ctl061')
    assert events == [
        {'event_id': 'ctl061:e01', 'time': .12, 'role': 'kick', 'velocity': None},
        {'event_id': 'ctl061:e02', 'time': .12, 'role': 'backbeat', 'velocity': None}]
    mixed = controls.control_reference('ctl067')
    assert [event['role'] for event in mixed] == ['kick', 'backbeat', 'hat']
    assert len({event['time'] for event in mixed}) == 1
    assert controls.control_reference('ctl085')[0]['role'] == 'hat'
    assert controls.control_reference('ctl091')[0]['role'] == 'tom'
    assert controls.control_reference('ctl097') == []


@pytest.mark.parametrize('bad_case', [None, True, 1, 'ctl000', 'ctl101', {}, {'id': 'ctl001'}])
def test_unknown_or_incomplete_case_inputs_are_rejected(bad_case):
    with pytest.raises(ValueError):
        controls.synthesize_input(bad_case)
    with pytest.raises(ValueError):
        controls.control_reference(bad_case)


@pytest.mark.parametrize(('key', 'value'), [
    ('sample_count', 15999), ('sample_rate', 8000), ('duration_seconds', True),
    ('level', 'normal'), ('seed', 91), ('category', 'silence'), ('extra_truth', []),
])
def test_mutated_inventory_cannot_silently_select_a_different_input(key, value):
    case = copy.deepcopy(controls.control_inventory()[0])
    case[key] = value
    with pytest.raises(ValueError, match='control inventory metadata was altered'):
        controls.synthesize_input(case)
    with pytest.raises(ValueError, match='control inventory metadata was altered'):
        controls.control_reference(case)

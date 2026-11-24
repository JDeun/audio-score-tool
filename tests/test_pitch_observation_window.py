from __future__ import annotations

import hashlib
import json

import numpy as np
import pytest

from audio_score_tool import pitch_observation_window as window


def _fixture(tmp_path, *, count=101, start=0, end=50, status='linked', dtype=np.float32):
    vocal = tmp_path / 'vocal'
    vocal.mkdir()
    raw = np.full(count, 440., dtype=dtype)
    periodicity = np.ones(count, dtype=dtype)
    loudness = np.full(count, -30., dtype=dtype)
    periodicity[1] = .1
    periodicity[2] = np.float32(.21)
    loudness[3] = -61
    hz = np.where((periodicity >= .21) & (loudness >= -60), raw, 0.)
    pitch = vocal / 'pitch.npz'
    np.savez(pitch, times=np.arange(count) * .01, hz=hz, raw_hz=raw,
             periodicity=periodicity, loudness_db_a=loudness)
    sha = hashlib.sha256(pitch.read_bytes()).hexdigest()
    receipt = {'schema_version': 2, 'source_frames': (count - 1) * 160, 'source_sample_rate': 16000,
               'hop': 160, 'source_sha256': 'a' * 64, 'prediction_sha256': sha}
    runtime = vocal / 'pitch.runtime.json'
    runtime.write_text(json.dumps(receipt))
    prefix = {'pitch_sha256': sha, 'pitch_runtime_sha256': hashlib.sha256(runtime.read_bytes()).hexdigest(),
              'stem_sha256': receipt['source_sha256'], 'frame_count': count,
              'mappings': [{'selected_id': 's0', 'status': status, 'frame_start': start,
                            'frame_end_exclusive': end}]}
    return prefix, pitch, runtime


def test_frames_gate_transitions_and_clamped_endpoints(tmp_path):
    prefix, _, _ = _fixture(tmp_path, start=0, end=99)
    result = window.pitch_observation_window(tmp_path, prefix, ['s0'])
    assert result['status'] == 'available'
    source = result['sources'][0]
    assert (source['start_frame'], source['end_frame_exclusive']) == (0, 101)
    assert (source['note_frame_start'], source['note_frame_end_exclusive']) == (0, 99)
    assert source['frames'][1]['raw_hz'] == 440. and source['frames'][1]['hz'] == 0
    assert source['frames'][2]['periodicity'] < .21 and source['frames'][2]['hz'] == 440.
    assert source['gate_transitions'][:2] == [
        {'kind': 'rejected', 'left_frame': 0, 'right_frame': 1, 'from_seconds': 0., 'to_seconds': .01},
        {'kind': 'accepted', 'left_frame': 1, 'right_frame': 2, 'from_seconds': .01, 'to_seconds': .02}]
    assert result['acoustic_onset'] == result['perceptual_onset'] == {'status': 'not_measured'}


def test_each_proven_source_is_ordered_even_when_raw_match_is_ambiguous(tmp_path):
    prefix, _, _ = _fixture(tmp_path, status='ambiguous', start=30, end=40)
    prefix['mappings'].append({'selected_id': 's1', 'status': 'unavailable',
                               'frame_start': 80, 'frame_end_exclusive': 101})
    result = window.pitch_observation_window(tmp_path, prefix, ['s1', 's0'])
    assert result['status'] == 'available'
    assert [x['source_id'] for x in result['sources']] == ['s1', 's0']
    assert [(x['start_frame'], x['end_frame_exclusive']) for x in result['sources']] == [(55, 101), (5, 65)]


@pytest.mark.parametrize(('dtype', 'filtered_hz'), [(np.float32, 440.), (np.float64, 0.)])
def test_native_dtype_gate_decision_is_retained_in_json(tmp_path, dtype, filtered_hz):
    prefix, _, _ = _fixture(tmp_path, dtype=dtype)
    result = window.pitch_observation_window(tmp_path, prefix, ['s0'])
    assert result['status'] == 'available'
    frame = result['sources'][0]['frames'][2]
    assert frame['periodicity'] == float(np.float32(.21)) < .21
    assert frame['hz'] == filtered_hz


def test_limits_empty_and_missing_sources_do_not_truncate(tmp_path):
    prefix, _, _ = _fixture(tmp_path, count=1301, start=25, end=1177)
    assert window.pitch_observation_window(tmp_path, prefix, ['s0'])['reason'] == 'limit_exceeded'
    prefix['mappings'][0]['frame_end_exclusive'] = 1176
    assert len(window.pitch_observation_window(tmp_path, prefix, ['s0'])['sources'][0]['frames']) == 1201
    prefix['mappings'][0]['frame_end_exclusive'] = 25
    assert window.pitch_observation_window(tmp_path, prefix, ['s0'])['reason'] == 'empty_interval'
    assert window.pitch_observation_window(tmp_path, prefix, ['missing'])['status'] == 'unavailable'
    assert window.pitch_observation_window(tmp_path, prefix, [str(i) for i in range(17)])['reason'] == 'limit_exceeded'
    assert window.pitch_observation_window(tmp_path, None, ['s0'])['status'] == 'unavailable'


@pytest.mark.parametrize('damage', ['hash', 'receipt', 'symlink', 'changed_during_read', 'malformed_zip'])
def test_foreign_or_changed_archive_fails_closed(tmp_path, monkeypatch, damage):
    prefix, pitch, runtime = _fixture(tmp_path)
    if damage == 'hash':
        pitch.write_bytes(b'bad zip')
    elif damage == 'receipt':
        runtime.write_text('{}')
    elif damage == 'symlink':
        other = tmp_path / 'other.npz'
        pitch.rename(other)
        pitch.symlink_to(other)
    elif damage == 'malformed_zip':
        pitch.write_bytes(b'not a zip archive')
        prefix['pitch_sha256'] = hashlib.sha256(pitch.read_bytes()).hexdigest()
        receipt = json.loads(runtime.read_text())
        receipt['prediction_sha256'] = prefix['pitch_sha256']
        runtime.write_text(json.dumps(receipt))
        prefix['pitch_runtime_sha256'] = hashlib.sha256(runtime.read_bytes()).hexdigest()
    else:
        read = window.read_tiny_pitch_observation
        def change(*args):
            arrays = read(*args)
            pitch.write_bytes(b'changed')
            return arrays
        monkeypatch.setattr(window, 'read_tiny_pitch_observation', change)
    assert window.pitch_observation_window(tmp_path, prefix, ['s0'])['status'] == 'unavailable'

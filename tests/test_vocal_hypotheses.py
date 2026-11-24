from __future__ import annotations

import hashlib
import json

import mido
import numpy as np
import pytest

from audio_score_tool.vocal_hypotheses import build, read, write


def _midi(path, notes):
    midi = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    for pitch in notes:
        track.append(mido.Message('note_on', note=pitch, velocity=80, time=0))
    for i, pitch in enumerate(notes):
        track.append(mido.Message('note_off', note=pitch, time=480 if i == 0 else 0))
    midi.save(path)


def _fixture(tmp_path, raw_notes=(60,), selected_notes=(60,)):
    vocal = tmp_path / 'vocal'
    vocal.mkdir()
    raw, selected = vocal / 'score.mid', vocal / 'selected.mid'
    _midi(raw, raw_notes)
    _midi(selected, selected_notes)
    pitch = vocal / 'pitch.npz'
    hz = np.full(101, 440.)
    np.savez(pitch, times=np.arange(101) * .01, hz=hz, raw_hz=hz,
             periodicity=np.ones(101), loudness_db_a=np.zeros(101))
    stem_sha = hashlib.sha256(b'vocal stem').hexdigest()
    receipt = {'schema_version': 2, 'source_frames': 16000, 'source_sample_rate': 16000, 'hop': 160,
               'source_sha256': stem_sha, 'prediction_sha256': hashlib.sha256(pitch.read_bytes()).hexdigest()}
    pitch_runtime = vocal / 'pitch.runtime.json'
    pitch_runtime.write_text(json.dumps(receipt))
    runtime = vocal / 'score.runtime.json'
    runtime.write_text('{}')
    def construct():
        return build(raw, selected, pitch, receipt, stem_sha, runtime, pitch_runtime)
    return construct, receipt, vocal


def test_unique_ambiguous_and_unavailable_raw_segments(tmp_path):
    for name, raw, selected, status, count in [('unique', (60,), (60,), 'linked', 1),
                                                ('duplicate', (60, 60), (60,), 'ambiguous', 2),
                                                ('missing', (61,), (60,), 'unavailable', 0)]:
        root = tmp_path / name
        root.mkdir()
        construct, _, _ = _fixture(root, raw, selected)
        result = construct()
        row = result['mappings'][0]
        assert row['status'] == status and row['candidate_count'] == count
        assert len(result['candidates']) == len(raw)
        assert (row['frame_start'], row['frame_end_exclusive']) == (0, 50)
        assert bool(row['candidate_ids']) == (status == 'linked')


def test_binding_and_archive_validation_refuse_fabricated_prefix(tmp_path):
    construct, receipt, vocal = _fixture(tmp_path)
    sidecar = vocal / 'note-hypotheses.json'
    sha = write(sidecar, construct())
    recipe = {'vocal_hypotheses': {'schema_version': 1, 'sha256': sha}, 'pitch_verifier': receipt,
              'melody': {'runtime': {}}}
    assert read(tmp_path, recipe)['mappings'][0]['status'] == 'linked'
    receipt['source_sha256'] = '0' * 64
    with pytest.raises(ValueError, match='binding'):
        construct()
    receipt['source_sha256'] = hashlib.sha256(b'vocal stem').hexdigest()
    receipt['schema_version'] = 1
    with pytest.raises(ValueError, match='binding'):
        construct()
    receipt['schema_version'] = 2
    sidecar.write_text('{}')
    with pytest.raises(ValueError, match='SHA'):
        read(tmp_path, recipe)


def test_frame_bounds_use_exact_midi_clock_at_frame_centers(tmp_path):
    construct, _, vocal = _fixture(tmp_path)
    midi = mido.MidiFile(ticks_per_beat=1000)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    for _ in range(100):
        track.append(mido.Message('note_on', note=60, velocity=80))
        track.append(mido.Message('note_off', note=60, time=10))
    midi.save(vocal / 'score.mid')
    midi.save(vocal / 'selected.mid')
    rows = construct()['mappings']
    assert [(row['frame_start'], row['frame_end_exclusive']) for row in rows] == [
        ((i + 1) // 2, (i + 2) // 2) for i in range(100)]


def test_tempo_changes_use_exact_rational_model_clock(tmp_path):
    construct, _, vocal = _fixture(tmp_path)
    midi = mido.MidiFile(ticks_per_beat=1000)
    midi.tracks.append(mido.MidiTrack([
        mido.MetaMessage('set_tempo', tempo=500000),
        mido.Message('note_on', note=60, velocity=80),
        mido.Message('note_off', note=60, time=10),
        mido.MetaMessage('set_tempo', tempo=1000000),
        mido.Message('note_on', note=62, velocity=80),
        mido.Message('note_off', note=62, time=10),
    ]))
    midi.save(vocal / 'score.mid')
    midi.save(vocal / 'selected.mid')
    result = construct()
    assert [row['status'] for row in result['mappings']] == ['linked', 'linked']
    assert [(row['frame_start'], row['frame_end_exclusive']) for row in result['mappings']] == [(0, 1), (1, 2)]
    assert result['candidates'][1]['start_seconds'] == .005
    assert result['candidates'][1]['release_seconds'] == .015

import pytest

from audio_score_tool.beat_clock import beat_rows


def test_observed_beats_and_derived_boundaries():
    rows, meta = beat_rows([.5, 1., 1.5, 2., 2.5], [.5, 2.5], 3., [[0, 1, 4, 4]])
    assert [float(row[0]) for row in rows] == [0, .5, 1, 1.5, 2, 2.5, 3]
    assert meta['leading_derived_count'] == 1 and meta['trailing_derived_count'] == 1
    assert [int(row[1]) for row in rows] == [4, 1, 2, 3, 4, 1, 2]


@pytest.mark.parametrize('meter', [[[0,1,6,8]], [[0,1,4,4], [1,1,3,4]], [[0,1,4,8]], [[0,1,2,4]]])
def test_unsupported_meter_fails(meter):
    with pytest.raises(ValueError, match='Unsupported'):
        beat_rows([0, .5, 1, 1.5, 2], [0, 2], 2, meter)


def test_ambiguous_phase_fails():
    with pytest.raises(ValueError, match='Ambiguous'):
        beat_rows([0,.5,1,1.5,2], [0,.5], 2, [[0,1,4,4]])


def test_beat_receipt_rejects_tampering(tmp_path, monkeypatch):
    import hashlib
    import json
    from types import SimpleNamespace

    import numpy as np

    from audio_score_tool import fixed_vocal_infer, runner
    from audio_score_tool.beat_clock import fixed_beat_track
    from audio_score_tool.fixed_lead_recipe import BEAT_RUNTIME

    source = tmp_path / 'source.wav'
    source.write_bytes(b'owned audio')
    output = tmp_path / 'beat.npz'
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def fixture(*args, **kwargs):
        np.savez_compressed(output, beats=[0., .5, 1.], downbeats=[0.],
                            beat_logits=[0., 1.], downbeat_logits=[1., 0.])
        receipt = {'provider': 'beat-this', 'model': 'final0', 'device': 'cpu', 'threads': 2,
                   'seed': 0, 'dbn': True, 'source_revision': 'b95c8ab0c58c2d9fcfd40508ae8dffbc05ac4f5c',
                   'checkpoint_sha256': '8c328b45f59d8dd3dff219253ff6a8d6482be57d0133a29140e2febbf8eb8331',
                   'source_tree_sha256': '3f8d310da05e5b26fb455645dfcad5b835570b23a511003e351ce0f33b45fd04',
                   'madmom_source_revision': '27f032e8947204902c675e5e341a3faf5dc86dae',
                   'madmom_python_sha256': '28255419eddab6a2c801b240df2e8f418e4e8d2704d6caaa1146d41661f8167e',
                   'madmom_pyx_sha256': {}, 'madmom_native_sha256': {'ml/hmm.so': 'a' * 64},
                   'madmom_native_platform': 'test', 'source_frames': 441, 'source_sample_rate': 22050,
                   'madmom_pretrained_weights': False,
                   'dbn_parameters': {'fps': 50, 'beats_per_bar': [3, 4], 'min_bpm': 55.0,
                                      'max_bpm': 215.0, 'transition_lambda': 100},
                   'source_sha256': digest(source), 'prediction_sha256': digest(output),
                   'beat_logits_sha256': hashlib.sha256(np.asarray([0., 1.]).tobytes()).hexdigest(),
                   'downbeat_logits_sha256': hashlib.sha256(np.asarray([1., 0.]).tobytes()).hexdigest(),
                   'adapter_sha256': digest(__import__('pathlib').Path(fixed_vocal_infer.__file__)),
                   'python': '3.11.15', 'runtime': BEAT_RUNTIME}
        output.with_suffix('.runtime.json').write_text(json.dumps(receipt))

    monkeypatch.setattr(runner, 'run_command', fixture)
    settings = SimpleNamespace(fixed_vocal_cmd='fixture', fixed_lead_snapshot=tmp_path)
    assert fixed_beat_track(source, output, settings=settings)['provider'] == 'beat-this'
    old_fixture = fixture
    def tampered(*args, **kwargs):
        old_fixture(*args, **kwargs)
        output.write_bytes(b'tampered')
    monkeypatch.setattr(runner, 'run_command', tampered)
    with pytest.raises(ValueError, match='provenance'):
        fixed_beat_track(source, output, settings=settings)

    def invalid_logits(*args, **kwargs):
        old_fixture(*args, **kwargs)
        np.savez_compressed(output, beats=[0., .5, 1.], downbeats=[0.],
                            beat_logits=[float('nan')], downbeat_logits=[0.])
        path = output.with_suffix('.runtime.json')
        receipt = json.loads(path.read_text())
        receipt['prediction_sha256'] = digest(output)
        path.write_text(json.dumps(receipt))
    monkeypatch.setattr(runner, 'run_command', invalid_logits)
    with pytest.raises(ValueError, match='logits'):
        fixed_beat_track(source, output, settings=settings)

    def truncated(*args, **kwargs):
        old_fixture(*args, **kwargs)
        path = output.with_suffix('.runtime.json')
        receipt = json.loads(path.read_text())
        receipt['source_frames'] = 4410
        path.write_text(json.dumps(receipt))
    monkeypatch.setattr(runner, 'run_command', truncated)
    with pytest.raises(ValueError, match='whole source'):
        fixed_beat_track(source, output, settings=settings)


@pytest.mark.parametrize(('meter', 'downs', 'expected'), [
    (3, [.5, 2.], [3, 1, 2, 3, 1, 2, 3]),
])
def test_simple_meter_prefix_tail_and_phase(meter, downs, expected):
    rows, info = beat_rows([.5, 1., 1.5, 2., 2.5], downs, 3., [[0, 1, meter, 4]])
    assert [int(row[1]) for row in rows] == expected
    assert info['leading_derived_count'] == info['trailing_derived_count'] == 1
    assert info['observed_beat_rows'][0]['beat'] == 1


def test_rejects_unmatched_weak_majority_and_unbounded_padding():
    with pytest.raises(ValueError, match='does not match'):
        beat_rows([0, .5, 1, 1.5, 2], [.2], 2, [[0, 1, 4, 4]])
    with pytest.raises(ValueError, match='Ambiguous'):
        beat_rows([i * .5 for i in range(12)], [0, .5, 1], 5.5, [[0, 1, 3, 4]])
    with pytest.raises(ValueError, match='event limit'):
        beat_rows([.1, .100000000001], [.1], 1., [[0, 1, 4, 4]])


def test_pipeline_metadata_uses_observed_clock():
    from types import SimpleNamespace

    from audio_score_tool.pipeline_v2 import _apply_audio_clock

    _, clock = beat_rows([.5, 1., 1.5, 2., 2.5], [.5, 2.5], 3., [[0, 1, 4, 4]])
    analysis = {'meter': '4/4', 'beats': clock['observed_beat_rows'],
                'downbeats': clock['observed_downbeat_rows'], 'clock_provider': 'beat-this',
                'nominal_tempo_bpm': clock['nominal_tempo_bpm']}
    structure = SimpleNamespace(trimmed=False, music_start_seconds=0)
    _apply_audio_clock(structure, analysis, 'vocal_lead_v1')
    assert structure.tempo_bpm == 120 and structure.first_downbeat_seconds == .5
    assert structure.tempo_source == 'beat_this_audio_grid' and structure.meter_source == 'sheetsage2_audio_model'


def test_short_clock_uses_single_intervals():
    _, clock = beat_rows([0, .46, .92], [0], .92, [[0, 1, 4, 4]])
    assert clock['nominal_tempo_bpm'] == 130.43


@pytest.mark.parametrize('tempo', [None, 0, -1, float('nan'), float('inf'), True, '120'])
def test_fixed_clock_rejects_invalid_nominal_tempo(tempo):
    from types import SimpleNamespace
    from audio_score_tool.pipeline import PipelineError
    from audio_score_tool.pipeline_v2 import _apply_audio_clock

    with pytest.raises(PipelineError, match='valid audio beat'):
        _apply_audio_clock(SimpleNamespace(), {'meter': '4/4', 'clock_provider': 'beat-this',
                                               'nominal_tempo_bpm': tempo}, 'vocal_lead_v1')


def test_near_tied_global_phase_is_rejected():
    beats = [i * .5 for i in range(168)]
    downbeats = sorted([beats[4 * i] for i in range(42)] + [beats[4 * i + 1] for i in range(37)])
    with pytest.raises(ValueError, match='Ambiguous'):
        beat_rows(beats, downbeats, beats[-1], [[0, 1, 4, 4]])


def test_visible_tempo_matches_ui_without_changing_hidden_clock(tmp_path):
    import json
    from types import SimpleNamespace

    from audio_score_tool.metrics import midi_notes
    from audio_score_tool.notation_backend import musicxml_to_midi
    from audio_score_tool.pipeline_v2 import _apply_audio_clock
    from audio_score_tool.sheetsage2_score import import_native_lead_sheet

    times = [0., .46, .92, 1.36, 1.82, 2.28, 2.72, 3.18, 3.64]
    _, clock = beat_rows(times, [0., 1.82, 3.64], 3.64, [[0, 1, 4, 4]])
    analysis = {'meter': '4/4', 'beats': clock['observed_beat_rows'],
                'downbeats': clock['observed_downbeat_rows'], 'clock_provider': 'beat-this',
                'nominal_tempo_bpm': clock['nominal_tempo_bpm']}
    structure = SimpleNamespace(trimmed=False, music_start_seconds=0)
    _apply_audio_clock(structure, analysis, 'vocal_lead_v1')
    assert structure.tempo_bpm == clock['nominal_tempo_bpm'] == 131.87
    midis = []
    for name, nominal in [('observed', '131.87'), ('other', '98')]:
        root = tmp_path / name
        root.mkdir()
        (root / 'score.abc').write_text(f'X:1\nM:4/4\nL:1/4\nQ:1/4={nominal}\nV:Vocal clef=treble\nK:C\nV: Vocal\nC D E F |]\n')
        (root / 'playback.json').write_text(json.dumps({'measures': [dict(start=0, end=1.82, score_start=0, score_end=1)]}))
        (root / 'notation').mkdir()
        (root / 'notation/song_beats.txt').write_text(''.join(f'{t} {i % 4 + 1} 4 4\n' for i, t in enumerate(times)))
        report = import_native_lead_sheet(root, root / 'score.musicxml')
        if name == 'observed':
            assert report['nominal_tempo_bpm'] == pytest.approx(structure.tempo_bpm)
        musicxml_to_midi(root / 'score.musicxml', root / 'score.mid')
        midis.append(midi_notes(root / 'score.mid'))
    assert midis[0] == midis[1]


@pytest.mark.parametrize('present', [False, True])
def test_offline_missing_or_changed_checkpoint_never_reaches_network(tmp_path, monkeypatch, present):
    import socket
    import sys
    import urllib.request

    from audio_score_tool import fixed_vocal_infer

    checkpoint = tmp_path / 'beat-this/final0.ckpt'
    if present:
        checkpoint.parent.mkdir()
        checkpoint.write_bytes(b'not the pinned checkpoint')
    monkeypatch.setattr(fixed_vocal_infer, 'require_runtime', lambda expected: expected)
    monkeypatch.setattr(socket, 'create_connection', lambda *a, **k: pytest.fail('network forbidden'))
    monkeypatch.setattr(urllib.request, 'urlopen', lambda *a, **k: pytest.fail('network forbidden'))
    monkeypatch.setattr(sys, 'argv', ['fixed', 'beat', str(tmp_path / 'source.wav'),
                                     str(tmp_path / 'output.npz'), '--snapshot', str(tmp_path)])
    with pytest.raises(ValueError, match='checkpoint'):
        fixed_vocal_infer.main()
    assert not (tmp_path / 'output.npz').exists()

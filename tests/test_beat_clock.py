import pytest

from audio_score_tool.beat_clock import beat_rows


def test_observed_beats_and_derived_boundaries():
    rows, meta = beat_rows([.5, 1., 1.5, 2., 2.5], [.5, 2.5], 3., [[0, 1, 4, 4]])
    assert [float(row[0]) for row in rows] == [0, .5, 1, 1.5, 2, 2.5, 3]
    assert meta['leading_derived_count'] == 1 and meta['trailing_derived_count'] == 1
    assert [int(row[1]) for row in rows] == [4, 1, 2, 3, 4, 1, 2]


@pytest.mark.parametrize('meter', [[[0,1,6,8]], [[0,1,4,4], [1,1,3,4]], [[0,1,4,8]]])
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
    from audio_score_tool.fixed_lead_recipe import YOUR_RUNTIME

    source = tmp_path / 'source.wav'
    source.write_bytes(b'owned audio')
    output = tmp_path / 'beat.npz'
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def fixture(*args, **kwargs):
        np.savez_compressed(output, beats=[0., .5, 1.], downbeats=[0.])
        receipt = {'provider': 'beat-this', 'model': 'final0', 'device': 'cpu', 'threads': 2,
                   'seed': 0, 'dbn': False, 'source_revision': 'b95c8ab0c58c2d9fcfd40508ae8dffbc05ac4f5c',
                   'checkpoint_sha256': '8c328b45f59d8dd3dff219253ff6a8d6482be57d0133a29140e2febbf8eb8331',
                   'source_tree_sha256': '3f8d310da05e5b26fb455645dfcad5b835570b23a511003e351ce0f33b45fd04',
                   'source_sha256': digest(source), 'prediction_sha256': digest(output),
                   'adapter_sha256': digest(__import__('pathlib').Path(fixed_vocal_infer.__file__)),
                   'python': '3.11.15', 'runtime': {**YOUR_RUNTIME, 'beat-this': '1.1.0', 'torch': '2.7.1',
                                                   'numpy': '2.4.6', 'soundfile': '0.14.0'}}
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


@pytest.mark.parametrize(('meter', 'downs', 'expected'), [
    (2, [.5, 1.5, 2.5], [2, 1, 2, 1, 2, 1, 2]),
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
                'downbeats': clock['observed_downbeat_rows'], 'clock_provider': 'beat-this'}
    structure = SimpleNamespace(trimmed=False, music_start_seconds=0)
    _apply_audio_clock(structure, analysis, 'vocal_lead_v1')
    assert structure.tempo_bpm == 120 and structure.first_downbeat_seconds == .5
    assert structure.tempo_source == 'beat_this_audio_grid' and structure.meter_source == 'sheetsage2_audio_model'


def test_near_tied_global_phase_is_rejected():
    beats = [i * .5 for i in range(168)]
    downbeats = sorted([beats[4 * i] for i in range(42)] + [beats[4 * i + 1] for i in range(37)])
    with pytest.raises(ValueError, match='Ambiguous'):
        beat_rows(beats, downbeats, beats[-1], [[0, 1, 4, 4]])

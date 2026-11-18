from pathlib import Path

import numpy as np
import pytest
from music21 import harmony, note, stream, tempo

from audio_score_tool import lead_audio_validation as lead
from audio_score_tool import validation_api as api
from audio_score_tool.config import Settings
from audio_score_tool.settings_store import SettingsStore
from audio_score_tool.song_store_v2 import SongStoreV2


def score_xml(pitch="A5", chord="A"):
    score = stream.Score()
    part = stream.Part()
    part.partName = "Voice"
    part.insert(0, tempo.MetronomeMark(number=120))
    part.insert(0, harmony.ChordSymbol(chord))
    part.insert(0, note.Note(pitch, quarterLength=4))
    score.insert(0, part)
    return str(score.write("musicxml"))


def test_separate_melody_and_chord_evidence_use_actual_current_score(tmp_path, monkeypatch):
    xml = Path(score_xml()).read_text()
    times = np.arange(100) * 0.02
    monkeypatch.setattr(lead, "vocal_pitch_track", lambda *_a, **_k: (times, np.full(100, 69.0)))
    monkeypatch.setattr(lead, "_decode_to_wav", lambda source, target, cmd: target)
    # Original backing evidence is C minor; score A major should be flagged.
    chroma = np.zeros((12, 100))
    chroma[[0, 3, 7]] = 1 / np.sqrt(3)
    monkeypatch.setattr(lead, "_read_pcm16", lambda _path: (np.ones(22050), 22050))
    monkeypatch.setattr(lead, "_chroma", lambda *_a: chroma)
    report = lead.compare_lead_stems(vocal_audio=tmp_path / "vocals.wav",
                                    backing_audio=tmp_path / "backing.wav", xml_text=xml,
                                    ffmpeg_cmd="ffmpeg")
    assert report["melody"]["octave_suspects"] == 1
    assert report["chords"]["spectral_warnings"] == 1
    assert {x["source"] for x in report["issues"]} == {"vocal_acoustic", "chord_acoustic"}
    assert report["policy"]["auto_edit"] is False
    corrected = Path(score_xml("A4", "Cm")).read_text()
    report = lead.compare_lead_stems(vocal_audio=tmp_path / "vocals.wav",
                                    backing_audio=tmp_path / "backing.wav", xml_text=corrected,
                                    ffmpeg_cmd="ffmpeg")
    assert report["melody"]["consistent_notes"] == 1
    assert report["issues"] == []
    assert report["chords"]["wcsr"] is None


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    store = SongStoreV2(path=tmp_path / "db.sqlite", cache_root=tmp_path / "cache",
                        asset_root=tmp_path / "assets", export_root=tmp_path / "exports")
    xml_path = Path(score_xml())
    assert store.sync_completed_jobs([{"job_id": "test", "kind": "transcription", "status": "done",
                                       "filename": "test.wav", "score_mode": "lead_sheet",
                                       "result": {"musicxml": str(xml_path)}}]) == 1
    owner = store.asset_root / "test"
    owner.mkdir(exist_ok=True)
    (owner / "original-audio.wav").write_bytes(b"owned original")
    store.set_analysis("test", "music_structure", {"trimmed": True, "music_start_seconds": 3.0})
    monkeypatch.setattr(api, "_songs", store)
    monkeypatch.setattr(api, "_store", SettingsStore(tmp_path / "settings.json"))
    monkeypatch.setattr(api, "song_assets_dir", lambda: store.asset_root)
    monkeypatch.setattr(api, "runtime_settings", lambda **_k: Settings(validation_soundfont=None))
    return store


def test_product_validation_runs_without_soundfont_and_preserves_manual_edits(workspace, monkeypatch):
    store = workspace
    edit = store.checkout_current("test")
    edit.write_text(Path(score_xml("A4")).read_text())
    store.commit_edit_from_path("test", edit)
    before = store.score_xml("test")
    seen = []
    def compare(**kwargs):
        seen.append(kwargs)
        return {"issues": [{"source": "vocal_acoustic", "severity": "warning",
                             "category": "octave discrepancy", "message": "Review original"}]}
    monkeypatch.setattr(api, "validate_lead_audio", compare)
    report = api.validate_song("test", api.ValidateRequest(use_audio=True))
    assert len(seen) == 1
    assert seen[0]["origin_seconds"] == 3
    assert seen[0]["xml_text"] == before
    assert report["audio"] is None and "SoundFont" in report["audio_skipped"]
    assert report["review_required"] is True
    assert store.score_xml("test") == before
    assert store.get("test")["revision"] == 2
    assert store.analysis("test", "acoustic_validation") == report["acoustic"]


@pytest.mark.parametrize("structure", [None, {"trimmed": "false"}, {"trimmed": True, "music_start_seconds": float("nan")}])
def test_unknown_or_invalid_audio_clock_is_abstention_not_correctness(workspace, monkeypatch, structure):
    store = workspace
    store.set_analysis("test", "music_structure", structure)
    monkeypatch.setattr(api, "validate_lead_audio", lambda **_k: pytest.fail("Unknown clock"))
    report = api.validate_song("test", api.ValidateRequest(use_audio=True))
    assert report["acoustic"] is None
    assert report["acoustic_skipped"]


def test_missing_separator_is_reported_as_unmeasured_not_success():
    from audio_score_tool.audio_symbol_validation import AudioSymbolValidationError

    with pytest.raises(AudioSymbolValidationError, match="Demucs"):
        lead.validate_lead_audio(source_audio=Path("input.wav"), xml_text="",
                                  settings=Settings(demucs_cmd="definitely-missing-demucs"))


@pytest.mark.parametrize("saved,current,expected", [
    ("vocal_lead_v1", "sheetsage2", True), ("sheetsage2", "vocal_lead_v1", False),
])
def test_saved_engine_routes_pitch_after_job_removal(workspace, monkeypatch, tmp_path, saved, current, expected):
    workspace.set_analysis('test', 'model_evidence', {'selection': {'transcription_engine': saved}})
    job = tmp_path / 'jobs/test'
    job.mkdir(parents=True)
    import shutil
    shutil.rmtree(job)
    monkeypatch.setattr(api, 'runtime_settings', lambda **_k: Settings(transcription_engine=current))
    seen = []
    monkeypatch.setattr(api, 'validate_lead_audio', lambda **kwargs: seen.append(kwargs) or {'issues': []})
    api.validate_song('test', api.ValidateRequest(use_audio=True))
    assert not job.exists() and seen[0]['fixed_tiny'] is expected


def test_fixed_tiny_track_is_used_without_yin_reestimation(tmp_path, monkeypatch):
    monkeypatch.setattr(lead, 'vocal_pitch_track', lambda *_a, **_k: pytest.fail('unexpected YIN'))
    monkeypatch.setattr(lead, '_decode_to_wav', lambda source, target, cmd: target)
    monkeypatch.setattr(lead, '_read_pcm16', lambda _path: (np.ones(22050), 22050))
    monkeypatch.setattr(lead, '_chroma', lambda *_a: np.zeros((12, 100)))
    track = (np.arange(100) * .02, np.full(100, 69.0))
    report = lead.compare_lead_stems(vocal_audio=tmp_path / 'v.wav', backing_audio=tmp_path / 'b.wav',
                                    xml_text=Path(score_xml('A4')).read_text(), ffmpeg_cmd='ffmpeg',
                                    pitch_track=track, pitch_receipt={'model': 'tiny'})
    assert report['provider'] == 'separated_waveform_torchcrepe_tiny_chroma_v1'
    assert report['melody']['consistent_notes'] == 1
    assert report['pitch_provenance']['model'] == 'tiny'


def test_missing_fixed_tiny_is_error_without_yin_fallback(tmp_path, monkeypatch):
    from audio_score_tool.audio_symbol_validation import AudioSymbolValidationError

    monkeypatch.setattr(lead, 'demucs_ready', lambda _settings: True)
    monkeypatch.setattr(lead, 'prepare_demucs_audio', lambda _source, target, **_k: target)
    monkeypatch.setattr(lead, 'run_command', lambda *_a, **_k: None)
    monkeypatch.setattr(lead, '_stem', lambda root, name: root / f'{name}.wav')
    def missing(*_args, **_kwargs):
        raise ValueError('Tiny runtime unavailable')
    monkeypatch.setattr(lead, 'fixed_tiny_pitch_track', missing)
    monkeypatch.setattr(lead, 'vocal_pitch_track', lambda *_a, **_k: pytest.fail('unexpected YIN'))
    with pytest.raises(AudioSymbolValidationError, match='Tiny runtime unavailable'):
        lead.validate_lead_audio(source_audio=tmp_path / 'source.wav', xml_text='',
                                 settings=Settings(), fixed_tiny=True)


def test_no_chord_ends_previous_harmony_interval(tmp_path, monkeypatch):
    score = stream.Score()
    part = stream.Part()
    part.partName = 'Voice'
    part.insert(0, tempo.MetronomeMark(number=120))
    part.insert(0, harmony.ChordSymbol('A'))
    part.insert(2, harmony.NoChord())
    part.insert(0, note.Note('A4', quarterLength=4))
    score.insert(0, part)
    xml = Path(score.write('musicxml')).read_text()
    monkeypatch.setattr(lead, 'vocal_pitch_track', lambda *_a, **_k: (np.arange(100)*.02, np.full(100, 69.)))
    monkeypatch.setattr(lead, '_decode_to_wav', lambda source, target, cmd: target)
    monkeypatch.setattr(lead, '_read_pcm16', lambda _path: (np.ones(22050*3), 22050))
    chroma = np.zeros((12, 60))
    chroma[[9, 1, 4], :20] = 1 / np.sqrt(3)
    chroma[[0, 3, 7], 20:] = 1 / np.sqrt(3)
    monkeypatch.setattr(lead, '_chroma', lambda *_a: chroma)
    report = lead.compare_lead_stems(vocal_audio=tmp_path/'v.wav', backing_audio=tmp_path/'b.wav',
                                     xml_text=xml, ffmpeg_cmd='ffmpeg')
    assert report['chords']['compared_intervals'] == 1
    assert report['chords']['spectral_warnings'] == 0


def test_source_audio_http_is_authenticated_ranged_and_read_only(workspace, monkeypatch):
    import io
    import wave

    from fastapi.testclient import TestClient

    from audio_score_tool.api import app

    store = workspace
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b'\x00\x00' * 80)
    audio = buffer.getvalue()
    path = store.asset_root / 'test/original-audio.wav'
    path.write_bytes(audio)
    before = (store.score_xml('test'), store.get('test')['revision'], store.analysis('test', 'music_structure'))
    monkeypatch.setenv('AST_API_TOKEN', 'owned-test-token')
    client = TestClient(app)
    url = '/api/songs/test/source-audio?expected_revision=1'
    assert client.get(url).status_code == 401
    headers = {'X-AudioScore-Token': 'owned-test-token'}
    response = client.get(url, headers=headers)
    assert response.status_code == 200 and response.content == audio
    assert response.headers['content-type'] == 'audio/wav'
    assert response.headers['cache-control'] == 'private, no-store'
    partial = client.get(url, headers={**headers, 'Range': 'bytes=4-11'})
    assert partial.status_code == 206 and partial.content == audio[4:12]
    assert partial.headers['content-range'] == f'bytes 4-11/{len(audio)}'
    assert client.get('/api/songs/test/source-audio?expected_revision=2', headers=headers).status_code == 409
    assert client.get('/api/songs/missing/source-audio?expected_revision=1', headers=headers).status_code == 404
    assert client.get('/api/songs/test/source-audio', headers=headers).status_code == 422
    assert client.get('/api/songs/test/source-audio?expected_revision=0', headers=headers).status_code == 422
    assert (store.score_xml('test'), store.get('test')['revision'], store.analysis('test', 'music_structure')) == before


def test_source_audio_http_rejects_missing_symlink_and_ambiguous(workspace, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from audio_score_tool.api import app

    monkeypatch.delenv('AST_API_TOKEN', raising=False)
    client = TestClient(app)
    owner = workspace.asset_root / 'test'
    path = owner / 'original-audio.wav'
    url = '/api/songs/test/source-audio?expected_revision=1'
    (owner / 'original-audio.mp3').write_bytes(b'second')
    assert client.get(url).status_code == 404
    (owner / 'original-audio.mp3').unlink()
    path.unlink()
    assert client.get(url).status_code == 404
    outside = tmp_path / 'outside.wav'
    outside.write_bytes(b'external')
    path.symlink_to(outside)
    assert client.get(url).status_code == 404
    (owner / 'original-audio.mp3').write_bytes(b'second')
    assert client.get(url).status_code == 404


def test_source_audio_does_not_serve_partial_copy(workspace, tmp_path, monkeypatch):
    import io
    import shutil
    import wave
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from fastapi.testclient import TestClient

    from audio_score_tool import song_store_v2
    from audio_score_tool.api import app

    owner = workspace.asset_root / 'test'
    (owner / 'original-audio.wav').unlink()
    jobs = tmp_path / 'jobs'
    source = jobs / 'test/input.wav'
    source.parent.mkdir(parents=True)
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b'\x00\x00' * 800)
    source.write_bytes(buffer.getvalue())
    monkeypatch.setattr(song_store_v2, 'jobs_dir', lambda: jobs)
    real_copy = shutil.copyfileobj
    started, release = Event(), Event()

    def paused_copy(src, dst, *args, **kwargs):
        if str(dst.name).endswith('.copying'):
            dst.write(src.read(56))
            dst.flush()
            started.set()
            assert release.wait(10)
        return real_copy(src, dst, *args, **kwargs)

    monkeypatch.setattr(song_store_v2.shutil, 'copyfileobj', paused_copy)
    client = TestClient(app)
    url = '/api/songs/test/source-audio?expected_revision=1'
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(workspace._preserve_original_audio, 'test')
        assert started.wait(10)
        try:
            assert client.get(url).status_code == 404
        finally:
            release.set()
        assert pending.result(timeout=10) is not None
    response = client.get(url)
    assert response.status_code == 200 and response.content == source.read_bytes()
    assert response.headers['content-type'] == 'audio/wav'

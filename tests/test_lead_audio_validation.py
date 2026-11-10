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


def test_saved_fixed_engine_selects_tiny_independent_of_current_settings(workspace, monkeypatch):
    workspace.set_analysis('test', 'model_evidence', {'selection': {'transcription_engine': 'vocal_lead_v1'}})
    seen = []
    monkeypatch.setattr(api, 'validate_lead_audio', lambda **kwargs: seen.append(kwargs) or {'issues': []})
    api.validate_song('test', api.ValidateRequest(use_audio=True))
    assert seen[0]['fixed_tiny'] is True


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

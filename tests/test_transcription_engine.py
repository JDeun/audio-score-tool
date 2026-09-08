import sys
from pathlib import Path

import pytest

from audio_score_tool.config import Settings
from audio_score_tool.transcription_engine import (
    MT3InferEngine,
    MuScriptorEngine,
    NativeCommandEngine,
    TranscriptionEngineUnavailable,
    available_engines,
    resolve_transcription_engine,
)


def test_resolve_transcription_engine_types(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "audio_score_tool.transcription_engine.backend_status",
        lambda _settings: {"music21": True, "lilypond": False, "musicxml2ly": False},
    )
    mt3_settings = Settings(
        usage_mode="commercial",
        transcription_engine="mt3_infer",
        mt3_infer_cmd=sys.executable,
        mt3_model="mr_mt3",
    )
    mt3 = resolve_transcription_engine(mt3_settings)
    assert isinstance(mt3, MT3InferEngine)
    assert mt3.ready() is True

    alias_settings = Settings(
        usage_mode="personal",
        transcription_engine="yourmt3",
        mt3_infer_cmd=sys.executable,
    )
    assert isinstance(resolve_transcription_engine(alias_settings), MT3InferEngine)

    checkpoint = tmp_path / "native.pt"
    checkpoint.write_bytes(b"checkpoint")
    native_settings = Settings(
        transcription_engine="native",
        native_engine_cmd=sys.executable,
        native_checkpoint=checkpoint,
    )
    native = resolve_transcription_engine(native_settings)
    assert isinstance(native, NativeCommandEngine)
    assert native.ready() is True

    muscriptor_settings = Settings(
        usage_mode="personal",
        transcription_engine="muscriptor",
        muscriptor_cmd=sys.executable,
        muscriptor_model="large",
    )
    muscriptor = resolve_transcription_engine(muscriptor_settings)
    assert isinstance(muscriptor, MuScriptorEngine)
    assert muscriptor.settings.muscriptor_model == "large"


def test_available_engines_reports_quality_license_and_amt_capabilities(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "audio_score_tool.transcription_engine.backend_status",
        lambda _settings: {"music21": True, "lilypond": False, "musicxml2ly": False},
    )
    checkpoint = tmp_path / "native.pt"
    checkpoint.write_bytes(b"checkpoint")
    settings = Settings(
        usage_mode="personal",
        mt3_infer_cmd=sys.executable,
        mt3_model="mr_mt3",
        native_engine_cmd=sys.executable,
        native_checkpoint=checkpoint,
        muscriptor_cmd=sys.executable,
        muscriptor_model="large",
    )
    engines = {item["key"]: item for item in available_engines(settings)}
    assert engines["mt3_infer"]["commercial_status"] == "commercial_candidate"
    assert engines["mt3_infer"]["model"] == "mr_mt3"
    assert engines["mt3_infer"]["model_commercial_status"] == "mit"
    assert engines["mt3_infer"]["quality_rank"] == 3
    assert engines["mt3_infer"]["midi_to_musicxml"] == {
        "music21": True,
        "lilypond": False,
        "musicxml2ly": False,
    }
    assert engines["native"]["commercial_status"] == "project_owned"
    assert engines["native"]["ready"] is True
    assert engines["muscriptor"]["commercial_status"] == "noncommercial_weights"
    assert engines["muscriptor"]["quality_rank"] == 1
    assert engines["muscriptor"]["model"] == "large"

    for engine in engines.values():
        assert engine["task_family"] == "automatic_music_transcription"
        assert engine["input_mode"] == "mixed_audio"
        assert engine["supports_polyphonic"] is True
        assert engine["supports_multi_instrument"] is True
        assert engine["supports_real_time"] is False


def test_yourmt3_is_quality_first_mt3_option(monkeypatch):
    monkeypatch.setattr(
        "audio_score_tool.transcription_engine.backend_status",
        lambda _settings: {"music21": True, "lilypond": False, "musicxml2ly": False},
    )
    settings = Settings(
        usage_mode="commercial",
        mt3_infer_cmd=sys.executable,
        mt3_model="yourmt3",
    )
    engines = {item["key"]: item for item in available_engines(settings)}
    assert engines["mt3_infer"]["model"] == "yourmt3"
    assert engines["mt3_infer"]["model_commercial_status"] == "apache_checkpoint_review_distribution"
    assert engines["mt3_infer"]["quality_rank"] == 2


def test_mt3_requires_music21_even_if_command_is_available(monkeypatch):
    monkeypatch.setattr(
        "audio_score_tool.transcription_engine.backend_status",
        lambda _settings: {"music21": False, "lilypond": True, "musicxml2ly": True},
    )
    settings = Settings(
        usage_mode="commercial",
        transcription_engine="mt3_infer",
        mt3_infer_cmd=sys.executable,
        mt3_model="mr_mt3",
    )
    engine = resolve_transcription_engine(settings)

    assert engine.ready() is False
    with pytest.raises(TranscriptionEngineUnavailable, match="music21"):
        engine.transcribe(Path("input.wav"), Path("output"), device="cpu")


def test_muscriptor_is_blocked_in_commercial_mode():
    settings = Settings(
        usage_mode="commercial",
        transcription_engine="muscriptor",
        muscriptor_cmd=sys.executable,
    )
    with pytest.raises(TranscriptionEngineUnavailable):
        resolve_transcription_engine(settings)
    engines = {item["key"]: item for item in available_engines(settings)}
    assert engines["muscriptor"]["allowed_for_usage_mode"] is False

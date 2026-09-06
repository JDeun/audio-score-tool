import sys
from pathlib import Path

from audio_score_tool.config import Settings
from audio_score_tool.transcription_engine import (
    MuScriptorEngine,
    NativeCommandEngine,
    YourMT3Engine,
    available_engines,
    resolve_transcription_engine,
)


def test_resolve_transcription_engine_types(tmp_path: Path):
    yourmt3_settings = Settings(
        transcription_engine="yourmt3",
        yourmt3_cmd=sys.executable,
    )
    yourmt3 = resolve_transcription_engine(yourmt3_settings)
    assert isinstance(yourmt3, YourMT3Engine)
    assert yourmt3.ready() is True

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

    muscriptor_settings = Settings(transcription_engine="muscriptor", muscriptor_cmd=sys.executable)
    muscriptor = resolve_transcription_engine(muscriptor_settings)
    assert isinstance(muscriptor, MuScriptorEngine)


def test_available_engines_reports_commercial_status(tmp_path: Path):
    checkpoint = tmp_path / "native.pt"
    checkpoint.write_bytes(b"checkpoint")
    settings = Settings(
        yourmt3_cmd=sys.executable,
        native_engine_cmd=sys.executable,
        native_checkpoint=checkpoint,
        muscriptor_cmd=sys.executable,
    )
    engines = {item["key"]: item for item in available_engines(settings)}
    assert engines["yourmt3"]["commercial_status"] == "permissive_checkpoint"
    assert engines["yourmt3"]["ready"] is True
    assert engines["native"]["commercial_status"] == "project_owned"
    assert engines["native"]["ready"] is True
    assert engines["muscriptor"]["commercial_status"] == "noncommercial_weights"

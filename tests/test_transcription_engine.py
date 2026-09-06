import sys
from pathlib import Path

from audio_score_tool.config import Settings
from audio_score_tool.transcription_engine import (
    MT3InferEngine,
    MuScriptorEngine,
    NativeCommandEngine,
    available_engines,
    resolve_transcription_engine,
)


def test_resolve_transcription_engine_types(tmp_path: Path):
    mt3_settings = Settings(
        transcription_engine="mt3_infer",
        mt3_infer_cmd=sys.executable,
        mt3_model="mr_mt3",
        musescore_cmd=sys.executable,
    )
    mt3 = resolve_transcription_engine(mt3_settings)
    assert isinstance(mt3, MT3InferEngine)
    assert mt3.ready() is True

    # Migrate the short-lived v0.7 prerelease key without breaking local settings.
    alias_settings = Settings(
        transcription_engine="yourmt3",
        mt3_infer_cmd=sys.executable,
        musescore_cmd=sys.executable,
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

    muscriptor_settings = Settings(transcription_engine="muscriptor", muscriptor_cmd=sys.executable)
    muscriptor = resolve_transcription_engine(muscriptor_settings)
    assert isinstance(muscriptor, MuScriptorEngine)


def test_available_engines_reports_commercial_status(tmp_path: Path):
    checkpoint = tmp_path / "native.pt"
    checkpoint.write_bytes(b"checkpoint")
    settings = Settings(
        mt3_infer_cmd=sys.executable,
        mt3_model="mr_mt3",
        musescore_cmd=sys.executable,
        native_engine_cmd=sys.executable,
        native_checkpoint=checkpoint,
        muscriptor_cmd=sys.executable,
    )
    engines = {item["key"]: item for item in available_engines(settings)}
    assert engines["mt3_infer"]["commercial_status"] == "permissive_default"
    assert engines["mt3_infer"]["model"] == "mr_mt3"
    assert engines["mt3_infer"]["model_commercial_status"] == "mit"
    assert engines["mt3_infer"]["ready"] is True
    assert engines["native"]["commercial_status"] == "project_owned"
    assert engines["native"]["ready"] is True
    assert engines["muscriptor"]["commercial_status"] == "noncommercial_weights"


def test_yourmt3_is_explicit_license_review_option():
    settings = Settings(
        mt3_infer_cmd=sys.executable,
        mt3_model="yourmt3",
        musescore_cmd=sys.executable,
    )
    engines = {item["key"]: item for item in available_engines(settings)}
    assert engines["mt3_infer"]["model"] == "yourmt3"
    assert engines["mt3_infer"]["model_commercial_status"] == "license_review_recommended"

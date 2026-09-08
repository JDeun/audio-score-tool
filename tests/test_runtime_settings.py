from pathlib import Path

from audio_score_tool.runtime_settings import runtime_settings
from audio_score_tool.settings_store import SettingsStore


def test_runtime_settings_migrates_legacy_yourmt3_engine_from_store(tmp_path: Path):
    store = SettingsStore(tmp_path / "settings.json")
    store.update(
        {
            "transcription_engine": "yourmt3",
            "yourmt3_cmd": "mt3-infer-custom",
        }
    )

    settings = runtime_settings(store=store)
    assert settings.transcription_engine == "mt3_infer"
    assert settings.mt3_infer_cmd == "mt3-infer-custom"
    assert settings.yourmt3_cmd == "mt3-infer-custom"


def test_runtime_settings_load_native_engine_from_store(tmp_path: Path):
    checkpoint = tmp_path / "native.pt"
    checkpoint.write_bytes(b"checkpoint")
    store = SettingsStore(tmp_path / "settings.json")
    store.update(
        {
            "transcription_engine": "native",
            "native_engine_cmd": "audio-score-native-custom",
            "native_checkpoint": str(checkpoint),
        }
    )

    settings = runtime_settings(store=store)
    assert settings.transcription_engine == "native"
    assert settings.native_engine_cmd == "audio-score-native-custom"
    assert settings.native_checkpoint == checkpoint


def test_runtime_settings_ignores_retired_musescore_key(tmp_path: Path):
    store = SettingsStore(tmp_path / "settings.json")
    store.update({"musescore_cmd": "/legacy/MuseScore4", "lilypond_cmd": "lilypond-custom"})

    settings = runtime_settings(store=store)

    assert settings.lilypond_cmd == "lilypond-custom"
    assert not hasattr(settings, "musescore_cmd")

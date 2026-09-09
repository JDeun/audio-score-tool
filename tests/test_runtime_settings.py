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


def test_runtime_settings_ignores_retired_external_notation_keys(tmp_path: Path):
    store = SettingsStore(tmp_path / "settings.json")
    store.update(
        {
            "musescore_cmd": "/legacy/MuseScore4",
            "lilypond_cmd": "/legacy/lilypond",
            "musicxml2ly_cmd": "/legacy/musicxml2ly",
        }
    )

    settings = runtime_settings(store=store)

    assert not hasattr(settings, "musescore_cmd")
    assert not hasattr(settings, "lilypond_cmd")
    assert not hasattr(settings, "musicxml2ly_cmd")


def test_packaged_runtime_ignores_persisted_system_command_paths(monkeypatch, tmp_path: Path):
    component_dir = tmp_path / "components"
    store = SettingsStore(tmp_path / "settings.json")
    store.update(
        {
            "mt3_infer_cmd": "/usr/local/bin/mt3-infer",
            "muscriptor_cmd": "/usr/local/bin/muscriptor",
            "yt_dlp_cmd": "/usr/local/bin/yt-dlp",
            "audiveris_cmd": "/Applications/Audiveris/bin/audiveris",
            "ffmpeg_cmd": "/usr/local/bin/ffmpeg",
        }
    )
    monkeypatch.setenv("AST_PACKAGED", "1")
    monkeypatch.setenv("AST_COMPONENT_DIR", str(component_dir))

    settings = runtime_settings(store=store)

    assert Path(settings.mt3_infer_cmd).is_relative_to(component_dir)
    assert Path(settings.muscriptor_cmd).is_relative_to(component_dir)
    assert Path(settings.yt_dlp_cmd).is_relative_to(component_dir)
    assert Path(settings.audiveris_cmd).is_relative_to(component_dir)
    assert Path(settings.ffmpeg_cmd).is_relative_to(component_dir)

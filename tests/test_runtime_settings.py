from pathlib import Path

from audio_score_tool.runtime_settings import runtime_settings
from audio_score_tool.settings_store import SettingsStore


def test_explicit_engine_environment_is_not_replaced_by_personal_default(tmp_path, monkeypatch):
    monkeypatch.setenv("AST_TRANSCRIPTION_ENGINE", "sheetsage2")
    monkeypatch.setenv("AST_USAGE_MODE", "personal")
    store = SettingsStore(tmp_path / "settings.json")
    assert runtime_settings(store=store).transcription_engine == "sheetsage2"
    store.update({"transcription_engine": "mt3_infer"})
    assert runtime_settings(store=store).transcription_engine == "mt3_infer"


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



def test_packaged_approved_mr_mt3_becomes_functional_default_without_muscriptor(
    monkeypatch, tmp_path: Path,
):
    from audio_score_tool import runtime_settings as runtime_module
    monkeypatch.setenv("AST_PACKAGED", "1")
    monkeypatch.setenv("AST_COMPONENT_DIR", str(tmp_path / "components"))
    monkeypatch.setattr(runtime_module, "published_managed_mt3_model", lambda: "mr_mt3")
    store = SettingsStore(tmp_path / "settings.json")

    first_run = runtime_settings(store=store)
    assert first_run.usage_mode == "personal"
    assert first_run.transcription_engine == "mt3_infer"
    assert first_run.mt3_model == "mr_mt3"

    # Stale preferences from an earlier QA version cannot select a model that
    # does not exist in the independently approved packaged archive.
    store.update({
        "usage_mode": "commercial",
        "transcription_engine": "mt3_infer",
        "mt3_model": "yourmt3",
    })
    restored = runtime_settings(store=store)
    assert restored.mt3_model == "mr_mt3"
    assert store.read()["mt3_model"] == "yourmt3"


def test_packaged_unpublished_model_keeps_current_disabled_default(
    monkeypatch, tmp_path: Path,
):
    from audio_score_tool import runtime_settings as runtime_module
    monkeypatch.setenv("AST_PACKAGED", "1")
    monkeypatch.setattr(runtime_module, "published_managed_mt3_model", lambda: None)
    settings = runtime_settings(store=SettingsStore(tmp_path / "settings.json"))
    assert settings.transcription_engine == "muscriptor"
    assert settings.mt3_model == "yourmt3"

from pathlib import Path

from audio_score_tool.config import Settings, managed_executable_path


def test_packaged_runtime_uses_only_app_managed_command_paths(monkeypatch, tmp_path: Path):
    component_dir = tmp_path / "components"
    monkeypatch.setenv("AST_PACKAGED", "1")
    monkeypatch.setenv("AST_COMPONENT_DIR", str(component_dir))
    monkeypatch.setenv("AST_MUSCRIPTOR_CMD", "/tmp/system-muscriptor")
    monkeypatch.setenv("AST_YT_DLP_CMD", "/tmp/system-yt-dlp")
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")

    settings = Settings()

    expected = {
        "mt3_infer_cmd": "mt3-infer",
        "muscriptor_cmd": "muscriptor",
        "native_engine_cmd": "audio-score-native",
        "demucs_cmd": "demucs",
        "whisperx_cmd": "whisperx",
        "yt_dlp_cmd": "yt-dlp",
        "audiveris_cmd": "audiveris",
        "ffmpeg_cmd": "ffmpeg",
        "fluidsynth_cmd": "fluidsynth",
    }
    for field, executable in expected.items():
        assert Path(getattr(settings, field)) == managed_executable_path(executable)


def test_managed_command_is_not_ready_until_app_installs_component(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("AST_PACKAGED", "1")
    monkeypatch.setenv("AST_COMPONENT_DIR", str(tmp_path / "components"))

    settings = Settings()

    assert not Path(settings.yt_dlp_cmd).exists()
    assert not Path(settings.audiveris_cmd).exists()

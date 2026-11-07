import hashlib
import os
import stat
import zipfile
from pathlib import Path

import pytest

from audio_score_tool.managed_components import ComponentArtifact, install_component_artifact
from audio_score_tool.managed_tool_resolver import (
    is_registered_managed_executable,
    registered_managed_tool,
)
from audio_score_tool.runner import CommandError, command_exists, run_command

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


def _install_verified_script(tmp_path: Path, monkeypatch):
    root = tmp_path / "components"
    archive = tmp_path / "tool.zip"
    relative = "bin/runtime-helper"
    with zipfile.ZipFile(archive, "w") as bundle:
        info = zipfile.ZipInfo(relative)
        info.external_attr = (stat.S_IFREG | 0o755) << 16
        bundle.writestr(info, b"#!/bin/sh\necho approved\n")
    artifact = ComponentArtifact(
        component="runtime-fixture",
        version="1",
        url="https://example.invalid/fixture.zip",
        sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        archive="zip",
        tools={"fixture-helper": relative},
    )
    install_component_artifact(artifact, root=root, local_archive=archive)
    monkeypatch.setenv("AST_PACKAGED", "1")
    monkeypatch.setenv("AST_COMPONENT_DIR", str(root))
    approved = registered_managed_tool("fixture-helper")
    assert approved is not None
    return root, approved


def test_packaged_runtime_blocks_unregistered_bin_even_when_file_exists(tmp_path, monkeypatch):
    root = tmp_path / "components"
    legacy = root / "bin" / "ffmpeg"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("fake binary", encoding="utf-8")
    monkeypatch.setenv("AST_PACKAGED", "1")
    monkeypatch.setenv("AST_COMPONENT_DIR", str(root))
    assert not is_registered_managed_executable(legacy)
    assert not command_exists(str(legacy))
    with pytest.raises(CommandError, match="not a verified app-managed component"):
        run_command(str(legacy), [])


def test_packaged_runtime_rejects_path_and_composite_command_fallback(tmp_path, monkeypatch):
    _root, approved = _install_verified_script(tmp_path, monkeypatch)
    assert command_exists(str(approved))
    assert is_registered_managed_executable(approved)
    assert not command_exists("sh")
    assert not command_exists(str(approved) + " --help")
    with pytest.raises(CommandError, match="not a verified app-managed component"):
        run_command("sh", ["-c", "echo should-not-run"])
    with pytest.raises(CommandError, match="not a verified app-managed component"):
        run_command(str(approved) + " --help", [])
    with pytest.raises(CommandError, match="not a verified app-managed component"):
        run_command(str(tmp_path / "outside"), [])


@pytest.mark.skipif(os.name == "nt", reason="Synthetic POSIX script is not a Windows executable")
def test_packaged_runner_can_execute_verified_installed_script(tmp_path, monkeypatch):
    _root, approved = _install_verified_script(tmp_path, monkeypatch)
    result = run_command(str(approved), [])
    assert result.stdout.strip() == "approved"


def test_packaged_runtime_blocks_post_install_tool_mutation(tmp_path, monkeypatch):
    _root, approved = _install_verified_script(tmp_path, monkeypatch)
    assert command_exists(str(approved))
    approved.write_bytes(b"tampered")
    assert not is_registered_managed_executable(approved)
    assert not command_exists(str(approved))
    with pytest.raises(CommandError, match="not a verified app-managed component"):
        run_command(str(approved), [])


def test_packaged_runtime_blocks_unregistered_tools_even_when_path_lookup_finds_one(
    tmp_path, monkeypatch,
):
    from audio_score_tool import runner

    _root, approved = _install_verified_script(tmp_path, monkeypatch)
    monkeypatch.setattr(runner.shutil, "which", lambda _name: str(approved))
    assert command_exists("fixture-helper") is False
    with pytest.raises(CommandError, match="not a verified app-managed component"):
        run_command("fixture-helper", [])

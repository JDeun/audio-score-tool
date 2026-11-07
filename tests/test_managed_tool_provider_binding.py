"""Packaged runtimes must never mix executable owners by shared tool name.

Synthetic local archives exercise the real installer and SHA-256 state without
network access, third-party binaries, or redistribution assumptions.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import zipfile
from pathlib import Path

import pytest

from audio_score_tool.config import Settings, managed_executable_path
from audio_score_tool.managed_components import (
    ComponentArtifact,
    component_status,
    install_component_artifact,
    remove_component_artifact,
    resolve_managed_tool,
)
from audio_score_tool.managed_tool_resolver import (
    is_registered_managed_executable,
    registered_managed_tool,
)
from audio_score_tool.runner import command_exists
from audio_score_tool.youtube import (
    _youtube_ffmpeg_args,
    _youtube_js_runtime_args,
    youtube_tool_status,
)


def _install(
    tmp_path: Path, root: Path, component: str, names: tuple[str, ...],
    *, version: str = "1",
) -> None:
    archive = tmp_path / f"{component}.zip"
    suffix = ".exe" if os.name == "nt" else ""
    with zipfile.ZipFile(archive, "w") as bundle:
        for name in names:
            info = zipfile.ZipInfo(f"bin/{name}{suffix}")
            info.external_attr = (stat.S_IFREG | 0o755) << 16
            bundle.writestr(info, f"owned-by-{component}:{name}".encode())
    artifact = ComponentArtifact(
        component=component,
        version=version,
        url="https://example.invalid/never-published-ci.zip",
        sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        archive="zip",
        tools={name: f"bin/{name}{suffix}" for name in names},
    )
    assert install_component_artifact(
        artifact, root=root, local_archive=archive,
    )["ready"] is True


@pytest.fixture
def dual_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "managed"
    # alphabetically first in state.json: previously a validation FFmpeg
    # silently shadowed the YouTube-owned FFmpeg.
    _install(tmp_path, root, "audio_validation", ("ffmpeg", "ffprobe", "fluidsynth"))
    _install(tmp_path, root, "youtube_runtime", ("yt-dlp", "deno", "ffmpeg", "ffprobe"))
    monkeypatch.setenv("AST_PACKAGED", "1")
    monkeypatch.setenv("AST_COMPONENT_DIR", str(root))
    return root


def test_packaged_youtube_uses_its_own_ffmpeg_ffprobe_and_deno(
    dual_provider: Path,
):
    youtube_ffmpeg = registered_managed_tool("ffmpeg", component="youtube_runtime")
    youtube_ffprobe = registered_managed_tool("ffprobe", component="youtube_runtime")
    youtube_deno = registered_managed_tool("deno", component="youtube_runtime")
    validation_ffmpeg = registered_managed_tool("ffmpeg", component="audio_validation")
    assert youtube_ffmpeg and youtube_ffprobe and youtube_deno and validation_ffmpeg
    assert youtube_ffmpeg != validation_ffmpeg

    # Explicit scope plus the generic default must use one deterministic owner.
    assert registered_managed_tool("ffmpeg") == youtube_ffmpeg
    assert registered_managed_tool("ffprobe") == youtube_ffprobe
    assert resolve_managed_tool("ffmpeg", root=dual_provider) == youtube_ffmpeg
    assert resolve_managed_tool(
        "ffmpeg", root=dual_provider, component="audio_validation",
    ) == validation_ffmpeg
    assert managed_executable_path("ffmpeg") == youtube_ffmpeg
    assert Settings().ffmpeg_cmd == str(youtube_ffmpeg)
    assert _youtube_js_runtime_args() == ["--js-runtimes", f"deno:{youtube_deno}"]
    assert _youtube_ffmpeg_args() == ["--ffmpeg-location", str(youtube_ffmpeg.parent)]

    status = youtube_tool_status(Settings())
    assert status["ready"] is True
    assert status["ffmpeg"] == str(youtube_ffmpeg)
    assert status["ffprobe"] == str(youtube_ffprobe)
    # Both owners can still use independently verified absolute executables.
    assert is_registered_managed_executable(validation_ffmpeg)
    assert command_exists(str(validation_ffmpeg))


def test_other_component_cannot_satisfy_missing_youtube_ffprobe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    root = tmp_path / "managed"
    _install(tmp_path, root, "audio_validation", ("ffmpeg", "ffprobe"))
    _install(tmp_path, root, "youtube_runtime", ("yt-dlp", "deno", "ffmpeg"))
    monkeypatch.setenv("AST_PACKAGED", "1")
    monkeypatch.setenv("AST_COMPONENT_DIR", str(root))
    assert registered_managed_tool("ffprobe") is not None
    assert registered_managed_tool("ffprobe", component="youtube_runtime") is None
    status = youtube_tool_status(Settings())
    assert status["ffprobe_ready"] is False
    assert status["ready"] is False


def test_mutated_youtube_ffmpeg_cannot_fallback_to_validation_bundle(
    dual_provider: Path,
):
    corrupt = registered_managed_tool("ffmpeg", component="youtube_runtime")
    spare = registered_managed_tool("ffmpeg", component="audio_validation")
    assert corrupt and spare
    corrupt.write_bytes(b"tampered-youtube-tool")
    assert registered_managed_tool("ffmpeg", component="youtube_runtime") is None
    # A generic consumer may still use the independently approved spare.
    assert registered_managed_tool("ffmpeg") == spare
    status = youtube_tool_status(Settings())
    assert status["ffmpeg_ready"] is False
    assert status["ready"] is False
    assert status["ffmpeg"] != str(spare)


def test_uninstalling_youtube_does_not_remove_validation_ffmpeg(
    dual_provider: Path,
):
    spare = registered_managed_tool("ffmpeg", component="audio_validation")
    assert spare
    assert remove_component_artifact("youtube_runtime", root=dual_provider)["removed"]
    assert registered_managed_tool("ffmpeg") == spare
    assert is_registered_managed_executable(spare)
    assert not youtube_tool_status(Settings())["ready"]


def test_forged_state_root_cannot_alias_another_component(
    dual_provider: Path,
):
    state_path = dual_provider / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    youtube_entry = state["components"]["youtube_runtime"]
    youtube_entry["root"] = "installed/audio_validation/1"
    youtube_entry["tools"]["ffmpeg"] = "bin/ffmpeg" + (".exe" if os.name == "nt" else "")
    youtube_entry["tool_sha256"]["ffmpeg"] = hashlib.sha256(
        (dual_provider / "installed/audio_validation/1" / youtube_entry["tools"]["ffmpeg"]).read_bytes()
    ).hexdigest()
    state_path.write_text(json.dumps(state), encoding="utf-8")
    assert component_status("youtube_runtime", root=dual_provider)["integrity"] == "state-invalid"
    assert registered_managed_tool("ffmpeg", component="youtube_runtime") is None

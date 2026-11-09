from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from audio_score_tool.api_ext import app
from audio_score_tool.config import Settings
from audio_score_tool.managed_components import ComponentArtifact, install_component_artifact
from audio_score_tool.managed_tool_resolver import registered_managed_tool
from audio_score_tool.runner import command_exists
from audio_score_tool.youtube import (
    YouTubeSourceError,
    download_youtube_audio,
    inspect_youtube,
    validate_youtube_url,
    youtube_tool_status,
)

_YOUTUBE_TOOLS = ("yt-dlp", "deno", "ffmpeg", "ffprobe")


def _install_youtube_fixture(tmp_path: Path, monkeypatch, *, missing: str | None = None):
    """Use the real installer and SHA-verified registry, never loose bin files."""
    root = tmp_path / "components"
    archive_path = tmp_path / "youtube-fixture.zip"
    suffix = ".exe" if os.name == "nt" else ""
    tools = {
        name: f"bin/{name}{suffix}" for name in _YOUTUBE_TOOLS if name != missing
    }
    with zipfile.ZipFile(archive_path, "w") as archive:
        for name, relative in tools.items():
            info = zipfile.ZipInfo(relative)
            info.external_attr = (stat.S_IFREG | 0o755) << 16
            archive.writestr(info, f"synthetic-{name}".encode())
    artifact = ComponentArtifact(
        component="youtube_runtime",
        version="fixture-1",
        url="https://example.invalid/ci-fixture.zip",
        sha256=hashlib.sha256(archive_path.read_bytes()).hexdigest(),
        archive="zip",
        tools=tools,
    )
    install_component_artifact(artifact, root=root, local_archive=archive_path)
    monkeypatch.setenv("AST_PACKAGED", "1")
    monkeypatch.setenv("AST_COMPONENT_DIR", str(root))
    return root


def test_validate_youtube_url_accepts_standard_hosts():
    assert validate_youtube_url("https://www.youtube.com/watch?v=abc123")
    assert validate_youtube_url("https://youtu.be/abc123")
    assert validate_youtube_url("https://music.youtube.com/watch?v=abc123")


def test_validate_youtube_url_rejects_other_hosts():
    with pytest.raises(YouTubeSourceError):
        validate_youtube_url("https://example.com/watch?v=abc123")


def test_validate_youtube_url_rejects_plain_http():
    with pytest.raises(YouTubeSourceError, match="HTTPS"):
        validate_youtube_url("http://www.youtube.com/watch?v=abc123")


@pytest.mark.parametrize(
    "url",
    [
        "https://user:password@www.youtube.com/watch?v=abc123",
        "https://www.youtube.com:444/watch?v=abc123",
        "https://127.0.0.1/watch?v=abc123",
        "file:///etc/passwd",
    ],
)
def test_validate_youtube_url_rejects_credential_and_ssrf_like_inputs(url: str):
    with pytest.raises(YouTubeSourceError):
        validate_youtube_url(url)


def test_commercial_youtube_job_requires_authorization_confirmation(monkeypatch):
    from audio_score_tool import job_lifecycle_api_v2 as jobs

    monkeypatch.setattr(jobs, "runtime_settings", lambda: Settings(usage_mode="commercial"))
    client = TestClient(app)
    response = client.post(
        "/api/jobs/youtube",
        json={
            "url": "https://www.youtube.com/watch?v=abc123",
            "authorized": False,
        },
    )
    assert response.status_code == 422
    assert "권한" in response.json()["detail"]


def test_youtube_job_rejects_non_youtube_url():
    client = TestClient(app)
    response = client.post(
        "/api/jobs/youtube",
        json={"url": "https://example.com/audio", "authorized": True},
    )
    assert response.status_code == 422


def test_inspect_youtube_parses_metadata(monkeypatch):
    payload = {
        "title": "Example Song",
        "uploader": "Example Artist",
        "duration": 123.4,
        "webpage_url": "https://www.youtube.com/watch?v=abc123",
        "thumbnail": "https://i.ytimg.com/example.jpg",
    }

    def fake_run_command(*args, **kwargs):
        return subprocess.CompletedProcess([], 0, json.dumps(payload))

    monkeypatch.setattr("audio_score_tool.youtube.run_command", fake_run_command)
    metadata = inspect_youtube(
        "https://www.youtube.com/watch?v=abc123",
        settings=Settings(yt_dlp_cmd="yt-dlp"),
    )
    assert metadata.title == "Example Song"
    assert metadata.uploader == "Example Artist"
    assert metadata.duration == 123.4


def test_packaged_youtube_binds_yt_dlp_to_managed_runtime(monkeypatch, tmp_path: Path):
    _install_youtube_fixture(tmp_path, monkeypatch)
    deno = registered_managed_tool("deno")
    ffmpeg = registered_managed_tool("ffmpeg")
    ffprobe = registered_managed_tool("ffprobe")
    assert deno and ffmpeg and ffprobe
    captured: list[list[object]] = []

    def fake_run_command(command, args, **kwargs):
        captured.append(list(args))
        return subprocess.CompletedProcess(
            [],
            0,
            json.dumps(
                {"title": "Example", "duration": 60, "webpage_url": "https://youtu.be/abc123"}
            ),
        )

    monkeypatch.setattr("audio_score_tool.youtube.run_command", fake_run_command)
    settings = Settings()
    metadata = inspect_youtube("https://youtu.be/abc123", settings=settings)

    assert metadata.title == "Example"
    assert captured
    args = [str(value) for value in captured[0]]
    assert args[:2] == ["--ignore-config", "--no-remote-components"]
    assert args.count("--ignore-config") == 1
    assert args.count("--no-remote-components") == 1
    assert "--remote-components" not in args
    js_index = args.index("--js-runtimes")
    assert args[js_index + 1] == f"deno:{deno}"
    ffmpeg_index = args.index("--ffmpeg-location")
    assert args[ffmpeg_index + 1] == str(ffmpeg.parent)

    status = youtube_tool_status(settings)
    assert status["ready"] is True
    assert status["js_runtime"] == str(deno)
    assert status["ffmpeg"] == str(ffmpeg)
    assert status["ffprobe"] == str(ffprobe)
    assert status["ffmpeg_ready"] is True
    assert status["ffprobe_ready"] is True
    setup = TestClient(app).get("/api/setup/center")
    assert setup.status_code == 200
    components = {item["key"]: item for item in setup.json()["components"]}
    assert components["youtube_runtime"]["ready"] is True


@pytest.mark.parametrize("missing_tool", _YOUTUBE_TOOLS)
def test_packaged_youtube_is_not_ready_without_required_managed_tool(
    monkeypatch, tmp_path: Path, missing_tool: str,
):
    _install_youtube_fixture(tmp_path, monkeypatch, missing=missing_tool)
    monkeypatch.setattr(
        "audio_score_tool.youtube.run_command",
        lambda *_a, **_kw: (_ for _ in ()).throw(
            AssertionError("Unverified YouTube runtime must not execute")
        ),
    )
    status = youtube_tool_status(Settings())
    assert status["ready"] is False
    setup = TestClient(app).get("/api/setup/center")
    assert setup.status_code == 200
    components = {item["key"]: item for item in setup.json()["components"]}
    assert components["youtube_runtime"]["ready"] is False
    key = {
        "deno": "js_runtime_ready",
        "ffmpeg": "ffmpeg_ready",
        "ffprobe": "ffprobe_ready",
    }.get(missing_tool)
    if key:
        assert status[key] is False
    with pytest.raises(YouTubeSourceError, match="incomplete or unverified"):
        inspect_youtube("https://youtu.be/abc123", settings=Settings())


@pytest.mark.parametrize("missing_tool", ["ffmpeg", "ffprobe"])
def test_development_youtube_readiness_requires_media_tools(monkeypatch, missing_tool):
    from audio_score_tool import youtube

    monkeypatch.delenv("AST_PACKAGED", raising=False)
    available = {"yt-dlp", "ffmpeg", "ffprobe"} - {missing_tool}
    monkeypatch.setattr(youtube, "command_exists", lambda cmd: cmd in available)
    status = youtube_tool_status(Settings(yt_dlp_cmd="yt-dlp", ffmpeg_cmd="ffmpeg"))
    assert status["ready"] is False
    assert status[f"{missing_tool}_ready"] is False


def test_unregistered_legacy_bin_files_do_not_enable_youtube(monkeypatch, tmp_path: Path):
    root = tmp_path / "components"
    legacy = root / "bin"
    legacy.mkdir(parents=True)
    for name in _YOUTUBE_TOOLS:
        (legacy / (name + (".exe" if os.name == "nt" else ""))).write_bytes(b"unverified")
    monkeypatch.setenv("AST_PACKAGED", "1")
    monkeypatch.setenv("AST_COMPONENT_DIR", str(root))
    settings = Settings()
    assert not command_exists(settings.yt_dlp_cmd)
    assert youtube_tool_status(settings)["ready"] is False
    monkeypatch.setattr(
        "audio_score_tool.youtube.run_command",
        lambda *_a, **_kw: (_ for _ in ()).throw(
            AssertionError("Loose unregistered executable must never execute")
        ),
    )
    with pytest.raises(YouTubeSourceError, match="incomplete or unverified"):
        inspect_youtube("https://youtu.be/abc123", settings=settings)


def test_packaged_youtube_rechecks_integrity_after_metadata_inspection(monkeypatch, tmp_path):
    _install_youtube_fixture(tmp_path, monkeypatch)
    deno = registered_managed_tool("deno")
    assert deno is not None
    calls = []

    def fake_run(command, args, **kwargs):
        calls.append(list(args))
        if "--dump-single-json" not in args:
            raise AssertionError("Download was started after managed Deno tampering")
        deno.write_bytes(b"modified-after-metadata")
        return subprocess.CompletedProcess(
            [], 0,
            json.dumps({
                "title": "Example",
                "duration": 60,
                "webpage_url": "https://youtu.be/abc123",
            }),
        )

    monkeypatch.setattr("audio_score_tool.youtube.run_command", fake_run)
    with pytest.raises(YouTubeSourceError, match="changed after inspection"):
        download_youtube_audio("https://youtu.be/abc123", tmp_path / "output", settings=Settings())
    assert len(calls) == 1


def test_inspect_youtube_rejects_active_live(monkeypatch):
    payload = {
        "title": "Live",
        "is_live": True,
        "webpage_url": "https://www.youtube.com/live/abc123",
    }

    monkeypatch.setattr(
        "audio_score_tool.youtube.run_command",
        lambda *args, **kwargs: subprocess.CompletedProcess([], 0, json.dumps(payload)),
    )
    with pytest.raises(YouTubeSourceError, match="생방송"):
        inspect_youtube("https://www.youtube.com/live/abc123", settings=Settings(yt_dlp_cmd="yt-dlp"))


def test_inspect_youtube_rejects_excessive_duration(monkeypatch):
    payload = {
        "title": "Very Long",
        "duration": 20_000,
        "webpage_url": "https://youtu.be/abc123",
    }
    monkeypatch.setattr(
        "audio_score_tool.youtube.run_command",
        lambda *args, **kwargs: subprocess.CompletedProcess([], 0, json.dumps(payload)),
    )
    with pytest.raises(YouTubeSourceError, match="최대"):
        inspect_youtube("https://youtu.be/abc123", settings=Settings(yt_dlp_cmd="yt-dlp"))


def test_download_youtube_audio_uses_downloaded_input(monkeypatch, tmp_path):
    payload = {
        "title": "Example Song",
        "duration": 60,
        "webpage_url": "https://youtu.be/abc123",
    }
    calls = 0

    def fake_run_command(command, args, **kwargs):
        nonlocal calls
        calls += 1
        if "--dump-single-json" in args:
            return subprocess.CompletedProcess([], 0, json.dumps(payload))
        (tmp_path / "input.m4a").write_bytes(b"audio")
        return subprocess.CompletedProcess([], 0, "")

    monkeypatch.setattr("audio_score_tool.youtube.run_command", fake_run_command)
    audio, metadata = download_youtube_audio(
        "https://youtu.be/abc123",
        tmp_path,
        settings=Settings(yt_dlp_cmd="yt-dlp"),
    )
    assert calls == 2
    assert audio == tmp_path / "input.m4a"
    assert metadata.title == "Example Song"


def test_personal_youtube_job_does_not_require_ownership_assertion(
    monkeypatch, tmp_path: Path,
):
    """The actual v2 HTTP route must not block a personal practice link."""
    from audio_score_tool import job_lifecycle_api_v2 as jobs

    submitted: list[dict] = []
    monkeypatch.setattr(jobs, "runtime_settings", lambda: Settings(usage_mode="personal"))
    monkeypatch.setattr(jobs, "preflight", lambda *_a, **_kw: {"ok": True})
    monkeypatch.setattr(jobs, "youtube_tool_status", lambda *_a, **_kw: {"ready": True})
    monkeypatch.setattr(jobs, "jobs_dir", lambda: tmp_path)
    monkeypatch.setattr(
        jobs, "_reserve_or_429",
        lambda _job_id, **payload: submitted.append(payload),
    )
    monkeypatch.setattr(jobs, "_start_or_mark_failed", lambda *_a: None)

    response = TestClient(app).post(
        "/api/jobs/youtube",
        json={
            "url": "https://www.youtube.com/watch?v=abc123",
            "authorized": False,
        },
    )
    assert response.status_code == 202
    assert response.json()["source"] == "youtube"
    assert submitted and submitted[0]["source_kind"] == "youtube"


def test_commercial_youtube_still_starts_after_explicit_confirmation(
    monkeypatch, tmp_path: Path,
):
    from audio_score_tool import job_lifecycle_api_v2 as jobs

    submitted: list[dict] = []
    monkeypatch.setattr(jobs, "runtime_settings", lambda: Settings(
        usage_mode="commercial", transcription_engine="mt3_infer",
    ))
    monkeypatch.setattr(jobs, "preflight", lambda *_a, **_kw: {"ok": True})
    monkeypatch.setattr(jobs, "youtube_tool_status", lambda *_a, **_kw: {"ready": True})
    monkeypatch.setattr(jobs, "jobs_dir", lambda: tmp_path)
    monkeypatch.setattr(
        jobs, "_reserve_or_429",
        lambda _job_id, **payload: submitted.append(payload),
    )
    monkeypatch.setattr(jobs, "_start_or_mark_failed", lambda *_a: None)

    response = TestClient(app).post(
        "/api/jobs/youtube",
        json={
            "url": "https://www.youtube.com/watch?v=abc123",
            "authorized": True,
        },
    )
    assert response.status_code == 202
    assert len(submitted) == 1
    assert submitted[0]["source_kind"] == "youtube"


def test_personal_permission_relaxation_never_disables_youtube_url_validation(
    monkeypatch,
):
    from audio_score_tool import job_lifecycle_api_v2 as jobs

    monkeypatch.setattr(jobs, "runtime_settings", lambda: Settings(usage_mode="personal"))
    response = TestClient(app).post(
        "/api/jobs/youtube",
        json={"url": "https://unauthorized.example/watch?v=abc123", "authorized": False},
    )
    assert response.status_code == 422


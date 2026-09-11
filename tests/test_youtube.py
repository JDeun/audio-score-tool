from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from audio_score_tool.api_ext import app
from audio_score_tool.config import Settings
from audio_score_tool.youtube import (
    YouTubeSourceError,
    download_youtube_audio,
    inspect_youtube,
    validate_youtube_url,
    youtube_tool_status,
)


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


def test_youtube_job_requires_authorization_confirmation():
    client = TestClient(app)
    response = client.post(
        "/api/jobs/youtube",
        json={
            "url": "https://www.youtube.com/watch?v=abc123",
            "authorized": False,
        },
    )
    assert response.status_code == 422


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
    component_dir = tmp_path / "components"
    bin_dir = component_dir / "bin"
    bin_dir.mkdir(parents=True)
    deno = bin_dir / "deno"
    ffmpeg = bin_dir / "ffmpeg"
    ffprobe = bin_dir / "ffprobe"
    yt_dlp = bin_dir / "yt-dlp"
    for path in (deno, ffmpeg, ffprobe, yt_dlp):
        path.write_bytes(path.name.encode("utf-8"))

    monkeypatch.setenv("AST_PACKAGED", "1")
    monkeypatch.setenv("AST_COMPONENT_DIR", str(component_dir))
    captured: list[list[object]] = []

    def fake_run_command(command, args, **kwargs):
        captured.append(list(args))
        return subprocess.CompletedProcess(
            [],
            0,
            json.dumps(
                {
                    "title": "Example",
                    "duration": 60,
                    "webpage_url": "https://youtu.be/abc123",
                }
            ),
        )

    monkeypatch.setattr("audio_score_tool.youtube.run_command", fake_run_command)
    settings = Settings()
    metadata = inspect_youtube("https://youtu.be/abc123", settings=settings)

    assert metadata.title == "Example"
    assert captured
    args = [str(value) for value in captured[0]]
    js_index = args.index("--js-runtimes")
    assert args[js_index + 1] == f"deno:{deno}"
    ffmpeg_index = args.index("--ffmpeg-location")
    assert args[ffmpeg_index + 1] == str(bin_dir)

    status = youtube_tool_status(settings)
    assert status["ready"] is True
    assert status["js_runtime"] == str(deno)
    assert status["ffmpeg"] == str(ffmpeg)
    assert status["ffprobe"] == str(ffprobe)
    assert status["ffmpeg_ready"] is True
    assert status["ffprobe_ready"] is True


@pytest.mark.parametrize("missing_tool", ["deno", "ffmpeg", "ffprobe"])
def test_packaged_youtube_is_not_ready_without_required_managed_tool(
    monkeypatch,
    tmp_path: Path,
    missing_tool: str,
):
    component_dir = tmp_path / "components"
    bin_dir = component_dir / "bin"
    bin_dir.mkdir(parents=True)
    for name in ("yt-dlp", "deno", "ffmpeg", "ffprobe"):
        if name != missing_tool:
            (bin_dir / name).write_bytes(name.encode("utf-8"))
    monkeypatch.setenv("AST_PACKAGED", "1")
    monkeypatch.setenv("AST_COMPONENT_DIR", str(component_dir))

    status = youtube_tool_status(Settings())
    assert status["ready"] is False
    readiness_key = {
        "deno": "js_runtime_ready",
        "ffmpeg": "ffmpeg_ready",
        "ffprobe": "ffprobe_ready",
    }[missing_tool]
    assert status[readiness_key] is False


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

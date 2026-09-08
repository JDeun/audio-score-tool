from __future__ import annotations

import json
import subprocess

import pytest
from fastapi.testclient import TestClient

from audio_score_tool.api_ext import app
from audio_score_tool.config import Settings
from audio_score_tool.youtube import (
    YouTubeSourceError,
    download_youtube_audio,
    inspect_youtube,
    validate_youtube_url,
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

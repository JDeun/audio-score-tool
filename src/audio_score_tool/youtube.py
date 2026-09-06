from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from urllib.parse import urlparse

from .config import Settings
from .runner import CommandCancelled, CommandError, command_exists, run_command


class YouTubeSourceError(RuntimeError):
    pass


class YouTubeSourceCancelled(YouTubeSourceError):
    pass


_ALLOWED_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
}


@dataclass(slots=True)
class YouTubeMetadata:
    title: str
    uploader: str | None
    duration: float | None
    webpage_url: str
    thumbnail: str | None

    def as_dict(self) -> dict:
        return {
            "title": self.title,
            "uploader": self.uploader,
            "duration": self.duration,
            "webpage_url": self.webpage_url,
            "thumbnail": self.thumbnail,
        }


def validate_youtube_url(value: str) -> str:
    value = value.strip()
    if not value:
        raise YouTubeSourceError("YouTube URL is required.")

    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise YouTubeSourceError("YouTube URL must use http or https.")

    host = (parsed.hostname or "").lower().rstrip(".")
    if host not in _ALLOWED_HOSTS:
        raise YouTubeSourceError("Only youtube.com and youtu.be URLs are supported.")

    if host == "youtu.be" and not parsed.path.strip("/"):
        raise YouTubeSourceError("The youtu.be URL does not contain a video id.")
    if host != "youtu.be" and parsed.path == "/watch" and not parsed.query:
        raise YouTubeSourceError("The YouTube watch URL does not contain a video id.")

    return value


def youtube_tool_status(settings: Settings | None = None) -> dict:
    settings = settings or Settings()
    return {
        "ready": command_exists(settings.yt_dlp_cmd),
        "command": settings.yt_dlp_cmd,
        "fallback_note": "Installed yt-dlp is preferred; uvx yt-dlp is used automatically when uvx is available.",
    }


def inspect_youtube(
    url: str,
    *,
    settings: Settings | None = None,
    cancel_event: Event | None = None,
) -> YouTubeMetadata:
    settings = settings or Settings()
    url = validate_youtube_url(url)
    try:
        completed = run_command(
            settings.yt_dlp_cmd,
            [
                "--dump-single-json",
                "--skip-download",
                "--no-playlist",
                "--no-warnings",
                url,
            ],
            cancel_event=cancel_event,
        )
    except CommandCancelled as exc:
        raise YouTubeSourceCancelled("YouTube inspection cancelled.") from exc
    except CommandError as exc:
        raise YouTubeSourceError(f"Could not inspect the YouTube URL.\n{exc}") from exc

    try:
        payload = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise YouTubeSourceError("yt-dlp returned invalid metadata.") from exc

    title = str(payload.get("title") or "YouTube audio")
    duration_raw = payload.get("duration")
    try:
        duration = float(duration_raw) if duration_raw is not None else None
    except (TypeError, ValueError):
        duration = None

    return YouTubeMetadata(
        title=title,
        uploader=payload.get("uploader") or payload.get("channel"),
        duration=duration,
        webpage_url=str(payload.get("webpage_url") or url),
        thumbnail=payload.get("thumbnail"),
    )


def download_youtube_audio(
    url: str,
    output_dir: Path,
    *,
    settings: Settings | None = None,
    cancel_event: Event | None = None,
) -> tuple[Path, YouTubeMetadata]:
    settings = settings or Settings()
    url = validate_youtube_url(url)
    output_dir.mkdir(parents=True, exist_ok=True)

    metadata = inspect_youtube(url, settings=settings, cancel_event=cancel_event)
    template = output_dir / "input.%(ext)s"
    try:
        run_command(
            settings.yt_dlp_cmd,
            [
                "--no-playlist",
                "--no-warnings",
                "--no-progress",
                "-f",
                "bestaudio[ext=m4a]/bestaudio[ext=mp4]/bestaudio",
                "-o",
                template,
                url,
            ],
            cancel_event=cancel_event,
        )
    except CommandCancelled as exc:
        raise YouTubeSourceCancelled("YouTube audio import cancelled.") from exc
    except CommandError as exc:
        raise YouTubeSourceError(f"Could not import YouTube audio.\n{exc}") from exc

    candidates = sorted(
        path for path in output_dir.glob("input.*")
        if path.is_file() and path.suffix.lower() not in {".part", ".ytdl"}
    )
    if not candidates:
        raise YouTubeSourceError("yt-dlp completed but no audio file was produced.")

    return candidates[0], metadata

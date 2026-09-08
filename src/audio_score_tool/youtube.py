from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from urllib.parse import parse_qs, urlparse

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
_VIDEO_PATH_PREFIXES = ("/shorts/", "/live/", "/embed/")
_DEFAULT_MAX_DURATION_SECONDS = 4 * 60 * 60


def _max_duration_seconds() -> int:
    raw = os.getenv("AST_MAX_YOUTUBE_DURATION_SECONDS", str(_DEFAULT_MAX_DURATION_SECONDS))
    try:
        return max(60, min(int(raw), 24 * 60 * 60))
    except ValueError:
        return _DEFAULT_MAX_DURATION_SECONDS


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
    if parsed.scheme != "https":
        raise YouTubeSourceError("YouTube URL must use HTTPS.")

    host = (parsed.hostname or "").lower().rstrip(".")
    if host not in _ALLOWED_HOSTS:
        raise YouTubeSourceError("Only youtube.com and youtu.be URLs are supported.")

    if host == "youtu.be":
        if not parsed.path.strip("/"):
            raise YouTubeSourceError("The youtu.be URL does not contain a video id.")
        return value

    if parsed.path == "/watch":
        video_id = parse_qs(parsed.query).get("v", [""])[0].strip()
        if not video_id:
            raise YouTubeSourceError("The YouTube watch URL does not contain a video id.")
        return value

    if any(parsed.path.startswith(prefix) and parsed.path[len(prefix):].strip("/") for prefix in _VIDEO_PATH_PREFIXES):
        return value

    raise YouTubeSourceError("Use a YouTube watch, Shorts, live, embed, or youtu.be video URL.")


def youtube_tool_status(settings: Settings | None = None) -> dict:
    settings = settings or Settings()
    return {
        "ready": command_exists(settings.yt_dlp_cmd),
        "command": settings.yt_dlp_cmd,
        "max_duration_seconds": _max_duration_seconds(),
        "live_broadcasts_allowed": False,
        "fallback_note": (
            "Installed yt-dlp is preferred; uvx yt-dlp is used automatically "
            "when uvx is available."
        ),
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
            timeout_seconds=120,
            max_output_bytes=4 * 1024 * 1024,
        )
    except CommandCancelled as exc:
        raise YouTubeSourceCancelled("YouTube inspection cancelled.") from exc
    except CommandError as exc:
        raise YouTubeSourceError(f"Could not inspect the YouTube URL.\n{exc}") from exc

    try:
        payload = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise YouTubeSourceError("yt-dlp returned invalid metadata.") from exc

    if bool(payload.get("is_live")):
        raise YouTubeSourceError("현재 진행 중인 YouTube 생방송은 가져올 수 없습니다. 방송 종료 후 다시 시도하세요.")

    title = str(payload.get("title") or "YouTube audio").strip()[:300] or "YouTube audio"
    uploader_raw = payload.get("uploader") or payload.get("channel")
    uploader = str(uploader_raw).strip()[:300] if uploader_raw else None
    duration_raw = payload.get("duration")
    try:
        duration = float(duration_raw) if duration_raw is not None else None
        if duration is not None and (not math.isfinite(duration) or duration < 0):
            duration = None
    except (TypeError, ValueError):
        duration = None
    if duration is not None and duration > _max_duration_seconds():
        raise YouTubeSourceError(
            f"영상 길이가 허용된 최대 {_max_duration_seconds() // 60}분을 초과합니다. "
            "필요하면 AST_MAX_YOUTUBE_DURATION_SECONDS를 조정하세요."
        )

    webpage_url = str(payload.get("webpage_url") or url)[:2_000]
    thumbnail_raw = payload.get("thumbnail")
    thumbnail = str(thumbnail_raw)[:2_000] if thumbnail_raw else None
    return YouTubeMetadata(
        title=title,
        uploader=uploader,
        duration=duration,
        webpage_url=webpage_url,
        thumbnail=thumbnail,
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
            timeout_seconds=max(600, min(_max_duration_seconds() * 2, 8 * 60 * 60)),
        )
    except CommandCancelled as exc:
        raise YouTubeSourceCancelled("YouTube audio import cancelled.") from exc
    except CommandError as exc:
        raise YouTubeSourceError(f"Could not import YouTube audio.\n{exc}") from exc

    candidates = sorted(
        path
        for path in output_dir.glob("input.*")
        if path.is_file() and path.suffix.lower() not in {".part", ".ytdl"}
    )
    if not candidates:
        raise YouTubeSourceError("yt-dlp completed but no audio file was produced.")

    return candidates[0], metadata

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from urllib.parse import parse_qs, urlparse

from .config import Settings, managed_executable_path, packaged_runtime
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


def _youtube_js_runtime_args() -> list[str]:
    """Use the app-managed Deno explicitly in packaged builds.

    yt-dlp enables Deno by default when it can discover it on PATH, but a packaged
    AudioScoreTool release deliberately does not rely on the user's PATH. Supplying
    the deterministic managed path keeps YouTube extraction self-contained.
    """

    if not packaged_runtime():
        return []
    deno = managed_executable_path("deno")
    return ["--js-runtimes", f"deno:{deno}"]


def _youtube_ffmpeg_args() -> list[str]:
    """Bind yt-dlp to the app-managed FFmpeg/ffprobe directory in packaged builds."""

    if not packaged_runtime():
        return []
    ffmpeg = managed_executable_path("ffmpeg")
    return ["--ffmpeg-location", str(ffmpeg.parent)]


def _youtube_runtime_args() -> list[str]:
    return [*_youtube_js_runtime_args(), *_youtube_ffmpeg_args()]


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
    if parsed.username is not None or parsed.password is not None:
        raise YouTubeSourceError("YouTube URL must not contain embedded credentials.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise YouTubeSourceError("YouTube URL contains an invalid port.") from exc
    if port not in {None, 443}:
        raise YouTubeSourceError("YouTube URL must use the standard HTTPS port.")

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

    if any(
        parsed.path.startswith(prefix) and parsed.path[len(prefix) :].strip("/")
        for prefix in _VIDEO_PATH_PREFIXES
    ):
        return value

    raise YouTubeSourceError("Use a YouTube watch, Shorts, live, embed, or youtu.be video URL.")


def youtube_tool_status(settings: Settings | None = None) -> dict:
    settings = settings or Settings()
    packaged = packaged_runtime()
    deno_path = managed_executable_path("deno") if packaged else None
    ffmpeg_path = managed_executable_path("ffmpeg") if packaged else None
    ffprobe_path = managed_executable_path("ffprobe") if packaged else None
    deno_ready = deno_path.is_file() if deno_path is not None else True
    ffmpeg_ready = ffmpeg_path.is_file() if ffmpeg_path is not None else True
    ffprobe_ready = ffprobe_path.is_file() if ffprobe_path is not None else True
    return {
        "ready": (
            command_exists(settings.yt_dlp_cmd)
            and deno_ready
            and ffmpeg_ready
            and ffprobe_ready
        ),
        "command": settings.yt_dlp_cmd,
        "js_runtime": str(deno_path) if deno_path is not None else "auto",
        "js_runtime_ready": deno_ready,
        "ffmpeg": str(ffmpeg_path) if ffmpeg_path is not None else "auto",
        "ffmpeg_ready": ffmpeg_ready,
        "ffprobe": str(ffprobe_path) if ffprobe_path is not None else "auto",
        "ffprobe_ready": ffprobe_ready,
        "max_duration_seconds": _max_duration_seconds(),
        "live_broadcasts_allowed": False,
        "fallback_note": (
            "Development mode may use yt-dlp/Deno/FFmpeg from the developer environment. "
            "Packaged mode requires app-managed yt-dlp, Deno, FFmpeg, and ffprobe."
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
                *_youtube_runtime_args(),
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
        raise YouTubeSourceError(
            "현재 진행 중인 YouTube 생방송은 가져올 수 없습니다. 방송 종료 후 다시 시도하세요."
        )

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
                *_youtube_runtime_args(),
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

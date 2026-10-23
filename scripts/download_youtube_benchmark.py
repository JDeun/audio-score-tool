"""Download a permitted YouTube audio sample for reproducible inference.

Only use media that you own, have permission to process, or are licensed to
download. No authentication or access-control bypass is attempted.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from urllib.parse import urlparse


def download(url: str, destination: Path, *, max_duration: int = 180) -> dict:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {
        "www.youtube.com", "youtube.com", "m.youtube.com", "youtu.be",
    }:
        raise ValueError("Only HTTPS YouTube URLs are accepted")
    if not 0 < max_duration <= 600:
        raise ValueError("max_duration must be within 1..600 seconds")
    metadata = subprocess.run(
        ["yt-dlp", "--no-playlist", "--dump-single-json", "--skip-download", url],
        check=True, capture_output=True, text=True, timeout=90,
    )
    info = json.loads(metadata.stdout)
    duration = info.get("duration")
    if not isinstance(duration, (int, float)) or duration <= 0 or duration > max_duration:
        raise ValueError(f"Video duration must be <= {max_duration}s")
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "yt-dlp", "--no-playlist", "--no-progress", "--no-overwrites",
        "-f", "bestaudio/best", "-x", "--audio-format", "wav",
        "-o", str(destination.with_suffix("")) + ".%(ext)s", url,
    ], check=True, timeout=240)
    if not destination.is_file() or destination.stat().st_size == 0:
        raise RuntimeError("YouTube audio conversion produced no WAV")
    return {"video_id": info.get("id"), "duration_seconds": duration,
            "audio": str(destination), "size_bytes": destination.stat().st_size}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("output", type=Path)
    parser.add_argument("--max-duration", type=int, default=180)
    args = parser.parse_args()
    print(json.dumps(download(args.url, args.output, max_duration=args.max_duration)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

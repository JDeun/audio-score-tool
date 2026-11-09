"""Conservative filename/YouTube title hints for opt-in metadata lookup.

A title hint is *not* authoritative metadata. Search results must still pass
MusicBrainz confidence and LRCLIB exact artist/title checks before application.
Never treat the YouTube uploader as a composer, performer or verified artist.
"""
from __future__ import annotations

import re
from pathlib import Path

_VIDEO_SUFFIX = re.compile(
    r"\s*[\[(]\s*(?:official(?:\s+music)?\s+video|official\s+audio|"
    r"lyric(?:s)?\s+video|lyrics?|visualizer|audio|mv|music\s+video|"
    r"remaster(?:ed)?(?:\s+\d{4})?)\s*[\])]\s*$",
    re.IGNORECASE,
)
_SEPARATOR = re.compile(r"\s+[-–—]\s+")
_AUDIO_SUFFIXES = frozenset({
    ".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma", ".aiff",
})


def title_artist_hints(filename: str | None) -> tuple[str, str] | None:
    """Only an explicit 'Artist - Track' title is safe enough for API lookup."""
    if not isinstance(filename, str) or not filename.strip():
        return None
    raw = filename.strip()
    if Path(raw).suffix.lower() in _AUDIO_SUFFIXES:
        raw = raw[: -len(Path(raw).suffix)]
    # Remove canonical annotation suffixes but never blindly discard meaningful
    # title parentheses such as (Live), (Acoustic), featured artists, etc.
    for _ in range(3):
        clean = _VIDEO_SUFFIX.sub("", raw).strip()
        if clean == raw:
            break
        raw = clean
    items = _SEPARATOR.split(raw, maxsplit=1)
    if len(items) != 2:
        return None
    artist, title = (part.strip() for part in items)
    if (
        not 1 <= len(artist) <= 300
        or not 1 <= len(title) <= 300
        or artist.lower() in {"unknown", "youtube", "official", "artist"}
        or title.lower() in {"untitled", "song", "video"}
    ):
        return None
    return title, artist

"""Conservative filename/YouTube title hints for opt-in metadata lookup.

A title hint is *not* authoritative metadata. Search results must still pass
MusicBrainz confidence and LRCLIB exact artist/title checks before application.
Never treat the YouTube uploader as a composer, performer or verified artist.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
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
        or artist.lower() in {"unknown", "youtube", "official"}
        or title.lower() in {
            "untitled", "video", "official video",
            "official music video", "official audio",
        }
    ):
        return None
    return title, artist



@dataclass(frozen=True, slots=True)
class SourceLookupHints:
    """Unverified search terms, never authoritative artist or composer credits."""

    title: str
    artist: str
    provenance: str
    album: str | None = None


def _clean_tag(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    clean = " ".join(value.strip().split())[:300]
    return clean if clean and clean.casefold() not in {"unknown", "untitled"} else None


def _same_label(first: str, second: str) -> bool:
    return " ".join(first.casefold().split()) == " ".join(second.casefold().split())


def resolve_source_lookup_hints(
    source_kind: str | None,
    display_name: str | None,
    *,
    audio_path: Path | None = None,
) -> SourceLookupHints | None:
    """Local: verified-file metadata as query hints, then consistent filename.

    YouTube: ONLY the video title; channel/uploader and downloader-added audio
    tags cannot be assumed to be the performing artist. Partial local tags may
    complement a filename only when they agree, never when they conflict.
    """
    parsed = title_artist_hints(display_name)
    if source_kind == "youtube":
        if parsed is None:
            return None
        title, artist = parsed
        return SourceLookupHints(title=title, artist=artist, provenance="youtube_title")
    if source_kind != "local":
        return None

    tags: dict = {}
    if audio_path is not None and audio_path.is_file() and not audio_path.is_symlink():
        from .source_identification import read_embedded_tags

        try:
            tags = read_embedded_tags(audio_path)
        except (OSError, ValueError):
            tags = {}
    tag_title = _clean_tag(tags.get("title"))
    tag_artist = _clean_tag(tags.get("artist"))
    tag_album = _clean_tag(tags.get("album"))
    if tag_title and tag_artist:
        return SourceLookupHints(
            title=tag_title, artist=tag_artist,
            album=tag_album, provenance="embedded_tags",
        )
    if parsed is not None:
        filename_title, filename_artist = parsed
        if tag_title and not _same_label(tag_title, filename_title):
            return None
        if tag_artist and not _same_label(tag_artist, filename_artist):
            return None
        return SourceLookupHints(
            title=tag_title or filename_title,
            artist=tag_artist or filename_artist,
            album=tag_album,
            provenance="combined_tags_filename" if tag_title or tag_artist else "filename",
        )
    return None

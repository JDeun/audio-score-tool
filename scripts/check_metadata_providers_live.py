"""Live, metadata-only provider contract check (no test audio or lyric output).

The test uses two known public API *search identities*, not any user media:
* MusicBrainz: Green Day / American Idiot, recording and work metadata.
* LRCLIB: its documented Borislav Slavov / I Want to Live API example.

Lyrics are inspected only in process for nonempty shape. Never serialize lyrics,
provider responses, captured HTTP bodies or private audio into artifacts/logs.
A remote 404, 429 or outage is reported explicitly as INCONCLUSIVE; it is not
silently counted as a passing API contract.
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from audio_score_tool.enrichment import (
    EnrichmentError,
    choose_high_confidence,
    fetch_lrclib_lyrics,
    lookup_musicbrainz_work_credits,
    search_musicbrainz,
)

# This fixture is the publicly documented API example, not a media asset.
_LRCLIB_TRACK = "I Want to Live"
_LRCLIB_ARTIST = "Borislav Slavov"
_LRCLIB_ALBUM = "Baldur's Gate 3 (Original Game Soundtrack)"
_MB_TRACK = "American Idiot"
_MB_ARTIST = "Green Day"


def _same(left: object, right: str) -> bool:
    return isinstance(left, str) and (
        " ".join(unicodedata.normalize("NFKC", left).casefold().split())
        == " ".join(unicodedata.normalize("NFKC", right).casefold().split())
    )


def _safe_http_status(exc: Exception) -> int | None:
    """Expose HTTP code only, never URL, error body or remote lyric content."""
    match = re.search(r"\bHTTP Error ([1-5][0-9]{2})\b", str(exc))
    return int(match.group(1)) if match else None


def check_live_providers(
    *,
    recording_search: Callable[..., list[dict[str, Any]]] = search_musicbrainz,
    work_lookup: Callable[..., dict[str, Any]] = lookup_musicbrainz_work_credits,
    lyrics_fetch: Callable[..., dict[str, Any] | None] = fetch_lrclib_lyrics,
) -> dict[str, Any]:
    """Return only statuses and shape checks. Never include a single lyric word."""
    result: dict[str, Any] = {
        "schema_version": 1,
        "purpose": "live-external-metadata-lyrics-api-contract",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "models_run": False,
        "copyright_audio_downloaded": False,
        "any_media_uploaded": False,
        "lyrics_content_published": False,
        "providers": {},
    }
    mb: dict[str, Any] = {"status": "inconclusive", "reason": None}
    try:
        candidates = recording_search(_MB_TRACK, _MB_ARTIST, limit=5)
        if not isinstance(candidates, list):
            raise ValueError("MusicBrainz search contract must return a list")
        same = [
            item for item in candidates
            if isinstance(item, dict)
            and _same(item.get("title"), _MB_TRACK)
            and _same(item.get("artist"), _MB_ARTIST)
        ]
        selected = choose_high_confidence(same, threshold=92)
        mb["matched_identity_count"] = len(same)
        mb["high_confidence_selected"] = selected is not None
        if selected is None:
            mb["reason"] = "no_verified_recording_candidate"
        elif not selected.get("recording_mbid"):
            mb["reason"] = "no_recording_id"
        else:
            mb["status"] = "matched"
            mb["reason"] = None
            credits = work_lookup(str(selected["recording_mbid"]))
            mb["work_status"] = str(credits.get("status") or "unknown")[:64]
            mb["composer_relation_present"] = bool(credits.get("composer"))
            mb["lyricist_relation_present"] = bool(credits.get("lyricist"))
            mb["album_present"] = bool(selected.get("album"))
    except (EnrichmentError, ValueError, OSError, TypeError) as exc:
        mb["status"] = "inconclusive"
        mb["reason"] = type(exc).__name__
        mb["http_status"] = _safe_http_status(exc)
    result["providers"]["musicbrainz"] = mb

    lrclib: dict[str, Any] = {"status": "inconclusive", "reason": None}
    try:
        lyrics = lyrics_fetch(
            _LRCLIB_TRACK, _LRCLIB_ARTIST, album=_LRCLIB_ALBUM,
        )
        if lyrics is None:
            lrclib["reason"] = "no_exact_lyrics_match"
        elif (
            lyrics.get("provider") != "lrclib"
            or not isinstance(lyrics.get("lyrics"), str)
            or not lyrics["lyrics"].strip()
            or not isinstance(lyrics.get("source_payload"), dict)
        ):
            lrclib["reason"] = "invalid_lyrics_contract"
        else:
            # Deliberately DO NOT include the text, a digest, or any quoted span.
            lrclib["status"] = "matched"
            lrclib["reason"] = None
            lrclib["synced_available"] = bool(lyrics.get("synced"))
    except (EnrichmentError, ValueError, OSError, TypeError) as exc:
        lrclib["reason"] = type(exc).__name__
        lrclib["http_status"] = _safe_http_status(exc)
    result["providers"]["lrclib"] = lrclib

    result["both_provider_contracts_live"] = (
        mb["status"] == "matched" and lrclib["status"] == "matched"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Check live metadata and lyrics provider schemas")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--strict-live", action="store_true",
        help="Fail if either public service cannot be verified (manual only)",
    )
    args = parser.parse_args()
    target = args.output.expanduser().resolve()
    if target.exists() or target.is_symlink():
        parser.error("Output must be a new JSON file")
    report = check_live_providers()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, ensure_ascii=False)
        stream.write("\n")
    # Metadata-only CLI; no lyrics, user audio, author names or HTTP bodies.
    print(json.dumps({
        "both_provider_contracts_live": report["both_provider_contracts_live"],
        "musicbrainz_status": report["providers"]["musicbrainz"]["status"],
        "musicbrainz_reason": report["providers"]["musicbrainz"]["reason"],
        "musicbrainz_http_status": report["providers"]["musicbrainz"].get("http_status"),
        "musicbrainz_work_status": report["providers"]["musicbrainz"].get("work_status"),
        "lrclib_status": report["providers"]["lrclib"]["status"],
        "lrclib_reason": report["providers"]["lrclib"]["reason"],
        "lrclib_http_status": report["providers"]["lrclib"].get("http_status"),
    }, sort_keys=True))
    return 1 if args.strict_live and not report["both_provider_contracts_live"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

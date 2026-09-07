from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

MUSICBRAINZ_BASE = "https://musicbrainz.org/ws/2"
USER_AGENT = "AudioScoreTool/0.8 (https://github.com/JDeun/audio-score-tool)"
_MAX_JSON_RESPONSE_BYTES = 4 * 1024 * 1024
_MAX_LYRICS_CHARS = 200_000

_mb_lock = threading.Lock()
_last_mb_request = 0.0


class EnrichmentError(RuntimeError):
    pass


@dataclass(slots=True)
class LyricsProvider:
    name: str
    url_template: str
    api_key_env: str | None = None


def _json_request(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
    max_bytes: int = _MAX_JSON_RESPONSE_BYTES,
) -> Any:
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    if int(content_length) > max_bytes:
                        raise EnrichmentError(
                            f"External metadata response is too large ({content_length} bytes)."
                        )
                except ValueError:
                    pass
            raw = response.read(max_bytes + 1)
            if len(raw) > max_bytes:
                raise EnrichmentError(
                    f"External metadata response exceeded the {max_bytes}-byte limit."
                )
            return json.loads(raw.decode("utf-8"))
    except EnrichmentError:
        raise
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EnrichmentError(str(exc)) from exc


def _musicbrainz_request(path: str, params: dict[str, str]) -> Any:
    global _last_mb_request
    with _mb_lock:
        now = time.monotonic()
        delay = 1.0 - (now - _last_mb_request)
        if delay > 0:
            time.sleep(delay)
        query = urllib.parse.urlencode({**params, "fmt": "json"})
        try:
            return _json_request(
                f"{MUSICBRAINZ_BASE}/{path}?{query}",
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            )
        finally:
            # Keep the process-wide rate limit even after failed requests so a transient
            # provider outage does not turn retries into an accidental request burst.
            _last_mb_request = time.monotonic()


def _recording_candidate(item: dict[str, Any]) -> dict[str, Any]:
    credits = item.get("artist-credit") or []
    artist_name = "".join(
        str(part.get("name") or part.get("artist", {}).get("name") or "")
        + str(part.get("joinphrase") or "")
        for part in credits
        if isinstance(part, dict)
    ).strip()
    releases = item.get("releases") or []
    release = releases[0] if releases and isinstance(releases[0], dict) else {}
    return {
        "provider": "musicbrainz",
        "recording_mbid": item.get("id"),
        "title": item.get("title"),
        "artist": artist_name or None,
        "first_release_date": item.get("first-release-date"),
        "album": release.get("title") if isinstance(release, dict) else None,
        "release_mbid": release.get("id") if isinstance(release, dict) else None,
        "length_ms": item.get("length"),
        "isrcs": item.get("isrcs") or [],
        "score": int(item.get("score") or 0),
        "license_scope": "MusicBrainz core metadata / CC0 where applicable",
    }


def search_musicbrainz(title: str, artist: str | None = None, *, limit: int = 5) -> list[dict[str, Any]]:
    title = title.strip()
    artist = (artist or "").strip()
    if not title:
        return []
    parts = [f'recording:"{title.replace(chr(34), "")}"']
    if artist:
        parts.append(f'artist:"{artist.replace(chr(34), "")}"')
    payload = _musicbrainz_request("recording/", {"query": " AND ".join(parts), "limit": str(limit)})
    return [
        _recording_candidate(item)
        for item in payload.get("recordings", []) if isinstance(payload, dict) and isinstance(item, dict)
    ]


def search_musicbrainz_by_isrc(isrc: str, *, limit: int = 5) -> list[dict[str, Any]]:
    normalized = "".join(char for char in isrc.upper() if char.isalnum())
    if not normalized:
        return []
    payload = _musicbrainz_request("recording/", {"query": f'isrc:"{normalized}"', "limit": str(limit)})
    results = [
        _recording_candidate(item)
        for item in payload.get("recordings", []) if isinstance(payload, dict) and isinstance(item, dict)
    ]
    for item in results:
        item["match_reason"] = "ISRC"
        item["score"] = max(98, int(item.get("score") or 0))
    return results


def choose_high_confidence(candidates: list[dict[str, Any]], *, threshold: int = 92) -> dict[str, Any] | None:
    if not candidates:
        return None
    best = max(candidates, key=lambda item: int(item.get("score") or 0))
    return best if int(best.get("score") or 0) >= threshold else None


def _format_lyrics_url(template: str, *, title: str, artist: str | None) -> str:
    try:
        return template.format(
            title=urllib.parse.quote(title, safe=""),
            artist=urllib.parse.quote((artist or ""), safe=""),
        )
    except (KeyError, IndexError, ValueError) as exc:
        raise EnrichmentError(
            "Lyrics provider URL template may only use the {title} and {artist} placeholders."
        ) from exc


def fetch_lyrics(provider: LyricsProvider, *, title: str, artist: str | None = None) -> dict[str, Any] | None:
    """Fetch lyrics only from an explicitly configured provider.

    The provider must return JSON containing `lyrics`, `plainLyrics`, or `syncedLyrics`.
    AudioScoreTool intentionally does not scrape arbitrary web pages for copyrighted lyrics.
    """
    template = provider.url_template.strip()
    if not template:
        return None
    if len(template) > 2_000:
        raise EnrichmentError("Lyrics provider URL template is too long.")
    parsed = urllib.parse.urlparse(template)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise EnrichmentError("Lyrics provider must be a valid http(s) URL.")
    if parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise EnrichmentError("Remote lyrics providers must use HTTPS.")
    url = _format_lyrics_url(template, title=title, artist=artist)
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    if provider.api_key_env:
        token = os.getenv(provider.api_key_env)
        if token:
            headers["Authorization"] = f"Bearer {token}"
    payload = _json_request(url, headers=headers)
    if not isinstance(payload, dict):
        return None
    text = payload.get("syncedLyrics") or payload.get("plainLyrics") or payload.get("lyrics")
    if not isinstance(text, str) or not text.strip():
        return None
    text = text.strip()
    if len(text) > _MAX_LYRICS_CHARS:
        raise EnrichmentError("Lyrics provider returned an unexpectedly large lyrics document.")
    # Persist only compact provider metadata. Arbitrary nested provider payloads can be
    # large or contain data the app never uses, so they should not be copied into SQLite.
    source_payload: dict[str, Any] = {}
    for key, value in payload.items():
        if key in {"lyrics", "plainLyrics", "syncedLyrics"}:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            source_payload[str(key)[:100]] = value if not isinstance(value, str) else value[:2_000]
        if len(source_payload) >= 32:
            break
    return {
        "provider": provider.name[:100],
        "lyrics": text,
        "synced": bool(payload.get("syncedLyrics")),
        "source_payload": source_payload,
    }

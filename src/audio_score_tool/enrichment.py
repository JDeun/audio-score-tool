from __future__ import annotations

import threading
import time
import unicodedata
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from .safe_http import DEFAULT_MAX_JSON_BYTES, open_json
from .secret_env import SecretEnvError, secret_from_env

MUSICBRAINZ_BASE = "https://musicbrainz.org/ws/2"
USER_AGENT = "AudioScoreTool/0.8 (https://github.com/JDeun/audio-score-tool)"
_MAX_JSON_RESPONSE_BYTES = DEFAULT_MAX_JSON_BYTES
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
        return open_json(request, timeout=timeout, max_bytes=max_bytes)
    except RuntimeError as exc:
        raise EnrichmentError(str(exc)) from exc


def _musicbrainz_request(path: str, params: dict[str, str]) -> Any:
    global _last_mb_request
    with _mb_lock:
        query = urllib.parse.urlencode({**params, "fmt": "json"})
        for attempt in range(2):
            now = time.monotonic()
            delay = 1.0 - (now - _last_mb_request)
            if delay > 0:
                time.sleep(delay)
            try:
                return _json_request(
                    f"{MUSICBRAINZ_BASE}/{path}?{query}",
                    headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                )
            except EnrichmentError as exc:
                # MusicBrainz occasionally responds with a temporary 5xx.
                # Retry ONCE after a delay. Never auto-retry 429 or 403:
                # honor the public service rate limit and user opt-in.
                if attempt or not any(
                    f"HTTP Error {code}" in str(exc) for code in (502, 503, 504)
                ):
                    raise
                time.sleep(2.0)
            finally:
                _last_mb_request = time.monotonic()
        raise EnrichmentError("MusicBrainz temporary outage persisted after bounded retry")


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
        "recording_mbid": str(item.get("id") or "")[:100] or None,
        "title": str(item.get("title") or "")[:300] or None,
        "artist": artist_name[:300] or None,
        "first_release_date": str(item.get("first-release-date") or "")[:50] or None,
        "album": str(release.get("title") or "")[:500] if isinstance(release, dict) else None,
        "release_mbid": str(release.get("id") or "")[:100] if isinstance(release, dict) else None,
        "length_ms": item.get("length"),
        "isrcs": [str(value)[:32] for value in (item.get("isrcs") or [])[:20]],
        "score": int(item.get("score") or 0),
        "license_scope": "MusicBrainz core metadata / CC0 where applicable",
    }


def search_musicbrainz(title: str, artist: str | None = None, *, limit: int = 5) -> list[dict[str, Any]]:
    title = title.strip()[:300]
    artist = (artist or "").strip()[:300]
    if not title:
        return []
    parts = [f'recording:"{title.replace(chr(34), "")}"']
    if artist:
        parts.append(f'artist:"{artist.replace(chr(34), "")}"')
    payload = _musicbrainz_request("recording/", {"query": " AND ".join(parts), "limit": str(max(1, min(limit, 20)))})
    return [
        _recording_candidate(item)
        for item in payload.get("recordings", []) if isinstance(payload, dict) and isinstance(item, dict)
    ]


def search_musicbrainz_by_isrc(isrc: str, *, limit: int = 5) -> list[dict[str, Any]]:
    normalized = "".join(char for char in isrc.upper() if char.isalnum())[:32]
    if not normalized:
        return []
    payload = _musicbrainz_request("recording/", {"query": f'isrc:"{normalized}"', "limit": str(max(1, min(limit, 20)))})
    results = [
        _recording_candidate(item)
        for item in payload.get("recordings", []) if isinstance(payload, dict) and isinstance(item, dict)
    ]
    for item in results:
        item["match_reason"] = "ISRC"
        item["score"] = max(98, int(item.get("score") or 0))
    return results



def lookup_musicbrainz_work_credits(recording_mbid: str) -> dict[str, Any]:
    """Resolve documented recording -> work -> artist composer/lyricist relations.

    Do not confuse the recording performer with a composition's writers. Work
    links can be incomplete or ambiguous, so return no credits if multiple
    distinct works are linked. Only accept literal composer/lyricist relations.
    """
    import re

    mbid = recording_mbid.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}", mbid):
        raise EnrichmentError("Invalid MusicBrainz recording identifier")
    document = _musicbrainz_request(f"recording/{mbid}", {"inc": "work-rels"})
    if not isinstance(document, dict) or document.get("id") != mbid:
        raise EnrichmentError("MusicBrainz recording identity does not match")
    relations = document.get("relations") or []
    works = {
        str(rel.get("work", {}).get("id") or "")
        for rel in relations
        if isinstance(rel, dict) and rel.get("target-type") == "work"
        and isinstance(rel.get("work"), dict) and rel.get("type") == "performance"
    }
    if len(works) != 1:
        return {
            "provider": "musicbrainz",
            "recording_mbid": mbid,
            "work_mbid": None,
            "composer": None,
            "lyricist": None,
            "status": "ambiguous_or_missing_work",
        }
    work_mbid = works.pop()
    if not re.fullmatch(r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}", work_mbid):
        raise EnrichmentError("Invalid MusicBrainz work identifier")
    work = _musicbrainz_request(f"work/{work_mbid}", {"inc": "artist-rels"})
    if not isinstance(work, dict) or work.get("id") != work_mbid:
        raise EnrichmentError("MusicBrainz work identity does not match")

    credits: dict[str, list[str]] = {"composer": [], "lyricist": []}
    for relation in work.get("relations") or []:
        if not isinstance(relation, dict) or relation.get("target-type") != "artist":
            continue
        role = relation.get("type")
        if role not in credits:
            continue
        artist = relation.get("artist")
        if not isinstance(artist, dict):
            continue
        person = str(artist.get("name") or "").strip()[:200]
        if person and person not in credits[role]:
            credits[role].append(person)
    return {
        "provider": "musicbrainz",
        "recording_mbid": mbid,
        "work_mbid": work_mbid,
        "composer": ", ".join(credits["composer"])[:200] or None,
        "lyricist": ", ".join(credits["lyricist"])[:200] or None,
        "status": "verified_work_relations",
    }


def fetch_lrclib_lyrics(
    title: str,
    artist: str | None,
    *,
    album: str | None = None,
) -> dict[str, Any] | None:
    """Find exact personal-use lyrics via LRCLIB's official GET/search APIs.

    /api/get can return 404 for a missing variant even when /api/search has
    an exact match. Retry only with LRCLIB's bounded *structured* search,
    never website scraping or fuzzy song/artist identity guesses. Multiple
    equally matching search results are ambiguous and stay on WhisperX.
    The caller never logs a payload or publishes lyrics without user action.
    """
    title, artist = title.strip()[:300], (artist or "").strip()[:300]
    album = (album or "").strip()[:300] or None
    if not title or not artist:
        return None

    def canonical(value: object) -> str:
        if not isinstance(value, str):
            return ""
        return " ".join(unicodedata.normalize("NFKC", value).casefold().split())

    def decode(record: object) -> dict[str, Any] | None:
        if not isinstance(record, dict):
            return None
        if (
            canonical(record.get("trackName")) != canonical(title)
            or canonical(record.get("artistName")) != canonical(artist)
            or (album is not None and canonical(record.get("albumName")) != canonical(album))
            or record.get("instrumental") is True
        ):
            return None
        text = record.get("plainLyrics") or record.get("syncedLyrics")
        if not isinstance(text, str) or not text.strip():
            return None
        if len(text) > _MAX_LYRICS_CHARS:
            raise EnrichmentError("LRCLIB returned an unexpectedly large lyrics document")
        return {
            "provider": "lrclib",
            "lyrics": text.strip(),
            "synced": bool(record.get("syncedLyrics")),
            "source_payload": {
                "trackName": str(record.get("trackName"))[:300],
                "artistName": str(record.get("artistName"))[:300],
                "albumName": str(record.get("albumName") or "")[:300],
                "id": record.get("id"),
            },
        }

    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    get_query = {"track_name": title, "artist_name": artist}
    if album is not None:
        get_query["album_name"] = album

    def request(path: str, query: dict[str, str]) -> Any:
        url = "https://lrclib.net" + path + "?" + urllib.parse.urlencode(query)
        try:
            return _json_request(
                url, headers=headers, timeout=10, max_bytes=_MAX_JSON_RESPONSE_BYTES,
            )
        except EnrichmentError as exc:
            if "HTTP Error 404" in str(exc):
                return None
            raise

    primary = request("/api/get", get_query)
    found = decode(primary)
    if found is not None:
        return found

    # One structured search only. With no album a title/artist can match
    # several distinct recordings; never pick an arbitrary karaoke/live
    # version just because the first result has lyrics.
    search_results = request("/api/search", get_query)
    if not isinstance(search_results, list) or len(search_results) > 20:
        return None
    matches = [candidate for row in search_results if (candidate := decode(row)) is not None]
    return matches[0] if len(matches) == 1 else None



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
    url = _format_lyrics_url(template, title=title[:300], artist=(artist or "")[:300])
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    if provider.api_key_env:
        try:
            token = secret_from_env(provider.api_key_env)
        except SecretEnvError as exc:
            raise EnrichmentError(str(exc)) from exc
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

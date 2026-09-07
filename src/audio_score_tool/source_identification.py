from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from mutagen import File as MutagenFile

ACOUSTID_LOOKUP = "https://api.acoustid.org/v2/lookup"
USER_AGENT = "AudioScoreTool/0.8 (https://github.com/JDeun/audio-score-tool)"


class SourceIdentificationError(RuntimeError):
    pass


def _first_tag(tags: Any, *keys: str) -> str | None:
    if not tags:
        return None
    lowered = {str(key).lower(): value for key, value in tags.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            value = value[0] if value else None
        text = str(value).strip() if value is not None else ""
        if text:
            return text
    return None


def read_embedded_tags(path: Path) -> dict[str, Any]:
    """Read clean local metadata before invoking any network or model inference."""
    try:
        audio = MutagenFile(path, easy=True)
    except Exception:
        audio = None
    tags = getattr(audio, "tags", None)
    title = _first_tag(tags, "title")
    artist = _first_tag(tags, "artist", "albumartist")
    album = _first_tag(tags, "album")
    date = _first_tag(tags, "date", "year")
    isrc = _first_tag(tags, "isrc")
    duration = None
    try:
        duration = float(audio.info.length) if audio is not None and getattr(audio, "info", None) else None
    except (TypeError, ValueError, AttributeError):
        duration = None
    return {
        "provider": "embedded_tags",
        "title": title,
        "artist": artist,
        "album": album,
        "date": date,
        "isrc": isrc,
        "duration_seconds": duration,
        "confidence": 1.0 if title and artist else 0.86 if title else 0.0,
    }


def _fpcalc(path: Path, command: str = "fpcalc") -> tuple[int, str]:
    try:
        proc = subprocess.run(
            [command, "-json", str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=90,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SourceIdentificationError(str(exc)) from exc
    if proc.returncode != 0:
        raise SourceIdentificationError(proc.stderr.strip() or f"fpcalc exited with {proc.returncode}")
    try:
        payload = json.loads(proc.stdout)
        return int(round(float(payload["duration"]))), str(payload["fingerprint"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SourceIdentificationError("fpcalc returned invalid JSON") from exc


def lookup_acoustid(path: Path, *, client_key: str, fpcalc_cmd: str = "fpcalc") -> list[dict[str, Any]]:
    duration, fingerprint = _fpcalc(path, fpcalc_cmd)
    params = urllib.parse.urlencode(
        {
            "client": client_key,
            "meta": "recordings+releasegroups+compress",
            "duration": str(duration),
            "fingerprint": fingerprint,
            "format": "json",
        }
    )
    request = urllib.request.Request(
        f"{ACOUSTID_LOOKUP}?{params}",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
        raise SourceIdentificationError(str(exc)) from exc

    candidates: list[dict[str, Any]] = []
    for result in payload.get("results", []) if isinstance(payload, dict) else []:
        score = float(result.get("score") or 0.0)
        for recording in result.get("recordings", []) or []:
            if not isinstance(recording, dict):
                continue
            artists = recording.get("artists") or []
            artist = ", ".join(
                str(item.get("name") or "") for item in artists if isinstance(item, dict) and item.get("name")
            ) or None
            releasegroups = recording.get("releasegroups") or []
            releasegroup = releasegroups[0] if releasegroups and isinstance(releasegroups[0], dict) else {}
            candidates.append(
                {
                    "provider": "acoustid",
                    "acoustid": result.get("id"),
                    "recording_mbid": recording.get("id"),
                    "title": recording.get("title"),
                    "artist": artist,
                    "album": releasegroup.get("title") if isinstance(releasegroup, dict) else None,
                    "confidence": round(score, 4),
                    "duration_seconds": duration,
                }
            )
    candidates.sort(key=lambda item: float(item.get("confidence") or 0.0), reverse=True)
    return candidates


def identify_source(
    path: Path,
    *,
    usage_mode: str = "personal",
    fpcalc_cmd: str = "fpcalc",
    acoustid_client_key_env: str = "ACOUSTID_CLIENT_KEY",
    acoustid_commercial_entitled: bool | None = None,
) -> dict[str, Any]:
    tags = read_embedded_tags(path)
    report: dict[str, Any] = {
        "source": str(path),
        "embedded_tags": tags,
        "acoustid": {"attempted": False, "candidates": [], "error": None},
        "selected": None,
        "policy": {
            "order": ["embedded_tags", "isrc", "acoustid", "musicbrainz_fuzzy", "model_fallback"],
            "model_is_last_resort": True,
            "commercial_entitlement_required_for_acoustid": True,
        },
    }

    if tags.get("title") and tags.get("artist"):
        report["selected"] = dict(tags)
        report["selected"]["reason"] = "trusted embedded title+artist tags"
        return report

    client_key = os.getenv(acoustid_client_key_env, "").strip()
    if acoustid_commercial_entitled is None:
        acoustid_commercial_entitled = os.getenv("AST_ACOUSTID_COMMERCIAL_ENTITLED", "").lower() in {
            "1", "true", "yes", "on"
        }
    commercial_blocked = usage_mode == "commercial" and not acoustid_commercial_entitled
    if not client_key:
        report["acoustid"]["error"] = f"{acoustid_client_key_env} is not configured"
    elif commercial_blocked:
        report["acoustid"]["error"] = "commercial AcoustID entitlement not confirmed"
    else:
        report["acoustid"]["attempted"] = True
        try:
            candidates = lookup_acoustid(path, client_key=client_key, fpcalc_cmd=fpcalc_cmd)
            report["acoustid"]["candidates"] = candidates[:5]
            if candidates and float(candidates[0].get("confidence") or 0.0) >= 0.90:
                report["selected"] = {**candidates[0], "reason": "high-confidence AcoustID fingerprint"}
        except SourceIdentificationError as exc:
            report["acoustid"]["error"] = str(exc)

    if report["selected"] is None and tags.get("title"):
        report["selected"] = {**tags, "reason": "embedded title hint; requires metadata enrichment"}
    return report

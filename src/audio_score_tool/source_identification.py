from __future__ import annotations

import json
import os
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from mutagen import File as MutagenFile

from .safe_http import open_json
from .secret_env import SecretEnvError, secret_from_env

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
    try:
        audio = MutagenFile(path, easy=True)
    except Exception:
        audio = None
    tags = getattr(audio, "tags", None)
    title = (_first_tag(tags, "title") or "")[:300] or None
    artist = (_first_tag(tags, "artist", "albumartist") or "")[:300] or None
    album = (_first_tag(tags, "album") or "")[:500] or None
    date = (_first_tag(tags, "date", "year") or "")[:50] or None
    isrc = (_first_tag(tags, "isrc") or "")[:32] or None
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
        raise SourceIdentificationError((proc.stderr or "").strip()[-4000:] or f"fpcalc exited with {proc.returncode}")
    if len(proc.stdout or "") > 8 * 1024 * 1024:
        raise SourceIdentificationError("fpcalc returned an unexpectedly large response")
    try:
        payload = json.loads(proc.stdout)
        fingerprint = str(payload["fingerprint"])
        if len(fingerprint) > 4 * 1024 * 1024:
            raise SourceIdentificationError("fpcalc fingerprint is unexpectedly large")
        return int(round(float(payload["duration"]))), fingerprint
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SourceIdentificationError("fpcalc returned invalid JSON") from exc


def lookup_acoustid(path: Path, *, client_key: str, fpcalc_cmd: str = "fpcalc") -> list[dict[str, Any]]:
    duration, fingerprint = _fpcalc(path, fpcalc_cmd)
    body = urllib.parse.urlencode(
        {
            "client": client_key,
            "meta": "recordings+releasegroups+compress",
            "duration": str(duration),
            "fingerprint": fingerprint,
            "format": "json",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        ACOUSTID_LOOKUP,
        data=body,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        payload = open_json(request, timeout=12)
    except RuntimeError as exc:
        raise SourceIdentificationError(str(exc)) from exc

    candidates: list[dict[str, Any]] = []
    for result in payload.get("results", []) if isinstance(payload, dict) else []:
        score = float(result.get("score") or 0.0)
        for recording in (result.get("recordings", []) or [])[:20]:
            if not isinstance(recording, dict):
                continue
            artists = recording.get("artists") or []
            artist = ", ".join(
                str(item.get("name") or "")[:150]
                for item in artists[:20]
                if isinstance(item, dict) and item.get("name")
            )[:300] or None
            releasegroups = recording.get("releasegroups") or []
            releasegroup = releasegroups[0] if releasegroups and isinstance(releasegroups[0], dict) else {}
            candidates.append(
                {
                    "provider": "acoustid",
                    "acoustid": str(result.get("id") or "")[:100] or None,
                    "recording_mbid": str(recording.get("id") or "")[:100] or None,
                    "title": str(recording.get("title") or "")[:300] or None,
                    "artist": artist,
                    "album": str(releasegroup.get("title") or "")[:500] if isinstance(releasegroup, dict) else None,
                    "confidence": round(max(0.0, min(1.0, score)), 4),
                    "duration_seconds": duration,
                }
            )
            if len(candidates) >= 100:
                break
        if len(candidates) >= 100:
            break
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
        "source_asset": path.name[:300],
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

    try:
        client_key = secret_from_env(acoustid_client_key_env) or ""
    except SecretEnvError as exc:
        report["acoustid"]["error"] = str(exc)
        client_key = ""
    if acoustid_commercial_entitled is None:
        acoustid_commercial_entitled = os.getenv("AST_ACOUSTID_COMMERCIAL_ENTITLED", "").lower() in {
            "1", "true", "yes", "on"
        }
    commercial_blocked = usage_mode == "commercial" and not acoustid_commercial_entitled
    if not client_key and report["acoustid"]["error"] is None:
        report["acoustid"]["error"] = f"{acoustid_client_key_env} is not configured"
    elif commercial_blocked:
        report["acoustid"]["error"] = "commercial AcoustID entitlement not confirmed"
    elif client_key:
        report["acoustid"]["attempted"] = True
        try:
            candidates = lookup_acoustid(path, client_key=client_key, fpcalc_cmd=fpcalc_cmd)
            report["acoustid"]["candidates"] = candidates[:5]
            if candidates and float(candidates[0].get("confidence") or 0.0) >= 0.90:
                report["selected"] = {**candidates[0], "reason": "high-confidence AcoustID fingerprint"}
        except SourceIdentificationError as exc:
            report["acoustid"]["error"] = str(exc)[:4000]

    if report["selected"] is None and tags.get("title"):
        report["selected"] = {**tags, "reason": "embedded title hint; requires metadata enrichment"}
    return report

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ENV = "AST_TIER2_TELEMETRY_FILE"
_LOCK = threading.RLock()
_EDIT_KEYS = (
    "manual_note_edits",
    "manual_chord_edits",
    "manual_measure_edits",
    "manual_part_edits",
    "manual_lyric_edits",
    "manual_layout_edits",
)
_REQUIRED_FINAL_EXPORTS = {"musicxml", "pdf", "midi", "parts"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Tier 2 telemetry started_at is missing")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def telemetry_path() -> Path | None:
    raw = os.getenv(_ENV, "").strip()
    return Path(raw).expanduser() if raw else None


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(raw_tmp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def start_edit_session(
    path: Path,
    *,
    case_id: str,
    song_id: str | None = None,
    started_at: datetime | None = None,
) -> dict[str, Any]:
    case_id = case_id.strip()
    if not case_id:
        raise ValueError("case_id is required")
    payload: dict[str, Any] = {
        "schema_version": "1",
        "case_id": case_id,
        "song_id": song_id.strip() if song_id else None,
        "started_at": _iso(started_at or _now()),
        "finished_at": None,
        **{key: 0 for key in _EDIT_KEYS},
        "total_edit_actions": 0,
        "time_to_publish_seconds": None,
        "successful_export": False,
    }
    with _LOCK:
        _atomic_write(path, payload)
    return payload


def read_edit_session(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != "1":
        raise ValueError("Unsupported Tier 2 telemetry file")
    return payload


def _category(method: str, path: str, body: bytes) -> str | None:
    method = method.upper()
    if method == "PATCH" and path.endswith("/publication"):
        return "manual_layout_edits"
    if method == "PATCH" and path.endswith("/chord"):
        return "manual_chord_edits"
    if "/measures/" in path and method in {"POST", "PATCH", "DELETE"}:
        return "manual_measure_edits"
    if "/notes/" in path and method in {"POST", "PATCH", "DELETE"}:
        if method == "PATCH" and body:
            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                payload = None
            if isinstance(payload, dict) and set(payload) <= {"lyric"} and "lyric" in payload:
                return "manual_lyric_edits"
        return "manual_note_edits"
    return None


def _is_complete_final_export(body: bytes) -> bool:
    """Return true only when the request asks for the complete publication bundle.

    The export endpoint defaults to all final formats when the body is empty or null.
    Explicit subset exports are useful during editing, but must not stop a Tier 2
    time-to-publish clock or count as a successful final publication.
    """

    if not body.strip():
        return True
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    if payload is None:
        return True
    if not isinstance(payload, dict):
        return False
    formats = payload.get("formats")
    if formats is None:
        return True
    if not isinstance(formats, list) or not all(isinstance(item, str) for item in formats):
        return False
    return _REQUIRED_FINAL_EXPORTS <= {item.strip().lower() for item in formats}


def record_successful_song_mutation(
    *,
    song_id: str,
    method: str,
    path: str,
    status_code: int,
    request_body: bytes = b"",
    finished_at: datetime | None = None,
) -> None:
    target = telemetry_path()
    if target is None or status_code < 200 or status_code >= 300 or not target.exists():
        return

    with _LOCK:
        try:
            payload = read_edit_session(target)
        except (OSError, ValueError, json.JSONDecodeError):
            return

        bound_song = payload.get("song_id")
        if bound_song is None:
            payload["song_id"] = song_id
        elif bound_song != song_id:
            return

        if method.upper() == "POST" and path.endswith("/export"):
            if not _is_complete_final_export(request_body):
                return
            end = finished_at or _now()
            started = _parse_time(payload.get("started_at"))
            payload["finished_at"] = _iso(end)
            payload["time_to_publish_seconds"] = round(
                max(0.0, (end - started).total_seconds()), 3
            )
            payload["successful_export"] = True
            _atomic_write(target, payload)
            return

        category = _category(method, path, request_body)
        if category is None:
            return
        payload[category] = int(payload.get(category) or 0) + 1
        payload["total_edit_actions"] = sum(int(payload.get(key) or 0) for key in _EDIT_KEYS)
        _atomic_write(target, payload)

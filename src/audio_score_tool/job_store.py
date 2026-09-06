from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from .paths import database_path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStore:
    def __init__(self, path: Path | None = None):
        self.path = path or database_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    stage TEXT,
                    progress INTEGER NOT NULL DEFAULT 0,
                    filename TEXT,
                    language TEXT,
                    skip_lyrics INTEGER NOT NULL DEFAULT 0,
                    preset TEXT,
                    muscriptor_model TEXT,
                    whisperx_model TEXT,
                    error TEXT,
                    result_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "UPDATE jobs SET status='interrupted', stage='interrupted' "
                "WHERE status IN ('queued', 'running', 'cancelling')"
            )

    def create(self, job_id: str, **values: Any) -> None:
        now = _now()
        payload = {
            "status": values.get("status", "queued"),
            "stage": values.get("stage", "queued"),
            "progress": int(values.get("progress", 0)),
            "filename": values.get("filename"),
            "language": values.get("language"),
            "skip_lyrics": int(bool(values.get("skip_lyrics", False))),
            "preset": values.get("preset"),
            "muscriptor_model": values.get("muscriptor_model"),
            "whisperx_model": values.get("whisperx_model"),
            "error": values.get("error"),
            "result_json": json.dumps(values.get("result")) if values.get("result") else None,
        }
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    job_id,status,stage,progress,filename,language,skip_lyrics,preset,
                    muscriptor_model,whisperx_model,error,result_json,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    job_id, payload["status"], payload["stage"], payload["progress"],
                    payload["filename"], payload["language"], payload["skip_lyrics"],
                    payload["preset"], payload["muscriptor_model"], payload["whisperx_model"],
                    payload["error"], payload["result_json"], now, now,
                ),
            )

    def update(self, job_id: str, **values: Any) -> None:
        if not values:
            return
        mapping = dict(values)
        if "result" in mapping:
            mapping["result_json"] = json.dumps(mapping.pop("result"))
        if "skip_lyrics" in mapping:
            mapping["skip_lyrics"] = int(bool(mapping["skip_lyrics"]))
        mapping["updated_at"] = _now()
        assignments = ", ".join(f"{key}=?" for key in mapping)
        with self._lock, self._connect() as conn:
            conn.execute(
                f"UPDATE jobs SET {assignments} WHERE job_id=?",
                (*mapping.values(), job_id),
            )

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return self._row(row) if row else None

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [self._row(row) for row in rows]

    def delete(self, job_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM jobs WHERE job_id=?", (job_id,))
            return cur.rowcount > 0

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["skip_lyrics"] = bool(result["skip_lyrics"])
        raw = result.pop("result_json", None)
        result["result"] = json.loads(raw) if raw else None
        return result

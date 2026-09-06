from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from .paths import database_path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SongTombstoneStore:
    def __init__(self, path: Path | None = None):
        self.path = path or database_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._init()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    def _init(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS song_tombstones (
                    job_id TEXT PRIMARY KEY,
                    deleted_at TEXT NOT NULL
                )
                """
            )

    def contains(self, job_id: str | None) -> bool:
        if not job_id:
            return False
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM song_tombstones WHERE job_id=?",
                (job_id,),
            ).fetchone()
        return row is not None

    def add(self, job_id: str | None) -> None:
        if not job_id:
            return
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO song_tombstones(job_id, deleted_at) VALUES (?, ?)",
                (job_id, _now()),
            )

    def remove(self, job_id: str | None) -> None:
        if not job_id:
            return
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM song_tombstones WHERE job_id=?", (job_id,))

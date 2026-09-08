from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from .paths import app_data_dir, database_path
from .publication_layout import merged_publication_settings


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PublicationStoreV2:
    """Persist per-song publication settings in SQLite.

    Legacy ``songs/<id>/publication.json`` files are imported lazily and then become
    compatibility artifacts only; SQLite is the canonical state from v0.8 onward.
    """

    def __init__(self, path: Path | None = None, legacy_root: Path | None = None):
        self.path = path or database_path()
        self.legacy_root = legacy_root or (app_data_dir() / "songs")
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
                CREATE TABLE IF NOT EXISTS publication_settings (
                    song_id TEXT PRIMARY KEY,
                    settings_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def _legacy_path(self, song_id: str) -> Path:
        return self.legacy_root / song_id / "publication.json"

    def exists(self, song_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM publication_settings WHERE song_id=?",
                (song_id,),
            ).fetchone()
        return bool(row) or self._legacy_path(song_id).exists()

    def read(self, song_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT settings_json FROM publication_settings WHERE song_id=?",
                (song_id,),
            ).fetchone()
        if row:
            try:
                payload = json.loads(row["settings_json"])
            except json.JSONDecodeError:
                payload = {}
            return merged_publication_settings(payload if isinstance(payload, dict) else {})

        legacy = self._legacy_path(song_id)
        if legacy.exists():
            try:
                payload = json.loads(legacy.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = {}
            migrated = merged_publication_settings(payload if isinstance(payload, dict) else {})
            self.write(song_id, migrated)
            return migrated
        return merged_publication_settings(None)

    def write(self, song_id: str, settings: dict[str, Any]) -> dict[str, Any]:
        merged = merged_publication_settings(settings)
        encoded = json.dumps(merged, ensure_ascii=False, separators=(",", ":"))
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO publication_settings(song_id, settings_json, updated_at)
                VALUES(?,?,?)
                ON CONFLICT(song_id) DO UPDATE SET
                    settings_json=excluded.settings_json,
                    updated_at=excluded.updated_at
                """,
                (song_id, encoded, _now()),
            )
        return merged

    def delete(self, song_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM publication_settings WHERE song_id=?", (song_id,))

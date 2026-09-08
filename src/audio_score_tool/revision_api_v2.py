from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from .publication_layout import merged_publication_settings
from .song_routes import _public, _require_song, _song_store

router = APIRouter(prefix="/api/songs", tags=["revision-v2"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _restore_revision_atomic(song_id: str, revision: int) -> bool:
    """Restore score, metadata and publication state in one SQLite transaction."""
    with _song_store._lock, _song_store._connect() as conn:  # shared canonical DB boundary
        row = conn.execute(
            "SELECT musicxml, publication_json, title, artist FROM song_revisions WHERE song_id=? AND revision=?",
            (song_id, revision),
        ).fetchone()
        if not row:
            return False
        try:
            publication = json.loads(row["publication_json"])
        except json.JSONDecodeError:
            publication = {}
        publication = merged_publication_settings(publication if isinstance(publication, dict) else {})
        encoded = json.dumps(publication, ensure_ascii=False, separators=(",", ":"))

        conn.execute(
            "UPDATE songs SET current_score_xml=?, title=?, artist=?, revision=?, updated_at=? WHERE song_id=?",
            (row["musicxml"], row["title"], row["artist"], revision, _now(), song_id),
        )
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
        conn.execute("DELETE FROM song_revisions WHERE song_id=? AND revision>=?", (song_id, revision))

    _song_store.clear_exports(song_id)
    shutil.rmtree(_song_store.cache_root / song_id, ignore_errors=True)
    return True


@router.post("/{song_id}/undo")
def undo_song_v2(song_id: str) -> dict:
    song = _require_song(song_id)
    current_revision = int(song.get("revision", 1))
    if current_revision <= 1:
        raise HTTPException(409, "되돌릴 수정 이력이 없습니다.")
    try:
        restored = _restore_revision_atomic(song_id, current_revision - 1)
    except sqlite3.Error as exc:
        raise HTTPException(500, f"Revision을 복구하지 못했습니다: {exc}") from exc
    if not restored:
        raise HTTPException(409, "되돌릴 수정 이력이 없습니다.")
    updated = _song_store.get(song_id)
    if not updated:
        raise HTTPException(404, "Song not found")
    return _public(updated)

from __future__ import annotations

import json
import sqlite3
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from .publication_layout import apply_publication_layout, merged_publication_settings
from .song_routes import (
    PublicationPatch,
    _discard_snapshot,
    _public,
    _publication_store,
    _require_song,
    _snapshot_before_edit,
    _song_store,
)
from .song_store_v2 import ConcurrentEditError

router = APIRouter(prefix="/api/songs", tags=["publication-v2"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.patch("/{song_id}/publication")
def update_publication_v2(song_id: str, payload: PublicationPatch) -> dict:
    song = _require_song(song_id)
    patch = payload.model_dump(exclude_unset=True)
    if not patch:
        return {"song": _public(song), "settings": _publication_store.read(song_id)}

    current = _publication_store.read(song_id)
    next_settings = merged_publication_settings({**current, **patch})
    snapshot_revision = _snapshot_before_edit(song)
    path = _song_store.checkout_current(song_id)
    expected_revision = int(song.get("revision", 1))

    try:
        apply_publication_layout(path, title=song["title"], settings=next_settings)
        xml_text = path.read_text(encoding="utf-8")
        root = ET.fromstring(xml_text)
        if root.tag.rsplit("}", 1)[-1] not in {"score-partwise", "score-timewise"}:
            raise ValueError("Document is not a MusicXML score")
        encoded = json.dumps(next_settings, ensure_ascii=False, separators=(",", ":"))
        with sqlite3.connect(_song_store.path, timeout=10) as conn:
            conn.execute("PRAGMA busy_timeout=10000")
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
            cur = conn.execute(
                """
                UPDATE songs
                SET current_score_xml=?, revision=revision+1, updated_at=?
                WHERE song_id=? AND revision=?
                """,
                (xml_text, _now(), song_id, expected_revision),
            )
            if cur.rowcount == 0:
                exists = conn.execute("SELECT 1 FROM songs WHERE song_id=?", (song_id,)).fetchone()
                if exists:
                    raise ConcurrentEditError("Song changed while publication settings were being applied")
                raise KeyError(song_id)
    except ConcurrentEditError as exc:
        _discard_snapshot(song_id, snapshot_revision)
        raise HTTPException(409, "악보가 다른 작업에서 변경되었습니다. 새로고침 후 다시 시도하세요.") from exc
    except KeyError as exc:
        _discard_snapshot(song_id, snapshot_revision)
        raise HTTPException(404, "Song not found") from exc
    except Exception as exc:
        _discard_snapshot(song_id, snapshot_revision)
        raise HTTPException(422, f"악보 조판 설정을 적용하지 못했습니다: {exc}") from exc

    _song_store.clear_exports(song_id)
    updated = _song_store.get(song_id) or song
    return {"song": _public(updated), "settings": next_settings}

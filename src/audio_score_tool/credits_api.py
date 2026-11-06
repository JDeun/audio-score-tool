from __future__ import annotations

import json
import sqlite3
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import Field

from .musicxml_editor import MusicXMLEditError, set_score_title
from .publication_layout import apply_publication_layout, merged_publication_settings
from .song_routes import (
    PublicationPatch,
    _public,
    _publication_store,
    _require_song,
    _song_store,
)
from .song_store_v2 import ConcurrentEditError, _valid_score_xml

router = APIRouter(prefix="/api/songs", tags=["atomic-credits"])


class CreditsPatch(PublicationPatch):
    """All first-page credits and song metadata in a single logical revision."""

    title: str = Field(max_length=300)
    artist: str | None = Field(default=None, max_length=300)
    expected_revision: int = Field(ge=1)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.patch("/{song_id}/credits")
def update_credits_atomic(song_id: str, payload: CreditsPatch) -> dict:
    """Atomically save title, artist, publication credits, MusicXML and Undo snapshot.

    Score materialization is only a scratch buffer. Canonical score/metadata and
    publication settings are persisted in one SQLite transaction. If a write fails
    or the editor's revision is stale, *none* of the fields are changed.
    """
    _require_song(song_id)
    title = payload.title.strip() or "제목 없는 곡"
    artist = payload.artist.strip() or None if payload.artist is not None else None
    current_publication = _publication_store.read(song_id)
    patch = payload.model_dump(exclude={"title", "artist", "expected_revision"}, exclude_unset=True)
    next_publication = merged_publication_settings({**current_publication, **patch})

    try:
        path = _song_store.checkout_current(song_id)
        set_score_title(path, title)
        apply_publication_layout(path, title=title, settings=next_publication)
        xml_text = _valid_score_xml(path.read_text(encoding="utf-8"))
        # Validate all rendering/serialization before beginning the database write.
        root = ET.fromstring(xml_text)
        if root.tag.rsplit("}", 1)[-1] not in {"score-partwise", "score-timewise"}:
            raise ValueError("Document is not a MusicXML score")
        old_publication_json = json.dumps(
            current_publication, ensure_ascii=False, separators=(",", ":")
        )
        next_publication_json = json.dumps(
            next_publication, ensure_ascii=False, separators=(",", ":")
        )

        with _song_store._lock, _song_store._connect() as conn:
            row = conn.execute(
                "SELECT revision, title, artist, current_score_xml FROM songs WHERE song_id=?",
                (song_id,),
            ).fetchone()
            if not row or not row["current_score_xml"]:
                raise KeyError(song_id)
            if int(row["revision"]) != payload.expected_revision:
                raise ConcurrentEditError("Song changed while first-page credits were being edited")

            stamp = _now()
            conn.execute(
                """
                INSERT OR REPLACE INTO song_revisions(
                    song_id, revision, musicxml, publication_json, title, artist, created_at
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    song_id,
                    payload.expected_revision,
                    row["current_score_xml"],
                    old_publication_json,
                    row["title"],
                    row["artist"],
                    stamp,
                ),
            )
            conn.execute(
                """
                INSERT INTO publication_settings(song_id, settings_json, updated_at)
                VALUES(?,?,?)
                ON CONFLICT(song_id) DO UPDATE SET
                    settings_json=excluded.settings_json,
                    updated_at=excluded.updated_at
                """,
                (song_id, next_publication_json, stamp),
            )
            updated = conn.execute(
                """
                UPDATE songs
                SET title=?, artist=?, current_score_xml=?, revision=revision+1, updated_at=?
                WHERE song_id=? AND revision=?
                """,
                (title, artist, xml_text, stamp, song_id, payload.expected_revision),
            )
            if updated.rowcount != 1:
                raise ConcurrentEditError("Song changed during first-page credit commit")

    except ConcurrentEditError as exc:
        raise HTTPException(409, "악보가 변경되었습니다. 새로고침 후 다시 저장하세요.") from exc
    except KeyError as exc:
        raise HTTPException(404, "Song not found") from exc
    except (ValueError, ET.ParseError, MusicXMLEditError) as exc:
        raise HTTPException(422, f"첫 페이지 제목과 크레딧을 적용할 수 없습니다: {exc}") from exc
    except (sqlite3.Error, OSError) as exc:
        raise HTTPException(500, f"제목·크레딧 저장에 실패했습니다: {exc}") from exc

    _song_store.clear_exports(song_id)
    song = _song_store.get(song_id)
    if not song:
        raise HTTPException(404, "Song not found")
    return {"song": _public(song), "settings": next_publication}

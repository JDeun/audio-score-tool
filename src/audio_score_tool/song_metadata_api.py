from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .musicxml_editor import set_score_title
from .publication_layout import apply_publication_layout
from .song_api_v2 import (
    SongMetadataPatch,
    _discard_snapshot,
    _public,
    _publication_store,
    _require_song,
    _snapshot_before_edit,
    _song_store,
)

router = APIRouter(prefix="/api/songs", tags=["song-metadata-v2"])


@router.patch("/{song_id}")
def update_song_metadata_v2(song_id: str, payload: SongMetadataPatch) -> dict:
    song = _require_song(song_id)
    next_title = (
        payload.title.strip() or "제목 없는 곡"
        if payload.title is not None
        else str(song.get("title") or "제목 없는 곡")
    )
    title_changed = next_title != song.get("title")
    snapshot_revision: int | None = None

    if title_changed:
        snapshot_revision = _snapshot_before_edit(song)
        path = _song_store.checkout_current(song_id)
        try:
            set_score_title(path, next_title)
            apply_publication_layout(
                path,
                title=next_title,
                settings=_publication_store.read(song_id),
            )
            _song_store.commit_edit_from_path(song_id, path)
        except Exception as exc:
            _discard_snapshot(song_id, snapshot_revision)
            raise HTTPException(422, f"제목을 악보에 반영하지 못했습니다: {exc}") from exc

    try:
        updated = _song_store.update_metadata(
            song_id,
            title=payload.title,
            artist=payload.artist,
        )
    except Exception as exc:
        if snapshot_revision is not None:
            restored_publication = _song_store.restore_revision(song_id, snapshot_revision)
            if restored_publication is not None:
                _publication_store.write(song_id, restored_publication)
        raise HTTPException(500, f"곡 메타데이터를 저장하지 못했습니다: {exc}") from exc

    if updated is None:
        if snapshot_revision is not None:
            restored_publication = _song_store.restore_revision(song_id, snapshot_revision)
            if restored_publication is not None:
                _publication_store.write(song_id, restored_publication)
        raise HTTPException(404, "Song not found")
    return _public(updated)

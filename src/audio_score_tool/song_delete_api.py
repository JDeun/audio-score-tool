from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .song_routes import _require_song, _song_store, _tombstones

router = APIRouter(prefix="/api/songs", tags=["song-delete-v2"])


@router.delete("/{song_id}")
def delete_song_v2(song_id: str) -> dict:
    """Delete canonical song state without leaving partial publication/tombstone state."""
    song = _require_song(song_id)
    job_id = song.get("job_id")

    # Add the tombstone first so concurrent library sync cannot re-ingest the source Job
    # between the canonical row deletion and the tombstone write. If deletion itself
    # fails, remove the tombstone and leave the song fully visible/unchanged.
    _tombstones.add(job_id)
    try:
        deleted = _song_store.delete(song_id)
    except Exception:
        _tombstones.remove(job_id)
        raise
    if not deleted:
        _tombstones.remove(job_id)
        raise HTTPException(404, "Song not found")
    return {"song_id": song_id, "deleted": True}

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .chord_editor import ChordEditError, set_chord_at_note
from .chord_listing import list_chords
from .job_store import JobStore
from .musicxml_editor import (
    MusicXMLEditError,
    score_summary,
    set_score_title,
    snapshot,
    undo_last,
    update_note,
)
from .musicxml_parts import list_score_parts
from .publication_layout import apply_publication_layout, merged_publication_settings
from .publication_store import PublicationStore
from .song_store import SongStore
from .song_tombstones import SongTombstoneStore

router = APIRouter(prefix="/api/songs", tags=["songs"])
_song_store = SongStore()
_job_store = JobStore()
_publication_store = PublicationStore()
_tombstones = SongTombstoneStore()


class SongMetadataPatch(BaseModel):
    title: str | None = None
    artist: str | None = None


class NotePatch(BaseModel):
    step: str | None = None
    alter: int | None = None
    octave: int | None = None
    lyric: str | None = None


class ChordPatch(BaseModel):
    symbol: str | None = None


class PublicationPatch(BaseModel):
    page_size: Literal["A4", "LETTER"] | None = None
    orientation: Literal["portrait", "landscape"] | None = None
    bars_per_system: int | None = Field(default=None, ge=1, le=12)
    systems_per_page: int | None = Field(default=None, ge=1, le=12)
    system_distance_mm: float | None = Field(default=None, ge=3, le=40)
    first_page_title_space_mm: float | None = Field(default=None, ge=15, le=90)
    top_margin_mm: float | None = Field(default=None, ge=5, le=40)
    bottom_margin_mm: float | None = Field(default=None, ge=5, le=40)
    left_margin_mm: float | None = Field(default=None, ge=5, le=40)
    right_margin_mm: float | None = Field(default=None, ge=5, le=40)
    title_font_size: float | None = Field(default=None, ge=14, le=48)
    subtitle_font_size: float | None = Field(default=None, ge=8, le=28)
    credit_font_size: float | None = Field(default=None, ge=7, le=18)
    subtitle: str | None = Field(default=None, max_length=200)
    composer: str | None = Field(default=None, max_length=200)
    lyricist: str | None = Field(default=None, max_length=200)
    arranger: str | None = Field(default=None, max_length=200)
    rights: str | None = Field(default=None, max_length=500)


def _initialize_publication(song: dict) -> None:
    song_id = song["song_id"]
    if _publication_store.exists(song_id):
        return
    settings = _publication_store.write(song_id, merged_publication_settings(None))
    try:
        apply_publication_layout(
            Path(song["current_musicxml"]),
            title=song["title"],
            settings=settings,
        )
    except Exception:
        # A malformed upstream MusicXML should remain accessible for manual repair.
        return


def _sync() -> None:
    jobs = [
        job
        for job in _job_store.list(limit=5000)
        if not _tombstones.contains(job.get("job_id"))
    ]
    _song_store.sync_completed_jobs(jobs)
    for song in _song_store.list():
        _initialize_publication(song)


def _part_exports(song: dict) -> list[dict]:
    current = Path(song["current_musicxml"])
    try:
        parts = list_score_parts(current)
    except Exception:
        return []
    export_dir = _song_store.export_dir(song["song_id"]) / "parts"
    result: list[dict] = []
    for part in parts:
        slug = str(part["slug"])
        result.append(
            {
                **part,
                "pdf": (export_dir / f"{slug}.pdf").exists(),
                "musicxml": (export_dir / f"{slug}.musicxml").exists(),
            }
        )
    return result


def _public(song: dict) -> dict:
    return {
        "song_id": song["song_id"],
        "job_id": song.get("job_id"),
        "title": song["title"],
        "artist": song.get("artist"),
        "source_kind": song.get("source_kind", "transcription"),
        "revision": song.get("revision", 1),
        "created_at": song.get("created_at"),
        "updated_at": song.get("updated_at"),
        "exports": {
            "pdf": bool((song.get("exports") or {}).get("pdf")),
            "midi": bool((song.get("exports") or {}).get("midi")),
            "musicxml": True,
        },
        "parts": _part_exports(song),
    }


def _require_song(song_id: str) -> dict:
    _sync()
    song = _song_store.get(song_id)
    if not song:
        raise HTTPException(404, "Song not found")
    return song


def _snapshot_before_edit(song: dict) -> None:
    revision = int(song.get("revision", 1))
    revisions_dir = _song_store.revision_dir(song["song_id"])
    snapshot(Path(song["current_musicxml"]), revisions_dir, revision)
    _publication_store.snapshot(song["song_id"], revisions_dir, revision)


def _discard_snapshot(song: dict) -> None:
    revision = int(song.get("revision", 1))
    revisions_dir = _song_store.revision_dir(song["song_id"])
    (revisions_dir / f"rev-{revision:04d}.musicxml").unlink(missing_ok=True)
    (revisions_dir / f"rev-{revision:04d}.publication.json").unlink(missing_ok=True)


def _commit_score_change(song_id: str) -> dict:
    _song_store.clear_exports(song_id)
    updated = _song_store.bump_revision(song_id)
    if not updated:
        raise HTTPException(404, "Song not found")
    return updated


@router.get("")
def list_songs() -> dict:
    _sync()
    return {"songs": [_public(song) for song in _song_store.list()]}


@router.get("/{song_id}")
def get_song(song_id: str) -> dict:
    return _public(_require_song(song_id))


@router.delete("/{song_id}")
def delete_song(song_id: str) -> dict:
    song = _require_song(song_id)
    _tombstones.add(song.get("job_id"))
    if not _song_store.delete(song_id):
        raise HTTPException(404, "Song not found")
    return {"song_id": song_id, "deleted": True}


@router.get("/{song_id}/score")
def get_score(song_id: str) -> FileResponse:
    song = _require_song(song_id)
    path = Path(song["current_musicxml"])
    if not path.exists():
        raise HTTPException(404, "Current MusicXML is missing")
    return FileResponse(
        path,
        media_type="application/vnd.recordare.musicxml+xml",
        filename=f"{song['title']}.musicxml",
    )


@router.get("/{song_id}/notes")
def get_notes(song_id: str) -> dict:
    song = _require_song(song_id)
    path = Path(song["current_musicxml"])
    try:
        summary = score_summary(path)
        chords = list_chords(path)
    except Exception as exc:
        raise HTTPException(422, f"Could not parse MusicXML: {exc}") from exc
    return {
        "song": _public(song),
        **summary,
        "chords": chords,
    }


@router.patch("/{song_id}")
def update_song(song_id: str, payload: SongMetadataPatch) -> dict:
    song = _require_song(song_id)
    title_changed = (
        payload.title is not None
        and (payload.title.strip() or "제목 없는 곡") != song["title"]
    )
    if title_changed:
        _snapshot_before_edit(song)
        title = payload.title.strip() or "제목 없는 곡"
        try:
            set_score_title(Path(song["current_musicxml"]), title)
            apply_publication_layout(
                Path(song["current_musicxml"]),
                title=title,
                settings=_publication_store.read(song_id),
            )
        except Exception as exc:
            _discard_snapshot(song)
            raise HTTPException(422, f"제목을 악보에 반영하지 못했습니다: {exc}") from exc
        song = _commit_score_change(song_id)

    updated = _song_store.update_metadata(
        song_id,
        title=payload.title,
        artist=payload.artist,
    )
    if not updated:
        raise HTTPException(404, "Song not found")
    return _public(updated)


@router.patch("/{song_id}/notes/{note_id}")
def patch_note(song_id: str, note_id: str, payload: NotePatch) -> dict:
    song = _require_song(song_id)
    patch = payload.model_dump(exclude_unset=True)
    if not patch:
        return {"song": _public(song), "note_id": note_id}

    _snapshot_before_edit(song)
    try:
        update_note(Path(song["current_musicxml"]), note_id, patch)
    except MusicXMLEditError as exc:
        _discard_snapshot(song)
        raise HTTPException(422, str(exc)) from exc

    updated = _commit_score_change(song_id)
    return {"song": _public(updated), "note_id": note_id}


@router.patch("/{song_id}/notes/{note_id}/chord")
def patch_chord(song_id: str, note_id: str, payload: ChordPatch) -> dict:
    song = _require_song(song_id)
    _snapshot_before_edit(song)
    try:
        set_chord_at_note(Path(song["current_musicxml"]), note_id, payload.symbol)
    except ChordEditError as exc:
        _discard_snapshot(song)
        raise HTTPException(422, str(exc)) from exc
    updated = _commit_score_change(song_id)
    return {"song": _public(updated), "note_id": note_id, "symbol": payload.symbol or ""}


@router.get("/{song_id}/publication")
def get_publication(song_id: str) -> dict:
    _require_song(song_id)
    return {"settings": _publication_store.read(song_id)}


@router.patch("/{song_id}/publication")
def update_publication(song_id: str, payload: PublicationPatch) -> dict:
    song = _require_song(song_id)
    patch = payload.model_dump(exclude_unset=True)
    if not patch:
        return {"song": _public(song), "settings": _publication_store.read(song_id)}

    current = _publication_store.read(song_id)
    next_settings = dict(current)
    next_settings.update(patch)
    _snapshot_before_edit(song)
    try:
        apply_publication_layout(
            Path(song["current_musicxml"]),
            title=song["title"],
            settings=next_settings,
        )
        saved = _publication_store.write(song_id, next_settings)
    except Exception as exc:
        _discard_snapshot(song)
        raise HTTPException(422, f"악보 조판 설정을 적용하지 못했습니다: {exc}") from exc

    updated = _commit_score_change(song_id)
    return {"song": _public(updated), "settings": saved}


@router.post("/{song_id}/undo")
def undo_song(song_id: str) -> dict:
    song = _require_song(song_id)
    current_revision = int(song.get("revision", 1))
    revisions_dir = _song_store.revision_dir(song_id)
    restored = undo_last(Path(song["current_musicxml"]), revisions_dir)
    if restored is None:
        raise HTTPException(409, "되돌릴 수정 이력이 없습니다.")
    _publication_store.restore_snapshot(song_id, revisions_dir, current_revision - 1)
    _song_store.clear_exports(song_id)
    updated = _song_store.set_revision(song_id, current_revision - 1)
    return _public(updated or song)


@router.post("/{song_id}/restore")
def restore_original(song_id: str) -> dict:
    song = _require_song(song_id)
    _snapshot_before_edit(song)
    original = Path(song["original_musicxml"])
    current = Path(song["current_musicxml"])
    if not original.exists():
        _discard_snapshot(song)
        raise HTTPException(404, "Original MusicXML is missing")
    try:
        shutil.copy2(original, current)
        apply_publication_layout(
            current,
            title=song["title"],
            settings=_publication_store.read(song_id),
        )
    except Exception as exc:
        _discard_snapshot(song)
        raise HTTPException(422, f"원본 악보를 복원하지 못했습니다: {exc}") from exc
    updated = _commit_score_change(song_id)
    return _public(updated)


@router.get("/{song_id}/files/parts/{slug}/{kind}")
def download_part_file(song_id: str, slug: str, kind: str) -> FileResponse:
    song = _require_song(song_id)
    allowed = {str(part["slug"]) for part in list_score_parts(Path(song["current_musicxml"]))}
    if slug not in allowed:
        raise HTTPException(404, "Unknown score part")
    if kind == "pdf":
        path = _song_store.export_dir(song_id) / "parts" / f"{slug}.pdf"
        media_type = "application/pdf"
    elif kind == "musicxml":
        path = _song_store.export_dir(song_id) / "parts" / f"{slug}.musicxml"
        media_type = "application/vnd.recordare.musicxml+xml"
    else:
        raise HTTPException(404, "Unknown part artifact")
    if not path.exists():
        raise HTTPException(404, "Part export is not available. Run export first.")
    return FileResponse(path, media_type=media_type, filename=path.name)


@router.get("/{song_id}/files/{kind}")
def download_song_file(song_id: str, kind: str) -> FileResponse:
    song = _require_song(song_id)
    if kind == "musicxml":
        path = Path(song["current_musicxml"])
        filename = f"{song['title']}.musicxml"
        media_type = "application/vnd.recordare.musicxml+xml"
    elif kind == "pdf":
        path = _song_store.export_dir(song_id) / "score.pdf"
        filename = f"{song['title']}.pdf"
        media_type = "application/pdf"
    elif kind == "midi":
        path = _song_store.export_dir(song_id) / "score.mid"
        filename = f"{song['title']}.mid"
        media_type = "audio/midi"
    else:
        raise HTTPException(404, "Unknown song artifact")

    if not path.exists():
        raise HTTPException(404, "Export file is not available. Run export first.")
    return FileResponse(path, media_type=media_type, filename=filename)

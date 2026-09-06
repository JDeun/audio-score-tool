from __future__ import annotations

from pathlib import Path
from typing import Callable, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .musicxml_editor import MusicXMLEditError, update_note
from .publication_layout import apply_publication_layout
from .publication_store import PublicationStore
from .score_structure import (
    delete_measure,
    delete_note,
    insert_measure,
    insert_note,
    set_measure_signature,
    structure_summary,
    update_note_structure,
)
from .song_api import (
    _commit_score_change,
    _discard_snapshot,
    _public,
    _require_song,
    _snapshot_before_edit,
)

router = APIRouter(prefix="/api/songs", tags=["advanced-score-editor"])
_publication_store = PublicationStore()
NoteType = Literal["whole", "half", "quarter", "eighth", "16th", "32nd", "64th"]


class NoteStructurePatch(BaseModel):
    step: Literal["A", "B", "C", "D", "E", "F", "G"] | None = None
    alter: int | None = Field(default=None, ge=-2, le=2)
    octave: int | None = Field(default=None, ge=0, le=9)
    lyric: str | None = Field(default=None, max_length=200)
    type: NoteType | None = None
    dots: int | None = Field(default=None, ge=0, le=2)
    rest: bool | None = None
    articulations: list[Literal["staccato", "tenuto", "accent", "strong-accent"]] | None = None
    ties: list[Literal["start", "stop"]] | None = None
    slurs: list[Literal["start", "stop"]] | None = None
    beam: Literal["begin", "continue", "end", "forward hook", "backward hook"] | None = None


class InsertNotePayload(BaseModel):
    position: Literal["before", "after"] = "after"
    rest: bool = False
    step: Literal["A", "B", "C", "D", "E", "F", "G"] = "C"
    alter: int = Field(default=0, ge=-2, le=2)
    octave: int = Field(default=4, ge=0, le=9)
    type: NoteType = "quarter"
    dots: int = Field(default=0, ge=0, le=2)
    lyric: str = Field(default="", max_length=200)


class SignaturePatch(BaseModel):
    key_fifths: int | None = Field(default=None, ge=-7, le=7)
    key_mode: Literal["major", "minor"] | None = None
    beats: int | None = Field(default=None, ge=1, le=32)
    beat_type: Literal[1, 2, 4, 8, 16, 32] | None = None


def _refresh_layout(song: dict) -> None:
    apply_publication_layout(
        Path(song["current_musicxml"]),
        title=song["title"],
        settings=_publication_store.read(song["song_id"]),
    )


def _mutate(song_id: str, operation: Callable[[dict], dict]) -> dict:
    song = _require_song(song_id)
    _snapshot_before_edit(song)
    try:
        result = operation(song)
        _refresh_layout(song)
    except MusicXMLEditError as exc:
        _discard_snapshot(song)
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        _discard_snapshot(song)
        raise HTTPException(422, f"악보 구조를 수정하지 못했습니다: {exc}") from exc
    updated = _commit_score_change(song_id)
    return {"song": _public(updated), "result": result}


@router.get("/{song_id}/structure")
def get_structure(song_id: str) -> dict:
    song = _require_song(song_id)
    return {"song": _public(song), **structure_summary(Path(song["current_musicxml"]))}


@router.patch("/{song_id}/notes/{note_id}/structure")
def patch_note_structure(song_id: str, note_id: str, payload: NoteStructurePatch) -> dict:
    patch = payload.model_dump(exclude_unset=True)
    if not patch:
        return {"song": _public(_require_song(song_id)), "note_id": note_id}

    def operation(song: dict) -> dict:
        path = Path(song["current_musicxml"])
        structure_fields = {
            key: value
            for key, value in patch.items()
            if key in {"type", "dots", "rest", "articulations", "ties", "slurs", "beam"}
        }
        if structure_fields:
            update_note_structure(path, note_id, structure_fields)
        basic_fields = {
            key: value
            for key, value in patch.items()
            if key in {"step", "alter", "octave", "lyric"}
        }
        if basic_fields:
            if patch.get("rest") is True:
                basic_fields = {key: value for key, value in basic_fields.items() if key == "lyric"}
            if basic_fields:
                update_note(path, note_id, basic_fields)
        return {"note_id": note_id}

    return _mutate(song_id, operation)


@router.post("/{song_id}/notes/{note_id}/insert")
def insert_score_note(song_id: str, note_id: str, payload: InsertNotePayload) -> dict:
    def operation(song: dict) -> dict:
        new_id = insert_note(
            Path(song["current_musicxml"]),
            note_id,
            position=payload.position,
            rest=payload.rest,
            step=payload.step,
            alter=payload.alter,
            octave=payload.octave,
            note_type=payload.type,
            dots=payload.dots,
            lyric=payload.lyric,
        )
        return {"note_id": new_id}

    return _mutate(song_id, operation)


@router.delete("/{song_id}/notes/{note_id}")
def delete_score_note(song_id: str, note_id: str) -> dict:
    def operation(song: dict) -> dict:
        delete_note(Path(song["current_musicxml"]), note_id)
        return {"deleted_note_id": note_id}

    return _mutate(song_id, operation)


@router.post("/{song_id}/measures/{measure_index}/insert-after")
def insert_score_measure(song_id: str, measure_index: int) -> dict:
    def operation(song: dict) -> dict:
        new_index = insert_measure(Path(song["current_musicxml"]), measure_index)
        return {"measure_index": new_index}

    return _mutate(song_id, operation)


@router.delete("/{song_id}/measures/{measure_index}")
def delete_score_measure(song_id: str, measure_index: int) -> dict:
    def operation(song: dict) -> dict:
        delete_measure(Path(song["current_musicxml"]), measure_index)
        return {"deleted_measure_index": measure_index}

    return _mutate(song_id, operation)


@router.patch("/{song_id}/measures/{measure_index}/signature")
def patch_measure_signature(song_id: str, measure_index: int, payload: SignaturePatch) -> dict:
    patch = payload.model_dump(exclude_unset=True)
    if not patch:
        return {"song": _public(_require_song(song_id)), "measure_index": measure_index}

    def operation(song: dict) -> dict:
        set_measure_signature(
            Path(song["current_musicxml"]),
            measure_index,
            fifths=patch.get("key_fifths"),
            mode=patch.get("key_mode"),
            beats=patch.get("beats"),
            beat_type=patch.get("beat_type"),
        )
        return {"measure_index": measure_index}

    return _mutate(song_id, operation)

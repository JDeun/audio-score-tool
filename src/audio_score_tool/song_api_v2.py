from __future__ import annotations

import platform
import shutil
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from .chord_editor import ChordEditError, set_chord_at_note
from .chord_listing import list_chords
from .job_store import JobStore
from .musicxml_editor import MusicXMLEditError, score_summary, set_score_title, update_note
from .musicxml_parts import extract_part_musicxml, list_score_parts
from .paths import cache_dir
from .pipeline import _resolve_musescore
from .publication_layout import apply_publication_layout, merged_publication_settings
from .publication_store_v2 import PublicationStoreV2
from .runner import CommandError, run_command
from .runtime_settings import runtime_settings
from .score_structure import (
    delete_measure,
    delete_note,
    insert_measure,
    insert_note,
    set_measure_signature,
    structure_summary,
    update_note_structure,
)
from .song_store_v2 import SongStoreV2
from .song_tombstones import SongTombstoneStore

router = APIRouter(prefix="/api/songs", tags=["songs-v2"])
_song_store = SongStoreV2()
_job_store = JobStore()
_publication_store = PublicationStoreV2()
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


ExportKind = Literal["musicxml", "pdf", "midi", "parts"]


class ExportRequest(BaseModel):
    formats: list[ExportKind] = Field(
        default_factory=lambda: ["musicxml", "pdf", "midi", "parts"],
        min_length=1,
    )


def _sync() -> None:
    jobs = [
        job
        for job in _job_store.list(limit=5000)
        if not _tombstones.contains(job.get("job_id"))
    ]
    _song_store.sync_completed_jobs(jobs)
    for song in _song_store.list():
        if _publication_store.exists(song["song_id"]):
            continue
        settings = _publication_store.write(song["song_id"], merged_publication_settings(None))
        path = _song_store.checkout_current(song["song_id"])
        try:
            apply_publication_layout(path, title=song["title"], settings=settings)
            _song_store.replace_current_from_path(song["song_id"], path)
        except Exception:
            _song_store.checkout_current(song["song_id"])


def _part_exports(song: dict) -> list[dict]:
    try:
        parts = list_score_parts(_song_store.checkout_current(song["song_id"]))
    except Exception:
        return []
    export_dir = _song_store.export_root / song["song_id"] / "parts"
    return [
        {
            **part,
            "pdf": (export_dir / f"{part['slug']}.pdf").exists(),
            "musicxml": (export_dir / f"{part['slug']}.musicxml").exists(),
        }
        for part in parts
    ]


def _public(song: dict) -> dict:
    exports = song.get("exports") or {}
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
            "pdf": bool(exports.get("pdf")),
            "midi": bool(exports.get("midi")),
            "musicxml": bool(exports.get("musicxml")),
        },
        "parts": _part_exports(song),
    }


def _require_song(song_id: str) -> dict:
    _sync()
    song = _song_store.get(song_id)
    if not song:
        raise HTTPException(404, "Song not found")
    return song


def _snapshot_before_edit(song: dict) -> int:
    return _song_store.snapshot_revision(
        song["song_id"],
        _publication_store.read(song["song_id"]),
    )


def _discard_snapshot(song_id: str, revision: int) -> None:
    _song_store.discard_snapshot(song_id, revision)
    try:
        _song_store.checkout_current(song_id)
    except KeyError:
        pass


def _commit_score_change(song_id: str, path: Path) -> dict:
    updated = _song_store.commit_edit_from_path(song_id, path)
    if not updated:
        raise HTTPException(404, "Song not found")
    return updated


def _refresh_layout(song: dict, path: Path | None = None) -> Path:
    target = path or _song_store.checkout_current(song["song_id"])
    apply_publication_layout(
        target,
        title=song["title"],
        settings=_publication_store.read(song["song_id"]),
    )
    return target


def _musescore_env() -> dict[str, str] | None:
    if platform.system() != "Linux":
        return None
    return {"QT_QPA_PLATFORM": "offscreen", "MU_QT_QPA_PLATFORM": "offscreen"}


def _mutate(song_id: str, operation) -> dict:
    song = _require_song(song_id)
    snapshot_revision = _snapshot_before_edit(song)
    path = _song_store.checkout_current(song_id)
    try:
        result = operation(song, path)
        _refresh_layout(song, path)
        updated = _commit_score_change(song_id, path)
    except (MusicXMLEditError, ChordEditError) as exc:
        _discard_snapshot(song_id, snapshot_revision)
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        _discard_snapshot(song_id, snapshot_revision)
        raise HTTPException(422, f"악보를 수정하지 못했습니다: {exc}") from exc
    return {"song": _public(updated), "result": result}


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
    _publication_store.delete(song_id)
    if not _song_store.delete(song_id):
        raise HTTPException(404, "Song not found")
    return {"song_id": song_id, "deleted": True}


@router.get("/{song_id}/score")
def get_score(song_id: str) -> Response:
    _require_song(song_id)
    try:
        content = _song_store.score_xml(song_id)
    except KeyError as exc:
        raise HTTPException(404, "Current MusicXML is missing") from exc
    return Response(content=content, media_type="application/vnd.recordare.musicxml+xml")


@router.get("/{song_id}/notes")
def get_notes(song_id: str) -> dict:
    song = _require_song(song_id)
    path = _song_store.checkout_current(song_id)
    try:
        summary = score_summary(path)
        chords = list_chords(path)
    except Exception as exc:
        raise HTTPException(422, f"Could not parse MusicXML: {exc}") from exc
    return {"song": _public(song), **summary, "chords": chords}


@router.patch("/{song_id}")
def update_song(song_id: str, payload: SongMetadataPatch) -> dict:
    song = _require_song(song_id)
    title_changed = (
        payload.title is not None
        and (payload.title.strip() or "제목 없는 곡") != song["title"]
    )
    if title_changed:
        snapshot_revision = _snapshot_before_edit(song)
        path = _song_store.checkout_current(song_id)
        title = payload.title.strip() or "제목 없는 곡"
        try:
            set_score_title(path, title)
            apply_publication_layout(
                path,
                title=title,
                settings=_publication_store.read(song_id),
            )
            _commit_score_change(song_id, path)
        except Exception as exc:
            _discard_snapshot(song_id, snapshot_revision)
            raise HTTPException(422, f"제목을 악보에 반영하지 못했습니다: {exc}") from exc

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
    patch = payload.model_dump(exclude_unset=True)
    if not patch:
        return {"song": _public(_require_song(song_id)), "note_id": note_id}

    def operation(_song: dict, path: Path) -> dict:
        update_note(path, note_id, patch)
        return {"note_id": note_id}

    return _mutate(song_id, operation)


@router.patch("/{song_id}/notes/{note_id}/chord")
def patch_chord(song_id: str, note_id: str, payload: ChordPatch) -> dict:
    def operation(_song: dict, path: Path) -> dict:
        set_chord_at_note(path, note_id, payload.symbol)
        return {"note_id": note_id, "symbol": payload.symbol or ""}

    response = _mutate(song_id, operation)
    return {
        "song": response["song"],
        "note_id": note_id,
        "symbol": payload.symbol or "",
    }


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
    snapshot_revision = _snapshot_before_edit(song)
    path = _song_store.checkout_current(song_id)
    try:
        apply_publication_layout(path, title=song["title"], settings=next_settings)
        saved = _publication_store.write(song_id, next_settings)
        updated = _commit_score_change(song_id, path)
    except Exception as exc:
        _publication_store.write(song_id, current)
        _discard_snapshot(song_id, snapshot_revision)
        raise HTTPException(422, f"악보 조판 설정을 적용하지 못했습니다: {exc}") from exc
    return {"song": _public(updated), "settings": saved}


@router.post("/{song_id}/undo")
def undo_song(song_id: str) -> dict:
    song = _require_song(song_id)
    current_revision = int(song.get("revision", 1))
    if current_revision <= 1:
        raise HTTPException(409, "되돌릴 수정 이력이 없습니다.")
    restored_publication = _song_store.restore_revision(song_id, current_revision - 1)
    if restored_publication is None:
        raise HTTPException(409, "되돌릴 수정 이력이 없습니다.")
    _publication_store.write(song_id, restored_publication)
    updated = _song_store.get(song_id)
    return _public(updated or song)


@router.post("/{song_id}/restore")
def restore_original(song_id: str) -> dict:
    song = _require_song(song_id)
    snapshot_revision = _snapshot_before_edit(song)
    current = _song_store.checkout_current(song_id)
    original = _song_store.checkout_original(song_id)
    try:
        shutil.copy2(original, current)
        apply_publication_layout(
            current,
            title=song["title"],
            settings=_publication_store.read(song_id),
        )
        updated = _commit_score_change(song_id, current)
    except Exception as exc:
        _discard_snapshot(song_id, snapshot_revision)
        raise HTTPException(422, f"원본 악보를 복원하지 못했습니다: {exc}") from exc
    return _public(updated)


@router.get("/{song_id}/structure")
def get_structure(song_id: str) -> dict:
    song = _require_song(song_id)
    return {"song": _public(song), **structure_summary(_song_store.checkout_current(song_id))}


@router.patch("/{song_id}/notes/{note_id}/structure")
def patch_note_structure(song_id: str, note_id: str, payload: NoteStructurePatch) -> dict:
    patch = payload.model_dump(exclude_unset=True)
    if not patch:
        return {"song": _public(_require_song(song_id)), "note_id": note_id}

    def operation(_song: dict, path: Path) -> dict:
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
    def operation(_song: dict, path: Path) -> dict:
        new_id = insert_note(
            path,
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
    def operation(_song: dict, path: Path) -> dict:
        delete_note(path, note_id)
        return {"deleted_note_id": note_id}

    return _mutate(song_id, operation)


@router.post("/{song_id}/measures/{measure_index}/insert-after")
def insert_score_measure(song_id: str, measure_index: int) -> dict:
    def operation(_song: dict, path: Path) -> dict:
        return {"measure_index": insert_measure(path, measure_index)}

    return _mutate(song_id, operation)


@router.delete("/{song_id}/measures/{measure_index}")
def delete_score_measure(song_id: str, measure_index: int) -> dict:
    def operation(_song: dict, path: Path) -> dict:
        delete_measure(path, measure_index)
        return {"deleted_measure_index": measure_index}

    return _mutate(song_id, operation)


@router.patch("/{song_id}/measures/{measure_index}/signature")
def patch_measure_signature(song_id: str, measure_index: int, payload: SignaturePatch) -> dict:
    patch = payload.model_dump(exclude_unset=True)
    if not patch:
        return {"song": _public(_require_song(song_id)), "measure_index": measure_index}

    def operation(_song: dict, path: Path) -> dict:
        set_measure_signature(
            path,
            measure_index,
            fifths=patch.get("key_fifths"),
            mode=patch.get("key_mode"),
            beats=patch.get("beats"),
            beat_type=patch.get("beat_type"),
        )
        return {"measure_index": measure_index}

    return _mutate(song_id, operation)


@router.post("/{song_id}/export")
def build_exports(song_id: str, payload: ExportRequest | None = None) -> dict:
    song = _require_song(song_id)
    requested = set((payload or ExportRequest()).formats)
    needs_renderer = bool(requested & {"pdf", "midi", "parts"})
    settings = runtime_settings()
    musescore = _resolve_musescore(settings) if needs_renderer else None
    if needs_renderer and not musescore:
        raise HTTPException(
            409,
            "MuseScore 4 실행 파일을 찾을 수 없습니다. Setup에서 경로를 지정하세요.",
        )

    _song_store.clear_exports(song_id)
    export_dir = _song_store.export_dir(song_id)
    env = _musescore_env()
    cache_root = cache_dir() / "export"
    cache_root.mkdir(parents=True, exist_ok=True)

    try:
        with tempfile.TemporaryDirectory(prefix=f"{song_id}-", dir=cache_root) as raw_temp:
            temp_dir = Path(raw_temp)
            source = temp_dir / "score.musicxml"
            source.write_text(_song_store.score_xml(song_id), encoding="utf-8")
            apply_publication_layout(
                source,
                title=song["title"],
                settings=_publication_store.read(song_id),
            )

            if "musicxml" in requested:
                shutil.copy2(source, export_dir / "score.musicxml")
            if "pdf" in requested:
                run_command(musescore, ["-o", export_dir / "score.pdf", source], env=env)
            if "midi" in requested:
                run_command(musescore, ["-o", export_dir / "score.mid", source], env=env)
            if "parts" in requested:
                parts_dir = export_dir / "parts"
                parts_dir.mkdir(parents=True, exist_ok=True)
                for part in list_score_parts(source):
                    slug = str(part["slug"])
                    part_xml = parts_dir / f"{slug}.musicxml"
                    part_pdf = parts_dir / f"{slug}.pdf"
                    extract_part_musicxml(source, str(part["part_id"]), part_xml)
                    run_command(musescore, ["-o", part_pdf, part_xml], env=env)
    except (CommandError, ValueError) as exc:
        _song_store.clear_exports(song_id)
        raise HTTPException(500, f"MuseScore export failed: {exc}") from exc

    updated = _song_store.get(song_id) or song
    files = {
        kind: f"/api/songs/{song_id}/files/{kind}"
        for kind in ("musicxml", "pdf", "midi")
        if kind in requested
    }
    return {
        "song": _public(updated),
        "files": files,
        "parts": _part_exports(updated),
        "formats": sorted(requested),
    }


@router.get("/{song_id}/files/parts/{slug}/{kind}")
def download_part_file(song_id: str, slug: str, kind: str) -> FileResponse:
    _require_song(song_id)
    current = _song_store.checkout_current(song_id)
    allowed = {str(part["slug"]) for part in list_score_parts(current)}
    if slug not in allowed:
        raise HTTPException(404, "Unknown score part")
    if kind == "pdf":
        path = _song_store.export_root / song_id / "parts" / f"{slug}.pdf"
        media_type = "application/pdf"
    elif kind == "musicxml":
        path = _song_store.export_root / song_id / "parts" / f"{slug}.musicxml"
        media_type = "application/vnd.recordare.musicxml+xml"
    else:
        raise HTTPException(404, "Unknown part artifact")
    if not path.exists():
        raise HTTPException(404, "Part export is not available. Run final export first.")
    return FileResponse(path, media_type=media_type, filename=path.name)


@router.get("/{song_id}/files/{kind}")
def download_song_file(song_id: str, kind: str):
    song = _require_song(song_id)
    export_dir = _song_store.export_root / song_id
    if kind == "musicxml":
        exported = export_dir / "score.musicxml"
        if exported.exists():
            return FileResponse(
                exported,
                media_type="application/vnd.recordare.musicxml+xml",
                filename=f"{song['title']}.musicxml",
            )
        return Response(
            content=_song_store.score_xml(song_id),
            media_type="application/vnd.recordare.musicxml+xml",
            headers={"Content-Disposition": 'attachment; filename="score.musicxml"'},
        )
    if kind == "pdf":
        path = export_dir / "score.pdf"
        media_type = "application/pdf"
        filename = f"{song['title']}.pdf"
    elif kind == "midi":
        path = export_dir / "score.mid"
        media_type = "audio/midi"
        filename = f"{song['title']}.mid"
    else:
        raise HTTPException(404, "Unknown song artifact")
    if not path.exists():
        raise HTTPException(404, "Export file is not available. Run final export first.")
    return FileResponse(path, media_type=media_type, filename=filename)

from __future__ import annotations

import platform
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .config import Settings
from .job_store import JobStore
from .musicxml_editor import (
    MusicXMLEditError,
    score_summary,
    set_score_title,
    snapshot,
    undo_last,
    update_note,
)
from .pipeline import _resolve_musescore
from .runner import CommandError, run_command
from .settings_store import SettingsStore
from .song_store import SongStore

router = APIRouter(prefix="/api/songs", tags=["songs"])
_song_store = SongStore()
_job_store = JobStore()
_settings_store = SettingsStore()


class SongMetadataPatch(BaseModel):
    title: str | None = None
    artist: str | None = None


class NotePatch(BaseModel):
    step: str | None = None
    alter: int | None = None
    octave: int | None = None
    lyric: str | None = None


def _runtime_settings() -> Settings:
    saved = _settings_store.read()
    defaults = Settings()
    return Settings(
        muscriptor_cmd=saved.get("muscriptor_cmd") or defaults.muscriptor_cmd,
        demucs_cmd=saved.get("demucs_cmd") or defaults.demucs_cmd,
        whisperx_cmd=saved.get("whisperx_cmd") or defaults.whisperx_cmd,
        yt_dlp_cmd=saved.get("yt_dlp_cmd") or defaults.yt_dlp_cmd,
        musescore_cmd=saved.get("musescore_cmd") or defaults.musescore_cmd,
        muscriptor_model=defaults.muscriptor_model,
        whisperx_model=defaults.whisperx_model,
    )


def _sync() -> None:
    _song_store.sync_completed_jobs(_job_store.list(limit=5000))


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
    }


def _require_song(song_id: str) -> dict:
    _sync()
    song = _song_store.get(song_id)
    if not song:
        raise HTTPException(404, "Song not found")
    return song


def _snapshot_before_edit(song: dict) -> None:
    snapshot(
        Path(song["current_musicxml"]),
        _song_store.revision_dir(song["song_id"]),
        int(song.get("revision", 1)),
    )


@router.get("")
def list_songs() -> dict:
    _sync()
    return {"songs": [_public(song) for song in _song_store.list()]}


@router.get("/{song_id}")
def get_song(song_id: str) -> dict:
    return _public(_require_song(song_id))


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
    except Exception as exc:
        raise HTTPException(422, f"Could not parse MusicXML: {exc}") from exc
    return {
        "song": _public(song),
        **summary,
    }


@router.patch("/{song_id}")
def update_song(song_id: str, payload: SongMetadataPatch) -> dict:
    song = _require_song(song_id)
    if payload.title is not None and payload.title.strip() != song["title"]:
        _snapshot_before_edit(song)
        set_score_title(Path(song["current_musicxml"]), payload.title.strip() or "제목 없는 곡")
        _song_store.bump_revision(song_id)
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
    _snapshot_before_edit(song)
    patch = payload.model_dump(exclude_unset=True)
    try:
        update_note(Path(song["current_musicxml"]), note_id, patch)
    except MusicXMLEditError as exc:
        revision_path = _song_store.revision_dir(song_id) / f"rev-{int(song.get('revision', 1)):04d}.musicxml"
        revision_path.unlink(missing_ok=True)
        raise HTTPException(422, str(exc)) from exc
    updated = _song_store.bump_revision(song_id)
    return {"song": _public(updated or song), "note_id": note_id}


@router.post("/{song_id}/undo")
def undo_song(song_id: str) -> dict:
    song = _require_song(song_id)
    restored = undo_last(
        Path(song["current_musicxml"]),
        _song_store.revision_dir(song_id),
    )
    if restored is None:
        raise HTTPException(409, "되돌릴 수정 이력이 없습니다.")
    updated = _song_store.set_revision(song_id, int(song.get("revision", 1)) - 1)
    return _public(updated or song)


@router.post("/{song_id}/restore")
def restore_original(song_id: str) -> dict:
    song = _require_song(song_id)
    _snapshot_before_edit(song)
    original = Path(song["original_musicxml"])
    current = Path(song["current_musicxml"])
    if not original.exists():
        raise HTTPException(404, "Original MusicXML is missing")
    shutil.copy2(original, current)
    updated = _song_store.bump_revision(song_id)
    return _public(updated or song)


@router.post("/{song_id}/export")
def build_exports(song_id: str) -> dict:
    song = _require_song(song_id)
    settings = _runtime_settings()
    musescore = _resolve_musescore(settings)
    if not musescore:
        raise HTTPException(409, "MuseScore 4 실행 파일을 찾을 수 없습니다. Setup에서 경로를 지정하세요.")

    current = Path(song["current_musicxml"])
    export_dir = _song_store.export_dir(song_id)
    pdf = export_dir / "score.pdf"
    midi = export_dir / "score.mid"
    env = None
    if platform.system() == "Linux":
        env = {"QT_QPA_PLATFORM": "offscreen", "MU_QT_QPA_PLATFORM": "offscreen"}
    try:
        run_command(musescore, ["-o", pdf, current], env=env)
        run_command(musescore, ["-o", midi, current], env=env)
    except CommandError as exc:
        raise HTTPException(500, f"MuseScore export failed: {exc}") from exc

    return {
        "song": _public(_song_store.get(song_id) or song),
        "files": {
            "musicxml": f"/api/songs/{song_id}/files/musicxml",
            "pdf": f"/api/songs/{song_id}/files/pdf",
            "midi": f"/api/songs/{song_id}/files/midi",
        },
    }


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

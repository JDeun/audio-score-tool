from __future__ import annotations

import shutil
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from threading import Thread

from fastapi import APIRouter, File, HTTPException, UploadFile

from .job_admission import JobCapacityError, reserve_job
from .job_store import JobStore
from .notation_backend import NotationBackendError, midi_to_musicxml, musicxml_to_midi
from .paths import jobs_dir
from .upload_storage import UploadStorageError, persist_stream_atomic

router = APIRouter(tags=["score-import"])
_store = JobStore()
_MUSICXML_EXTENSIONS = {".musicxml", ".xml"}
_MIDI_EXTENSIONS = {".mid", ".midi"}
_ALLOWED = _MUSICXML_EXTENSIONS | _MIDI_EXTENSIONS
_MAX_NOTATION_BYTES = 64 * 1024 * 1024
_FORBIDDEN_XML_MARKERS = (b"<!DOCTYPE", b"<!ENTITY")


def _validate_musicxml_file(path: Path) -> None:
    size = path.stat().st_size
    if size <= 0:
        raise ValueError("MusicXML 파일이 비어 있습니다.")
    if size > _MAX_NOTATION_BYTES:
        raise ValueError("MusicXML 파일은 64 MiB를 초과할 수 없습니다.")
    raw = path.read_bytes()
    upper = raw.upper()
    if any(marker in upper for marker in _FORBIDDEN_XML_MARKERS):
        raise ValueError("DOCTYPE/ENTITY가 포함된 MusicXML은 가져올 수 없습니다.")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError(f"MusicXML을 파싱할 수 없습니다: {exc}") from exc
    if root.tag.rsplit("}", 1)[-1] not in {"score-partwise", "score-timewise"}:
        raise ValueError("유효한 MusicXML score 문서가 아닙니다.")


def _cleanup_reservation(job_id: str, job_dir: Path) -> None:
    shutil.rmtree(job_dir, ignore_errors=True)
    _store.delete(job_id)


def _worker(job_id: str, source: Path, suffix: str) -> None:
    output_dir = jobs_dir() / job_id / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    _store.update(job_id, status="running", stage="notation:import", progress=20)
    warnings: list[str] = []
    try:
        musicxml = output_dir / "score.musicxml"
        midi: Path | None = None
        if suffix in _MIDI_EXTENSIONS:
            midi = output_dir / "score.mid"
            shutil.copy2(source, midi)
            midi_to_musicxml(midi, musicxml)
            _validate_musicxml_file(musicxml)
        else:
            _validate_musicxml_file(source)
            shutil.copy2(source, musicxml)
            midi = output_dir / "score.mid"
            try:
                musicxml_to_midi(musicxml, midi)
            except NotationBackendError as exc:
                midi = None
                warnings.append(f"MusicXML은 가져왔지만 MIDI 보조 자산 생성은 건너뛰었습니다: {exc}")

        result = {
            "musicxml": str(musicxml),
            "warnings": warnings,
            "import_format": "midi" if suffix in _MIDI_EXTENSIONS else "musicxml",
        }
        if midi is not None and midi.is_file():
            result["midi"] = str(midi)
        _store.update(
            job_id,
            status="done",
            stage="complete",
            progress=100,
            result=result,
        )
    except (OSError, ValueError, NotationBackendError) as exc:
        _store.update(job_id, status="failed", stage="failed", error=str(exc))
    except Exception as exc:
        _store.update(job_id, status="failed", stage="failed", error=f"악보 가져오기 실패: {exc}")


@router.post("/api/import/notation", status_code=202)
async def import_notation(file: UploadFile = File(...)) -> dict:
    filename = file.filename or "score"
    suffix = Path(filename).suffix.lower()
    if suffix not in _ALLOWED:
        raise HTTPException(415, "MusicXML(.musicxml/.xml) 또는 MIDI(.mid/.midi)만 가져올 수 있습니다.")

    job_id = uuid.uuid4().hex
    try:
        reserve_job(
            _store,
            job_id,
            kind="notation-import",
            status="queued",
            stage="uploading",
            progress=0,
            filename=filename,
            preset="direct-notation-import",
            skip_lyrics=True,
        )
    except JobCapacityError as exc:
        raise HTTPException(429, str(exc)) from exc

    job_dir = jobs_dir() / job_id
    source = job_dir / f"source{suffix}"
    try:
        job_dir.mkdir(parents=True, exist_ok=False)
        persist_stream_atomic(file.file, source)
        if source.stat().st_size > _MAX_NOTATION_BYTES:
            raise HTTPException(413, "악보 파일은 64 MiB를 초과할 수 없습니다.")
        if suffix in _MUSICXML_EXTENSIONS:
            _validate_musicxml_file(source)
        _store.update(job_id, stage="queued")
    except UploadStorageError as exc:
        _cleanup_reservation(job_id, job_dir)
        raise HTTPException(exc.status_code, str(exc)) from exc
    except HTTPException:
        _cleanup_reservation(job_id, job_dir)
        raise
    except ValueError as exc:
        _cleanup_reservation(job_id, job_dir)
        raise HTTPException(422, str(exc)) from exc
    except Exception:
        _cleanup_reservation(job_id, job_dir)
        raise

    thread = Thread(target=_worker, args=(job_id, source, suffix), daemon=True)
    try:
        thread.start()
    except RuntimeError as exc:
        _store.update(
            job_id,
            status="failed",
            stage="failed",
            error=f"백그라운드 작업을 시작하지 못했습니다: {exc}",
        )
        raise HTTPException(503, "백그라운드 악보 가져오기 작업을 시작하지 못했습니다.") from exc
    return {"job_id": job_id, "status": "queued", "kind": "notation-import"}

from __future__ import annotations

import re
import shutil
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from threading import Thread

from fastapi import APIRouter, File, HTTPException, UploadFile

from . import runtime_services as runtime
from .job_admission import JobCapacityError, reserve_job
from .job_store import JobStore
from .notation_backend import NotationBackendError, midi_to_musicxml, musicxml_to_midi
from .omr import OMRImportError, normalize_musicxml
from .paths import jobs_dir
from .upload_storage import UploadStorageError, persist_stream_atomic

router = APIRouter(tags=["score-import"])
_store = JobStore()
_MUSICXML_EXTENSIONS = {".musicxml", ".xml", ".mxl"}
_MIDI_EXTENSIONS = {".mid", ".midi"}
_ALLOWED = _MUSICXML_EXTENSIONS | _MIDI_EXTENSIONS
_MAX_NOTATION_BYTES = 64 * 1024 * 1024
_FORBIDDEN_XML_MARKERS = (b"<!DOCTYPE", b"<!ENTITY")
# Only trusted music21-generated scores may have a standard DTD stripped.
# An uploaded MusicXML/MXL source must continue to reject all DOCTYPE/ENTITY.
_GENERATED_DOCTYPE = re.compile(rb"<!DOCTYPE\s+score-partwise\b[^>\[]*>", re.IGNORECASE)


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


def _normalize_generated_musicxml(path: Path) -> None:
    """Strip a top-level DTD only from an internally generated MIDI conversion.

    Reject external entities, internal DTD subsets and non-header DOCTYPE tags;
    never call this normalization on a directly uploaded XML or MXL document.
    """
    raw = path.read_bytes()
    if b"<!ENTITY" in raw.upper():
        raise ValueError("Generated MusicXML contains an unsafe ENTITY declaration.")
    if b"<!DOCTYPE" in raw.upper():
        matches = list(_GENERATED_DOCTYPE.finditer(raw))
        if len(matches) != 1:
            raise ValueError("Generated MusicXML contains an unsupported DOCTYPE declaration.")
        match = matches[0]
        prefix = raw[:match.start()]
        if re.fullmatch(rb'\s*(?:<\?xml[^>]*\?>\s*)?', prefix) is None:
            raise ValueError("Generated MusicXML DOCTYPE is not at the document header.")
        normalized = raw[:match.start()] + raw[match.end():]
        if b"<!DOCTYPE" in normalized.upper():
            raise ValueError("Generated MusicXML still contains a DOCTYPE declaration.")
        path.write_bytes(normalized)
    _validate_musicxml_file(path)


def _cleanup_reservation(job_id: str, job_dir: Path) -> None:
    shutil.rmtree(job_dir, ignore_errors=True)
    _store.delete(job_id)


class _ImportCancelled(Exception):
    """A queued or in-progress notation conversion was cancelled."""


def _worker(job_id: str, source: Path, suffix: str) -> None:
    cancel_event = runtime._register_cancel_event(job_id)

    def check_cancelled() -> None:
        if cancel_event.is_set():
            raise _ImportCancelled()

    try:
        check_cancelled()
        output_dir = jobs_dir() / job_id / "outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        _store.update(job_id, status="running", stage="notation:import", progress=20)
        check_cancelled()
        warnings: list[str] = []
        musicxml = output_dir / "score.musicxml"
        midi: Path | None = None
        if suffix in _MIDI_EXTENSIONS:
            midi = output_dir / "score.mid"
            shutil.copy2(source, midi)
            check_cancelled()
            midi_to_musicxml(midi, musicxml)
            check_cancelled()
            _normalize_generated_musicxml(musicxml)
        else:
            if suffix == ".mxl":
                normalize_musicxml(source, musicxml)
                check_cancelled()
                _validate_musicxml_file(musicxml)
            else:
                _validate_musicxml_file(source)
                check_cancelled()
                shutil.copy2(source, musicxml)
            check_cancelled()
            midi = output_dir / "score.mid"
            try:
                musicxml_to_midi(musicxml, midi)
            except NotationBackendError as exc:
                midi = None
                warnings.append(f"MusicXML은 가져왔지만 MIDI 보조 자산 생성은 건너뛰었습니다: {exc}")

        # Converters are synchronous; their output must never become a
        # successful canonical Song if the user cancelled while they ran.
        check_cancelled()
        result = {
            "musicxml": str(musicxml),
            "warnings": warnings,
            "import_format": "midi" if suffix in _MIDI_EXTENSIONS else "musicxml",
        }
        if midi is not None and midi.is_file():
            result["midi"] = str(midi)
        # No cancel can race between the final check and the done commit.
        with runtime._runtime_lock:
            check_cancelled()
            _store.update(job_id, status="done", stage="complete", progress=100, result=result)
    except _ImportCancelled:
        _store.update(job_id, status="cancelled", stage="cancelled")
    except (OSError, ValueError, NotationBackendError, OMRImportError) as exc:
        if cancel_event.is_set():
            _store.update(job_id, status="cancelled", stage="cancelled")
        else:
            _store.update(job_id, status="failed", stage="failed", error=str(exc))
    except Exception as exc:
        if cancel_event.is_set():
            _store.update(job_id, status="cancelled", stage="cancelled")
        else:
            _store.update(job_id, status="failed", stage="failed", error=f"악보 가져오기 실패: {exc}")
    finally:
        runtime._unregister_cancel_event(job_id)

@router.post("/api/import/notation", status_code=202)
async def import_notation(file: UploadFile = File(...)) -> dict:
    filename = file.filename or "score"
    suffix = Path(filename).suffix.lower()
    if suffix not in _ALLOWED:
        raise HTTPException(415, "MusicXML(.musicxml/.xml/.mxl) 또는 MIDI(.mid/.midi)만 가져올 수 있습니다.")

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
        persist_stream_atomic(file.file, source, max_bytes=_MAX_NOTATION_BYTES)
        if suffix in _MUSICXML_EXTENSIONS - {".mxl"}:
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

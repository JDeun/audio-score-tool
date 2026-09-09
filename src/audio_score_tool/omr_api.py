from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from threading import Thread

from fastapi import APIRouter, File, HTTPException, UploadFile

from .config import Settings
from .job_store import JobStore
from .omr import OMRImportCancelled, audiveris_status, transcribe_score
from .paths import jobs_dir, song_assets_dir
from .runtime_settings import runtime_settings
from .upload_storage import UploadStorageError, persist_stream_atomic

router = APIRouter(tags=["omr"])
_store = JobStore()
_ALLOWED = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}
_MAX_OMR_SOURCE_BYTES = 256 * 1024 * 1024


def _worker(job_id: str, source: Path, settings: Settings) -> None:
    _store.update(job_id, status="running", stage="omr:recognizing", progress=15)
    try:
        artifacts = transcribe_score(
            source,
            jobs_dir() / job_id / "outputs",
            command=settings.audiveris_cmd,
        )
        asset = song_assets_dir() / job_id / f"original-score{source.suffix.lower()}"
        asset.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, asset)
        _store.update(
            job_id,
            status="done",
            stage="complete",
            progress=100,
            result={
                "musicxml": str(artifacts.musicxml_path),
                "source_score": str(asset),
                "omr_provider": artifacts.provider,
                "warnings": [
                    "OMR 결과는 원본 악보와 대조 검토하는 것을 권장합니다. 검증 메뉴에서 구조적 오류를 확인하세요."
                ],
            },
        )
    except OMRImportCancelled:
        _store.update(job_id, status="cancelled", stage="cancelled")
    except Exception as exc:
        _store.update(job_id, status="failed", stage="failed", error=str(exc))


@router.get("/api/omr/status")
def get_omr_status() -> dict:
    settings = runtime_settings()
    return audiveris_status(settings.audiveris_cmd)


@router.post("/api/import/score", status_code=202)
async def import_score(file: UploadFile = File(...)) -> dict:
    filename = file.filename or "score"
    suffix = Path(filename).suffix.lower()
    if suffix not in _ALLOWED:
        raise HTTPException(
            415,
            "PDF 또는 악보 이미지(PNG/JPG/TIFF/BMP)만 가져올 수 있습니다.",
        )
    settings = runtime_settings()
    if not audiveris_status(settings.audiveris_cmd)["ready"]:
        raise HTTPException(
            503,
            "OMR 구성요소가 준비되어 있지 않습니다. Setup Center에서 OMR 구성요소 상태를 확인하세요.",
        )

    job_id = uuid.uuid4().hex
    job_dir = jobs_dir() / job_id
    job_dir.mkdir(parents=True, exist_ok=False)
    source = job_dir / f"source-score{suffix}"
    try:
        persist_stream_atomic(file.file, source, max_bytes=_MAX_OMR_SOURCE_BYTES)
    except UploadStorageError as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(exc.status_code, str(exc)) from exc

    try:
        _store.create(
            job_id,
            kind="omr",
            status="queued",
            stage="queued",
            progress=0,
            filename=filename,
            preset="omr-audiveris",
            skip_lyrics=True,
        )
    except Exception:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise
    try:
        Thread(target=_worker, args=(job_id, source, settings), daemon=True).start()
    except RuntimeError as exc:
        _store.update(job_id, status="failed", stage="failed", error=str(exc))
        raise HTTPException(503, "백그라운드 OMR 작업을 시작하지 못했습니다.") from exc
    return {"job_id": job_id, "status": "queued", "kind": "omr"}

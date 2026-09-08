from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from threading import Thread

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from . import api as base_api
from .job_admission import JobCapacityError, reserve_job
from .paths import jobs_dir
from .upload_storage import UploadStorageError, persist_stream_atomic

router = APIRouter(tags=["uploads-v2"])


def _cleanup_failed_job(job_id: str, path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
    base_api._store.delete(job_id)


def _start_worker_or_fail(job_id: str, thread: Thread) -> None:
    try:
        thread.start()
    except RuntimeError as exc:
        # Keep the uploaded input so the failed Job remains retryable, but never leave
        # a worker-start failure looking like a permanently queued transcription.
        base_api._store.update(
            job_id,
            status="failed",
            stage="failed",
            error=f"백그라운드 작업을 시작하지 못했습니다: {exc}",
        )
        raise HTTPException(503, "백그라운드 작업을 시작하지 못했습니다. 작업 내역에서 다시 시도하세요.") from exc


def _reserve_or_429(job_id: str, **values) -> None:
    try:
        reserve_job(base_api._store, job_id, **values)
    except JobCapacityError as exc:
        raise HTTPException(429, str(exc)) from exc


@router.post("/api/jobs", status_code=202)
async def create_job_v2(
    file: UploadFile = File(...),
    language: str | None = Form(None),
    skip_lyrics: bool = Form(False),
    preset: str = Form("auto"),
    muscriptor_model: str | None = Form(None),
    whisperx_model: str | None = Form(None),
) -> dict:
    try:
        selected = base_api.resolve_preset(preset)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    resolved_muscriptor = muscriptor_model or selected.muscriptor_model
    resolved_whisperx = whisperx_model or selected.whisperx_model
    suffix = base_api._validate_upload(file.filename, base_api._AUDIO_EXTENSIONS, "audio")

    job_id = uuid.uuid4().hex
    _reserve_or_429(
        job_id,
        status="queued",
        stage="uploading",
        progress=0,
        filename=file.filename,
        language=language,
        skip_lyrics=skip_lyrics,
        preset=preset,
        muscriptor_model=resolved_muscriptor,
        whisperx_model=resolved_whisperx,
    )
    job_dir = jobs_dir() / job_id
    try:
        job_dir.mkdir(parents=True, exist_ok=False)
        audio = job_dir / f"input{suffix}"
        persist_stream_atomic(file.file, audio)
        base_api._store.update(job_id, stage="queued")
    except UploadStorageError as exc:
        _cleanup_failed_job(job_id, job_dir)
        raise HTTPException(exc.status_code, str(exc)) from exc
    except Exception:
        _cleanup_failed_job(job_id, job_dir)
        raise

    thread = Thread(
        target=base_api._worker,
        args=(
            job_id,
            audio,
            language,
            skip_lyrics,
            resolved_muscriptor,
            resolved_whisperx,
        ),
        daemon=True,
    )
    _start_worker_or_fail(job_id, thread)
    return {"job_id": job_id, "status": "queued"}


@router.post("/api/benchmarks", status_code=202)
async def create_benchmark_v2(
    file: UploadFile = File(...),
    reference_midi: UploadFile | None = File(None),
    language: str | None = Form(None),
    profile: str = Form("all"),
) -> dict:
    try:
        base_api.configs_for_profile(profile)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    audio_suffix = base_api._validate_upload(file.filename, base_api._AUDIO_EXTENSIONS, "audio")
    if reference_midi is not None:
        base_api._validate_upload(reference_midi.filename, base_api._MIDI_EXTENSIONS, "reference MIDI")

    job_id = uuid.uuid4().hex
    _reserve_or_429(
        job_id,
        kind="benchmark",
        status="queued",
        stage="uploading",
        progress=0,
        filename=file.filename,
        language=language,
        preset=profile,
    )
    job_dir = jobs_dir() / job_id
    reference_path: Path | None = None

    try:
        job_dir.mkdir(parents=True, exist_ok=False)
        audio = job_dir / f"input{audio_suffix}"
        persist_stream_atomic(file.file, audio)
        if reference_midi is not None:
            reference_path = job_dir / "reference.mid"
            persist_stream_atomic(reference_midi.file, reference_path)
        base_api._store.update(job_id, stage="queued")
    except UploadStorageError as exc:
        _cleanup_failed_job(job_id, job_dir)
        raise HTTPException(exc.status_code, str(exc)) from exc
    except Exception:
        _cleanup_failed_job(job_id, job_dir)
        raise

    thread = Thread(
        target=base_api._benchmark_worker,
        args=(job_id, audio, reference_path, language, profile),
        daemon=True,
    )
    _start_worker_or_fail(job_id, thread)
    return {"job_id": job_id, "status": "queued", "kind": "benchmark"}

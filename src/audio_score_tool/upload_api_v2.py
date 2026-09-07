from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from threading import Thread

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from . import api as base_api
from .paths import jobs_dir
from .upload_storage import UploadStorageError, persist_stream_atomic

router = APIRouter(tags=["uploads-v2"])


def _cleanup_failed_job_dir(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


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
    job_dir = jobs_dir() / job_id
    job_dir.mkdir(parents=True, exist_ok=False)
    audio = job_dir / f"input{suffix}"
    try:
        persist_stream_atomic(file.file, audio)
        base_api._store.create(
            job_id,
            status="queued",
            stage="queued",
            progress=0,
            filename=file.filename,
            language=language,
            skip_lyrics=skip_lyrics,
            preset=preset,
            muscriptor_model=resolved_muscriptor,
            whisperx_model=resolved_whisperx,
        )
    except UploadStorageError as exc:
        _cleanup_failed_job_dir(job_dir)
        raise HTTPException(exc.status_code, str(exc)) from exc
    except Exception:
        _cleanup_failed_job_dir(job_dir)
        raise

    Thread(
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
    ).start()
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
    job_dir = jobs_dir() / job_id
    job_dir.mkdir(parents=True, exist_ok=False)
    audio = job_dir / f"input{audio_suffix}"
    reference_path: Path | None = None

    try:
        persist_stream_atomic(file.file, audio)
        if reference_midi is not None:
            reference_path = job_dir / "reference.mid"
            persist_stream_atomic(reference_midi.file, reference_path)
        base_api._store.create(
            job_id,
            kind="benchmark",
            status="queued",
            stage="queued",
            progress=0,
            filename=file.filename,
            language=language,
            preset=profile,
        )
    except UploadStorageError as exc:
        _cleanup_failed_job_dir(job_dir)
        raise HTTPException(exc.status_code, str(exc)) from exc
    except Exception:
        _cleanup_failed_job_dir(job_dir)
        raise

    Thread(
        target=base_api._benchmark_worker,
        args=(job_id, audio, reference_path, language, profile),
        daemon=True,
    ).start()
    return {"job_id": job_id, "status": "queued", "kind": "benchmark"}

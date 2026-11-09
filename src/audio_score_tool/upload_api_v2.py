from __future__ import annotations

import shutil
import uuid
from dataclasses import replace
from pathlib import Path
from threading import Thread

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from . import api as base_api
from .config import packaged_runtime
from .demucs_runtime import managed_demucs_repository
from .job_admission import JobCapacityError, reserve_job
from .job_transcription_settings import transcription_job_selection
from .paths import jobs_dir
from .preflight_v2 import preflight
from .presets import resolve_job_models
from .runner import command_exists
from .runtime_settings import runtime_settings
from .score_requests import needs_stem_separation, validate_score_mode
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
    score_mode: str = Form("full"),
    auto_enrich: bool = Form(True),
    muscriptor_model: str | None = Form(None),
    whisperx_model: str | None = Form(None),
) -> dict:
    try:
        defaults = runtime_settings()
        score_mode = validate_score_mode(score_mode)
        resolved_muscriptor, resolved_whisperx = resolve_job_models(
            preset,
            selected_muscriptor_model=defaults.muscriptor_model,
            selected_whisperx_model=defaults.whisperx_model,
            muscriptor_override=muscriptor_model,
            whisperx_override=whisperx_model,
        )
        selected = replace(
            defaults, muscriptor_model=resolved_muscriptor,
            whisperx_model=resolved_whisperx,
        )
        selection = transcription_job_selection(selected)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    suffix = base_api._validate_upload(file.filename, base_api._AUDIO_EXTENSIONS, "audio")
    readiness = preflight(selected, require_lyrics=False)
    if not readiness["ok"]:
        raise HTTPException(
            503,
            "채보 필수 실행환경이 준비되지 않았습니다: " + ", ".join(readiness["missing"]),
        )

    if needs_stem_separation(score_mode) and (
        not command_exists(defaults.demucs_cmd)
        or (packaged_runtime() and managed_demucs_repository(defaults) is None)
    ):
        raise HTTPException(503, "선택 악기 채보에는 Demucs가 필요합니다. 구성요소 상태에서 설치하세요.")

    job_id = uuid.uuid4().hex
    _reserve_or_429(
        job_id,
        status="queued",
        stage="uploading",
        progress=0,
        filename=file.filename,
        source_kind="local",
        language=language,
        skip_lyrics=skip_lyrics,
        preset=preset,
        score_mode=score_mode,
        auto_enrich=auto_enrich,
        **selection,
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

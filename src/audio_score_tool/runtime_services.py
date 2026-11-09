from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from threading import Event, Lock, Thread

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from .benchmark import configs_for_profile, run_benchmark_matrix
from .config import packaged_runtime
from .desktop_utils import reveal_in_file_manager
from .devices import detect_device_plan
from .job_store import JobStore
from .paths import jobs_dir
from .pipeline import PipelineCancelled
from .pipeline_v2 import transcribe
from .preflight_v2 import preflight
from .presets import list_presets, resolve_job_models
from .runtime_settings import runtime_settings
from .score_requests import validate_score_mode
from .settings_store import SettingsStore
from .setup_info import setup_instructions
from .source_metadata_hints import resolve_source_lookup_hints
from .system_status import storage_status
from .youtube import (
    YouTubeSourceCancelled,
    YouTubeSourceError,
    download_youtube_audio,
    inspect_youtube,
    validate_youtube_url,
    youtube_tool_status,
)

app = FastAPI(title="AudioScoreTool", version="0.4.0")
_ALLOWED_ORIGINS = {
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
}

app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(_ALLOWED_ORIGINS),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def protect_local_mutations(request: Request, call_next):
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        if origin is not None and origin not in _ALLOWED_ORIGINS:
            return JSONResponse({"detail": "Untrusted origin"}, status_code=403)
    return await call_next(request)


_AUDIO_EXTENSIONS = {
    ".wav",
    ".mp3",
    ".flac",
    ".m4a",
    ".aac",
    ".ogg",
    ".opus",
    ".webm",
}
_MIDI_EXTENSIONS = {".mid", ".midi"}


def _validate_upload(filename: str | None, allowed: set[str], label: str) -> str:
    name = filename or ""
    suffix = Path(name).suffix.lower()
    if suffix not in allowed:
        choices = ", ".join(sorted(allowed))
        raise HTTPException(415, f"Unsupported {label} format. Allowed: {choices}")
    return suffix


_store = JobStore()
_settings_store = SettingsStore()


class LocalIdentificationPreference(BaseModel):
    enabled: bool = False


def get_local_identification_preference() -> dict:
    enabled = _settings_store.read().get("auto_local_identification_enabled") == "true"
    return {
        "enabled": enabled,
        "scope": "local_embedded_tags_only",
        "external_requests": False,
    }


def update_local_identification_preference(payload: LocalIdentificationPreference) -> dict:
    _settings_store.update({
        "auto_local_identification_enabled": "true" if payload.enabled else "false",
    })
    return get_local_identification_preference()


class ToolPathSettings(BaseModel):
    muscriptor_cmd: str | None = None
    demucs_cmd: str | None = None
    whisperx_cmd: str | None = None
    yt_dlp_cmd: str | None = None


class YouTubeInspectRequest(BaseModel):
    url: str


class YouTubeJobRequest(BaseModel):
    url: str
    authorized: bool = False
    language: str | None = None
    skip_lyrics: bool = False
    preset: str = "auto"
    score_mode: str = "full"
    auto_enrich: bool = True
    muscriptor_model: str | None = None
    whisperx_model: str | None = None


def _runtime_settings(
    *,
    muscriptor_model: str | None = None,
    whisperx_model: str = "small",
):
    return runtime_settings(
        muscriptor_model=muscriptor_model,
        whisperx_model=whisperx_model,
        store=_settings_store,
    )


_cancel_events: dict[str, Event] = {}
_runtime_lock = Lock()
_inference_lock = Lock()


def _register_cancel_event(job_id: str) -> Event:
    cancel_event = Event()
    with _runtime_lock:
        # The user may cancel a queued Job before its Thread is scheduled.
        # Serialize registration with cancel_job's persisted status update so
        # that an early cancellation is never lost.
        job = _store.get(job_id)
        if job is not None and job["status"] == "cancelling":
            cancel_event.set()
        _cancel_events[job_id] = cancel_event
    return cancel_event


def _unregister_cancel_event(job_id: str) -> None:
    with _runtime_lock:
        _cancel_events.pop(job_id, None)


def _acquire_inference_slot(job_id: str, cancel_event: Event) -> bool:
    _store.update(job_id, status="queued", stage="queued")
    while not cancel_event.is_set():
        if _inference_lock.acquire(timeout=0.25):
            if cancel_event.is_set():
                _inference_lock.release()
                return False
            return True
    return False


def _execute_transcription(
    job_id: str,
    audio: Path,
    language: str | None,
    skip_lyrics: bool,
    muscriptor_model: str,
    whisperx_model: str,
    cancel_event: Event,
    *,
    source_progress_floor: int = 0,
) -> None:
    if not _acquire_inference_slot(job_id, cancel_event):
        _store.update(job_id, status="cancelled", stage="cancelled")
        return

    _store.update(job_id, status="running", stage="starting")

    def report_progress(stage: str, percent: int) -> None:
        if source_progress_floor:
            mapped = source_progress_floor + round(
                percent * (100 - source_progress_floor) / 100
            )
        else:
            mapped = percent
        _store.update(job_id, stage=stage, progress=min(100, mapped))

    completed_for_enrichment: dict | None = None
    try:
        stored = _store.get(job_id) or {}
        mode = validate_score_mode(stored.get("score_mode", "full"))
        settings = _runtime_settings(
            muscriptor_model=muscriptor_model,
            whisperx_model=whisperx_model,
        )
        hint = (
            resolve_source_lookup_hints(
                stored.get("source_kind"), stored.get("filename"),
                audio_path=audio if stored.get("source_kind") == "local" else None,
            )
            if stored.get("auto_enrich") is True else None
        )
        api_lyrics = None
        api_warning = None
        # Explicit user opt-in: query only the title/artist hint. Never send
        # original audio to an external service. API lookup comes BEFORE ASR.
        if hint and not skip_lyrics and getattr(settings, "usage_mode", "personal") == "personal":
            from .enrichment import EnrichmentError, fetch_lrclib_lyrics

            try:
                api_lyrics = fetch_lrclib_lyrics(
                    hint.title, hint.artist, album=hint.album,
                )
            except EnrichmentError as exc:
                api_warning = (
                    f"External lyric API unavailable ({type(exc).__name__}); "
                    "falling back to WhisperX transcription."
                )
        extra_args = {}
        if mode != "full":
            extra_args["score_mode"] = mode
        if api_lyrics is not None:
            extra_args["reference_lyrics"] = api_lyrics
        result = transcribe(
            audio,
            jobs_dir() / job_id / "outputs",
            language=language,
            skip_lyrics=skip_lyrics,
            settings=settings,
            progress=report_progress,
            cancel_event=cancel_event,
            **extra_args,
        )
        if api_warning:
            result.warnings.append(api_warning)
        if cancel_event.is_set():
            _store.update(job_id, status="cancelled", stage="cancelled")
        else:
            _store.update(
                job_id,
                status="done",
                stage="complete",
                progress=100,
                result=result.as_dict(),
            )
            if stored.get("auto_enrich") is True:
                completed_for_enrichment = _store.get(job_id)
                if completed_for_enrichment is not None:
                    # Internal, in-memory query evidence only; no audio bytes
                    # and no filename parsing during remote metadata lookup.
                    completed_for_enrichment["_source_lookup_hints"] = hint
    except PipelineCancelled:
        _store.update(job_id, status="cancelled", stage="cancelled")
    except Exception as exc:
        _store.update(job_id, status="failed", stage="failed", error=str(exc))
    finally:
        _inference_lock.release()

    # The score is already finished and its inference lock is released.
    # Enrichment is best-effort; no remote API error can turn a valid Song
    # into a failed transcription or overwrite a newer user revision.
    if completed_for_enrichment is not None:
        try:
            from .automatic_song_enrichment import enrich_completed_job

            enrich_completed_job(completed_for_enrichment)
        except Exception:
            # Song editing can always retry explicit enrichment from the UI.
            # Avoid logging raw media, provider credentials or lyric content.
            pass


def _worker(
    job_id: str,
    audio: Path,
    language: str | None,
    skip_lyrics: bool,
    muscriptor_model: str,
    whisperx_model: str,
) -> None:
    cancel_event = _register_cancel_event(job_id)
    try:
        _execute_transcription(
            job_id,
            audio,
            language,
            skip_lyrics,
            muscriptor_model,
            whisperx_model,
            cancel_event,
        )
    finally:
        _unregister_cancel_event(job_id)


def _youtube_worker(
    job_id: str,
    url: str,
    language: str | None,
    skip_lyrics: bool,
    muscriptor_model: str,
    whisperx_model: str,
) -> None:
    cancel_event = _register_cancel_event(job_id)
    job_dir = jobs_dir() / job_id
    try:
        _store.update(
            job_id,
            status="running",
            stage="starting",
            progress=3,
        )
        audio, metadata = download_youtube_audio(
            url,
            job_dir,
            settings=_runtime_settings(
                muscriptor_model=muscriptor_model,
                whisperx_model=whisperx_model,
            ),
            cancel_event=cancel_event,
        )
        if cancel_event.is_set():
            _store.update(job_id, status="cancelled", stage="cancelled")
            return

        _store.update(
            job_id,
            filename=metadata.title,
            source_kind="youtube",
            stage="queued",
            progress=10,
        )
        _execute_transcription(
            job_id,
            audio,
            language,
            skip_lyrics,
            muscriptor_model,
            whisperx_model,
            cancel_event,
            source_progress_floor=10,
        )
    except YouTubeSourceCancelled:
        _store.update(job_id, status="cancelled", stage="cancelled")
    except YouTubeSourceError as exc:
        _store.update(job_id, status="failed", stage="failed", error=str(exc))
    except Exception as exc:
        _store.update(job_id, status="failed", stage="failed", error=str(exc))
    finally:
        _unregister_cancel_event(job_id)


def _benchmark_worker(
    job_id: str,
    audio: Path,
    reference_midi: Path | None,
    language: str | None,
    profile: str,
) -> None:
    cancel_event = _register_cancel_event(job_id)

    if not _acquire_inference_slot(job_id, cancel_event):
        _store.update(job_id, status="cancelled", stage="cancelled")
        _unregister_cancel_event(job_id)
        return

    _store.update(job_id, status="running", stage="benchmark:starting")
    output_root = jobs_dir() / job_id / "benchmark"
    try:
        results = run_benchmark_matrix(
            audio,
            output_root,
            language=language,
            configs=configs_for_profile(profile),
            reference_midi=reference_midi,
            base_settings=_runtime_settings(),
            progress=lambda stage, percent: _store.update(
                job_id,
                stage=stage,
                progress=percent,
            ),
            cancel_event=cancel_event,
        )
        if cancel_event.is_set():
            _store.update(job_id, status="cancelled", stage="cancelled")
        else:
            _store.update(
                job_id,
                status="done",
                stage="complete",
                progress=100,
                result={
                    "benchmark_json": str(output_root / "benchmark.json"),
                    "benchmark_csv": str(output_root / "benchmark.csv"),
                    "runs": len(results),
                    "successful_runs": sum(1 for item in results if item.success),
                },
            )
    except Exception as exc:
        _store.update(job_id, status="failed", stage="failed", error=str(exc))
    finally:
        _inference_lock.release()
        _unregister_cancel_event(job_id)


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "packaged_runtime": packaged_runtime(),
        "usage_mode": getattr(_runtime_settings(), "usage_mode", "commercial"),
        "device_plan": detect_device_plan().as_dict(),
        "preflight": preflight(_runtime_settings()),
        "presets": list_presets(),
        "data_dir": str(jobs_dir().parent),
        "system": storage_status(),
        "youtube": youtube_tool_status(_runtime_settings()),
    }


@app.get("/api/setup")
def setup() -> dict:
    return {
        "packaged_runtime": packaged_runtime(),
        "preflight": preflight(_runtime_settings()),
        "instructions": setup_instructions(),
        "tool_paths": _settings_store.read(),
        "youtube": youtube_tool_status(_runtime_settings()),
    }


@app.get("/api/settings")
def get_settings() -> dict:
    return {
        "tool_paths": _settings_store.read(),
        "data_dir": str(jobs_dir().parent),
        "system": storage_status(),
    }


@app.get("/api/storage")
def get_storage() -> dict:
    return storage_status()


@app.post("/api/storage/cleanup")
def cleanup_storage(keep: int = 30) -> dict:
    keep = max(0, min(keep, 1000))
    jobs = _store.list(limit=5000)
    removable = [
        job
        for job in jobs[keep:]
        if job["status"] not in {"queued", "running", "cancelling"}
    ]
    deleted = 0
    for job in removable:
        path = jobs_dir() / job["job_id"]
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
        if _store.delete(job["job_id"]):
            deleted += 1
    return {
        "deleted_jobs": deleted,
        "kept_jobs": keep,
        "system": storage_status(),
    }


@app.put("/api/settings/tool-paths")
def update_tool_paths(payload: ToolPathSettings) -> dict:
    if packaged_runtime():
        raise HTTPException(
            409,
            "패키지 앱은 사용자 지정 실행 명령을 허용하지 않습니다. Setup Center에서 앱 관리형 구성요소를 확인하세요.",
        )
    saved = _settings_store.update(payload.model_dump())
    return {
        "tool_paths": saved,
        "preflight": preflight(_runtime_settings()),
        "youtube": youtube_tool_status(_runtime_settings()),
    }


@app.get("/api/presets")
def presets() -> dict:
    return list_presets()


@app.get("/api/sources/youtube/status")
def youtube_status() -> dict:
    return youtube_tool_status(_runtime_settings())


@app.post("/api/sources/youtube/inspect")
def inspect_youtube_source(payload: YouTubeInspectRequest) -> dict:
    try:
        return inspect_youtube(payload.url, settings=_runtime_settings()).as_dict()
    except YouTubeSourceError as exc:
        raise HTTPException(422, str(exc)) from exc


def _job_with_artifacts(job: dict) -> dict:
    # Resolve availability at request time so stale paths and optional outputs do
    # not become broken download buttons in the desktop client.
    from .job_artifact_api_v2 import available_job_artifacts

    return {**job, "available_artifacts": available_job_artifacts(job)}


@app.get("/api/jobs")
def list_jobs(limit: int = 50) -> dict:
    return {"jobs": [_job_with_artifacts(job) for job in _store.list(limit=limit)]}


@app.post("/api/jobs", status_code=202)
async def create_job(
    file: UploadFile = File(...),
    language: str | None = Form(None),
    skip_lyrics: bool = Form(False),
    preset: str = Form("auto"),
    muscriptor_model: str | None = Form(None),
    whisperx_model: str | None = Form(None),
) -> dict:
    try:
        defaults = _runtime_settings()
        resolved_muscriptor, resolved_whisperx = resolve_job_models(
            preset,
            selected_muscriptor_model=defaults.muscriptor_model,
            selected_whisperx_model=defaults.whisperx_model,
            muscriptor_override=muscriptor_model,
            whisperx_override=whisperx_model,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    suffix = _validate_upload(file.filename, _AUDIO_EXTENSIONS, "audio")
    job_id = uuid.uuid4().hex
    job_dir = jobs_dir() / job_id
    job_dir.mkdir(parents=True, exist_ok=False)
    audio = job_dir / f"input{suffix}"

    with audio.open("wb") as handle:
        shutil.copyfileobj(file.file, handle)

    _store.create(
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
    Thread(
        target=_worker,
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


@app.post("/api/jobs/youtube", status_code=202)
def create_youtube_job(payload: YouTubeJobRequest) -> dict:
    try:
        url = validate_youtube_url(payload.url)
        defaults = _runtime_settings()
        # Personal offline practice is not a public redistribution workflow.
        # Commercial mode retains an explicit rights confirmation; automated
        # release QA has a separate, stricter reviewed-source contract.
        if getattr(defaults, "usage_mode", None) != "personal" and not payload.authorized:
            raise HTTPException(
                422,
                "Confirm that you are authorized to process this content before importing it.",
            )
        resolved_muscriptor, resolved_whisperx = resolve_job_models(
            payload.preset,
            selected_muscriptor_model=defaults.muscriptor_model,
            selected_whisperx_model=defaults.whisperx_model,
            muscriptor_override=payload.muscriptor_model,
            whisperx_override=payload.whisperx_model,
        )
    except (YouTubeSourceError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc

    job_id = uuid.uuid4().hex
    job_dir = jobs_dir() / job_id
    job_dir.mkdir(parents=True, exist_ok=False)
    _store.create(
        job_id,
        status="queued",
        stage="queued",
        progress=0,
        filename="YouTube import",
        source_kind="youtube",
        language=payload.language,
        skip_lyrics=payload.skip_lyrics,
        preset=payload.preset,
        muscriptor_model=resolved_muscriptor,
        whisperx_model=resolved_whisperx,
    )
    Thread(
        target=_youtube_worker,
        args=(
            job_id,
            url,
            payload.language,
            payload.skip_lyrics,
            resolved_muscriptor,
            resolved_whisperx,
        ),
        daemon=True,
    ).start()
    return {"job_id": job_id, "status": "queued", "source": "youtube"}


@app.post("/api/benchmarks", status_code=202)
async def create_benchmark(
    file: UploadFile = File(...),
    reference_midi: UploadFile | None = File(None),
    language: str | None = Form(None),
    profile: str = Form("all"),
) -> dict:
    try:
        configs_for_profile(profile)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    job_id = uuid.uuid4().hex
    job_dir = jobs_dir() / job_id
    job_dir.mkdir(parents=True, exist_ok=False)

    audio_suffix = _validate_upload(file.filename, _AUDIO_EXTENSIONS, "audio")
    audio = job_dir / f"input{audio_suffix}"
    with audio.open("wb") as handle:
        shutil.copyfileobj(file.file, handle)

    reference_path: Path | None = None
    if reference_midi is not None:
        _validate_upload(reference_midi.filename, _MIDI_EXTENSIONS, "reference MIDI")
        reference_path = job_dir / "reference.mid"
        with reference_path.open("wb") as handle:
            shutil.copyfileobj(reference_midi.file, handle)

    _store.create(
        job_id,
        kind="benchmark",
        status="queued",
        stage="queued",
        progress=0,
        filename=file.filename,
        language=language,
        preset=profile,
    )
    Thread(
        target=_benchmark_worker,
        args=(job_id, audio, reference_path, language, profile),
        daemon=True,
    ).start()
    return {"job_id": job_id, "status": "queued", "kind": "benchmark"}


@app.post("/api/jobs/{job_id}/retry", status_code=202)
def retry_job(job_id: str) -> dict:
    source = _store.get(job_id)
    if not source:
        raise HTTPException(404, "Job not found")
    if source["status"] in {"queued", "running", "cancelling"}:
        raise HTTPException(409, "Running jobs cannot be retried.")

    source_dir = jobs_dir() / job_id
    audio_candidates = sorted(source_dir.glob("input.*"))
    if not audio_candidates:
        raise HTTPException(404, "Original input audio is missing.")

    new_id = uuid.uuid4().hex
    target_dir = jobs_dir() / new_id
    target_dir.mkdir(parents=True, exist_ok=False)
    audio = target_dir / audio_candidates[0].name
    shutil.copy2(audio_candidates[0], audio)

    if source.get("kind") == "benchmark":
        reference_source = source_dir / "reference.mid"
        reference_target = target_dir / "reference.mid" if reference_source.exists() else None
        if reference_target is not None:
            shutil.copy2(reference_source, reference_target)
        profile = source.get("preset") or "all"
        _store.create(
            new_id,
            kind="benchmark",
            status="queued",
            stage="queued",
            progress=0,
            filename=source.get("filename"),
            language=source.get("language"),
            preset=profile,
        )
        Thread(
            target=_benchmark_worker,
            args=(new_id, audio, reference_target, source.get("language"), profile),
            daemon=True,
        ).start()
    else:
        _store.create(
            new_id,
            kind="transcription",
            status="queued",
            stage="queued",
            progress=0,
            filename=source.get("filename"),
            language=source.get("language"),
            skip_lyrics=source.get("skip_lyrics", False),
            preset=source.get("preset"),
            muscriptor_model=source.get("muscriptor_model"),
            whisperx_model=source.get("whisperx_model"),
        )
        Thread(
            target=_worker,
            args=(
                new_id,
                audio,
                source.get("language"),
                source.get("skip_lyrics", False),
                source.get("muscriptor_model") or "medium",
                source.get("whisperx_model") or "small",
            ),
            daemon=True,
        ).start()

    return {"job_id": new_id, "status": "queued", "retried_from": job_id}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = _store.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return _job_with_artifacts(job)


@app.post("/api/jobs/{job_id}/cancel", status_code=202)
def cancel_job(job_id: str) -> dict:
    job = _store.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job["status"] not in {"queued", "running", "cancelling"}:
        return {"job_id": job_id, "status": job["status"], "cancelled": False}

    with _runtime_lock:
        # Check again under the same lock used for worker registration.
        current = _store.get(job_id)
        if current is None:
            raise HTTPException(404, "Job not found")
        if current["status"] not in {"queued", "running", "cancelling"}:
            return {"job_id": job_id, "status": current["status"], "cancelled": False}
        _store.update(job_id, status="cancelling", stage="cancelling")
        event = _cancel_events.get(job_id)
        if event is not None:
            event.set()
    return {"job_id": job_id, "status": "cancelling", "cancelled": True}


@app.post("/api/jobs/{job_id}/reveal")
def reveal_job(job_id: str) -> dict:
    job = _store.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    path = jobs_dir() / job_id
    if not path.exists():
        raise HTTPException(404, "Job directory is missing")
    try:
        reveal_in_file_manager(path)
    except OSError as exc:
        raise HTTPException(500, f"Could not open file manager: {exc}") from exc
    return {"job_id": job_id, "revealed": True}


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str) -> dict:
    job = _store.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job["status"] in {"queued", "running", "cancelling"}:
        raise HTTPException(409, "Cancel the running job before deleting it.")

    path = jobs_dir() / job_id
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    _store.delete(job_id)
    return {"job_id": job_id, "deleted": True}


@app.get("/api/jobs/{job_id}/files/{kind}")
def download(job_id: str, kind: str) -> FileResponse:
    job = _store.get(job_id)
    if not job or job.get("status") != "done" or not job.get("result"):
        raise HTTPException(404, "Completed job not found")
    result = job["result"]

    mapping = {
        "midi": result.get("midi"),
        "musicxml": result.get("lyric_musicxml") or result.get("musicxml"),
        "pdf": result.get("pdf"),
        "transcript": result.get("transcript_json"),
        "benchmark_json": result.get("benchmark_json"),
        "benchmark_csv": result.get("benchmark_csv"),
    }
    path_str = mapping.get(kind)
    if not path_str:
        raise HTTPException(404, f"Artifact not available: {kind}")
    path = Path(path_str)
    if not path.exists():
        raise HTTPException(404, "Artifact file is missing")
    return FileResponse(path, filename=path.name)


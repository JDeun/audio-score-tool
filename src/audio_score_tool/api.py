from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from threading import Event, Lock, Thread

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .benchmark import configs_for_profile, run_benchmark_matrix
from .config import Settings
from .desktop_utils import reveal_in_file_manager
from .devices import detect_device_plan
from .job_store import JobStore
from .paths import jobs_dir
from .pipeline import PipelineCancelled, preflight, transcribe
from .presets import list_presets, resolve_preset
from .settings_store import SettingsStore
from .setup_info import setup_instructions
from .system_status import storage_status

app = FastAPI(title="AudioScoreTool", version="0.3.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "tauri://localhost",
        "http://tauri.localhost",
        "https://tauri.localhost",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_store = JobStore()
_settings_store = SettingsStore()


class ToolPathSettings(BaseModel):
    muscriptor_cmd: str | None = None
    demucs_cmd: str | None = None
    whisperx_cmd: str | None = None
    musescore_cmd: str | None = None


def _runtime_settings(
    *,
    muscriptor_model: str = "medium",
    whisperx_model: str = "small",
) -> Settings:
    saved = _settings_store.read()
    defaults = Settings()
    return Settings(
        muscriptor_cmd=saved.get("muscriptor_cmd") or defaults.muscriptor_cmd,
        demucs_cmd=saved.get("demucs_cmd") or defaults.demucs_cmd,
        whisperx_cmd=saved.get("whisperx_cmd") or defaults.whisperx_cmd,
        musescore_cmd=saved.get("musescore_cmd") or defaults.musescore_cmd,
        muscriptor_model=muscriptor_model,
        whisperx_model=whisperx_model,
    )
_cancel_events: dict[str, Event] = {}
_runtime_lock = Lock()
_inference_lock = Lock()


def _acquire_inference_slot(job_id: str, cancel_event: Event) -> bool:
    _store.update(job_id, status="queued", stage="queued")
    while not cancel_event.is_set():
        if _inference_lock.acquire(timeout=0.25):
            if cancel_event.is_set():
                _inference_lock.release()
                return False
            return True
    return False


def _worker(
    job_id: str,
    audio: Path,
    language: str | None,
    skip_lyrics: bool,
    muscriptor_model: str,
    whisperx_model: str,
) -> None:
    cancel_event = Event()
    with _runtime_lock:
        _cancel_events[job_id] = cancel_event

    if not _acquire_inference_slot(job_id, cancel_event):
        _store.update(job_id, status="cancelled", stage="cancelled")
        with _runtime_lock:
            _cancel_events.pop(job_id, None)
        return

    _store.update(job_id, status="running", stage="starting")
    try:
        result = transcribe(
            audio,
            jobs_dir() / job_id / "outputs",
            language=language,
            skip_lyrics=skip_lyrics,
            settings=_runtime_settings(
                muscriptor_model=muscriptor_model,
                whisperx_model=whisperx_model,
            ),
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
                result=result.as_dict(),
            )
    except PipelineCancelled:
        _store.update(job_id, status="cancelled", stage="cancelled")
    except Exception as exc:
        _store.update(job_id, status="failed", stage="failed", error=str(exc))
    finally:
        _inference_lock.release()
        with _runtime_lock:
            _cancel_events.pop(job_id, None)


def _benchmark_worker(
    job_id: str,
    audio: Path,
    reference_midi: Path | None,
    language: str | None,
    profile: str,
) -> None:
    cancel_event = Event()
    with _runtime_lock:
        _cancel_events[job_id] = cancel_event

    if not _acquire_inference_slot(job_id, cancel_event):
        _store.update(job_id, status="cancelled", stage="cancelled")
        with _runtime_lock:
            _cancel_events.pop(job_id, None)
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
        with _runtime_lock:
            _cancel_events.pop(job_id, None)


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "device_plan": detect_device_plan().as_dict(),
        "preflight": preflight(_runtime_settings()),
        "presets": list_presets(),
        "data_dir": str(jobs_dir().parent),
        "system": storage_status(),
    }


@app.get("/api/setup")
def setup() -> dict:
    return {
        "preflight": preflight(_runtime_settings()),
        "instructions": setup_instructions(),
        "tool_paths": _settings_store.read(),
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
        job for job in jobs[keep:]
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
    saved = _settings_store.update(payload.model_dump())
    return {
        "tool_paths": saved,
        "preflight": preflight(_runtime_settings()),
    }


@app.get("/api/presets")
def presets() -> dict:
    return list_presets()


@app.get("/api/jobs")
def list_jobs(limit: int = 50) -> dict:
    return {"jobs": _store.list(limit=limit)}


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
        selected = resolve_preset(preset)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    resolved_muscriptor = muscriptor_model or selected.muscriptor_model
    resolved_whisperx = whisperx_model or selected.whisperx_model

    job_id = uuid.uuid4().hex
    job_dir = jobs_dir() / job_id
    job_dir.mkdir(parents=True, exist_ok=False)
    suffix = Path(file.filename or "audio.wav").suffix or ".wav"
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

    audio_suffix = Path(file.filename or "audio.wav").suffix or ".wav"
    audio = job_dir / f"input{audio_suffix}"
    with audio.open("wb") as handle:
        shutil.copyfileobj(file.file, handle)

    reference_path: Path | None = None
    if reference_midi is not None:
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
    return job


@app.post("/api/jobs/{job_id}/cancel", status_code=202)
def cancel_job(job_id: str) -> dict:
    job = _store.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job["status"] not in {"queued", "running", "cancelling"}:
        return {"job_id": job_id, "status": job["status"], "cancelled": False}

    with _runtime_lock:
        event = _cancel_events.get(job_id)
        if event is not None:
            event.set()
    _store.update(job_id, status="cancelling", stage="cancelling")
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


def run() -> None:
    uvicorn.run("audio_score_tool.api:app", host="127.0.0.1", port=8080, reload=False)


if __name__ == "__main__":
    run()

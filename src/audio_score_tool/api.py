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

from .config import Settings
from .devices import detect_device_plan
from .job_store import JobStore
from .paths import jobs_dir
from .pipeline import PipelineCancelled, preflight, transcribe
from .presets import list_presets, resolve_preset
from .settings_store import SettingsStore
from .setup_info import setup_instructions

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

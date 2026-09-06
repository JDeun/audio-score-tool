from __future__ import annotations

import shutil
import tempfile
import uuid
from pathlib import Path
from threading import Lock, Thread
from typing import Any

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .devices import detect_device_plan
from .pipeline import preflight, transcribe

app = FastAPI(title="AudioScoreTool", version="0.2.0")
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

_jobs: dict[str, dict[str, Any]] = {}
_lock = Lock()
_upload_root = Path(tempfile.gettempdir()) / "audio-score-tool"
_upload_root.mkdir(parents=True, exist_ok=True)


def _set_job(job_id: str, **values: Any) -> None:
    with _lock:
        _jobs.setdefault(job_id, {}).update(values)


def _worker(job_id: str, audio: Path, language: str | None, skip_lyrics: bool) -> None:
    _set_job(job_id, status="running")
    try:
        result = transcribe(
            audio,
            _upload_root / job_id / "outputs",
            language=language,
            skip_lyrics=skip_lyrics,
            progress=lambda stage, percent: _set_job(
                job_id,
                stage=stage,
                progress=percent,
            ),
        )
        _set_job(job_id, status="done", result=result.as_dict())
    except Exception as exc:
        _set_job(job_id, status="failed", error=str(exc))


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "device_plan": detect_device_plan().as_dict(),
        "preflight": preflight(),
    }


@app.post("/api/jobs", status_code=202)
async def create_job(
    file: UploadFile = File(...),
    language: str | None = Form(None),
    skip_lyrics: bool = Form(False),
) -> dict:
    job_id = uuid.uuid4().hex
    job_dir = _upload_root / job_id
    job_dir.mkdir(parents=True, exist_ok=False)
    suffix = Path(file.filename or "audio.wav").suffix or ".wav"
    audio = job_dir / f"input{suffix}"

    with audio.open("wb") as handle:
        shutil.copyfileobj(file.file, handle)

    _set_job(
        job_id,
        status="queued",
        stage="queued",
        progress=0,
        filename=file.filename,
        language=language,
        skip_lyrics=skip_lyrics,
    )
    Thread(
        target=_worker,
        args=(job_id, audio, language, skip_lyrics),
        daemon=True,
    ).start()
    return {"job_id": job_id, "status": "queued"}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        return {"job_id": job_id, **job}


@app.get("/api/jobs/{job_id}/files/{kind}")
def download(job_id: str, kind: str) -> FileResponse:
    with _lock:
        job = _jobs.get(job_id)
        if not job or job.get("status") != "done":
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

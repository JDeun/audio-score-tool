from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from . import api as base_api
from .paths import jobs_dir

router = APIRouter(tags=["job-artifacts-v2"])


def _managed_job_file(job_id: str, raw_path: str | None) -> Path | None:
    if not raw_path:
        return None
    root = (jobs_dir() / job_id).resolve()
    try:
        candidate = Path(raw_path).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


@router.get("/api/jobs/{job_id}/files/{kind}")
def download_job_artifact_v2(job_id: str, kind: str) -> FileResponse:
    job = base_api._store.get(job_id)
    if not job or job.get("status") != "done" or not job.get("result"):
        raise HTTPException(404, "Completed job not found")
    result = job["result"]
    if not isinstance(result, dict):
        raise HTTPException(404, "Completed job result is unavailable")

    mapping = {
        "midi": result.get("midi"),
        "musicxml": result.get("lyric_musicxml") or result.get("musicxml"),
        "pdf": result.get("pdf"),
        "transcript": result.get("transcript_json"),
        "benchmark_json": result.get("benchmark_json"),
        "benchmark_csv": result.get("benchmark_csv"),
    }
    if kind not in mapping:
        raise HTTPException(404, f"Artifact not available: {kind}")
    path = _managed_job_file(job_id, mapping[kind])
    if path is None:
        raise HTTPException(404, "Artifact is missing or outside the managed Job workspace")
    return FileResponse(path, filename=path.name)

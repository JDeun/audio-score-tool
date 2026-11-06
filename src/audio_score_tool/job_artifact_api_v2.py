from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from . import api as base_api
from .paths import jobs_dir

router = APIRouter(tags=["job-artifacts-v2"])


def _managed_job_file(job_id: str, raw_path: object) -> Path | None:
    if not isinstance(raw_path, (str, Path)) or not str(raw_path).strip():
        return None
    root = (jobs_dir() / job_id).resolve()
    try:
        candidate = Path(raw_path).expanduser().resolve()
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _artifact_candidates(result: dict) -> dict[str, tuple[object, ...]]:
    return {
        "midi": (result.get("midi"),),
        # The lyric overlay is preferred when present, but a deleted/invalid overlay
        # must not hide the still-usable canonical transcription score.
        "musicxml": (result.get("lyric_musicxml"), result.get("musicxml")),
        "pdf": (result.get("pdf"),),
        "transcript": (result.get("transcript_json"),),
        "benchmark_json": (result.get("benchmark_json"),),
        "benchmark_csv": (result.get("benchmark_csv"),),
    }


def _artifact_path(job_id: str, result: dict, kind: str) -> Path | None:
    for raw_path in _artifact_candidates(result).get(kind, ()):
        path = _managed_job_file(job_id, raw_path)
        if path is not None:
            return path
    return None


def available_job_artifacts(job: dict) -> list[str]:
    """Advertise only artifacts the authenticated download route can return now."""
    if job.get("status") != "done" or not isinstance(job.get("result"), dict):
        return []
    job_id = str(job.get("job_id") or "")
    if not job_id:
        return []
    result = job["result"]
    return [
        kind
        for kind in _artifact_candidates(result)
        if _artifact_path(job_id, result, kind) is not None
    ]


@router.get("/api/jobs/{job_id}/files/{kind}")
def download_job_artifact_v2(job_id: str, kind: str) -> FileResponse:
    job = base_api._store.get(job_id)
    if not job or job.get("status") != "done" or not job.get("result"):
        raise HTTPException(404, "Completed job not found")
    result = job["result"]
    if not isinstance(result, dict):
        raise HTTPException(404, "Completed job result is unavailable")

    if kind not in _artifact_candidates(result):
        raise HTTPException(404, f"Artifact not available: {kind}")
    path = _artifact_path(job_id, result, kind)
    if path is None:
        raise HTTPException(404, "Artifact is missing or outside the managed Job workspace")
    return FileResponse(path, filename=path.name)

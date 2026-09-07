from __future__ import annotations

import shutil

from fastapi import APIRouter

from . import api as base_api
from .paths import jobs_dir
from .song_store_v2 import SongStoreV2
from .song_tombstones import SongTombstoneStore
from .system_status import storage_status

router = APIRouter(tags=["storage-v2"])
_songs = SongStoreV2()
_tombstones = SongTombstoneStore()


@router.post("/api/storage/cleanup")
def cleanup_storage_v2(keep: int = 30) -> dict:
    keep = max(0, min(keep, 1000))
    jobs = base_api._store.list(limit=5000)

    # Promote completed score-producing jobs to canonical SQLite before their transient
    # workspaces can be considered for deletion. An intentionally deleted song is
    # excluded by its tombstone and may have its old Job workspace reclaimed.
    promotable = [
        job
        for job in jobs
        if job.get("status") == "done"
        and job.get("kind") != "benchmark"
        and not _tombstones.contains(job.get("job_id"))
    ]
    _songs.sync_completed_jobs(promotable)

    removable = [
        job
        for job in jobs[keep:]
        if job.get("status") not in {"queued", "running", "cancelling"}
    ]
    deleted = 0
    protected = 0
    for job in removable:
        job_id = str(job.get("job_id") or "")
        if not job_id:
            continue
        if (
            job.get("status") == "done"
            and job.get("kind") != "benchmark"
            and not _tombstones.contains(job_id)
            and _songs.get_by_job(job_id) is None
        ):
            # A successful score job is not disposable until canonical ingestion is
            # confirmed; retain it so a transient parse/storage problem is recoverable.
            protected += 1
            continue

        path = jobs_dir() / job_id
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
        if base_api._store.delete(job_id):
            deleted += 1

    return {
        "deleted_jobs": deleted,
        "protected_uningested_jobs": protected,
        "kept_jobs": keep,
        "system": storage_status(),
    }

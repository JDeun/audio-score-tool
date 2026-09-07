from __future__ import annotations

import shutil

from fastapi import APIRouter

from . import api as base_api
from .paths import jobs_dir, song_assets_dir
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
    orphan_assets_removed = 0
    for job in removable:
        job_id = str(job.get("job_id") or "")
        if not job_id:
            continue
        canonical_song = _songs.get_by_job(job_id)
        if (
            job.get("status") == "done"
            and job.get("kind") != "benchmark"
            and not _tombstones.contains(job_id)
            and canonical_song is None
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
            # Failed/cancelled jobs may have preserved source audio before inference
            # failed. Remove that managed asset only when no canonical Song owns it.
            if canonical_song is None:
                asset_dir = song_assets_dir() / job_id
                if asset_dir.exists():
                    shutil.rmtree(asset_dir, ignore_errors=True)
                    if not asset_dir.exists():
                        orphan_assets_removed += 1

    return {
        "deleted_jobs": deleted,
        "protected_uningested_jobs": protected,
        "orphan_asset_dirs_removed": orphan_assets_removed,
        "kept_jobs": keep,
        "system": storage_status(),
    }

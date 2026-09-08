from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"expected block not found in {path}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "src/audio_score_tool/song_api_v2.py",
    "from .job_store import JobStore\n",
    "from .job_ingestion import reconcile_completed_jobs\nfrom .job_store import JobStore\n",
)
replace_once(
    "src/audio_score_tool/song_api_v2.py",
    "def _sync() -> None:\n    jobs = [\n        job\n        for job in _job_store.list(limit=5000)\n        if not _tombstones.contains(job.get(\"job_id\"))\n    ]\n    _song_store.sync_completed_jobs(jobs)\n",
    "def _sync() -> None:\n    # Reconcile one bounded page on ordinary API reads. Completed jobs are ordered by\n    # a durable `(updated_at, job_id)` cursor, so cost does not grow with job history.\n    reconcile_completed_jobs(\n        job_store=_job_store,\n        song_store=_song_store,\n        tombstones=_tombstones,\n        batch_size=200,\n        max_batches=1,\n    )\n",
)
replace_once(
    "src/audio_score_tool/api_ext.py",
    "from .job_lifecycle_api_v2 import router as job_lifecycle_router\n",
    "from .job_ingestion import full_reconcile_completed_jobs\nfrom .job_lifecycle_api_v2 import router as job_lifecycle_router\n",
)
replace_once(
    "src/audio_score_tool/api_ext.py",
    "from .song_mutation_lock import SongMutationSerializationMiddleware\n",
    "from .song_mutation_lock import SongMutationSerializationMiddleware\nfrom .song_store_v2 import SongStoreV2\nfrom .song_tombstones import SongTombstoneStore\n",
)
replace_once(
    "src/audio_score_tool/api_ext.py",
    "    diagnostics = recover_startup_state(job_store=base_api._store)\n    _startup_diagnostics.clear()\n",
    "    diagnostics = recover_startup_state(job_store=base_api._store)\n    ingestion = full_reconcile_completed_jobs(\n        job_store=base_api._store,\n        song_store=SongStoreV2(),\n        tombstones=SongTombstoneStore(),\n    )\n    diagnostics[\"job_ingestion\"] = ingestion\n    _startup_diagnostics.clear()\n",
)

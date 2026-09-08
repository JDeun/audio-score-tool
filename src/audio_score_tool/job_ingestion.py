from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .job_store import JobStore
from .paths import database_path
from .song_store_v2 import SongStoreV2
from .song_tombstones import SongTombstoneStore
from .sqlite_runtime import connect_sqlite


@dataclass(frozen=True)
class IngestionCursor:
    updated_at: str = ""
    job_id: str = ""


class JobIngestionState:
    """Durable cursor for idempotent Job -> Song reconciliation."""

    KEY = "completed-job-to-song-v1"

    def __init__(self, path: Path | None = None):
        self.path = path or database_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self.path, row_factory=True)

    def _init(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ingestion_state (
                    key TEXT PRIMARY KEY,
                    cursor_updated_at TEXT NOT NULL,
                    cursor_job_id TEXT NOT NULL
                )
                """
            )

    def read(self) -> IngestionCursor:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT cursor_updated_at, cursor_job_id FROM ingestion_state WHERE key=?",
                (self.KEY,),
            ).fetchone()
        if not row:
            return IngestionCursor()
        return IngestionCursor(str(row["cursor_updated_at"]), str(row["cursor_job_id"]))

    def write(self, cursor: IngestionCursor) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ingestion_state(key, cursor_updated_at, cursor_job_id)
                VALUES(?,?,?)
                ON CONFLICT(key) DO UPDATE SET
                    cursor_updated_at=excluded.cursor_updated_at,
                    cursor_job_id=excluded.cursor_job_id
                """,
                (self.KEY, cursor.updated_at, cursor.job_id),
            )

    def reset(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM ingestion_state WHERE key=?", (self.KEY,))


def reconcile_completed_jobs(
    *,
    job_store: JobStore,
    song_store: SongStoreV2,
    tombstones: SongTombstoneStore,
    state: JobIngestionState | None = None,
    batch_size: int = 200,
    max_batches: int | None = 1,
) -> dict[str, int | str]:
    """Incrementally ingest completed jobs without scanning the whole job table.

    Cursor advancement is ordered by `(updated_at, job_id)`, making restart behavior
    deterministic. `SongStoreV2.sync_completed_jobs` remains the idempotency boundary
    through its unique `job_id` constraint.
    """

    state = state or JobIngestionState(job_store.path)
    cursor = state.read()
    scanned = 0
    created = 0
    batches = 0

    while max_batches is None or batches < max_batches:
        jobs = job_store.list_completed_after(
            cursor_updated_at=cursor.updated_at,
            cursor_job_id=cursor.job_id,
            limit=batch_size,
        )
        if not jobs:
            break
        batches += 1
        scanned += len(jobs)
        eligible = [job for job in jobs if not tombstones.contains(job.get("job_id"))]
        created += song_store.sync_completed_jobs(eligible)
        last = jobs[-1]
        cursor = IngestionCursor(str(last["updated_at"]), str(last["job_id"]))
        state.write(cursor)
        if len(jobs) < batch_size:
            break

    return {
        "scanned": scanned,
        "created": created,
        "batches": batches,
        "cursor_updated_at": cursor.updated_at,
        "cursor_job_id": cursor.job_id,
    }


def full_reconcile_completed_jobs(
    *,
    job_store: JobStore,
    song_store: SongStoreV2,
    tombstones: SongTombstoneStore,
    batch_size: int = 500,
) -> dict[str, int | str]:
    return reconcile_completed_jobs(
        job_store=job_store,
        song_store=song_store,
        tombstones=tombstones,
        batch_size=batch_size,
        max_batches=None,
    )

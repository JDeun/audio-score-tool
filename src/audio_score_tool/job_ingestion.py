from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .job_store import JobStore
from .paths import database_path
from .sqlite_runtime import connect_sqlite


class SongIngestionStore(Protocol):
    def sync_completed_jobs(self, jobs: list[dict]) -> int: ...
    def get_by_job(self, job_id: str) -> dict | None: ...


class TombstoneLookup(Protocol):
    def contains(self, job_id: str | None) -> bool: ...


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
    song_store: SongIngestionStore,
    tombstones: TombstoneLookup,
    state: JobIngestionState | None = None,
    batch_size: int = 200,
    max_batches: int | None = 1,
) -> dict[str, int | str]:
    """Incrementally ingest completed jobs without scanning the whole job table.

    The durable cursor advances only after a Job is known to be safe to pass: it was
    explicitly tombstoned, was already ingested, or was successfully ingested now.
    A transient missing/corrupt score therefore blocks at that Job and is retried on
    the next reconciliation instead of being skipped forever.
    """

    state = state or JobIngestionState(job_store.path)
    cursor = state.read()
    scanned = 0
    created = 0
    batches = 0
    blocked = 0

    while max_batches is None or batches < max_batches:
        jobs = job_store.list_completed_after(
            cursor_updated_at=cursor.updated_at,
            cursor_job_id=cursor.job_id,
            limit=batch_size,
        )
        if not jobs:
            break
        batches += 1

        for job in jobs:
            scanned += 1
            job_id = str(job.get("job_id") or "")
            if not job_id:
                blocked += 1
                break

            if tombstones.contains(job_id):
                cursor = IngestionCursor(str(job["updated_at"]), job_id)
                state.write(cursor)
                continue

            if song_store.get_by_job(job_id) is None:
                created_now = song_store.sync_completed_jobs([job])
                created += created_now
                if created_now == 0 and song_store.get_by_job(job_id) is None:
                    blocked += 1
                    break

            cursor = IngestionCursor(str(job["updated_at"]), job_id)
            state.write(cursor)
        else:
            if len(jobs) < batch_size:
                break
            continue

        # A blocked Job must remain the next candidate on a later pass.
        break

    return {
        "scanned": scanned,
        "created": created,
        "blocked": blocked,
        "batches": batches,
        "cursor_updated_at": cursor.updated_at,
        "cursor_job_id": cursor.job_id,
    }


def full_reconcile_completed_jobs(
    *,
    job_store: JobStore,
    song_store: SongIngestionStore,
    tombstones: TombstoneLookup,
    batch_size: int = 500,
) -> dict[str, int | str]:
    return reconcile_completed_jobs(
        job_store=job_store,
        song_store=song_store,
        tombstones=tombstones,
        batch_size=batch_size,
        max_batches=None,
    )

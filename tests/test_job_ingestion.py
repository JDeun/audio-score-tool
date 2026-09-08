from __future__ import annotations

from pathlib import Path

from audio_score_tool.job_ingestion import JobIngestionState, reconcile_completed_jobs
from audio_score_tool.job_store import JobStore


class FakeSongs:
    def __init__(self, *, fail_on: set[str] | None = None):
        self.ingested: set[str] = set()
        self.fail_on = fail_on or set()

    def get_by_job(self, job_id: str):
        return {"job_id": job_id} if job_id in self.ingested else None

    def sync_completed_jobs(self, jobs: list[dict]) -> int:
        created = 0
        for job in jobs:
            job_id = str(job["job_id"])
            if job_id in self.fail_on or job_id in self.ingested:
                continue
            self.ingested.add(job_id)
            created += 1
        return created


class FakeTombstones:
    def __init__(self, values: set[str] | None = None):
        self.values = values or set()

    def contains(self, job_id: str | None) -> bool:
        return bool(job_id and job_id in self.values)


def _insert_done_jobs(store: JobStore, count: int) -> None:
    rows = []
    for index in range(count):
        job_id = f"job-{index:05d}"
        stamp = f"2026-01-01T00:00:{index:05d}Z"
        rows.append(
            (
                job_id,
                "transcription",
                "done",
                "complete",
                100,
                f"song-{index}.wav",
                None,
                0,
                "auto",
                None,
                None,
                None,
                None,
                stamp,
                stamp,
            )
        )
    with store._connect() as conn:
        conn.executemany(
            """
            INSERT INTO jobs(
                job_id,kind,status,stage,progress,filename,language,skip_lyrics,preset,
                muscriptor_model,whisperx_model,error,result_json,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            rows,
        )


def test_completed_cursor_pages_beyond_legacy_5000_cap(tmp_path: Path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    _insert_done_jobs(store, 10_050)

    cursor_updated_at = ""
    cursor_job_id = ""
    seen: list[str] = []
    while True:
        page = store.list_completed_after(
            cursor_updated_at=cursor_updated_at,
            cursor_job_id=cursor_job_id,
            limit=777,
        )
        if not page:
            break
        seen.extend(str(job["job_id"]) for job in page)
        cursor_updated_at = str(page[-1]["updated_at"])
        cursor_job_id = str(page[-1]["job_id"])

    assert len(seen) == 10_050
    assert len(set(seen)) == 10_050
    assert seen[0] == "job-00000"
    assert seen[-1] == "job-10049"


def test_reconciliation_stops_at_failure_and_resumes_after_restart(tmp_path: Path):
    db = tmp_path / "jobs.sqlite3"
    store = JobStore(db)
    _insert_done_jobs(store, 3)
    songs = FakeSongs(fail_on={"job-00001"})
    tombstones = FakeTombstones()

    first = reconcile_completed_jobs(
        job_store=store,
        song_store=songs,
        tombstones=tombstones,
        state=JobIngestionState(db),
        batch_size=10,
        max_batches=None,
    )
    assert songs.ingested == {"job-00000"}
    assert first["blocked"] == 1
    assert first["cursor_job_id"] == "job-00000"

    # Simulate a process restart: create a fresh durable state object and clear the
    # transient failure. The blocked Job must be the first one reconsidered.
    songs.fail_on.clear()
    second = reconcile_completed_jobs(
        job_store=store,
        song_store=songs,
        tombstones=tombstones,
        state=JobIngestionState(db),
        batch_size=10,
        max_batches=None,
    )
    assert second["blocked"] == 0
    assert songs.ingested == {"job-00000", "job-00001", "job-00002"}
    assert second["cursor_job_id"] == "job-00002"


def test_tombstoned_job_advances_cursor_without_reingestion(tmp_path: Path):
    db = tmp_path / "jobs.sqlite3"
    store = JobStore(db)
    _insert_done_jobs(store, 2)
    songs = FakeSongs()

    result = reconcile_completed_jobs(
        job_store=store,
        song_store=songs,
        tombstones=FakeTombstones({"job-00000"}),
        state=JobIngestionState(db),
        batch_size=10,
        max_batches=None,
    )

    assert songs.ingested == {"job-00001"}
    assert result["cursor_job_id"] == "job-00001"

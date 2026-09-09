from __future__ import annotations

import json
import threading
from pathlib import Path

from audio_score_tool.job_store import JobStore
from audio_score_tool.startup_recovery import recover_startup_state


class FakeSongStore:
    def __init__(self, root: Path):
        self.export_root = root / "exports"
        self.cache_root = root / "cache"
        self.export_root.mkdir(parents=True)
        self.cache_root.mkdir(parents=True)
        self._songs: list[dict] = []

    def list(self):
        return list(self._songs)


class FakeJobLookup:
    def __init__(self, values: dict[str, dict | None]):
        self.values = values

    def get(self, job_id: str):
        return self.values.get(job_id)


def test_job_store_survives_corrupt_historical_result_json(tmp_path: Path):
    store = JobStore(tmp_path / "state.sqlite3")
    store.create("job-1", status="done", result={"ok": True})
    with store._connect() as conn:
        conn.execute("UPDATE jobs SET result_json=? WHERE job_id=?", ("{broken", "job-1"))

    row = store.get("job-1")
    assert row is not None
    assert row["result"] is None
    assert row["result_corrupt"] is True
    assert store.list()[0]["job_id"] == "job-1"


def test_job_store_serializes_concurrent_updates_without_losing_row(tmp_path: Path):
    store = JobStore(tmp_path / "state.sqlite3")
    store.create("job-1", status="queued", progress=0)
    failures: list[BaseException] = []

    def writer(index: int):
        try:
            for offset in range(20):
                store.update("job-1", progress=index * 20 + offset, stage=f"writer-{index}")
        except BaseException as exc:  # pragma: no cover - assertion collects thread failures
            failures.append(exc)

    threads = [threading.Thread(target=writer, args=(index,)) for index in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not failures
    assert all(not thread.is_alive() for thread in threads)
    row = store.get("job-1")
    assert row is not None
    assert row["stage"].startswith("writer-")
    assert isinstance(row["progress"], int)


def test_startup_recovery_removes_partial_uploads_and_orphan_work_dirs(tmp_path: Path):
    store = FakeSongStore(tmp_path)
    jobs = tmp_path / "jobs"
    partial = jobs / "job-1" / "source.wav.uploading"
    partial.parent.mkdir(parents=True)
    partial.write_bytes(b"partial")
    work = store.cache_root / "song-1" / "work"
    work.mkdir(parents=True)
    (work / "scratch.musicxml").write_text("scratch", encoding="utf-8")

    result = recover_startup_state(store, jobs_root=jobs, job_store=FakeJobLookup({}))

    assert result["removed_partial_uploads"] == 1
    assert result["removed_score_work_dirs"] == 1
    assert not partial.exists()
    assert not work.exists()


def test_startup_recovery_restores_staged_job_when_db_record_survived(tmp_path: Path):
    store = FakeSongStore(tmp_path)
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    token = "a" * 32
    staged = jobs / f".deleting-job-1-{token}"
    staged.mkdir()
    (staged / "payload.json").write_text(json.dumps({"ok": True}), encoding="utf-8")

    result = recover_startup_state(
        store,
        jobs_root=jobs,
        job_store=FakeJobLookup({"job-1": {"job_id": "job-1"}}),
    )

    assert result["restored_staged_job_deletions"] == 1
    assert (jobs / "job-1" / "payload.json").is_file()
    assert not staged.exists()


def test_startup_recovery_deletes_staged_job_when_db_delete_committed(tmp_path: Path):
    store = FakeSongStore(tmp_path)
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    staged = jobs / f".deleting-job-1-{'b' * 32}"
    staged.mkdir()

    result = recover_startup_state(store, jobs_root=jobs, job_store=FakeJobLookup({"job-1": None}))

    assert result["removed_staged_job_deletions"] == 1
    assert not staged.exists()

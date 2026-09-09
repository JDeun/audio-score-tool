from __future__ import annotations

import threading
from pathlib import Path

from audio_score_tool.job_store import JobStore
from audio_score_tool.startup_recovery import recover_startup_state


class _SongStoreFixture:
    def __init__(self, root: Path):
        self.export_root = root / "exports"
        self.cache_root = root / "cache"
        self.export_root.mkdir(parents=True)
        self.cache_root.mkdir(parents=True)

    def list(self):
        return []


class _JobLookup:
    def get(self, _job_id: str):
        return None


def test_job_store_concurrency_soak(tmp_path: Path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    store.create("job-soak", status="queued", progress=0)
    errors: list[BaseException] = []
    start = threading.Barrier(13)

    def writer(worker: int):
        try:
            start.wait(timeout=5)
            for iteration in range(100):
                store.update(
                    "job-soak",
                    progress=worker * 100 + iteration,
                    stage=f"worker-{worker}-{iteration}",
                )
                row = store.get("job-soak")
                assert row is not None
        except BaseException as exc:  # pragma: no cover - collected below
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(worker,)) for worker in range(12)]
    for thread in threads:
        thread.start()
    start.wait(timeout=5)
    for thread in threads:
        thread.join(timeout=30)

    assert not errors
    assert all(not thread.is_alive() for thread in threads)
    final = store.get("job-soak")
    assert final is not None
    assert isinstance(final["progress"], int)
    assert str(final["stage"]).startswith("worker-")


def test_startup_recovery_is_idempotent_under_repetition(tmp_path: Path):
    store = _SongStoreFixture(tmp_path)
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    for index in range(25):
        partial = jobs / f"job-{index}" / "source.wav.uploading"
        partial.parent.mkdir(parents=True)
        partial.write_bytes(b"partial")
        work = store.cache_root / f"song-{index}" / "work"
        work.mkdir(parents=True)
        (work / "scratch").write_text("scratch", encoding="utf-8")

    first = recover_startup_state(store, jobs_root=jobs, job_store=_JobLookup())
    second = recover_startup_state(store, jobs_root=jobs, job_store=_JobLookup())

    assert first["removed_partial_uploads"] == 25
    assert first["removed_score_work_dirs"] == 25
    assert second["removed_partial_uploads"] == 0
    assert second["removed_score_work_dirs"] == 0

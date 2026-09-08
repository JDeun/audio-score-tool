from __future__ import annotations

import pytest

from audio_score_tool.job_admission import JobCapacityError, max_pending_jobs, reserve_job


class FakeStore:
    def __init__(self):
        self.jobs: dict[str, dict] = {}

    def list(self, limit: int = 50) -> list[dict]:
        return list(self.jobs.values())[-limit:]

    def create(self, job_id: str, **values) -> None:
        self.jobs[job_id] = {"job_id": job_id, **values}


def test_reserve_job_blocks_when_active_queue_is_full(monkeypatch):
    monkeypatch.setenv("AST_MAX_PENDING_JOBS", "2")
    store = FakeStore()
    reserve_job(store, "a", status="queued")
    reserve_job(store, "b", status="running")

    with pytest.raises(JobCapacityError, match="2/2"):
        reserve_job(store, "c", status="queued")

    assert "c" not in store.jobs


def test_terminal_jobs_do_not_consume_admission_capacity(monkeypatch):
    monkeypatch.setenv("AST_MAX_PENDING_JOBS", "1")
    store = FakeStore()
    store.create("old", status="done")

    reserve_job(store, "next", status="queued")

    assert store.jobs["next"]["status"] == "queued"


def test_invalid_or_extreme_capacity_env_is_safely_bounded(monkeypatch):
    monkeypatch.setenv("AST_MAX_PENDING_JOBS", "invalid")
    assert max_pending_jobs() == 8

    monkeypatch.setenv("AST_MAX_PENDING_JOBS", "0")
    assert max_pending_jobs() == 1

    monkeypatch.setenv("AST_MAX_PENDING_JOBS", "9999")
    assert max_pending_jobs() == 64

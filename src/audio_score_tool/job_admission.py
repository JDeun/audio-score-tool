from __future__ import annotations

import os
from threading import Lock
from typing import Any, Protocol

_ACTIVE_STATUSES = {"queued", "running", "cancelling"}
_DEFAULT_MAX_PENDING_JOBS = 8
_HARD_MAX_PENDING_JOBS = 64
_admission_lock = Lock()


class JobCapacityError(RuntimeError):
    pass


class JobStoreLike(Protocol):
    def list(self, limit: int = 50) -> list[dict[str, Any]]: ...

    def create(self, job_id: str, **values: Any) -> None: ...


def max_pending_jobs() -> int:
    raw = os.getenv("AST_MAX_PENDING_JOBS", str(_DEFAULT_MAX_PENDING_JOBS))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = _DEFAULT_MAX_PENDING_JOBS
    return max(1, min(value, _HARD_MAX_PENDING_JOBS))


def reserve_job(store: JobStoreLike, job_id: str, **values: Any) -> None:
    """Atomically enforce a bounded in-process background-job queue.

    Reservation and capacity inspection share one process lock, so concurrent API
    requests cannot all observe the same free slot and over-admit work. The Job row is
    created before large inputs are persisted; callers must delete the reservation if
    ingestion fails.
    """

    with _admission_lock:
        active = sum(
            1
            for job in store.list(limit=5000)
            if str(job.get("status") or "") in _ACTIVE_STATUSES
        )
        limit = max_pending_jobs()
        if active >= limit:
            raise JobCapacityError(
                f"Background job queue is full ({active}/{limit}). "
                "Wait for a running job to finish or cancel an existing job."
            )
        store.create(job_id, **values)

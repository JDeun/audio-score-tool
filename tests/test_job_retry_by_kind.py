from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from audio_score_tool import job_lifecycle_api_v2 as lifecycle
from audio_score_tool import omr
from audio_score_tool.job_store import JobStore


@pytest.mark.parametrize(
    ("kind", "source_name", "expected_worker"),
    [
        ("transcription", "input.wav", "_worker"),
        ("benchmark", "input.mp3", "_benchmark_worker"),
        ("omr", "source-score.pdf", "_worker"),
        ("notation-import", "source.musicxml", "_worker"),
        ("notation-import", "source.mxl", "_worker"),
        ("notation-import", "source.mid", "_worker"),
    ],
)
def test_retry_dispatches_by_original_job_kind_and_keeps_source(
    tmp_path: Path, monkeypatch, kind: str, source_name: str, expected_worker: str
):
    store = JobStore(tmp_path / "jobs.sqlite3")
    jobs = tmp_path / "jobs"
    original = jobs / "previous" / source_name
    original.parent.mkdir(parents=True)
    original.write_bytes(b"fixture")
    if kind == "benchmark":
        (original.parent / "reference.mid").write_bytes(b"MThd")

    store.create(
        "previous",
        kind=kind,
        status="failed",
        filename="original-title" if kind == "transcription" else source_name,
        language="ko",
        skip_lyrics=kind != "transcription",
        preset="balanced" if kind == "transcription" else ("all" if kind == "benchmark" else kind),
        muscriptor_model="small",
        whisperx_model="large-v3",
    )
    monkeypatch.setattr(lifecycle.base_api, "_store", store)
    monkeypatch.setattr(lifecycle, "jobs_dir", lambda: jobs)
    monkeypatch.setattr(
        lifecycle, "runtime_settings",
        lambda: SimpleNamespace(muscriptor_model="large", whisperx_model="small", audiveris_cmd="audiveris"),
    )
    monkeypatch.setattr(omr, "audiveris_status", lambda command: {"ready": True})

    threads = []

    class CapturedThread:
        def __init__(self, *, target, args, daemon):
            self.target = target
            self.args = args
            self.daemon = daemon
            self.started = False
            threads.append(self)

        def start(self):
            self.started = True

    monkeypatch.setattr(lifecycle, "Thread", CapturedThread)

    response = lifecycle.retry_job_v2("previous")
    new_id = response["job_id"]
    new_job = store.get(new_id)

    assert response["kind"] == kind
    assert response["retried_from"] == "previous"
    assert new_job is not None and new_job["kind"] == kind
    assert new_job["filename"] == store.get("previous")["filename"]
    assert new_job["status"] == "queued"
    assert (jobs / new_id / source_name).read_bytes() == b"fixture"
    assert len(threads) == 1 and threads[0].started
    assert threads[0].target.__name__ == expected_worker
    assert threads[0].args[0] == new_id
    assert threads[0].args[1] == jobs / new_id / source_name
    if kind == "benchmark":
        assert (jobs / new_id / "reference.mid").read_bytes() == b"MThd"
    elif kind == "notation-import":
        assert threads[0].args[2] == Path(source_name).suffix
    elif kind == "transcription":
        assert new_job["muscriptor_model"] == "small"
        assert new_job["whisperx_model"] == "large-v3"


@pytest.mark.parametrize(
    ("kind", "source_name"),
    [
        ("transcription", "input.wav"),
        ("omr", "source-score.pdf"),
        ("notation-import", "source.mxl"),
    ],
)
def test_retry_missing_or_symlinked_original_does_not_create_job(
    tmp_path: Path, monkeypatch, kind: str, source_name: str
):
    store = JobStore(tmp_path / "jobs.sqlite3")
    store.create("previous", kind=kind, status="failed")
    monkeypatch.setattr(lifecycle.base_api, "_store", store)
    monkeypatch.setattr(lifecycle, "jobs_dir", lambda: tmp_path / "jobs")
    monkeypatch.setattr(lifecycle, "runtime_settings", lambda: SimpleNamespace(audiveris_cmd="audiveris"))
    monkeypatch.setattr(omr, "audiveris_status", lambda command: {"ready": True})

    with pytest.raises(HTTPException) as error:
        lifecycle.retry_job_v2("previous")
    assert error.value.status_code == 404
    assert [job["job_id"] for job in store.list()] == ["previous"]


def test_retry_rejects_unsupported_kind_before_creating_a_job(tmp_path: Path, monkeypatch):
    store = JobStore(tmp_path / "jobs.sqlite3")
    store.create("previous", kind="future-provider", status="failed")
    monkeypatch.setattr(lifecycle.base_api, "_store", store)
    monkeypatch.setattr(lifecycle, "jobs_dir", lambda: tmp_path / "jobs")
    with pytest.raises(HTTPException) as error:
        lifecycle.retry_job_v2("previous")
    assert error.value.status_code == 409
    assert [job["job_id"] for job in store.list()] == ["previous"]

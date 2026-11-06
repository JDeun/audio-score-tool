from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from audio_score_tool import job_lifecycle_api_v2 as lifecycle
from audio_score_tool import upload_api_v2 as upload
from audio_score_tool.api import app
from audio_score_tool.job_store import JobStore


def _defaults():
    return SimpleNamespace(muscriptor_model="small", whisperx_model="small")


def test_audio_job_admission_rejects_missing_core_engine_without_queued_job(
    tmp_path: Path, monkeypatch
):
    store = JobStore(tmp_path / "jobs.sqlite3")
    monkeypatch.setattr(upload.base_api, "_store", store)
    monkeypatch.setattr(upload, "jobs_dir", lambda: tmp_path / "jobs")
    monkeypatch.setattr(upload, "runtime_settings", _defaults)
    monkeypatch.setattr(
        upload, "preflight",
        lambda *_args, **_kwargs: {"ok": False, "missing": ["transcription_engine:mt3_infer"]},
    )

    response = TestClient(app).post(
        "/api/jobs", files={"file": ("audio.wav", b"valid-extension", "audio/wav")},
        data={"preset": "auto"},
    )
    assert response.status_code == 503
    assert "transcription_engine" in response.json()["detail"]
    assert store.list() == []


def test_youtube_job_admission_rejects_missing_ingestion_runtime(
    tmp_path: Path, monkeypatch
):
    store = JobStore(tmp_path / "jobs.sqlite3")
    monkeypatch.setattr(lifecycle.base_api, "_store", store)
    monkeypatch.setattr(lifecycle, "jobs_dir", lambda: tmp_path / "jobs")
    monkeypatch.setattr(lifecycle, "runtime_settings", _defaults)
    monkeypatch.setattr(
        lifecycle, "preflight", lambda *_args, **_kwargs: {"ok": True, "missing": []}
    )
    monkeypatch.setattr(
        lifecycle, "youtube_tool_status", lambda _settings: {"ready": False}
    )

    response = TestClient(app).post(
        "/api/jobs/youtube",
        json={
            "url": "https://www.youtube.com/watch?v=abcdef12345",
            "authorized": True,
            "preset": "auto",
        },
    )
    assert response.status_code == 503
    assert "YouTube" in response.json()["detail"]
    assert store.list() == []


def test_missing_optional_lyrics_runtime_does_not_block_basic_job(
    tmp_path: Path, monkeypatch
):
    store = JobStore(tmp_path / "jobs.sqlite3")
    monkeypatch.setattr(upload.base_api, "_store", store)
    monkeypatch.setattr(upload, "jobs_dir", lambda: tmp_path / "jobs")
    monkeypatch.setattr(upload, "runtime_settings", _defaults)
    monkeypatch.setattr(
        upload, "preflight",
        lambda *_args, **_kwargs: {"ok": True, "missing": [], "tools": {"whisperx": False}},
    )

    class FakeThread:
        def __init__(self, *, target, args, daemon):
            pass

        def start(self):
            pass

    monkeypatch.setattr(upload, "Thread", FakeThread)
    response = TestClient(app).post(
        "/api/jobs",
        files={"file": ("audio.wav", b"valid-extension", "audio/wav")},
        data={"preset": "auto", "skip_lyrics": "true"},
    )
    assert response.status_code == 202
    assert store.get(response.json()["job_id"])["status"] == "queued"

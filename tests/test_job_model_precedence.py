from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from audio_score_tool import job_lifecycle_api_v2 as lifecycle
from audio_score_tool import upload_api_v2 as upload
from audio_score_tool.api import app
from audio_score_tool.job_store import JobStore
from audio_score_tool.presets import resolve_job_models


@pytest.mark.parametrize(
    ("preset", "expected"),
    [
        ("auto", ("small", "small")),
        ("fast", ("small", "small")),
        ("balanced", ("medium", "small")),
        ("quality", ("large", "large-v3")),
    ],
)
def test_saved_default_only_applies_to_auto_preset(preset, expected):
    assert resolve_job_models(
        preset,
        selected_muscriptor_model="small",
        selected_whisperx_model="small",
    ) == expected


def test_explicit_custom_overrides_are_never_lost():
    assert resolve_job_models(
        "balanced",
        selected_muscriptor_model="large",
        selected_whisperx_model="small",
        muscriptor_override="small",
        whisperx_override="large-v3",
    ) == ("small", "large-v3")


def test_unknown_preset_remains_rejected():
    with pytest.raises(ValueError, match="Unknown preset"):
        resolve_job_models("not-a-preset", selected_muscriptor_model="small")


@pytest.mark.parametrize("source", ["audio", "youtube"])
@pytest.mark.parametrize(
    ("preset", "expected"),
    [
        ("auto", ("small", "small")),
        ("balanced", ("medium", "small")),
        ("quality", ("large", "large-v3")),
    ],
)
def test_canonical_job_endpoints_apply_saved_model_for_auto_only(
    tmp_path: Path, monkeypatch, source, preset, expected
):
    store = JobStore(tmp_path / "jobs.sqlite3")
    jobs = tmp_path / "jobs"
    default = SimpleNamespace(muscriptor_model="small", whisperx_model="small")
    monkeypatch.setattr(upload.base_api, "_store", store)
    monkeypatch.setattr(upload, "jobs_dir", lambda: jobs)
    monkeypatch.setattr(lifecycle, "jobs_dir", lambda: jobs)
    monkeypatch.setattr(upload, "runtime_settings", lambda: default)
    monkeypatch.setattr(lifecycle, "runtime_settings", lambda: default)

    class FakeThread:
        def __init__(self, *, target, args, daemon):
            self.args = args

        def start(self):
            pass

    monkeypatch.setattr(upload, "Thread", FakeThread)
    monkeypatch.setattr(lifecycle, "Thread", FakeThread)

    client = TestClient(app)
    if source == "audio":
        response = client.post(
            "/api/jobs",
            files={"file": ("fixture.wav", b"test-data", "audio/wav")},
            data={"preset": preset, "skip_lyrics": "true"},
        )
    else:
        response = client.post(
            "/api/jobs/youtube",
            json={
                "url": "https://www.youtube.com/watch?v=abcdef12345",
                "authorized": True,
                "preset": preset,
                "skip_lyrics": True,
            },
        )

    assert response.status_code == 202
    job = store.get(response.json()["job_id"])
    assert job is not None
    assert (job["muscriptor_model"], job["whisperx_model"]) == expected
    assert job["preset"] == preset


def test_canonical_job_explicit_overrides_take_precedence(tmp_path: Path, monkeypatch):
    store = JobStore(tmp_path / "jobs.sqlite3")
    monkeypatch.setattr(lifecycle.base_api, "_store", store)
    monkeypatch.setattr(lifecycle, "jobs_dir", lambda: tmp_path / "jobs")
    monkeypatch.setattr(
        lifecycle,
        "runtime_settings",
        lambda: SimpleNamespace(muscriptor_model="large", whisperx_model="small"),
    )

    class FakeThread:
        def __init__(self, *, target, args, daemon):
            pass

        def start(self):
            pass

    monkeypatch.setattr(lifecycle, "Thread", FakeThread)
    response = TestClient(app).post(
        "/api/jobs/youtube",
        json={
            "url": "https://www.youtube.com/watch?v=abcdef12345",
            "authorized": True,
            "preset": "balanced",
            "muscriptor_model": "small",
            "whisperx_model": "large-v3",
        },
    )
    assert response.status_code == 202
    job = store.get(response.json()["job_id"])
    assert job is not None
    assert (job["muscriptor_model"], job["whisperx_model"]) == ("small", "large-v3")

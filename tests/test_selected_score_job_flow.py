"""End-to-end selection contracts: form/JSON -> SQLite -> retry -> worker.

All tests use local synthetic fixtures and never download YouTube content.
"""
from __future__ import annotations

import sqlite3
from dataclasses import replace

from fastapi.testclient import TestClient

from audio_score_tool import job_lifecycle_api_v2 as lifecycle
from audio_score_tool import runtime_services as runtime
from audio_score_tool import upload_api_v2 as upload
from audio_score_tool.api import app
from audio_score_tool.config import Settings
from audio_score_tool.job_store import JobStore


class NoStartThread:
    created = []

    def __init__(self, *, target, args, daemon):
        self.target, self.args, self.daemon = target, args, daemon
        self.created.append(self)

    def start(self):
        pass


def _prepare(tmp_path, monkeypatch, *, separator=True):
    store = JobStore(tmp_path / "jobs.sqlite3")
    monkeypatch.setattr(runtime, "_store", store)
    monkeypatch.setattr(upload.base_api, "_store", store)
    monkeypatch.setattr(lifecycle.base_api, "_store", store)
    monkeypatch.setattr(upload, "jobs_dir", lambda: tmp_path / "jobs")
    monkeypatch.setattr(lifecycle, "jobs_dir", lambda: tmp_path / "jobs")
    def defaults():
        return Settings(
            demucs_cmd="demucs",
            muscriptor_model="small",
            whisperx_model="small",
            usage_mode="personal",
        )
    monkeypatch.setattr(upload, "runtime_settings", defaults)
    monkeypatch.setattr(lifecycle, "runtime_settings", defaults)
    monkeypatch.setattr(upload, "preflight", lambda *_a, **_kw: {"ok": True, "missing": []})
    monkeypatch.setattr(lifecycle, "preflight", lambda *_a, **_kw: {"ok": True, "missing": []})
    monkeypatch.setattr(lifecycle, "youtube_tool_status", lambda *_a: {"ready": True})
    monkeypatch.setattr(upload, "command_exists", lambda *_a: separator)
    monkeypatch.setattr(lifecycle, "command_exists", lambda *_a: separator)
    monkeypatch.setattr(upload, "Thread", NoStartThread)
    monkeypatch.setattr(lifecycle, "Thread", NoStartThread)
    return store


def test_file_upload_persists_selected_guitar_vocal_and_legacy_defaults_full(
    tmp_path, monkeypatch,
):
    store = _prepare(tmp_path, monkeypatch)
    response = TestClient(app).post(
        "/api/jobs",
        files={"file": ("original.wav", b"not-a-real-audio-fixture", "audio/wav")},
        data={"score_mode": "guitar_vocal", "skip_lyrics": "true"},
    )
    assert response.status_code == 202, response.text
    row = store.get(response.json()["job_id"])
    assert row["score_mode"] == "guitar_vocal"
    assert row["auto_enrich"] is True
    assert row["skip_lyrics"] is True
    assert NoStartThread.created[-1].args[0] == row["job_id"]
    normal = TestClient(app).post(
        "/api/jobs",
        files={"file": ("other.wav", b"second-synthetic", "audio/wav")},
    )
    assert normal.status_code == 202
    assert store.get(normal.json()["job_id"])["score_mode"] == "full"


def test_youtube_score_request_can_choose_lead_sheet_without_ownership_proof(
    tmp_path, monkeypatch,
):
    store = _prepare(tmp_path, monkeypatch)
    response = TestClient(app).post(
        "/api/jobs/youtube",
        json={
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "score_mode": "lead_sheet",
            "skip_lyrics": False,
        },
    )
    assert response.status_code == 202, response.text
    assert store.get(response.json()["job_id"])["score_mode"] == "lead_sheet"
    assert store.get(response.json()["job_id"])["auto_enrich"] is True
    assert store.get(response.json()["job_id"])["source_kind"] == "youtube"


def test_sheetsage2_admission_needs_no_demucs_but_requires_lead_sheet(tmp_path, monkeypatch):
    store = _prepare(tmp_path, monkeypatch, separator=False)
    defaults = upload.runtime_settings()
    settings = replace(defaults, transcription_engine="sheetsage2")
    monkeypatch.setattr(upload, "runtime_settings", lambda: settings)
    monkeypatch.setattr(lifecycle, "runtime_settings", lambda: settings)
    client = TestClient(app)
    response = client.post("/api/jobs", files={"file": ("vocal.wav", b"fixture", "audio/wav")},
                           data={"score_mode": "lead_sheet", "skip_lyrics": "true"})
    assert response.status_code == 202, response.text
    assert store.get(response.json()["job_id"])["transcription_engine"] == "sheetsage2"
    youtube = client.post("/api/jobs/youtube", json={
        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "score_mode": "lead_sheet"})
    assert youtube.status_code == 202, youtube.text
    for mode in ("full", "guitar_vocal"):
        invalid = client.post("/api/jobs", files={"file": ("vocal.wav", b"fixture", "audio/wav")},
                              data={"score_mode": mode})
        assert invalid.status_code == 422
    assert len(store.list()) == 2


def test_invalid_mode_or_missing_demucs_fails_before_job_or_youtube_download(
    tmp_path, monkeypatch,
):
    store = _prepare(tmp_path, monkeypatch, separator=False)
    client = TestClient(app)
    for bad in ("guitar", "synth", "full_score"):
        response = client.post(
            "/api/jobs/youtube",
            json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "score_mode": bad},
        )
        assert response.status_code == 422
    selected = client.post(
        "/api/jobs/youtube",
        json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
              "score_mode": "guitar_vocal"},
    )
    assert selected.status_code == 503
    selected_file = client.post(
        "/api/jobs",
        files={"file": ("audio.wav", b"fixture", "audio/wav")},
        data={"score_mode": "lead_sheet"},
    )
    assert selected_file.status_code == 503
    assert store.list() == []


def test_job_sqlite_migrates_without_changing_historical_full_score_intent(tmp_path):
    target = tmp_path / "old.sqlite3"
    with sqlite3.connect(target) as con:
        con.execute("""
            CREATE TABLE jobs (
                job_id TEXT PRIMARY KEY, kind TEXT DEFAULT 'transcription',
                status TEXT NOT NULL, stage TEXT, progress INTEGER DEFAULT 0,
                filename TEXT, source_kind TEXT, language TEXT,
                skip_lyrics INTEGER DEFAULT 0, preset TEXT,
                muscriptor_model TEXT, whisperx_model TEXT,
                error TEXT, result_json TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )
        """)
        con.execute(
            "INSERT INTO jobs(job_id,status,created_at,updated_at) VALUES(?,?,?,?)",
            ("historical", "done", "2025-01-01", "2025-01-01"),
        )
    store = JobStore(target)
    assert store.get("historical")["score_mode"] == "full"
    assert store.get("historical")["transcription_engine"] is None
    assert store.get("historical")["mt3_model"] is None
    assert store.get("historical")["native_checkpoint_sha256"] is None
    assert store.get("historical")["transcription_selection_version"] == 0
    store.create("new", score_mode="guitar_vocal", status="done")
    assert store.get("new")["score_mode"] == "guitar_vocal"


def test_retry_preserves_requested_parts_and_avoids_unavailable_separator(
    tmp_path, monkeypatch,
):
    store = _prepare(tmp_path, monkeypatch)
    original = tmp_path / "jobs" / "old" / "input.wav"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"original-private-input")
    store.create("old", kind="transcription", source_kind="local",
                 status="failed", score_mode="guitar_vocal", auto_enrich=True)
    reply = TestClient(app).post("/api/jobs/old/retry")
    assert reply.status_code == 202, reply.text
    new = store.get(reply.json()["job_id"])
    assert new["score_mode"] == "guitar_vocal"
    assert new["auto_enrich"] is True
    assert new["source_kind"] == "local"
    monkeypatch.setattr(lifecycle, "command_exists", lambda *_a: False)
    stop = TestClient(app).post("/api/jobs/old/retry")
    assert stop.status_code == 503
    assert len(store.list()) == 2

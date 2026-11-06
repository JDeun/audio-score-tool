from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from audio_score_tool import job_artifact_api_v2 as artifacts
from audio_score_tool import runtime_services as runtime
from audio_score_tool.api import app
from audio_score_tool.job_store import JobStore


def test_job_list_and_detail_expose_only_downloadable_artifacts(tmp_path: Path, monkeypatch):
    store = JobStore(tmp_path / "jobs.sqlite3")
    root = tmp_path / "jobs"
    musicxml = root / "notation-job" / "outputs" / "score.musicxml"
    musicxml.parent.mkdir(parents=True)
    musicxml.write_bytes(b"<score-partwise/>")
    outside = tmp_path / "private.mid"
    outside.write_bytes(b"MThd")

    store.create(
        "notation-job",
        kind="notation-import",
        status="done",
        result={
            "musicxml": str(musicxml),
            "pdf": str(musicxml.parent / "never-created.pdf"),
            "midi": str(outside),
        },
    )
    monkeypatch.setattr(runtime, "_store", store)
    monkeypatch.setattr(artifacts, "jobs_dir", lambda: root)
    client = TestClient(app)

    listed = client.get("/api/jobs?limit=100")
    detail = client.get("/api/jobs/notation-job")
    assert listed.status_code == 200
    assert detail.status_code == 200
    assert listed.json()["jobs"][0]["available_artifacts"] == ["musicxml"]
    assert detail.json()["available_artifacts"] == ["musicxml"]
    assert client.get("/api/jobs/notation-job/files/musicxml").content == b"<score-partwise/>"
    assert client.get("/api/jobs/notation-job/files/pdf").status_code == 404
    assert client.get("/api/jobs/notation-job/files/midi").status_code == 404

    # Availability reflects the actual current Job workspace, not stale DB metadata.
    musicxml.unlink()
    assert client.get("/api/jobs/notation-job").json()["available_artifacts"] == []


def test_download_falls_back_to_base_musicxml_if_lyric_overlay_is_missing(tmp_path: Path, monkeypatch):
    store = JobStore(tmp_path / "jobs.sqlite3")
    root = tmp_path / "jobs"
    score = root / "audio-job" / "outputs" / "score.musicxml"
    score.parent.mkdir(parents=True)
    score.write_bytes(b"base score")
    store.create(
        "audio-job",
        status="done",
        result={
            "lyric_musicxml": str(score.parent / "missing-lyrics.musicxml"),
            "musicxml": str(score),
        },
    )
    monkeypatch.setattr(runtime, "_store", store)
    monkeypatch.setattr(artifacts, "jobs_dir", lambda: root)
    client = TestClient(app)

    assert client.get("/api/jobs/audio-job").json()["available_artifacts"] == ["musicxml"]
    download = client.get("/api/jobs/audio-job/files/musicxml")
    assert download.status_code == 200
    assert download.content == b"base score"


def test_benchmark_and_corrupt_artifact_paths_are_not_advertised(tmp_path: Path, monkeypatch):
    store = JobStore(tmp_path / "jobs.sqlite3")
    root = tmp_path / "jobs"
    report = root / "benchmark-job" / "outputs" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text('{"ok": true}', encoding="utf-8")
    store.create(
        "benchmark-job",
        kind="benchmark",
        status="done",
        result={"benchmark_json": str(report), "benchmark_csv": ["not", "a", "path"]},
    )
    store.create("pending-job", status="running", result={"musicxml": str(report)})
    monkeypatch.setattr(runtime, "_store", store)
    monkeypatch.setattr(artifacts, "jobs_dir", lambda: root)
    client = TestClient(app)

    assert client.get("/api/jobs/benchmark-job").json()["available_artifacts"] == ["benchmark_json"]
    assert client.get("/api/jobs/benchmark-job/files/benchmark_json").status_code == 200
    assert client.get("/api/jobs/benchmark-job/files/benchmark_csv").status_code == 404
    assert client.get("/api/jobs/pending-job").json()["available_artifacts"] == []

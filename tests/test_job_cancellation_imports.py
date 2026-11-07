"""Cancellation contract for non-AMT import jobs and their shared HTTP endpoint."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from audio_score_tool import direct_score_import_api as notation
from audio_score_tool import omr_api as omr
from audio_score_tool import runtime_services as runtime
from audio_score_tool.api import app
from audio_score_tool.config import Settings
from audio_score_tool.job_store import JobStore
from audio_score_tool.omr import OMRImportCancelled

SCORE_XML = (
    '<?xml version="1.0"?><score-partwise version="4.0">'
    '<part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list>'
    '<part id="P1"><measure number="1"><note><pitch><step>C</step>'
    '<octave>4</octave></pitch><duration>1</duration><type>quarter</type>'
    '</note></measure></part></score-partwise>'
)


@pytest.fixture
def imports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = JobStore(tmp_path / "jobs.db")
    job_root = tmp_path / "jobs"
    assets = tmp_path / "assets"
    monkeypatch.setattr(runtime, "_store", store)
    monkeypatch.setattr(omr, "_store", store)
    monkeypatch.setattr(notation, "_store", store)
    monkeypatch.setattr(omr, "jobs_dir", lambda: job_root)
    monkeypatch.setattr(notation, "jobs_dir", lambda: job_root)
    monkeypatch.setattr(omr, "song_assets_dir", lambda: assets)
    yield store, job_root, assets


def _source(store: JobStore, jobs: Path, job_id: str, kind: str, suffix: str) -> Path:
    store.create(job_id, kind=kind, status="queued")
    filename = f"source-score{suffix}" if kind == "omr" else f"source{suffix}"
    source = jobs / job_id / filename
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"%PDF-1.4\n" if kind == "omr" else SCORE_XML.encode())
    return source


@pytest.mark.parametrize("kind,suffix", [("omr", ".pdf"), ("notation-import", ".musicxml")])
def test_queued_cancel_before_worker_registration_is_honored(
    imports, monkeypatch, kind: str, suffix: str,
):
    store, jobs, _assets = imports
    source = _source(store, jobs, f"queued-{kind}", kind, suffix)
    if kind == "omr":
        monkeypatch.setattr(omr, "transcribe_score", lambda *_a, **_kw: pytest.fail(
            "Cancelled queued OMR must never invoke Audiveris"
        ))
    else:
        monkeypatch.setattr(notation, "musicxml_to_midi", lambda *_a, **_kw: pytest.fail(
            "Cancelled queued notation must never invoke conversion"
        ))
    response = TestClient(app).post(f"/api/jobs/queued-{kind}/cancel")
    assert response.status_code == 202
    assert response.json()["status"] == "cancelling"
    assert response.json()["cancelled"] is True

    if kind == "omr":
        omr._worker(f"queued-{kind}", source, Settings())
    else:
        notation._worker(f"queued-{kind}", source, suffix)

    row = store.get(f"queued-{kind}")
    assert row is not None and row["status"] == "cancelled"
    assert row["result"] is None
    assert f"queued-{kind}" not in runtime._cancel_events


def test_cancel_running_omr_interrupts_audiveris_and_does_not_create_song(
    imports, monkeypatch,
):
    store, jobs, assets = imports
    source = _source(store, jobs, "omr-running", "omr", ".pdf")
    captured = []

    def interrupt_omr(_source: Path, _output: Path, *, command: str, cancel_event):
        assert command == "synthetic-audiveris"
        captured.append(cancel_event)
        response = TestClient(app).post("/api/jobs/omr-running/cancel")
        assert response.status_code == 202
        assert cancel_event.is_set()
        raise OMRImportCancelled("cancelled by user")

    monkeypatch.setattr(omr, "transcribe_score", interrupt_omr)
    omr._worker("omr-running", source, Settings(audiveris_cmd="synthetic-audiveris"))
    assert len(captured) == 1
    row = store.get("omr-running")
    assert row is not None and row["status"] == "cancelled"
    assert row["result"] is None
    assert not (assets / "omr-running").exists()


def test_cancel_after_omr_returns_does_not_commit_or_copy_assets(imports, monkeypatch):
    store, jobs, assets = imports
    source = _source(store, jobs, "omr-finish-race", "omr", ".pdf")

    def finished_while_cancelled(_source, output_dir, *, command, cancel_event):
        result = TestClient(app).post("/api/jobs/omr-finish-race/cancel")
        assert result.status_code == 202
        assert cancel_event.is_set()
        return SimpleNamespace(musicxml_path=output_dir / "score.musicxml", provider="fixture")

    monkeypatch.setattr(omr, "transcribe_score", finished_while_cancelled)
    omr._worker("omr-finish-race", source, Settings())
    assert store.get("omr-finish-race")["status"] == "cancelled"
    assert not (assets / "omr-finish-race").exists()


def test_cancel_during_direct_musicxml_conversion_blocks_successful_result(
    imports, monkeypatch,
):
    store, jobs, _assets = imports
    source = _source(store, jobs, "notation-running", "notation-import", ".musicxml")

    def cancel_in_converter(_musicxml: Path, midi: Path):
        midi.write_bytes(b"MThd-synthetic")
        response = TestClient(app).post("/api/jobs/notation-running/cancel")
        assert response.status_code == 202

    monkeypatch.setattr(notation, "musicxml_to_midi", cancel_in_converter)
    notation._worker("notation-running", source, ".musicxml")
    job = store.get("notation-running")
    assert job is not None and job["status"] == "cancelled"
    assert job["result"] is None
    assert "notation-running" not in runtime._cancel_events


def test_cancel_during_direct_midi_conversion_blocks_successful_result(imports, monkeypatch):
    store, jobs, _assets = imports
    source = _source(store, jobs, "midi-running", "notation-import", ".mid")
    source.write_bytes(b"MThd" + b"synthetic")

    def cancel_in_converter(_midi: Path, musicxml: Path):
        musicxml.write_text(SCORE_XML, encoding="utf-8")
        response = TestClient(app).post("/api/jobs/midi-running/cancel")
        assert response.status_code == 202

    monkeypatch.setattr(notation, "midi_to_musicxml", cancel_in_converter)
    notation._worker("midi-running", source, ".mid")
    job = store.get("midi-running")
    assert job is not None and job["status"] == "cancelled"
    assert job["result"] is None


def test_notation_without_cancel_still_completes_normally(imports, monkeypatch):
    store, jobs, _assets = imports
    source = _source(store, jobs, "notation-normal", "notation-import", ".musicxml")
    monkeypatch.setattr(notation, "musicxml_to_midi", lambda _score, midi: midi.write_bytes(
        b"MThd-synthetic"
    ))
    notation._worker("notation-normal", source, ".musicxml")
    job = store.get("notation-normal")
    assert job is not None and job["status"] == "done"
    assert job["result"]["musicxml"].endswith("score.musicxml")
    assert "notation-normal" not in runtime._cancel_events


def test_omr_without_cancel_still_completes_normally(imports, monkeypatch):
    store, jobs, assets = imports
    source = _source(store, jobs, "omr-normal", "omr", ".pdf")
    output = jobs / "omr-normal" / "outputs" / "score.musicxml"

    def finished(_source, _dir, *, command, cancel_event):
        assert not cancel_event.is_set()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(SCORE_XML, encoding="utf-8")
        return SimpleNamespace(musicxml_path=output, provider="fixture")

    monkeypatch.setattr(omr, "transcribe_score", finished)
    omr._worker("omr-normal", source, Settings())
    job = store.get("omr-normal")
    assert job is not None and job["status"] == "done"
    assert (assets / "omr-normal" / "original-score.pdf").read_bytes() == source.read_bytes()

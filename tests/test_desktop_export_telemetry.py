from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from audio_score_tool import export_api_v2
from audio_score_tool.api import app
from audio_score_tool.benchmark_edit_telemetry import (
    read_edit_session,
    record_successful_song_mutation,
    start_edit_session,
)

FINAL_FORMATS = ["musicxml", "pdf", "midi", "parts"]


@pytest.fixture
def editing(tmp_path: Path, monkeypatch):
    report = tmp_path / "case-a.product.json"
    started = datetime(2026, 11, 6, 4, 0, tzinfo=timezone.utc)
    start_edit_session(report, case_id="case-a", song_id="song-a", started_at=started)
    monkeypatch.setenv("AST_TIER2_TELEMETRY_FILE", str(report))
    return report, started


def test_desktop_export_to_counts_success_once_and_preserves_first_time(editing):
    report, started = editing
    record_successful_song_mutation(
        song_id="song-a",
        method="POST",
        path="/api/songs/song-a/export-to",
        status_code=200,
        request_body=b'{"formats":["musicxml","pdf","midi","parts"],"destination_dir":"/tmp/out"}',
        finished_at=started + timedelta(seconds=100),
    )
    first = read_edit_session(report)
    assert first["successful_export"] is True
    assert first["time_to_publish_seconds"] == 100.0
    assert first["finished_at"] == (started + timedelta(seconds=100)).isoformat()

    record_successful_song_mutation(
        song_id="song-a",
        method="POST",
        path="/api/songs/song-a/export",
        status_code=200,
        request_body=b"",
        finished_at=started + timedelta(seconds=800),
    )
    second = read_edit_session(report)
    assert second == first


@pytest.mark.parametrize(
    ("status_code", "formats"),
    [
        (200, ["musicxml"]),
        (200, ["musicxml", "pdf", "midi"]),
        (500, FINAL_FORMATS),
        (507, FINAL_FORMATS),
    ],
)
def test_no_publish_completion_on_subset_or_failed_copy(editing, status_code, formats):
    report, started = editing
    import json

    record_successful_song_mutation(
        song_id="song-a",
        method="POST",
        path="/api/songs/song-a/export-to",
        status_code=status_code,
        request_body=json.dumps({"formats": formats, "destination_dir": "/tmp"}).encode(),
        finished_at=started + timedelta(seconds=180),
    )
    result = read_edit_session(report)
    assert result["successful_export"] is False
    assert result["time_to_publish_seconds"] is None


def test_other_song_export_does_not_finish_current_case(editing):
    report, _ = editing
    record_successful_song_mutation(
        song_id="song-b",
        method="POST",
        path="/api/songs/song-b/export-to",
        status_code=200,
        request_body=b'{"formats":["musicxml","pdf","midi","parts"]}',
    )
    assert read_edit_session(report)["successful_export"] is False


@pytest.mark.parametrize("part_ids", [["P1"], ["P1", "P2"], []])
def test_selected_parts_do_not_complete_whole_score_benchmark(editing, part_ids):
    import json

    report, started = editing
    record_successful_song_mutation(
        song_id="song-a", method="POST", path="/api/songs/song-a/export-to", status_code=200,
        request_body=json.dumps({"formats": FINAL_FORMATS, "part_ids": part_ids}).encode(),
        finished_at=started + timedelta(seconds=90),
    )
    assert read_edit_session(report)["successful_export"] is False


def test_actual_export_to_api_sets_telemetry_only_after_files_are_copied(
    editing, tmp_path: Path, monkeypatch
):
    report, _started = editing
    export_root = tmp_path / "managed_exports"
    managed = export_root / "song-a"
    parts = managed / "parts"
    parts.mkdir(parents=True)
    for name in ("score.musicxml", "score.pdf", "score.mid"):
        (managed / name).write_text(name, encoding="utf-8")
    (parts / "piano.pdf").write_bytes(b"%PDF-1.4")

    monkeypatch.setattr(
        export_api_v2, "_song_store", SimpleNamespace(export_root=export_root)
    )
    monkeypatch.setattr(
        export_api_v2, "_require_song",
        lambda _song_id: {"song_id": "song-a", "title": "Example score"},
    )
    def build_and_copy(_song_id, _request, *, destination_root):
        target = destination_root / "Example score"
        shutil.copytree(managed, target)
        return {"parts": [], "song": {"song_id": "song-a"}, "destination": str(target)}

    monkeypatch.setattr(export_api_v2, "build_exports_v3", build_and_copy)

    client = TestClient(app)
    destination = tmp_path / "published"
    result = client.post(
        "/api/songs/song-a/export-to",
        json={"destination_dir": str(destination), "formats": FINAL_FORMATS},
    )
    assert result.status_code == 200, result.text
    assert (destination / "Example score" / "score.pdf").is_file()
    assert read_edit_session(report)["successful_export"] is True


def test_actual_export_to_api_copy_failure_is_not_marked_as_published(
    editing, tmp_path: Path, monkeypatch
):
    report, _started = editing
    export_root = tmp_path / "managed"
    (export_root / "song-a").mkdir(parents=True)
    monkeypatch.setattr(
        export_api_v2, "_song_store", SimpleNamespace(export_root=export_root)
    )
    monkeypatch.setattr(
        export_api_v2, "_require_song",
        lambda _song_id: {"song_id": "song-a", "title": "Example score"},
    )
    def build_and_copy(_song_id, _request, *, destination_root):
        target = destination_root / "Example score"
        shutil.copytree(export_root / "song-a", target)
        return {"parts": [], "destination": str(target)}

    monkeypatch.setattr(export_api_v2, "build_exports_v3", build_and_copy)

    def deny_copy(*_args, **_kwargs):
        raise OSError("injected destination copy failure")

    monkeypatch.setattr(shutil, "copytree", deny_copy)
    result = TestClient(app).post(
        "/api/songs/song-a/export-to",
        json={"destination_dir": str(tmp_path / "published"), "formats": FINAL_FORMATS},
    )
    assert result.status_code == 500
    assert read_edit_session(report)["successful_export"] is False

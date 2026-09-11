from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from audio_score_tool.benchmark_edit_telemetry import (
    read_edit_session,
    record_successful_song_mutation,
    start_edit_session,
)


def test_edit_telemetry_counts_successful_mutations_and_export(tmp_path: Path, monkeypatch):
    path = tmp_path / "case-001.product.json"
    started = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)
    start_edit_session(path, case_id="case-001", started_at=started)
    monkeypatch.setenv("AST_TIER2_TELEMETRY_FILE", str(path))

    record_successful_song_mutation(
        song_id="song-1",
        method="PATCH",
        path="/api/songs/song-1/notes/n1",
        status_code=200,
        request_body=b'{"step":"D"}',
    )
    record_successful_song_mutation(
        song_id="song-1",
        method="PATCH",
        path="/api/songs/song-1/notes/n2",
        status_code=200,
        request_body=b'{"lyric":"hello"}',
    )
    record_successful_song_mutation(
        song_id="song-1",
        method="PATCH",
        path="/api/songs/song-1/notes/n3/chord",
        status_code=200,
        request_body=b'{"symbol":"Cmaj7"}',
    )
    record_successful_song_mutation(
        song_id="song-1",
        method="PATCH",
        path="/api/songs/song-1/publication",
        status_code=200,
        request_body=b'{"bars_per_system":4}',
    )
    record_successful_song_mutation(
        song_id="song-1",
        method="POST",
        path="/api/songs/song-1/export",
        status_code=200,
        finished_at=started + timedelta(seconds=125.5),
    )

    payload = read_edit_session(path)
    assert payload["song_id"] == "song-1"
    assert payload["manual_note_edits"] == 1
    assert payload["manual_lyric_edits"] == 1
    assert payload["manual_chord_edits"] == 1
    assert payload["manual_layout_edits"] == 1
    assert payload["total_edit_actions"] == 4
    assert payload["successful_export"] is True
    assert payload["time_to_publish_seconds"] == 125.5


def test_edit_telemetry_ignores_failed_and_other_song_mutations(tmp_path: Path, monkeypatch):
    path = tmp_path / "case-001.product.json"
    start_edit_session(path, case_id="case-001", song_id="song-1")
    monkeypatch.setenv("AST_TIER2_TELEMETRY_FILE", str(path))

    record_successful_song_mutation(
        song_id="song-1",
        method="PATCH",
        path="/api/songs/song-1/notes/n1",
        status_code=422,
        request_body=b'{"step":"D"}',
    )
    record_successful_song_mutation(
        song_id="song-2",
        method="PATCH",
        path="/api/songs/song-2/notes/n1",
        status_code=200,
        request_body=b'{"step":"D"}',
    )

    payload = read_edit_session(path)
    assert payload["total_edit_actions"] == 0
    assert payload["successful_export"] is False

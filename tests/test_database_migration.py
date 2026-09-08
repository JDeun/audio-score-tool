from __future__ import annotations

import sqlite3

from audio_score_tool.paths import database_path


def test_legacy_database_migration_preserves_committed_wal_rows(tmp_path, monkeypatch):
    monkeypatch.setenv("AST_DATA_DIR", str(tmp_path))
    legacy = tmp_path / "jobs.sqlite3"

    connection = sqlite3.connect(legacy)
    try:
        assert connection.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower() == "wal"
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute("CREATE TABLE migration_probe(value TEXT NOT NULL)")
        connection.execute("INSERT INTO migration_probe(value) VALUES ('preserved')")
        connection.commit()

        # Keep the source connection open so the committed transaction remains eligible
        # to live only in the WAL while database_path() performs the first-launch move.
        migrated = database_path()
    finally:
        connection.close()

    assert migrated == tmp_path / "audio-score-tool.sqlite3"
    assert migrated.exists()
    with sqlite3.connect(migrated) as migrated_connection:
        row = migrated_connection.execute("SELECT value FROM migration_probe").fetchone()
    assert row == ("preserved",)

from pathlib import Path

import sqlite3

from audio_score_tool.sqlite_runtime import configure_sqlite


def test_configure_sqlite_enables_wal(tmp_path: Path):
    database = tmp_path / "app.sqlite3"
    status = configure_sqlite(database)

    assert status["journal_mode"] == "wal"
    assert status["busy_timeout_ms"] == 10000
    with sqlite3.connect(database) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"

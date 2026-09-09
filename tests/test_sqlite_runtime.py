import sqlite3
from pathlib import Path

import pytest

from audio_score_tool.song_store_v2 import SongStoreV2
from audio_score_tool.sqlite_runtime import configure_sqlite, connect_sqlite, verify_sqlite_integrity


def test_configure_sqlite_enables_wal(tmp_path: Path):
    database = tmp_path / "app.sqlite3"
    status = configure_sqlite(database)

    assert status["journal_mode"] == "wal"
    assert status["busy_timeout_ms"] == 10000
    with sqlite3.connect(database) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_connect_sqlite_applies_connection_local_runtime_policy(tmp_path: Path):
    database = tmp_path / "app.sqlite3"
    configure_sqlite(database)

    with connect_sqlite(database, row_factory=True) as conn:
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 10000
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1  # NORMAL
        conn.execute("CREATE TABLE demo(value TEXT)")
        conn.execute("INSERT INTO demo(value) VALUES ('ok')")
        row = conn.execute("SELECT value FROM demo").fetchone()
        assert isinstance(row, sqlite3.Row)
        assert row["value"] == "ok"


def test_song_store_uses_shared_connection_policy(tmp_path: Path):
    database = tmp_path / "songs.sqlite3"
    configure_sqlite(database)
    store = SongStoreV2(
        path=database,
        cache_root=tmp_path / "cache",
        asset_root=tmp_path / "assets",
        export_root=tmp_path / "exports",
    )

    with store._connect() as conn:
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 10000
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.row_factory is sqlite3.Row


def test_corrupt_sqlite_is_never_deleted_or_reinitialized(tmp_path: Path):
    database = tmp_path / "corrupt.sqlite3"
    original = b"not a sqlite database\x00\xff" * 64
    database.write_bytes(original)

    with pytest.raises(sqlite3.DatabaseError):
        verify_sqlite_integrity(database)
    assert database.read_bytes() == original

    with pytest.raises(sqlite3.DatabaseError):
        configure_sqlite(database)
    assert database.read_bytes() == original

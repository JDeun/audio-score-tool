from __future__ import annotations

import sqlite3
from pathlib import Path

from .paths import database_path

_BUSY_TIMEOUT_MS = 10_000


def connect_sqlite(path: Path, *, row_factory: bool = False) -> sqlite3.Connection:
    """Open an application SQLite connection with consistent runtime pragmas.

    ``journal_mode=WAL`` is persistent at the database-file level and is configured by
    :func:`configure_sqlite`. ``busy_timeout`` and ``synchronous`` are connection-local,
    so every Store connection must apply them explicitly.
    """
    conn = sqlite3.connect(path, timeout=_BUSY_TIMEOUT_MS / 1000)
    try:
        conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA synchronous=NORMAL")
        if row_factory:
            conn.row_factory = sqlite3.Row
        return conn
    except Exception:
        conn.close()
        raise


def configure_sqlite(path: Path | None = None) -> dict[str, str | int]:
    """Configure database-level WAL mode and verify local connection defaults."""
    target = path or database_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with connect_sqlite(target) as conn:
        journal_mode = str(conn.execute("PRAGMA journal_mode=WAL").fetchone()[0])
        synchronous = int(conn.execute("PRAGMA synchronous").fetchone()[0])
        busy_timeout = int(conn.execute("PRAGMA busy_timeout").fetchone()[0])
    return {
        "journal_mode": journal_mode.lower(),
        "busy_timeout_ms": busy_timeout,
        "synchronous": synchronous,
    }

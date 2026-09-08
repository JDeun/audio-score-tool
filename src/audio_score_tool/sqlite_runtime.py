from __future__ import annotations

import sqlite3
from pathlib import Path

from .paths import database_path


def configure_sqlite(path: Path | None = None) -> dict[str, str | int]:
    """Configure process-wide SQLite durability/concurrency defaults.

    WAL is persistent for the database file and lets background readers/progress writes
    coexist more reliably with score edits. NORMAL synchronous keeps WAL durability
    appropriate for a local desktop database without forcing a full fsync on every page.
    """
    target = path or database_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(target, timeout=10) as conn:
        conn.execute("PRAGMA busy_timeout=10000")
        journal_mode = str(conn.execute("PRAGMA journal_mode=WAL").fetchone()[0])
        conn.execute("PRAGMA synchronous=NORMAL")
        synchronous = int(conn.execute("PRAGMA synchronous").fetchone()[0])
    return {
        "journal_mode": journal_mode.lower(),
        "busy_timeout_ms": 10000,
        "synchronous": synchronous,
    }

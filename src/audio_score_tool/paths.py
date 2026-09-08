from __future__ import annotations

import os
import platform
import sqlite3
from pathlib import Path


def app_data_dir() -> Path:
    override = os.getenv("AST_DATA_DIR")
    if override:
        root = Path(override).expanduser()
    elif platform.system() == "Windows":
        root = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "AudioScoreTool"
    elif platform.system() == "Darwin":
        root = Path.home() / "Library" / "Application Support" / "AudioScoreTool"
    else:
        base = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        root = base / "audio-score-tool"
    root.mkdir(parents=True, exist_ok=True)
    return root


def jobs_dir() -> Path:
    path = app_data_dir() / "jobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_dir() -> Path:
    path = app_data_dir() / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def song_assets_dir() -> Path:
    path = app_data_dir() / "assets" / "songs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def exports_dir() -> Path:
    path = app_data_dir() / "exports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _remove_sqlite_sidecars(path: Path) -> None:
    path.unlink(missing_ok=True)
    Path(f"{path}-wal").unlink(missing_ok=True)
    Path(f"{path}-shm").unlink(missing_ok=True)


def _backup_sqlite(source: Path, destination: Path) -> None:
    """Create a consistent SQLite snapshot, including committed WAL contents."""
    _remove_sqlite_sidecars(destination)
    with sqlite3.connect(source, timeout=10) as source_conn:
        with sqlite3.connect(destination, timeout=10) as destination_conn:
            source_conn.backup(destination_conn)


def database_path() -> Path:
    """Return the canonical application database, migrating the v0.7 filename once.

    v0.7 stored both jobs and songs in ``jobs.sqlite3`` even though the database had
    already become application-wide state. v0.8 uses an explicit application DB name.
    Migration uses SQLite's backup API instead of copying the database file so committed
    changes that still live in a WAL are preserved.
    """

    root = app_data_dir()
    current = root / "audio-score-tool.sqlite3"
    legacy = root / "jobs.sqlite3"
    if not current.exists() and legacy.exists():
        migrating = root / ".audio-score-tool.sqlite3.migrating"
        try:
            _backup_sqlite(legacy, migrating)
            migrating.replace(current)
            _remove_sqlite_sidecars(migrating)
        except (OSError, sqlite3.Error):
            _remove_sqlite_sidecars(migrating)
            # Keep the legacy DB usable if migration is blocked by permissions/locking.
            return legacy
    return current

from __future__ import annotations

import os
import platform
import shutil
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


def database_path() -> Path:
    """Return the canonical application database, migrating the v0.7 filename once.

    v0.7 stored both jobs and songs in ``jobs.sqlite3`` even though the database had
    already become application-wide state. v0.8 uses an explicit application DB name
    while preserving existing data by copying the legacy database on first launch.
    """

    root = app_data_dir()
    current = root / "audio-score-tool.sqlite3"
    legacy = root / "jobs.sqlite3"
    if not current.exists() and legacy.exists():
        migrating = root / ".audio-score-tool.sqlite3.migrating"
        try:
            migrating.unlink(missing_ok=True)
            shutil.copy2(legacy, migrating)
            migrating.replace(current)
        except OSError:
            migrating.unlink(missing_ok=True)
            # Keep the legacy DB usable if migration is blocked by permissions/locking.
            return legacy
    return current

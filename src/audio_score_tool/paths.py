from __future__ import annotations

import os
import platform
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
        root = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "audio-score-tool"
    root.mkdir(parents=True, exist_ok=True)
    return root


def jobs_dir() -> Path:
    path = app_data_dir() / "jobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def database_path() -> Path:
    return app_data_dir() / "jobs.sqlite3"

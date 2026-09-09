from __future__ import annotations

import shutil
from pathlib import Path

from .hf_session import authenticated
from .paths import app_data_dir, jobs_dir


def _dir_size(root: Path) -> int:
    total = 0
    if not root.exists():
        return 0
    for path in root.rglob("*"):
        try:
            if path.is_file():
                total += path.stat().st_size
        except OSError:
            continue
    return total


def huggingface_authenticated() -> bool:
    """Return session/environment auth state without reading arbitrary user caches."""

    return authenticated()


def storage_status() -> dict:
    root = app_data_dir()
    usage = shutil.disk_usage(root)
    return {
        "data_dir": str(root),
        "jobs_bytes": _dir_size(jobs_dir()),
        "disk_total_bytes": usage.total,
        "disk_used_bytes": usage.used,
        "disk_free_bytes": usage.free,
        "hf_authenticated": huggingface_authenticated(),
    }

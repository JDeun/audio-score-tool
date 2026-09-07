from __future__ import annotations

import shutil
from pathlib import Path

from .paths import jobs_dir
from .song_store_v2 import SongStoreV2


def _safe_rmtree(path: Path) -> bool:
    try:
        if path.exists():
            shutil.rmtree(path)
        return True
    except OSError:
        return False


def _safe_unlink(path: Path) -> bool:
    try:
        path.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def recover_startup_state(
    store: SongStoreV2 | None = None,
    *,
    jobs_root: Path | None = None,
) -> dict[str, int]:
    """Best-effort repair of disposable state left by a hard process termination."""
    store = store or SongStoreV2()
    export_root = store.export_root
    try:
        export_root.mkdir(parents=True, exist_ok=True)
    except OSError:
        return {
            "restored_exports": 0,
            "removed_export_backups": 0,
            "removed_staged_exports": 0,
            "removed_partial_uploads": 0,
            "removed_score_work_dirs": 0,
            "removed_staged_job_deletions": 0,
            "recovery_errors": 1,
        }

    restored_exports = 0
    removed_backups = 0
    removed_staged = 0
    removed_uploads = 0
    removed_work_dirs = 0
    removed_job_deletions = 0
    recovery_errors = 0

    try:
        songs = store.list()
    except Exception:
        songs = []
        recovery_errors += 1

    for song in songs:
        song_id = str(song.get("song_id") or "")
        if not song_id:
            continue
        final = export_root / song_id
        try:
            backups = sorted(
                export_root.glob(f".{song_id}.backup-*"),
                key=_safe_mtime,
                reverse=True,
            )
        except OSError:
            backups = []
            recovery_errors += 1

        if final.exists():
            for backup in backups:
                if _safe_rmtree(backup):
                    removed_backups += 1
                else:
                    recovery_errors += 1
        elif backups:
            newest, *older = backups
            try:
                newest.replace(final)
                restored_exports += 1
            except OSError:
                older = backups
                recovery_errors += 1
            for backup in older:
                if _safe_rmtree(backup):
                    removed_backups += 1
                else:
                    recovery_errors += 1

        try:
            staged_items = list(export_root.glob(f".{song_id}-staged-*"))
        except OSError:
            staged_items = []
            recovery_errors += 1
        for staged in staged_items:
            if _safe_rmtree(staged):
                removed_staged += 1
            else:
                recovery_errors += 1

    try:
        orphan_staged = list(export_root.glob(".*-staged-*"))
    except OSError:
        orphan_staged = []
        recovery_errors += 1
    for staged in orphan_staged:
        if _safe_rmtree(staged):
            removed_staged += 1
        else:
            recovery_errors += 1

    root = jobs_root or jobs_dir()
    try:
        partials = list(root.rglob("*.uploading")) if root.exists() else []
    except OSError:
        partials = []
        recovery_errors += 1
    for partial in partials:
        if _safe_unlink(partial):
            removed_uploads += 1
        else:
            recovery_errors += 1

    # Job deletion uses an atomic rename before deleting the DB row. Any `.deleting-*`
    # directory surviving a process restart is disposable staging state and can be swept.
    try:
        deleting_dirs = list(root.glob(".deleting-*")) if root.exists() else []
    except OSError:
        deleting_dirs = []
        recovery_errors += 1
    for deleting in deleting_dirs:
        if _safe_rmtree(deleting):
            removed_job_deletions += 1
        else:
            recovery_errors += 1

    try:
        work_dirs = list(store.cache_root.glob("*/work")) if store.cache_root.exists() else []
    except OSError:
        work_dirs = []
        recovery_errors += 1
    for work in work_dirs:
        if _safe_rmtree(work):
            removed_work_dirs += 1
        else:
            recovery_errors += 1

    return {
        "restored_exports": restored_exports,
        "removed_export_backups": removed_backups,
        "removed_staged_exports": removed_staged,
        "removed_partial_uploads": removed_uploads,
        "removed_score_work_dirs": removed_work_dirs,
        "removed_staged_job_deletions": removed_job_deletions,
        "recovery_errors": recovery_errors,
    }

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


def recover_startup_state(
    store: SongStoreV2 | None = None,
    *,
    jobs_root: Path | None = None,
) -> dict[str, int]:
    """Repair disposable filesystem state left by a hard process termination.

    SQLite is canonical. Work/check-out files and ``*.uploading`` objects are therefore
    safe to discard. Export backups are different: if the process died after moving the
    old final tree aside but before publishing the staged tree, restore the newest backup.
    """
    store = store or SongStoreV2()
    export_root = store.export_root
    export_root.mkdir(parents=True, exist_ok=True)

    restored_exports = 0
    removed_backups = 0
    removed_staged = 0
    removed_uploads = 0
    removed_work_dirs = 0

    for song in store.list():
        song_id = str(song.get("song_id") or "")
        if not song_id:
            continue
        final = export_root / song_id
        backups = sorted(
            export_root.glob(f".{song_id}.backup-*"),
            key=lambda path: path.stat().st_mtime if path.exists() else 0,
            reverse=True,
        )
        if final.exists():
            for backup in backups:
                if _safe_rmtree(backup):
                    removed_backups += 1
        elif backups:
            newest, *older = backups
            try:
                newest.replace(final)
                restored_exports += 1
            except OSError:
                older = backups
            for backup in older:
                if _safe_rmtree(backup):
                    removed_backups += 1

        for staged in export_root.glob(f".{song_id}-staged-*"):
            if _safe_rmtree(staged):
                removed_staged += 1

    # Staged exports for songs that were deleted before the crash are always disposable.
    for staged in export_root.glob(".*-staged-*"):
        if _safe_rmtree(staged):
            removed_staged += 1

    # Upload persistence uses an atomic .uploading suffix. A leftover file was never
    # promoted to a valid job input and must not be consumed after restart.
    root = jobs_root or jobs_dir()
    if root.exists():
        for partial in root.rglob("*.uploading"):
            if _safe_unlink(partial):
                removed_uploads += 1

    # Materialized MusicXML work files are projections of canonical SQLite state.
    if store.cache_root.exists():
        for work in store.cache_root.glob("*/work"):
            if _safe_rmtree(work):
                removed_work_dirs += 1

    return {
        "restored_exports": restored_exports,
        "removed_export_backups": removed_backups,
        "removed_staged_exports": removed_staged,
        "removed_partial_uploads": removed_uploads,
        "removed_score_work_dirs": removed_work_dirs,
    }

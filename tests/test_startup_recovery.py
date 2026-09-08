from pathlib import Path

from audio_score_tool.song_store_v2 import SongStoreV2
from audio_score_tool.startup_recovery import recover_startup_state

SCORE = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list>
  <part id="P1"><measure number="1"/></part>
</score-partwise>
"""


class FakeJobStore:
    def __init__(self, job_ids: set[str] | None = None):
        self.job_ids = job_ids or set()

    def get(self, job_id: str):
        return {"job_id": job_id} if job_id in self.job_ids else None


def _store(tmp_path: Path) -> SongStoreV2:
    store = SongStoreV2(
        path=tmp_path / "app.sqlite3",
        cache_root=tmp_path / "cache" / "scores",
        asset_root=tmp_path / "assets",
        export_root=tmp_path / "exports",
    )
    source = tmp_path / "generated.musicxml"
    source.write_text(SCORE, encoding="utf-8")
    assert store.sync_completed_jobs([
        {
            "job_id": "song-1",
            "status": "done",
            "kind": "transcription",
            "filename": "demo.wav",
            "result": {"musicxml": str(source)},
        }
    ]) == 1
    return store


def test_startup_recovery_restores_export_backup_and_removes_disposable_state(tmp_path: Path):
    store = _store(tmp_path)
    backup = store.export_root / ".song-1.backup-deadbeef"
    backup.mkdir(parents=True)
    (backup / "score.pdf").write_bytes(b"old-pdf")
    staged = store.export_root / ".song-1-staged-deadbeef"
    staged.mkdir()
    (staged / "score.pdf").write_bytes(b"partial")

    work = store.cache_root / "song-1" / "work"
    work.mkdir(parents=True)
    (work / "score.musicxml").write_text(SCORE, encoding="utf-8")

    jobs_root = tmp_path / "jobs"
    jobs_root.mkdir()
    partial = jobs_root / "input.wav.uploading"
    partial.write_bytes(b"partial")
    deleting = jobs_root / ".deleting-old-job-0123456789abcdef0123456789abcdef"
    deleting.mkdir()
    (deleting / "input.wav").write_bytes(b"old")

    report = recover_startup_state(
        store,
        jobs_root=jobs_root,
        job_store=FakeJobStore(),
    )

    assert (store.export_root / "song-1" / "score.pdf").read_bytes() == b"old-pdf"
    assert not backup.exists()
    assert not staged.exists()
    assert not work.exists()
    assert not partial.exists()
    assert not deleting.exists()
    assert report["restored_exports"] == 1
    assert report["removed_staged_exports"] >= 1
    assert report["removed_partial_uploads"] == 1
    assert report["removed_score_work_dirs"] == 1
    assert report["removed_staged_job_deletions"] == 1
    assert report["restored_staged_job_deletions"] == 0


def test_startup_recovery_restores_job_workspace_if_db_delete_did_not_commit(tmp_path: Path):
    store = _store(tmp_path)
    jobs_root = tmp_path / "jobs"
    jobs_root.mkdir()
    job_id = "job-still-present"
    staged = jobs_root / f".deleting-{job_id}-0123456789abcdef0123456789abcdef"
    staged.mkdir()
    (staged / "input.wav").write_bytes(b"retryable")

    report = recover_startup_state(
        store,
        jobs_root=jobs_root,
        job_store=FakeJobStore({job_id}),
    )

    restored = jobs_root / job_id
    assert restored.is_dir()
    assert (restored / "input.wav").read_bytes() == b"retryable"
    assert not staged.exists()
    assert report["restored_staged_job_deletions"] == 1
    assert report["removed_staged_job_deletions"] == 0


def test_startup_recovery_preserves_unknown_staged_deletion_without_job_lookup(tmp_path: Path):
    store = _store(tmp_path)
    jobs_root = tmp_path / "jobs"
    jobs_root.mkdir()
    staged = jobs_root / ".deleting-unknown-0123456789abcdef0123456789abcdef"
    staged.mkdir()

    report = recover_startup_state(store, jobs_root=jobs_root)

    assert staged.exists()
    assert report["recovery_errors"] >= 1


def test_startup_recovery_keeps_current_export_and_drops_stale_backup(tmp_path: Path):
    store = _store(tmp_path)
    final = store.export_root / "song-1"
    final.mkdir(parents=True)
    (final / "score.pdf").write_bytes(b"current")
    backup = store.export_root / ".song-1.backup-old"
    backup.mkdir()
    (backup / "score.pdf").write_bytes(b"old")

    report = recover_startup_state(store, jobs_root=tmp_path / "jobs")

    assert (final / "score.pdf").read_bytes() == b"current"
    assert not backup.exists()
    assert report["removed_export_backups"] == 1

from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from .paths import app_data_dir, database_path, jobs_dir


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SongStore:
    def __init__(self, path: Path | None = None, root: Path | None = None):
        self.path = path or database_path()
        self.root = root or (app_data_dir() / "songs")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS songs (
                    song_id TEXT PRIMARY KEY,
                    job_id TEXT UNIQUE,
                    title TEXT NOT NULL,
                    artist TEXT,
                    source_kind TEXT NOT NULL DEFAULT 'transcription',
                    original_musicxml TEXT NOT NULL,
                    current_musicxml TEXT NOT NULL,
                    original_midi TEXT,
                    original_pdf TEXT,
                    revision INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    @staticmethod
    def _title_from_filename(value: str | None) -> str:
        if not value:
            return "제목 없는 곡"
        path = Path(value)
        if path.suffix:
            return path.stem or value
        return value

    @staticmethod
    def _source_kind(job: dict[str, Any], source_dir: Path) -> str:
        filename = job.get("filename") or ""
        has_extension = bool(Path(filename).suffix)
        if not has_extension and any(source_dir.glob("input.*")):
            return "youtube"
        return "local"

    def sync_completed_jobs(self, jobs: list[dict[str, Any]]) -> int:
        created = 0
        for job in jobs:
            if job.get("kind") == "benchmark" or job.get("status") != "done":
                continue
            result = job.get("result") or {}
            source_xml = result.get("lyric_musicxml") or result.get("musicxml")
            if not source_xml:
                continue
            source_path = Path(source_xml)
            if not source_path.exists():
                continue
            if self.get_by_job(job["job_id"]):
                continue

            song_id = job["job_id"]
            song_dir = self.root / song_id
            song_dir.mkdir(parents=True, exist_ok=True)
            original_xml = song_dir / "original.musicxml"
            current_xml = song_dir / "score.musicxml"
            shutil.copy2(source_path, original_xml)
            shutil.copy2(source_path, current_xml)

            original_midi: Path | None = None
            midi_source = result.get("midi")
            if midi_source and Path(midi_source).exists():
                original_midi = song_dir / "original.mid"
                shutil.copy2(midi_source, original_midi)

            original_pdf: Path | None = None
            pdf_source = result.get("pdf")
            if pdf_source and Path(pdf_source).exists():
                original_pdf = song_dir / "original.pdf"
                shutil.copy2(pdf_source, original_pdf)

            now = _now()
            with self._lock, self._connect() as conn:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO songs (
                        song_id, job_id, title, artist, source_kind,
                        original_musicxml, current_musicxml, original_midi, original_pdf,
                        revision, created_at, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        song_id,
                        job["job_id"],
                        self._title_from_filename(job.get("filename")),
                        None,
                        self._source_kind(job, jobs_dir() / job["job_id"]),
                        str(original_xml),
                        str(current_xml),
                        str(original_midi) if original_midi else None,
                        str(original_pdf) if original_pdf else None,
                        1,
                        now,
                        now,
                    ),
                )
                if conn.total_changes:
                    created += 1
        return created

    def list(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM songs ORDER BY updated_at DESC").fetchall()
        return [self._row(row) for row in rows]

    def get(self, song_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM songs WHERE song_id=?", (song_id,)).fetchone()
        return self._row(row) if row else None

    def get_by_job(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM songs WHERE job_id=?", (job_id,)).fetchone()
        return self._row(row) if row else None

    def update_metadata(
        self,
        song_id: str,
        *,
        title: str | None = None,
        artist: str | None = None,
    ) -> dict[str, Any] | None:
        fields: dict[str, Any] = {}
        if title is not None:
            fields["title"] = title.strip() or "제목 없는 곡"
        if artist is not None:
            fields["artist"] = artist.strip() or None
        if not fields:
            return self.get(song_id)
        fields["updated_at"] = _now()
        assignments = ", ".join(f"{key}=?" for key in fields)
        with self._lock, self._connect() as conn:
            conn.execute(
                f"UPDATE songs SET {assignments} WHERE song_id=?",
                (*fields.values(), song_id),
            )
        return self.get(song_id)

    def bump_revision(self, song_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE songs SET revision=revision+1, updated_at=? WHERE song_id=?",
                (_now(), song_id),
            )
        return self.get(song_id)

    def set_revision(self, song_id: str, revision: int) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE songs SET revision=?, updated_at=? WHERE song_id=?",
                (max(1, revision), _now(), song_id),
            )
        return self.get(song_id)

    def song_dir(self, song_id: str) -> Path:
        return self.root / song_id

    def revision_dir(self, song_id: str) -> Path:
        path = self.song_dir(song_id) / "revisions"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def export_dir(self, song_id: str) -> Path:
        path = self.song_dir(song_id) / "exports"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def clear_exports(self, song_id: str) -> None:
        export_dir = self.song_dir(song_id) / "exports"
        if not export_dir.exists():
            return
        for name in ("score.pdf", "score.mid"):
            (export_dir / name).unlink(missing_ok=True)

    def delete(self, song_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM songs WHERE song_id=?", (song_id,))
        if cur.rowcount:
            shutil.rmtree(self.song_dir(song_id), ignore_errors=True)
            return True
        return False

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["exports"] = {}
        song_dir = Path(result["current_musicxml"]).parent
        export_dir = song_dir / "exports"
        for kind, name in (("pdf", "score.pdf"), ("midi", "score.mid")):
            path = export_dir / name
            if path.exists():
                result["exports"][kind] = str(path)
        return result

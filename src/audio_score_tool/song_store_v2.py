from __future__ import annotations

import json
import shutil
import sqlite3
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from .paths import cache_dir, database_path, exports_dir, jobs_dir, song_assets_dir


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(text, encoding="utf-8")
    temp.replace(path)


def _valid_score_xml(text: str) -> str:
    if not text.strip():
        raise ValueError("MusicXML document is empty")
    root = ET.fromstring(text)
    if root.tag.rsplit("}", 1)[-1] not in {"score-partwise", "score-timewise"}:
        raise ValueError("Document is not a MusicXML score")
    return text


class SongStoreV2:
    """SQLite-canonical Song/Score store with managed cache and explicit exports.

    MusicXML, publication-compatible revision snapshots, and analysis JSON live in the
    database. Files under ``cache`` are disposable materializations for libraries and
    external tools that require paths. Files under ``exports`` are created only by an
    explicit final-export action.
    """

    def __init__(
        self,
        path: Path | None = None,
        cache_root: Path | None = None,
        asset_root: Path | None = None,
        export_root: Path | None = None,
    ):
        self.path = path or database_path()
        self.cache_root = cache_root or (cache_dir() / "scores")
        self.asset_root = asset_root or song_assets_dir()
        self.export_root = export_root or exports_dir()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self.asset_root.mkdir(parents=True, exist_ok=True)
        self.export_root.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._init()
        self._migrate_legacy_rows()
        self._migrate_source_kinds()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}

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
                    original_musicxml TEXT,
                    current_musicxml TEXT,
                    original_midi TEXT,
                    original_pdf TEXT,
                    original_score_xml TEXT,
                    current_score_xml TEXT,
                    revision INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            columns = self._columns(conn, "songs")
            for name, ddl in (
                ("original_score_xml", "TEXT"),
                ("current_score_xml", "TEXT"),
            ):
                if name not in columns:
                    conn.execute(f"ALTER TABLE songs ADD COLUMN {name} {ddl}")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS song_revisions (
                    song_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    musicxml TEXT NOT NULL,
                    publication_json TEXT NOT NULL,
                    title TEXT NOT NULL,
                    artist TEXT,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(song_id, revision)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS song_analysis (
                    song_id TEXT NOT NULL,
                    analysis_type TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(song_id, analysis_type)
                )
                """
            )

    @staticmethod
    def _legacy_xml(value: str | None) -> str | None:
        if not value:
            return None
        stripped = value.lstrip()
        if stripped.startswith("<?xml") or stripped.startswith("<score-"):
            try:
                return _valid_score_xml(value)
            except (ValueError, ET.ParseError):
                return None
        try:
            path = Path(value)
            if path.is_file():
                return _valid_score_xml(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, ET.ParseError):
            return None
        return None

    def _migrate_legacy_rows(self) -> None:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT song_id, original_musicxml, current_musicxml,
                       original_score_xml, current_score_xml
                FROM songs
                WHERE original_score_xml IS NULL OR current_score_xml IS NULL
                """
            ).fetchall()
        for row in rows:
            original = row["original_score_xml"] or self._legacy_xml(row["original_musicxml"])
            current = row["current_score_xml"] or self._legacy_xml(row["current_musicxml"])
            original = original or current
            current = current or original
            if not original or not current:
                continue
            with self._lock, self._connect() as conn:
                conn.execute(
                    """
                    UPDATE songs
                    SET original_score_xml=?, current_score_xml=?, updated_at=?
                    WHERE song_id=?
                    """,
                    (original, current, _now(), row["song_id"]),
                )

    def _migrate_source_kinds(self) -> None:
        """Repair early v0.8 OMR rows that were incorrectly labelled as local audio."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT song_id, source_kind FROM songs WHERE source_kind='local'"
            ).fetchall()
        for row in rows:
            asset_dir = self.asset_root / str(row["song_id"])
            if asset_dir.exists() and any(asset_dir.glob("original-score.*")):
                with self._lock, self._connect() as conn:
                    conn.execute(
                        "UPDATE songs SET source_kind=?, updated_at=? WHERE song_id=? AND source_kind='local'",
                        ("omr", _now(), row["song_id"]),
                    )

    @staticmethod
    def _title_from_filename(value: str | None) -> str:
        if not value:
            return "제목 없는 곡"
        path = Path(value)
        return path.stem if path.suffix and path.stem else value

    @staticmethod
    def _source_kind(job: dict[str, Any]) -> str:
        if str(job.get("kind") or "").lower() == "omr":
            return "omr"
        filename = str(job.get("filename") or "")
        if filename and not Path(filename).suffix:
            return "youtube"
        source_dir = jobs_dir() / str(job.get("job_id") or "")
        is_youtube_cache = (
            source_dir.exists()
            and any(source_dir.glob("input.*"))
            and not Path(filename).suffix
        )
        return "youtube" if is_youtube_cache else "local"

    def _exists_by_job(self, job_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM songs WHERE job_id=?", (job_id,)).fetchone()
        return row is not None

    def _copy_midi_asset(self, song_id: str, source: str | None) -> str | None:
        if not source:
            return None
        path = Path(source)
        if not path.is_file():
            return None
        target = self.asset_root / song_id / "original.mid"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        return str(target)

    def _ingest_json_file(self, song_id: str, kind: str, path_value: str | None) -> None:
        if not path_value:
            return
        path = Path(path_value)
        if not path.is_file():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        self.set_analysis(song_id, kind, payload)

    def sync_completed_jobs(self, jobs: list[dict[str, Any]]) -> int:
        created = 0
        for job in jobs:
            if job.get("kind") == "benchmark" or job.get("status") != "done":
                continue
            job_id = str(job.get("job_id") or "")
            if not job_id or self._exists_by_job(job_id):
                continue
            result = job.get("result") or {}
            source_value = result.get("lyric_musicxml") or result.get("musicxml")
            if not source_value:
                continue
            source = Path(source_value)
            if not source.is_file():
                continue
            try:
                score_xml = _valid_score_xml(source.read_text(encoding="utf-8"))
            except (OSError, ValueError, ET.ParseError):
                continue

            now = _now()
            midi_asset = self._copy_midi_asset(job_id, result.get("midi"))
            with self._lock, self._connect() as conn:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO songs (
                        song_id, job_id, title, artist, source_kind,
                        original_musicxml, current_musicxml, original_midi, original_pdf,
                        original_score_xml, current_score_xml,
                        revision, created_at, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        job_id,
                        job_id,
                        self._title_from_filename(job.get("filename")),
                        None,
                        self._source_kind(job),
                        str(source),
                        str(source),
                        midi_asset,
                        None,
                        score_xml,
                        score_xml,
                        1,
                        now,
                        now,
                    ),
                )
                inserted = conn.total_changes > 0
            if not inserted:
                continue
            created += 1
            self._ingest_json_file(job_id, "automatic_chords", result.get("chord_report"))
            self._ingest_json_file(job_id, "lyrics_transcript", result.get("transcript_json"))
            work_dir = result.get("work_dir")
            if work_dir:
                alignment = str(Path(work_dir) / "alignment.json")
                self._ingest_json_file(job_id, "lyric_alignment", alignment)
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

    def score_xml(self, song_id: str, *, original: bool = False) -> str:
        column = "original_score_xml" if original else "current_score_xml"
        with self._connect() as conn:
            row = conn.execute(f"SELECT {column} FROM songs WHERE song_id=?", (song_id,)).fetchone()
        if not row or not row[column]:
            raise KeyError(song_id)
        return str(row[column])

    def cache_song_dir(self, song_id: str) -> Path:
        path = self.cache_root / song_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def checkout_current(self, song_id: str) -> Path:
        path = self.cache_song_dir(song_id) / "score.musicxml"
        _atomic_text(path, self.score_xml(song_id))
        return path

    def checkout_original(self, song_id: str) -> Path:
        path = self.cache_song_dir(song_id) / "original.musicxml"
        _atomic_text(path, self.score_xml(song_id, original=True))
        return path

    def replace_current_from_path(self, song_id: str, path: Path) -> dict[str, Any] | None:
        text = _valid_score_xml(path.read_text(encoding="utf-8"))
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE songs SET current_score_xml=?, updated_at=? WHERE song_id=?",
                (text, _now(), song_id),
            )
        return self.get(song_id)

    def commit_edit_from_path(self, song_id: str, path: Path) -> dict[str, Any] | None:
        text = _valid_score_xml(path.read_text(encoding="utf-8"))
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE songs
                SET current_score_xml=?, revision=revision+1, updated_at=?
                WHERE song_id=?
                """,
                (text, _now(), song_id),
            )
        self.clear_exports(song_id)
        return self.get(song_id)

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

    def snapshot_revision(self, song_id: str, publication: dict[str, Any]) -> int:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT revision, current_score_xml, title, artist FROM songs WHERE song_id=?",
                (song_id,),
            ).fetchone()
            if not row or not row["current_score_xml"]:
                raise KeyError(song_id)
            revision = int(row["revision"])
            conn.execute(
                """
                INSERT OR REPLACE INTO song_revisions(
                    song_id, revision, musicxml, publication_json, title, artist, created_at
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    song_id,
                    revision,
                    row["current_score_xml"],
                    json.dumps(publication, ensure_ascii=False, separators=(",", ":")),
                    row["title"],
                    row["artist"],
                    _now(),
                ),
            )
        return revision

    def discard_snapshot(self, song_id: str, revision: int) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "DELETE FROM song_revisions WHERE song_id=? AND revision=?",
                (song_id, revision),
            )

    def restore_revision(self, song_id: str, revision: int) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT musicxml, publication_json, title, artist
                FROM song_revisions WHERE song_id=? AND revision=?
                """,
                (song_id, revision),
            ).fetchone()
            if not row:
                return None
            conn.execute(
                """
                UPDATE songs
                SET current_score_xml=?, title=?, artist=?, revision=?, updated_at=?
                WHERE song_id=?
                """,
                (row["musicxml"], row["title"], row["artist"], revision, _now(), song_id),
            )
            conn.execute(
                "DELETE FROM song_revisions WHERE song_id=? AND revision>=?",
                (song_id, revision),
            )
        self.clear_exports(song_id)
        shutil.rmtree(self.cache_root / song_id, ignore_errors=True)
        try:
            publication = json.loads(row["publication_json"])
        except json.JSONDecodeError:
            publication = {}
        return publication if isinstance(publication, dict) else {}

    def set_analysis(self, song_id: str, analysis_type: str, data: Any) -> None:
        encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO song_analysis(song_id, analysis_type, data_json, updated_at)
                VALUES(?,?,?,?)
                ON CONFLICT(song_id, analysis_type) DO UPDATE SET
                    data_json=excluded.data_json,
                    updated_at=excluded.updated_at
                """,
                (song_id, analysis_type, encoded, _now()),
            )

    def analysis(self, song_id: str, analysis_type: str) -> Any | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT data_json FROM song_analysis WHERE song_id=? AND analysis_type=?",
                (song_id, analysis_type),
            ).fetchone()
        if not row:
            return None
        try:
            return json.loads(row["data_json"])
        except json.JSONDecodeError:
            return None

    def export_dir(self, song_id: str) -> Path:
        path = self.export_root / song_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def clear_exports(self, song_id: str) -> None:
        shutil.rmtree(self.export_root / song_id, ignore_errors=True)

    def delete(self, song_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM songs WHERE song_id=?", (song_id,))
            conn.execute("DELETE FROM song_revisions WHERE song_id=?", (song_id,))
            conn.execute("DELETE FROM song_analysis WHERE song_id=?", (song_id,))
            if "publication_settings" in {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }:
                conn.execute("DELETE FROM publication_settings WHERE song_id=?", (song_id,))
        if not cur.rowcount:
            return False
        shutil.rmtree(self.cache_root / song_id, ignore_errors=True)
        shutil.rmtree(self.asset_root / song_id, ignore_errors=True)
        shutil.rmtree(self.export_root / song_id, ignore_errors=True)
        return True

    def _row(self, row: sqlite3.Row) -> dict[str, Any]:
        # Reading song metadata must be side-effect free. Earlier v0.8 code rewrote the
        # shared score cache here, so a background list/get request could overwrite a
        # MusicXML file while an edit operation was mutating it before commit.
        result = dict(row)
        original_xml = result.pop("original_score_xml", None)
        current_xml = result.pop("current_score_xml", None)
        if original_xml:
            result["original_musicxml"] = str(self.cache_root / result["song_id"] / "original.musicxml")
        if current_xml:
            result["current_musicxml"] = str(self.cache_root / result["song_id"] / "score.musicxml")
        export_dir = self.export_root / result["song_id"]
        result["exports"] = {}
        for kind, name in (
            ("musicxml", "score.musicxml"),
            ("pdf", "score.pdf"),
            ("midi", "score.mid"),
        ):
            path = export_dir / name
            if path.exists():
                result["exports"][kind] = str(path)
        return result

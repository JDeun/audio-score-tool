from __future__ import annotations

import json
import re
import shutil
import sqlite3
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock, get_ident
from typing import Any

from .model_evidence import preserve_model_evidence
from .paths import cache_dir, database_path, exports_dir, jobs_dir, song_assets_dir
from .score_requests import requested_parts_for_mode, validate_score_mode
from .settings_store import SettingsStore
from .sqlite_runtime import connect_sqlite


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


class ConcurrentEditError(RuntimeError):
    """Raised when a score changed after a caller checked out its edit buffer."""


@dataclass(frozen=True)
class SongExportSnapshot:
    song_id: str
    title: str
    artist: str | None
    revision: int
    current_score_xml: str
    updated_at: str
    publication_json: str | None


class SongStoreV2:
    """SQLite-canonical Song/Score store with managed cache and explicit exports."""

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
        return connect_sqlite(self.path, row_factory=True)

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
            for name, ddl in (("original_score_xml", "TEXT"), ("current_score_xml", "TEXT")):
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
                    "UPDATE songs SET original_score_xml=?, current_score_xml=?, updated_at=? WHERE song_id=?",
                    (original, current, _now(), row["song_id"]),
                )

    def _migrate_source_kinds(self) -> None:
        with self._connect() as conn:
            rows = conn.execute("SELECT song_id FROM songs WHERE source_kind='local'").fetchall()
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
        kind = str(job.get("kind") or "").lower()
        if kind == "omr":
            return "omr"
        if kind == "notation-import":
            return "notation"
        # New Jobs carry an explicit, durable source marker. A YouTube title
        # can contain .mp3, dates or dots and must not determine provenance.
        # Pre-migration records have NULL and retain the legacy heuristic.
        declared = job.get("source_kind")
        if declared in {"local", "youtube"}:
            return declared
        filename = str(job.get("filename") or "")
        if filename and not Path(filename).suffix:
            return "youtube"
        source_dir = jobs_dir() / str(job.get("job_id") or "")
        is_youtube_cache = source_dir.exists() and any(source_dir.glob("input.*")) and not Path(filename).suffix
        return "youtube" if is_youtube_cache else "local"

    def _exists_by_job(self, job_id: str) -> bool:
        with self._connect() as conn:
            return conn.execute("SELECT 1 FROM songs WHERE job_id=?", (job_id,)).fetchone() is not None

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

    def _preserve_original_audio(self, song_id: str) -> Path | None:
        """Copy an owned Job input into Song assets for later local identification.

        A completed Job may be deleted by storage cleanup. The source audio
        must survive in the Song workspace, independently of temporary Jobs.
        Reject symlinks and unsupported sources; never load from arbitrary
        directories or use a caller-provided path.
        """
        safe_suffixes = {
            ".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".webm",
        }
        jobs_root = jobs_dir().resolve()
        source_dir = jobs_root / song_id
        if source_dir.is_symlink():
            return None
        root = source_dir.resolve()
        if root.parent != jobs_root or not root.is_dir():
            return None
        candidates = sorted(
            file for file in root.glob("input.*")
            if file.is_file() and not file.is_symlink()
            and file.suffix.lower() in safe_suffixes
            and file.resolve().parent == root
        )
        if len(candidates) != 1:
            return None
        original = candidates[0]
        assets_root = self.asset_root.resolve()
        target_dir = self.asset_root / song_id
        if target_dir.is_symlink():
            return None
        target_dir.mkdir(parents=True, exist_ok=True)
        if target_dir.resolve().parent != assets_root:
            return None
        target = target_dir / f"original-audio{original.suffix.lower()}"
        if target.exists():
            return target if target.is_file() and not target.is_symlink() else None
        temp = target.with_suffix(target.suffix + ".copying")
        try:
            with original.open("rb") as source, temp.open("xb") as destination:
                shutil.copyfileobj(source, destination)
            temp.replace(target)
        except OSError:
            temp.unlink(missing_ok=True)
            return None
        return target

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

    def preserve_job_evidence(self, job: dict[str, Any]) -> bool:
        """A model Job is disposable only after its observations are durably owned."""
        try:
            report = preserve_model_evidence(job, jobs_root=jobs_dir(), asset_root=self.asset_root)
        except (OSError, ValueError, KeyError, TypeError):
            return False
        if self._exists_by_job(str(job.get("job_id") or "")):
            self.set_analysis(str(job["job_id"]), "model_evidence", report)
        return True

    def sync_completed_jobs(self, jobs: list[dict[str, Any]]) -> int:
        created = 0
        for job in jobs:
            if job.get("kind") == "benchmark" or job.get("status") != "done":
                continue
            job_id = str(job.get("job_id") or "")
            if not job_id:
                continue
            if self._exists_by_job(job_id):
                self.preserve_job_evidence(job)
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
            if not self.preserve_job_evidence(job):
                continue
            now = _now()
            midi_asset = self._copy_midi_asset(job_id, result.get("midi"))
            with self._lock, self._connect() as conn:
                before = conn.total_changes
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
                        job_id, job_id, self._title_from_filename(job.get("filename")), None,
                        self._source_kind(job), str(source), str(source), midi_asset, None,
                        score_xml, score_xml, 1, now, now,
                    ),
                )
                inserted = conn.total_changes > before
            if not inserted:
                continue
            created += 1
            self.preserve_job_evidence(job)
            audio = None
            if self._source_kind(job) in {"local", "youtube"}:
                audio = self._preserve_original_audio(job_id)
            mode = validate_score_mode(job.get("score_mode") or "full")
            self.set_analysis(job_id, "score_request", {
                "score_mode": mode,
                "requested_parts": requested_parts_for_mode(mode),
                "source_kind": self._source_kind(job),
            })
            self._ingest_json_file(job_id, "automatic_chords", result.get("chord_report"))
            self._ingest_json_file(job_id, "lyrics_transcript", result.get("transcript_json"))
            work_dir = result.get("work_dir")
            if work_dir:
                self._ingest_json_file(job_id, "lyric_alignment", str(Path(work_dir) / "alignment.json"))
            # Local-only automatic tags are opt-in and run once per newly
            # imported audio Song. No external services are called.
            try:
                enabled = (
                    SettingsStore().read().get("auto_local_identification_enabled") == "true"
                )
                if enabled and audio is not None:
                    from .local_source_identification import identify_local_on_import

                    identify_local_on_import(self, job_id, audio)
            except Exception:
                # Optional metadata processing must not block Job -> Song ingestion.
                pass
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

    def _current_state(self, song_id: str) -> tuple[str, int]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT current_score_xml, revision FROM songs WHERE song_id=?",
                (song_id,),
            ).fetchone()
        if not row or not row["current_score_xml"]:
            raise KeyError(song_id)
        return str(row["current_score_xml"]), int(row["revision"])

    @staticmethod
    def _read_export_snapshot(conn: sqlite3.Connection, song_id: str) -> SongExportSnapshot:
        # One SELECT binds metadata, canonical notes, revision and publication
        # settings to the same SQLite snapshot, including background enrichment.
        row = conn.execute(
            """
            SELECT s.song_id, s.title, s.artist, s.revision, s.current_score_xml,
                   s.updated_at, p.settings_json AS publication_json
            FROM songs AS s LEFT JOIN publication_settings AS p ON p.song_id=s.song_id
            WHERE s.song_id=?
            """,
            (song_id,),
        ).fetchone()
        if not row or not row["current_score_xml"]:
            raise KeyError(song_id)
        return SongExportSnapshot(**dict(row))

    def export_snapshot(self, song_id: str) -> SongExportSnapshot:
        with closing(self._connect()) as conn:
            return self._read_export_snapshot(conn, song_id)

    @contextmanager
    def guard_export_snapshot(self, snapshot: SongExportSnapshot) -> Iterator[None]:
        """Keep the final check and filesystem activation atomic with DB writers.

        Rendering and cross-filesystem copying must happen before this short
        guard. BEGIN IMMEDIATE coordinates independent Store instances/processes;
        an instance-local lock or the HTTP mutation lane cannot protect workers.
        """
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                try:
                    current = self._read_export_snapshot(conn, snapshot.song_id)
                except KeyError:
                    current = None
                if current != snapshot:
                    raise ConcurrentEditError("Song changed while its export was being prepared.")
                yield
            finally:
                conn.rollback()

    def cache_song_dir(self, song_id: str) -> Path:
        path = self.cache_root / song_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _thread_materialization(self, song_id: str, stem: str) -> Path:
        return self.cache_song_dir(song_id) / "work" / f"{stem}-{get_ident()}.musicxml"

    def checkout_current(self, song_id: str) -> Path:
        text, revision = self._current_state(song_id)
        path = self._thread_materialization(song_id, f"current-r{revision}")
        _atomic_text(path, text)
        return path

    def checkout_original(self, song_id: str) -> Path:
        path = self._thread_materialization(song_id, "original")
        _atomic_text(path, self.score_xml(song_id, original=True))
        return path

    @staticmethod
    def _revision_from_materialized_path(path: Path) -> int | None:
        match = re.search(r"(?:^|-)current-r(\d+)(?:-|$)", path.stem)
        return int(match.group(1)) if match else None

    def replace_current_from_path(self, song_id: str, path: Path) -> dict[str, Any] | None:
        text = _valid_score_xml(path.read_text(encoding="utf-8"))
        with self._lock, self._connect() as conn:
            conn.execute("UPDATE songs SET current_score_xml=?, updated_at=? WHERE song_id=?", (text, _now(), song_id))
        return self.get(song_id)

    def commit_edit_from_path(
        self,
        song_id: str,
        path: Path,
        *,
        expected_revision: int | None = None,
    ) -> dict[str, Any] | None:
        text = _valid_score_xml(path.read_text(encoding="utf-8"))
        if expected_revision is None:
            expected_revision = self._revision_from_materialized_path(path)
        retired_exports = None
        with self._lock, self._connect() as conn:
            if expected_revision is None:
                cur = conn.execute(
                    "UPDATE songs SET current_score_xml=?, revision=revision+1, updated_at=? WHERE song_id=?",
                    (text, _now(), song_id),
                )
            else:
                cur = conn.execute(
                    """
                    UPDATE songs
                    SET current_score_xml=?, revision=revision+1, updated_at=?
                    WHERE song_id=? AND revision=?
                    """,
                    (text, _now(), song_id, expected_revision),
                )
                if cur.rowcount == 0:
                    exists = conn.execute("SELECT 1 FROM songs WHERE song_id=?", (song_id,)).fetchone()
                    if exists:
                        raise ConcurrentEditError(
                            f"Song {song_id} changed while this edit was in progress. Reload and retry."
                        )
            if cur.rowcount == 0:
                return None
            retired_exports = self._detach_exports(song_id)
        if retired_exports is not None:
            shutil.rmtree(retired_exports, ignore_errors=True)
        return self.get(song_id)

    def commit_identified_metadata(
        self,
        song_id: str,
        *,
        title: str,
        artist: str | None,
        score_xml: str,
        publication: dict[str, Any],
        expected_revision: int,
        next_publication: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Commit identified metadata and canonical MusicXML as one Undo revision.

        Never persist a snapshot before validating the expected revision. An
        artist-only change must be as undoable as a title/score change, while a
        repeated identical identification must not inflate revisions or remove
        otherwise valid exports.
        """
        xml_text = _valid_score_xml(score_xml)
        normalized_title = title.strip() or "제목 없는 곡"
        normalized_artist = artist.strip() or None if artist is not None else None
        serialized_publication = json.dumps(
            publication, ensure_ascii=False, separators=(",", ":")
        )
        serialized_next_publication = (
            json.dumps(next_publication, ensure_ascii=False, separators=(",", ":"))
            if next_publication is not None else None
        )
        changed = False
        retired_exports = None
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT revision, title, artist, current_score_xml
                FROM songs WHERE song_id=?
                """,
                (song_id,),
            ).fetchone()
            if not row or not row["current_score_xml"]:
                raise KeyError(song_id)
            revision = int(row["revision"])
            if revision != expected_revision:
                raise ConcurrentEditError(
                    f"Song {song_id} changed during source identification. Reload and retry."
                )
            changed = (
                row["title"] != normalized_title
                or row["artist"] != normalized_artist
                or row["current_score_xml"] != xml_text
                or (
                    serialized_next_publication is not None
                    and serialized_next_publication != serialized_publication
                )
            )
            if changed:
                stamp = _now()
                conn.execute(
                    """
                    INSERT OR REPLACE INTO song_revisions(
                        song_id, revision, musicxml, publication_json,
                        title, artist, created_at
                    ) VALUES(?,?,?,?,?,?,?)
                    """,
                    (
                        song_id, revision, row["current_score_xml"],
                        serialized_publication, row["title"], row["artist"], stamp,
                    ),
                )
                if serialized_next_publication is not None:
                    conn.execute(
                        """
                        INSERT INTO publication_settings(song_id, settings_json, updated_at)
                        VALUES(?,?,?)
                        ON CONFLICT(song_id) DO UPDATE SET
                            settings_json=excluded.settings_json,
                            updated_at=excluded.updated_at
                        """,
                        (song_id, serialized_next_publication, stamp),
                    )
                updated = conn.execute(
                    """
                    UPDATE songs
                    SET title=?, artist=?, current_score_xml=?,
                        revision=revision+1, updated_at=?
                    WHERE song_id=? AND revision=?
                    """,
                    (
                        normalized_title, normalized_artist, xml_text, stamp,
                        song_id, expected_revision,
                    ),
                )
                if updated.rowcount != 1:
                    raise ConcurrentEditError(
                        "Song changed while saving identified metadata."
                    )
                # Retire stale exports before releasing this writer transaction.
                # A delayed post-commit clear could otherwise delete a new export
                # already produced for the newly committed revision.
                retired_exports = self._detach_exports(song_id)
        if retired_exports is not None:
            shutil.rmtree(retired_exports, ignore_errors=True)
        current = self.get(song_id)
        if current is None:
            raise KeyError(song_id)
        return current

    def update_metadata(self, song_id: str, *, title: str | None = None, artist: str | None = None) -> dict[str, Any] | None:
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
            conn.execute(f"UPDATE songs SET {assignments} WHERE song_id=?", (*fields.values(), song_id))
        return self.get(song_id)

    def snapshot_revision(self, song_id: str, publication: dict[str, Any]) -> int:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT revision, current_score_xml, title, artist FROM songs WHERE song_id=?", (song_id,)
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
                    song_id, revision, row["current_score_xml"],
                    json.dumps(publication, ensure_ascii=False, separators=(",", ":")),
                    row["title"], row["artist"], _now(),
                ),
            )
        return revision

    def discard_snapshot(self, song_id: str, revision: int) -> None:
        # A failed editor should discard only a snapshot that still belongs to the
        # current canonical revision. If another concurrent editor already committed and
        # advanced the song, that same snapshot is now the successful edit's Undo state.
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT revision FROM songs WHERE song_id=?", (song_id,)).fetchone()
            if not row or int(row["revision"]) != revision:
                return
            conn.execute("DELETE FROM song_revisions WHERE song_id=? AND revision=?", (song_id, revision))

    def restore_revision(self, song_id: str, revision: int) -> dict[str, Any] | None:
        retired_exports = None
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT musicxml, publication_json, title, artist FROM song_revisions WHERE song_id=? AND revision=?",
                (song_id, revision),
            ).fetchone()
            if not row:
                return None
            conn.execute(
                "UPDATE songs SET current_score_xml=?, title=?, artist=?, revision=?, updated_at=? WHERE song_id=?",
                (row["musicxml"], row["title"], row["artist"], revision, _now(), song_id),
            )
            conn.execute("DELETE FROM song_revisions WHERE song_id=? AND revision>=?", (song_id, revision))
            retired_exports = self._detach_exports(song_id)
        if retired_exports is not None:
            shutil.rmtree(retired_exports, ignore_errors=True)
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
                    data_json=excluded.data_json, updated_at=excluded.updated_at
                """,
                (song_id, analysis_type, encoded, _now()),
            )

    def analysis(self, song_id: str, analysis_type: str) -> Any | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT data_json FROM song_analysis WHERE song_id=? AND analysis_type=?", (song_id, analysis_type)
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
        # Explicit invalidation also coordinates with export activation. Only an
        # atomic directory rename is inside the writer guard; deletion is outside.
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            retired = self._detach_exports(song_id)
        if retired is not None:
            shutil.rmtree(retired, ignore_errors=True)

    def _detach_exports(self, song_id: str) -> Path | None:
        """Call while holding a SQLite writer transaction."""
        source = self.export_root / song_id
        retired = self.export_root / f".{song_id}.invalidated-{uuid.uuid4().hex}"
        try:
            source.replace(retired)
        except FileNotFoundError:
            return None
        return retired

    def delete(self, song_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM songs WHERE song_id=?", (song_id,))
            conn.execute("DELETE FROM song_revisions WHERE song_id=?", (song_id,))
            conn.execute("DELETE FROM song_analysis WHERE song_id=?", (song_id,))
            if "publication_settings" in {
                row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }:
                conn.execute("DELETE FROM publication_settings WHERE song_id=?", (song_id,))
        if not cur.rowcount:
            return False
        shutil.rmtree(self.cache_root / song_id, ignore_errors=True)
        shutil.rmtree(self.asset_root / song_id, ignore_errors=True)
        shutil.rmtree(self.export_root / song_id, ignore_errors=True)
        return True

    def _row(self, row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        original_xml = result.pop("original_score_xml", None)
        current_xml = result.pop("current_score_xml", None)
        if original_xml:
            result["original_musicxml"] = None
        if current_xml:
            result["current_musicxml"] = None
        export_dir = self.export_root / result["song_id"]
        result["exports"] = {}
        for kind, name in (("musicxml", "score.musicxml"), ("pdf", "score.pdf"), ("midi", "score.mid")):
            path = export_dir / name
            if path.exists():
                result["exports"][kind] = str(path)
        return result

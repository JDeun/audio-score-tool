from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from .job_transcription_settings import validate_job_selection
from .paths import database_path
from .score_requests import validate_score_mode
from .sqlite_runtime import connect_sqlite
from .youtube import canonical_youtube_url


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStore:
    def __init__(self, path: Path | None = None):
        self.path = path or database_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._init()

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self.path, row_factory=True)

    def _init(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL DEFAULT 'transcription',
                    status TEXT NOT NULL,
                    stage TEXT,
                    progress INTEGER NOT NULL DEFAULT 0,
                    filename TEXT,
                    source_kind TEXT,
                    language TEXT,
                    skip_lyrics INTEGER NOT NULL DEFAULT 0,
                    preset TEXT,
                    score_mode TEXT NOT NULL DEFAULT 'full',
                    auto_enrich INTEGER NOT NULL DEFAULT 0,
                    youtube_video_id TEXT,
                    source_authorized INTEGER NOT NULL DEFAULT 0,
                    transcription_selection_version INTEGER NOT NULL DEFAULT 0,
                    transcription_engine TEXT,
                    mt3_model TEXT,
                    native_checkpoint_sha256 TEXT,
                    muscriptor_model TEXT,
                    whisperx_model TEXT,
                    error TEXT,
                    result_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
            if "kind" not in columns:
                conn.execute("ALTER TABLE jobs ADD COLUMN kind TEXT NOT NULL DEFAULT 'transcription'")
            if "source_kind" not in columns:
                # Older jobs cannot be re-attributed safely from a title; NULL
                # preserves the historical best-effort fallback without inventing origin.
                conn.execute("ALTER TABLE jobs ADD COLUMN source_kind TEXT")
            if "score_mode" not in columns:
                conn.execute("ALTER TABLE jobs ADD COLUMN score_mode TEXT NOT NULL DEFAULT 'full'")
            if "auto_enrich" not in columns:
                # No surprise external requests for previously saved jobs.
                conn.execute("ALTER TABLE jobs ADD COLUMN auto_enrich INTEGER NOT NULL DEFAULT 0")
            if "youtube_video_id" not in columns:
                conn.execute("ALTER TABLE jobs ADD COLUMN youtube_video_id TEXT")
            if "source_authorized" not in columns:
                conn.execute("ALTER TABLE jobs ADD COLUMN source_authorized INTEGER NOT NULL DEFAULT 0")
            if "transcription_selection_version" not in columns:
                conn.execute(
                    "ALTER TABLE jobs ADD COLUMN transcription_selection_version INTEGER NOT NULL DEFAULT 0"
                )
            for column in ("transcription_engine", "mt3_model", "native_checkpoint_sha256"):
                if column not in columns:
                    # Old rows did not record an engine. Do not invent one from
                    # a MuScriptor preset which could have accompanied MT3.
                    conn.execute(f"ALTER TABLE jobs ADD COLUMN {column} TEXT")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_completed_cursor "
                "ON jobs(status, updated_at, job_id)"
            )
            conn.execute(
                "UPDATE jobs SET status='interrupted', stage='interrupted' "
                "WHERE status IN ('queued', 'running', 'cancelling')"
            )

    def create(self, job_id: str, **values: Any) -> None:
        if values.get("source_kind") not in {None, "local", "youtube", "omr", "notation"}:
            raise ValueError("Unsupported Job source_kind")
        mode = validate_score_mode(values.get("score_mode", "full"))
        video_id = values.get("youtube_video_id")
        if video_id is not None:
            canonical_youtube_url(video_id)
            if values.get("source_kind") != "youtube":
                raise ValueError("YouTube identity requires source_kind=youtube")
        selection_version = values.get(
            "transcription_selection_version", 0 if values.get("transcription_engine") is None else 1,
        )
        validate_job_selection(
            values.get("transcription_engine"), values.get("mt3_model"),
            values.get("native_checkpoint_sha256"),
            selection_version=selection_version,
        )
        now = _now()
        payload = {
            "kind": values.get("kind", "transcription"),
            "status": values.get("status", "queued"),
            "stage": values.get("stage", "queued"),
            "progress": int(values.get("progress", 0)),
            "filename": values.get("filename"),
            "source_kind": values.get("source_kind"),
            "language": values.get("language"),
            "skip_lyrics": int(bool(values.get("skip_lyrics", False))),
            "preset": values.get("preset"),
            "score_mode": mode,
            "auto_enrich": int(bool(values.get("auto_enrich", False))),
            "youtube_video_id": video_id,
            "source_authorized": int(bool(values.get("source_authorized", False))),
            "transcription_engine": values.get("transcription_engine"),
            "transcription_selection_version": selection_version,
            "mt3_model": values.get("mt3_model"),
            "native_checkpoint_sha256": values.get("native_checkpoint_sha256"),
            "muscriptor_model": values.get("muscriptor_model"),
            "whisperx_model": values.get("whisperx_model"),
            "error": values.get("error"),
            "result_json": json.dumps(values.get("result")) if values.get("result") else None,
        }
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    job_id,kind,status,stage,progress,filename,source_kind,language,skip_lyrics,preset,
                    score_mode,auto_enrich,muscriptor_model,whisperx_model,error,result_json,created_at,updated_at,
                    transcription_engine,mt3_model,native_checkpoint_sha256,transcription_selection_version,
                    youtube_video_id,source_authorized
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    job_id, payload["kind"], payload["status"], payload["stage"], payload["progress"],
                    payload["filename"], payload["source_kind"], payload["language"], payload["skip_lyrics"],
                    payload["preset"], payload["score_mode"], payload["auto_enrich"], payload["muscriptor_model"], payload["whisperx_model"],
                    payload["error"], payload["result_json"], now, now,
                    payload["transcription_engine"], payload["mt3_model"], payload["native_checkpoint_sha256"],
                    payload["transcription_selection_version"], payload["youtube_video_id"],
                    payload["source_authorized"],
                ),
            )

    def update(self, job_id: str, **values: Any) -> None:
        if not values:
            return
        mapping = dict(values)
        if {"transcription_engine", "mt3_model", "native_checkpoint_sha256", "transcription_selection_version"} & mapping.keys():
            validate_job_selection(
                mapping.get("transcription_engine"), mapping.get("mt3_model"),
                mapping.get("native_checkpoint_sha256"),
                selection_version=mapping.get("transcription_selection_version"),
            )
        if "youtube_video_id" in mapping and mapping["youtube_video_id"] is not None:
            canonical_youtube_url(mapping["youtube_video_id"])
        if "source_authorized" in mapping:
            mapping["source_authorized"] = int(bool(mapping["source_authorized"]))
        if "score_mode" in mapping:
            mapping["score_mode"] = validate_score_mode(mapping["score_mode"])
        if "source_kind" in mapping and mapping["source_kind"] not in {None, "local", "youtube", "omr", "notation"}:
            raise ValueError("Unsupported Job source_kind")
        if "result" in mapping:
            mapping["result_json"] = json.dumps(mapping.pop("result"))
        if "skip_lyrics" in mapping:
            mapping["skip_lyrics"] = int(bool(mapping["skip_lyrics"]))
        if "auto_enrich" in mapping:
            mapping["auto_enrich"] = int(bool(mapping["auto_enrich"]))
        mapping["updated_at"] = _now()
        assignments = ", ".join(f"{key}=?" for key in mapping)
        with self._lock, self._connect() as conn:
            conn.execute(
                f"UPDATE jobs SET {assignments} WHERE job_id=?",
                (*mapping.values(), job_id),
            )

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return self._row(row) if row else None

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                (max(1, min(limit, 5000)),),
            ).fetchall()
        return [self._row(row) for row in rows]

    def list_completed_after(
        self,
        *,
        cursor_updated_at: str = "",
        cursor_job_id: str = "",
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Return completed non-benchmark jobs in stable cursor order.

        This query is intentionally independent from the user-facing history limit so
        Job -> Song reconciliation never loses old completed jobs after 5,000 records.
        """
        page_size = max(1, min(limit, 2000))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM jobs
                WHERE status='done'
                  AND kind <> 'benchmark'
                  AND (updated_at > ? OR (updated_at = ? AND job_id > ?))
                ORDER BY updated_at ASC, job_id ASC
                LIMIT ?
                """,
                (cursor_updated_at, cursor_updated_at, cursor_job_id, page_size),
            ).fetchall()
        return [self._row(row) for row in rows]

    def delete(self, job_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM jobs WHERE job_id=?", (job_id,))
            return cur.rowcount > 0

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["skip_lyrics"] = bool(result["skip_lyrics"])
        result["auto_enrich"] = bool(result["auto_enrich"])
        result["source_authorized"] = bool(result["source_authorized"])
        raw = result.pop("result_json", None)
        result["result_corrupt"] = False
        if not raw:
            result["result"] = None
            return result
        try:
            result["result"] = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            # One malformed historical row must not make the entire job history or song
            # synchronization endpoint unavailable. Preserve the row and expose its
            # corruption explicitly so cleanup/retry UI can still recover around it.
            result["result"] = None
            result["result_corrupt"] = True
        return result

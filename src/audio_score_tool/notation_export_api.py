from __future__ import annotations

import errno
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .musicxml_parts import extract_part_musicxml, list_score_parts
from .notation_backend import (
    NotationBackendError,
    NotationBackendUnavailable,
    backend_status,
    musicxml_to_midi,
    render_pdf,
)
from .paths import cache_dir
from .publication_layout import apply_publication_layout
from .runtime_settings import runtime_settings
from .song_routes import (
    _part_exports,
    _public,
    _publication_store,
    _require_song,
    _song_store,
)

router = APIRouter(prefix="/api/songs", tags=["notation-export"])

ExportKind = Literal["musicxml", "pdf", "midi", "parts"]


class ExportRequest(BaseModel):
    formats: list[ExportKind] = Field(
        default_factory=lambda: ["musicxml", "pdf", "midi", "parts"],
        min_length=1,
    )


def _publish_export_tree(song_id: str, staged: Path) -> Path:
    """Replace the managed export tree only after the new tree is complete."""
    final = _song_store.export_root / song_id
    backup = _song_store.export_root / f".{song_id}.backup-{uuid.uuid4().hex}"
    had_previous = final.exists()
    try:
        if had_previous:
            final.replace(backup)
        staged.replace(final)
    except OSError:
        if had_previous and backup.exists() and not final.exists():
            try:
                backup.replace(final)
            except OSError:
                pass
        raise
    else:
        shutil.rmtree(backup, ignore_errors=True)
    return final


def _export_error(exc: Exception) -> HTTPException:
    if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
        return HTTPException(507, "저장 공간이 부족해 최종 파일을 생성하지 못했습니다. 기존 export는 보존했습니다.")
    return HTTPException(500, f"최종 파일 생성에 실패했습니다: {exc}")


def build_exports_v3(song_id: str, payload: ExportRequest | None = None) -> dict:
    song = _require_song(song_id)
    requested = set((payload or ExportRequest()).formats)
    settings = runtime_settings()
    status = backend_status(settings)

    if "midi" in requested and not status["music21"]:
        raise HTTPException(500, "앱 내장 music21 runtime이 누락되었습니다.")
    if requested & {"pdf", "parts"} and not (status["verovio"] and status["fpdf2"]):
        raise HTTPException(500, "앱 내장 PDF renderer(verovio/fpdf2)가 누락되었습니다.")

    _song_store.export_root.mkdir(parents=True, exist_ok=True)
    cache_root = cache_dir() / "export"
    cache_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"{song_id}-", dir=cache_root) as tmp:
        staged = Path(tmp) / "tree"
        staged.mkdir(parents=True)
        score = _song_store.checkout_current(song_id)
        publication = _publication_store.read(song_id)
        apply_publication_layout(score, title=song["title"], settings=publication)

        try:
            if "musicxml" in requested:
                shutil.copy2(score, staged / "score.musicxml")
            if "pdf" in requested:
                render_pdf(score, staged / "score.pdf", settings=settings)
            if "midi" in requested:
                musicxml_to_midi(score, staged / "score.mid")
            if "parts" in requested:
                parts_dir = staged / "parts"
                parts_dir.mkdir()
                for part in list_score_parts(score):
                    slug = part["slug"]
                    part_xml = parts_dir / f"{slug}.musicxml"
                    extract_part_musicxml(score, str(part["id"]), part_xml)
                    render_pdf(part_xml, parts_dir / f"{slug}.pdf", settings=settings)
        except (NotationBackendError, NotationBackendUnavailable, OSError) as exc:
            raise _export_error(exc) from exc
        except Exception as exc:
            raise _export_error(exc) from exc

        try:
            final = _publish_export_tree(song_id, staged)
        except Exception as exc:
            raise _export_error(exc) from exc

    exports = {
        "pdf": (final / "score.pdf").exists(),
        "midi": (final / "score.mid").exists(),
        "musicxml": (final / "score.musicxml").exists(),
    }
    _song_store.set_exports(song_id, exports)
    updated = _song_store.get(song_id) or song
    return {"song": _public(updated), "parts": _part_exports(updated)}


def build_exports(song_id: str, payload: ExportRequest | None = None) -> dict:
    return build_exports_v3(song_id, payload)


@router.post("/{song_id}/export")
def export_song(song_id: str, payload: ExportRequest | None = None) -> dict:
    return build_exports_v3(song_id, payload)

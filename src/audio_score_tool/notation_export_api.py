from __future__ import annotations

import errno
import shutil
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException

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
from .song_api_v2 import (
    ExportRequest,
    _part_exports,
    _public,
    _publication_store,
    _require_song,
    _song_store,
)

router = APIRouter(prefix="/api/songs", tags=["notation-export"])


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
        raise HTTPException(409, "MIDI export에는 music21이 필요합니다.")
    if requested & {"pdf", "parts"} and not (
        status["lilypond"] and status["musicxml2ly"]
    ):
        raise HTTPException(
            409,
            "PDF export에는 LilyPond와 musicxml2ly가 필요합니다. "
            "MusicXML/MIDI export는 PDF renderer 없이도 사용할 수 있습니다.",
        )

    _song_store.export_root.mkdir(parents=True, exist_ok=True)
    cache_root = cache_dir() / "export"
    cache_root.mkdir(parents=True, exist_ok=True)
    renderers: set[str] = set()
    staged = Path(tempfile.mkdtemp(prefix=f".{song_id}-staged-", dir=_song_store.export_root))

    try:
        with tempfile.TemporaryDirectory(prefix=f"{song_id}-work-", dir=cache_root) as raw_temp:
            temp_dir = Path(raw_temp)
            source = temp_dir / "score.musicxml"
            source.write_text(_song_store.score_xml(song_id), encoding="utf-8")
            apply_publication_layout(
                source,
                title=song["title"],
                settings=_publication_store.read(song_id),
            )

            if "musicxml" in requested:
                shutil.copy2(source, staged / "score.musicxml")
            if "pdf" in requested:
                _, renderer = render_pdf(source, staged / "score.pdf", settings=settings)
                renderers.add(renderer)
            if "midi" in requested:
                musicxml_to_midi(source, staged / "score.mid")
            if "parts" in requested:
                parts_dir = staged / "parts"
                parts_dir.mkdir(parents=True, exist_ok=True)
                for part in list_score_parts(source):
                    slug = str(part["slug"])
                    part_xml = parts_dir / f"{slug}.musicxml"
                    part_pdf = parts_dir / f"{slug}.pdf"
                    extract_part_musicxml(source, str(part["part_id"]), part_xml)
                    _, renderer = render_pdf(part_xml, part_pdf, settings=settings)
                    renderers.add(renderer)

        _publish_export_tree(song_id, staged)
    except (NotationBackendError, NotationBackendUnavailable, ValueError, OSError) as exc:
        shutil.rmtree(staged, ignore_errors=True)
        raise _export_error(exc) from exc
    except Exception:
        shutil.rmtree(staged, ignore_errors=True)
        raise

    updated = _song_store.get(song_id) or song
    files = {
        kind: f"/api/songs/{song_id}/files/{kind}"
        for kind in ("musicxml", "pdf", "midi")
        if kind in requested
    }
    return {
        "song": _public(updated),
        "files": files,
        "parts": _part_exports(updated),
        "formats": sorted(requested),
        "notation_backends": status,
        "pdf_renderers_used": sorted(renderers),
    }


@router.post("/{song_id}/export")
def build_exports(song_id: str, payload: ExportRequest | None = None) -> dict:
    return build_exports_v3(song_id, payload)

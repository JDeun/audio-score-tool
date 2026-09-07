from __future__ import annotations

import shutil
import tempfile
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


def build_exports_v3(song_id: str, payload: ExportRequest | None = None) -> dict:
    song = _require_song(song_id)
    requested = set((payload or ExportRequest()).formats)
    settings = runtime_settings()
    status = backend_status(settings)

    if "midi" in requested and not status["music21"]:
        raise HTTPException(409, "MIDI export에는 music21이 필요합니다.")
    if requested & {"pdf", "parts"} and not (
        (status["lilypond"] and status["musicxml2ly"]) or status["musescore"]
    ):
        raise HTTPException(
            409,
            "PDF renderer가 없습니다. LilyPond를 설치하거나 선택적으로 MuseScore를 지정하세요.",
        )

    _song_store.clear_exports(song_id)
    export_dir = _song_store.export_dir(song_id)
    cache_root = cache_dir() / "export"
    cache_root.mkdir(parents=True, exist_ok=True)
    renderers: set[str] = set()

    try:
        with tempfile.TemporaryDirectory(prefix=f"{song_id}-", dir=cache_root) as raw_temp:
            temp_dir = Path(raw_temp)
            source = temp_dir / "score.musicxml"
            source.write_text(_song_store.score_xml(song_id), encoding="utf-8")
            apply_publication_layout(
                source,
                title=song["title"],
                settings=_publication_store.read(song_id),
            )

            if "musicxml" in requested:
                shutil.copy2(source, export_dir / "score.musicxml")
            if "pdf" in requested:
                _, renderer = render_pdf(
                    source,
                    export_dir / "score.pdf",
                    settings=settings,
                )
                renderers.add(renderer)
            if "midi" in requested:
                musicxml_to_midi(source, export_dir / "score.mid")
            if "parts" in requested:
                parts_dir = export_dir / "parts"
                parts_dir.mkdir(parents=True, exist_ok=True)
                for part in list_score_parts(source):
                    slug = str(part["slug"])
                    part_xml = parts_dir / f"{slug}.musicxml"
                    part_pdf = parts_dir / f"{slug}.pdf"
                    extract_part_musicxml(source, str(part["part_id"]), part_xml)
                    _, renderer = render_pdf(part_xml, part_pdf, settings=settings)
                    renderers.add(renderer)
    except (NotationBackendError, NotationBackendUnavailable, ValueError, OSError) as exc:
        _song_store.clear_exports(song_id)
        raise HTTPException(500, f"최종 파일 생성에 실패했습니다: {exc}") from exc

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

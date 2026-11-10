from __future__ import annotations

import errno
import json
import re
import shutil
import tempfile
import uuid
import xml.etree.ElementTree as ET
from contextlib import ExitStack
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from .musicxml_metadata_projection import normalize_suspended_seventh
from .musicxml_parts import extract_part_musicxml, extract_parts_musicxml, list_score_parts
from .notation_backend import (
    backend_status,
    musicxml_to_midi,
    render_pdf,
)
from .paths import cache_dir
from .publication_layout import apply_publication_layout, merged_publication_settings
from .runtime_settings import runtime_settings
from .song_routes import (
    _part_exports,
    _public,
    _publication_store,
    _require_song,
    _song_store,
)
from .song_store_v2 import ConcurrentEditError

router = APIRouter(prefix="/api/songs", tags=["notation-export"])

ExportKind = Literal["musicxml", "pdf", "midi", "parts"]
SELECTION_DIRECTORY = "selection"
EXPORT_RECEIPT = ".export.json"


class ExportRequest(BaseModel):
    formats: list[ExportKind] = Field(
        default_factory=lambda: ["musicxml", "pdf", "midi", "parts"],
        min_length=1,
    )
    part_ids: list[str] | None = Field(default=None, min_length=1, max_length=256)
    expected_revision: int | None = Field(default=None, ge=1)

    @field_validator("part_ids")
    @classmethod
    def validate_part_ids(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and (
            any(not part_id.strip() for part_id in value) or len(set(value)) != len(value)
        ):
            raise ValueError("파트 ID는 비어 있거나 중복될 수 없습니다.")
        return value


def _publish_export_tree(
    song_id: str, staged: Path, *, selection: bool = False,
    retired: list[Path] | None = None,
) -> Path:
    """Replace the managed export tree only after the new tree is complete."""
    final = _song_store.export_root / song_id
    if selection:
        final = final / SELECTION_DIRECTORY
    final.parent.mkdir(parents=True, exist_ok=True)
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
        if retired is not None:
            retired.append(backup)
        else:
            shutil.rmtree(backup, ignore_errors=True)
    return final


def _export_error(exc: Exception) -> HTTPException:
    if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
        return HTTPException(507, "저장 공간이 부족해 최종 파일을 생성하지 못했습니다. 기존 export는 보존했습니다.")
    return HTTPException(500, f"최종 파일 생성에 실패했습니다: {exc}")


def _unique_destination(root: Path, title: str) -> Path:
    cleaned = re.sub(r"[^0-9A-Za-z가-힣._ -]+", "_", title).strip(" ._")
    base = root / (cleaned or "AudioScoreTool Export")
    if not base.exists():
        return base
    for index in range(2, 10000):
        candidate = root / f"{base.name} ({index})"
        if not candidate.exists():
            return candidate
    raise HTTPException(409, "저장 폴더 이름을 만들 수 없습니다.")


def build_exports_v3(
    song_id: str, payload: ExportRequest | None = None, *,
    destination_root: Path | None = None,
) -> dict:
    song = _require_song(song_id)
    payload = payload or ExportRequest()
    # Migrate any legacy publication settings before taking the single DB snapshot.
    _publication_store.read(song_id)
    try:
        snapshot = _song_store.export_snapshot(song_id)
    except KeyError:
        raise HTTPException(404, "Song not found") from None
    if payload.expected_revision is not None and payload.expected_revision != snapshot.revision:
        raise HTTPException(409, "악보가 변경되었습니다. 출력 창을 다시 열어 현재 악보를 확인하세요.")
    song = {**song, "title": snapshot.title, "artist": snapshot.artist, "revision": snapshot.revision}
    requested = set(payload.formats)
    selection = payload.part_ids is not None
    settings = runtime_settings()
    status = backend_status(settings)

    if "midi" in requested and not status["music21"]:
        raise HTTPException(500, "앱 내장 music21 runtime이 누락되었습니다.")
    if requested & {"pdf", "parts"} and not (status["verovio"] and status["fpdf2"]):
        raise HTTPException(500, "앱 내장 PDF renderer(verovio/fpdf2)가 누락되었습니다.")

    _song_store.export_root.mkdir(parents=True, exist_ok=True)
    cache_root = cache_dir() / "export"
    cache_root.mkdir(parents=True, exist_ok=True)
    destination = None
    activated = False
    retired: list[Path] = []
    try:
        with ExitStack() as cleanup:
            tmp = Path(cleanup.enter_context(tempfile.TemporaryDirectory(
                prefix=f"{song_id}-", dir=cache_root,
            )))
            staged = tmp / "tree"
            staged.mkdir()
            current = tmp / "current.musicxml"
            current.write_text(snapshot.current_score_xml, encoding="utf-8")
            score = tmp / "publication.musicxml"
            all_parts = list_score_parts(current)
            if selection:
                try:
                    extract_parts_musicxml(current, payload.part_ids, score)
                except ValueError as exc:
                    raise HTTPException(422, str(exc)) from exc
            else:
                shutil.copy2(current, score)
            exported_parts = [
                part for part in all_parts
                if payload.part_ids is None or part["part_id"] in payload.part_ids
            ]
            try:
                publication = json.loads(snapshot.publication_json or "{}")
            except ValueError:
                publication = {}
            publication = merged_publication_settings(
                publication if isinstance(publication, dict) else {},
            )
            apply_publication_layout(score, title=snapshot.title, settings=publication)
            tree = ET.parse(score)
            normalize_suspended_seventh(tree.getroot())
            tree.write(score, encoding="utf-8", xml_declaration=True)
            basename = "selected-score" if selection else "score"
            receipt = {
                "export_id": uuid.uuid4().hex,
                "scope": "selection" if selection else "full",
                "revision": snapshot.revision,
                "part_ids": [part["part_id"] for part in exported_parts],
            }
            if "musicxml" in requested:
                shutil.copy2(score, staged / f"{basename}.musicxml")
            if "pdf" in requested:
                render_pdf(score, staged / f"{basename}.pdf", settings=settings)
            if "midi" in requested:
                musicxml_to_midi(score, staged / f"{basename}.mid")
            if "parts" in requested:
                parts_dir = staged / "parts"
                parts_dir.mkdir()
                for part in exported_parts:
                    slug = part["slug"]
                    part_xml = parts_dir / f"{slug}.musicxml"
                    extract_part_musicxml(score, str(part["part_id"]), part_xml)
                    render_pdf(part_xml, parts_dir / f"{slug}.pdf", settings=settings)
            (staged / EXPORT_RECEIPT).write_text(
                json.dumps(receipt, ensure_ascii=False), encoding="utf-8",
            )
            desktop_staged = None
            if destination_root is not None:
                desktop_tmp = Path(cleanup.enter_context(tempfile.TemporaryDirectory(
                    prefix=".audioscore-export-", dir=destination_root,
                )))
                desktop_staged = desktop_tmp / "tree"
                # Copy our immutable render result, never the shared export tree
                # that background metadata enrichment can invalidate.
                shutil.copytree(staged, desktop_staged)

            with _song_store.guard_export_snapshot(snapshot):
                if desktop_staged is not None:
                    title = snapshot.title + (" - 선택 파트" if selection else "")
                    destination = _unique_destination(destination_root, title)
                    desktop_staged.replace(destination)
                _publish_export_tree(song_id, staged, selection=selection, retired=retired)
                updated = _song_store.get(song_id) or song
                # Reuse the parsed immutable snapshot; the short writer guard
                # performs only export-file existence checks, never another XML
                # checkout/parse of a potentially large score.
                part_exports = _part_exports(updated, parts=all_parts)
                result = {
                    "song": _public(updated, parts=part_exports),
                    "parts": part_exports, "export": receipt,
                }
                if destination is not None:
                    result["destination"] = str(destination)
            activated = True
    except ConcurrentEditError as exc:
        raise HTTPException(409, "악보가 변경되었습니다. 현재 악보를 확인하고 다시 출력하세요.") from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise _export_error(exc) from exc
    finally:
        if destination is not None and not activated:
            shutil.rmtree(destination, ignore_errors=True)
        for obsolete in retired:
            shutil.rmtree(obsolete, ignore_errors=True)
    return result


def build_exports(song_id: str, payload: ExportRequest | None = None) -> dict:
    return build_exports_v3(song_id, payload)


@router.post("/{song_id}/export")
def export_song(song_id: str, payload: ExportRequest | None = None) -> dict:
    return build_exports_v3(song_id, payload)

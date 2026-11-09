from __future__ import annotations

import errno
import json
import shutil
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .desktop_utils import open_pdf_document
from .notation_export_api import (
    EXPORT_RECEIPT,
    SELECTION_DIRECTORY,
    ExportRequest,
    build_exports_v3,
)
from .paths import cache_dir
from .song_routes import _require_song, _song_store
from .song_store_v2 import ConcurrentEditError

router = APIRouter(prefix="/api/songs", tags=["desktop-export-v2"])


class DesktopExportRequest(ExportRequest):
    destination_dir: str


class OpenExportPdfRequest(BaseModel):
    scope: Literal["full", "selection"] = "full"
    export_id: str = Field(min_length=1, max_length=64)
    expected_revision: int = Field(ge=1)


@router.post("/{song_id}/export-to")
def export_to_directory(song_id: str, payload: DesktopExportRequest) -> dict:
    _require_song(song_id)
    raw_destination = payload.destination_dir.strip()
    if not raw_destination:
        raise HTTPException(422, "저장 폴더를 선택하세요.")

    destination_root = Path(raw_destination).expanduser()
    try:
        destination_root.mkdir(parents=True, exist_ok=True)
        destination_root = destination_root.resolve()
    except OSError as exc:
        status = 507 if exc.errno == errno.ENOSPC else 422
        raise HTTPException(status, f"저장 폴더에 접근할 수 없습니다: {exc}") from exc
    if not destination_root.is_dir():
        raise HTTPException(422, "선택한 저장 위치가 폴더가 아닙니다.")
    if destination_root.is_relative_to(_song_store.export_root.resolve()):
        raise HTTPException(422, "앱의 임시 출력 폴더 밖에 최종 저장 위치를 선택하세요.")

    try:
        return build_exports_v3(song_id, ExportRequest(
            formats=payload.formats, part_ids=payload.part_ids,
            expected_revision=payload.expected_revision,
        ), destination_root=destination_root)
    except OSError as exc:
        status = 507 if exc.errno == errno.ENOSPC else 500
        raise HTTPException(status, f"최종 파일을 선택한 폴더에 저장하지 못했습니다: {exc}") from exc


@router.post("/{song_id}/export/open-pdf")
def open_export_pdf(song_id: str, payload: OpenExportPdfRequest) -> dict:
    """Open only the exact generated PDF, never a caller-supplied filesystem path."""
    _require_song(song_id)
    try:
        snapshot = _song_store.export_snapshot(song_id)
    except KeyError:
        raise HTTPException(404, "Song not found") from None
    if snapshot.revision != payload.expected_revision:
        raise HTTPException(409, "악보가 변경되었습니다. 현재 악보의 PDF를 다시 생성하세요.")
    root = _song_store.export_root / song_id
    basename = "score"
    if payload.scope == "selection":
        root = root / SELECTION_DIRECTORY
        basename = "selected-score"
    viewer_directory = None
    try:
        with _song_store.guard_export_snapshot(snapshot):
            try:
                receipt = json.loads((root / EXPORT_RECEIPT).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raise HTTPException(404, "생성한 PDF를 찾을 수 없습니다. 최종 파일을 다시 생성하세요.") from None
            if not isinstance(receipt, dict) or (
                receipt.get("export_id") != payload.export_id
                or receipt.get("scope") != payload.scope
                or receipt.get("revision") != payload.expected_revision
            ):
                raise HTTPException(409, "출력 파일이 변경되었습니다. 최종 파일을 다시 생성하세요.")
            pdf = root / f"{basename}.pdf"
            if pdf.is_symlink() or not pdf.is_file():
                raise HTTPException(404, "PDF 출력이 없습니다. PDF 형식을 선택해 다시 생성하세요.")
            try:
                viewer_root = cache_dir() / "pdf-viewer"
                viewer_root.mkdir(parents=True, exist_ok=True)
                viewer_directory = Path(tempfile.mkdtemp(prefix="opened-", dir=viewer_root))
                viewer_pdf = viewer_directory / f"{basename}.pdf"
                # OS launchers return before the viewer opens its input. Keep a
                # unique immutable copy outside song/export invalidation so later
                # edits cannot remove the file while the viewer is starting.
                shutil.copyfile(pdf, viewer_pdf)
            except OSError as exc:
                if viewer_directory is not None:
                    shutil.rmtree(viewer_directory, ignore_errors=True)
                status = 507 if exc.errno == errno.ENOSPC else 500
                raise HTTPException(status, f"PDF 뷰어용 파일을 준비하지 못했습니다: {exc}") from exc
    except ConcurrentEditError as exc:
        raise HTTPException(409, "악보가 변경되었습니다. 현재 악보의 PDF를 다시 생성하세요.") from exc
    # Native process creation is deliberately outside the DB writer guard.
    try:
        open_pdf_document(viewer_pdf)
    except OSError as exc:
        shutil.rmtree(viewer_directory, ignore_errors=True)
        raise HTTPException(500, f"PDF 뷰어를 열지 못했습니다: {exc}") from exc
    return {"opened": True}

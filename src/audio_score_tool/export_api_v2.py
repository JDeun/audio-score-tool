from __future__ import annotations

import errno
import re
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .notation_export_api import ExportKind, ExportRequest, build_exports_v3
from .song_api_v2 import _require_song, _song_store

router = APIRouter(prefix="/api/songs", tags=["desktop-export-v2"])


class DesktopExportRequest(BaseModel):
    formats: list[ExportKind] = Field(
        default_factory=lambda: ["musicxml", "pdf", "midi", "parts"],
        min_length=1,
    )
    destination_dir: str


def _safe_folder_name(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z가-힣._ -]+", "_", value).strip(" ._")
    return cleaned or "AudioScoreTool Export"


def _unique_destination(root: Path, title: str) -> Path:
    base = root / _safe_folder_name(title)
    if not base.exists():
        return base
    for index in range(2, 10000):
        candidate = root / f"{base.name} ({index})"
        if not candidate.exists():
            return candidate
    raise HTTPException(409, "저장 폴더 이름을 만들 수 없습니다.")


@router.post("/{song_id}/export-to")
def export_to_directory(song_id: str, payload: DesktopExportRequest) -> dict:
    song = _require_song(song_id)
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

    result = build_exports_v3(song_id, ExportRequest(formats=payload.formats))
    source = _song_store.export_root / song_id
    target = _unique_destination(destination_root, song["title"])
    try:
        shutil.copytree(source, target)
    except OSError as exc:
        shutil.rmtree(target, ignore_errors=True)
        status = 507 if exc.errno == errno.ENOSPC else 500
        raise HTTPException(status, f"최종 파일을 선택한 폴더에 저장하지 못했습니다: {exc}") from exc

    return {
        **result,
        "destination": str(target),
    }

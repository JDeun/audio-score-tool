from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from .notation_backend import backend_status
from .omr import audiveris_status
from .runtime_settings import runtime_settings
from .settings_store import SettingsStore

router = APIRouter(prefix="/api/notation", tags=["notation"])
_store = SettingsStore()


class NotationSettingsPayload(BaseModel):
    audiveris_cmd: str | None = None
    lilypond_cmd: str | None = None
    musicxml2ly_cmd: str | None = None


def _snapshot() -> dict:
    settings = runtime_settings(store=_store)
    return {
        "paths": {
            "audiveris_cmd": settings.audiveris_cmd,
            "lilypond_cmd": settings.lilypond_cmd,
            "musicxml2ly_cmd": settings.musicxml2ly_cmd,
        },
        "backends": backend_status(settings),
        "omr": audiveris_status(settings.audiveris_cmd),
        "policy": {
            "preview": "osmd",
            "midi_musicxml": "music21",
            "pdf_renderer": "lilypond",
            "musescore_required": False,
        },
    }


@router.get("")
def get_notation_settings() -> dict:
    return _snapshot()


@router.put("")
def update_notation_settings(payload: NotationSettingsPayload) -> dict:
    _store.update(payload.model_dump())
    return _snapshot()

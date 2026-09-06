from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .config import Settings
from .pipeline import preflight
from .settings_store import SettingsStore
from .transcription_engine import available_engines

router = APIRouter(prefix="/api/engine-settings", tags=["engine-settings"])
_store = SettingsStore()


class EngineSettingsPayload(BaseModel):
    transcription_engine: str
    native_engine_cmd: str | None = None
    native_checkpoint: str | None = None


@router.get("")
def get_engine_settings() -> dict:
    saved = _store.read()
    settings = Settings()
    return {
        "transcription_engine": settings.transcription_engine,
        "native_engine_cmd": settings.native_engine_cmd,
        "native_checkpoint": str(settings.native_checkpoint) if settings.native_checkpoint else None,
        "saved": saved,
        "engines": available_engines(settings),
        "preflight": preflight(settings),
    }


@router.put("")
def update_engine_settings(payload: EngineSettingsPayload) -> dict:
    engine = payload.transcription_engine.strip().lower()
    if engine not in {"muscriptor", "native"}:
        raise HTTPException(422, "transcription_engine must be 'muscriptor' or 'native'.")

    saved = _store.update(
        {
            "transcription_engine": engine,
            "native_engine_cmd": payload.native_engine_cmd,
            "native_checkpoint": payload.native_checkpoint,
        }
    )
    settings = Settings()
    return {
        "transcription_engine": settings.transcription_engine,
        "native_engine_cmd": settings.native_engine_cmd,
        "native_checkpoint": str(settings.native_checkpoint) if settings.native_checkpoint else None,
        "saved": saved,
        "engines": available_engines(settings),
        "preflight": preflight(settings),
    }

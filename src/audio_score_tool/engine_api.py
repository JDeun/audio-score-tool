from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from .pipeline import preflight
from .runtime_settings import runtime_settings
from .settings_store import SettingsStore
from .transcription_engine import available_engines

router = APIRouter(prefix="/api/engines", tags=["engines"])
_store = SettingsStore()


class EngineSettingsPayload(BaseModel):
    transcription_engine: str
    yourmt3_cmd: str | None = None
    native_engine_cmd: str | None = None
    native_checkpoint: str | None = None

    @field_validator("transcription_engine")
    @classmethod
    def validate_engine(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"yourmt3", "muscriptor", "native"}:
            raise ValueError(
                "transcription_engine must be 'yourmt3', 'muscriptor', or 'native'"
            )
        return normalized


@router.get("")
def get_engines() -> dict:
    settings = runtime_settings(store=_store)
    return {
        "selected": settings.transcription_engine,
        "yourmt3_cmd": settings.yourmt3_cmd,
        "native_checkpoint": str(settings.native_checkpoint) if settings.native_checkpoint else None,
        "native_engine_cmd": settings.native_engine_cmd,
        "engines": available_engines(settings),
        "preflight": preflight(settings),
    }


@router.put("")
def update_engine(payload: EngineSettingsPayload) -> dict:
    checkpoint = payload.native_checkpoint.strip() if payload.native_checkpoint else None
    if payload.transcription_engine == "native":
        if not checkpoint:
            raise HTTPException(422, "AudioScore Native requires a project-owned checkpoint path.")
        path = Path(checkpoint).expanduser()
        if not path.is_file():
            raise HTTPException(422, f"Native checkpoint does not exist: {path}")

    _store.update(
        {
            "transcription_engine": payload.transcription_engine,
            "yourmt3_cmd": payload.yourmt3_cmd,
            "native_engine_cmd": payload.native_engine_cmd,
            "native_checkpoint": checkpoint,
        }
    )
    return get_engines()

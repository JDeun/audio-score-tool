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
    mt3_infer_cmd: str | None = None
    mt3_model: str | None = None
    native_engine_cmd: str | None = None
    native_checkpoint: str | None = None

    @field_validator("transcription_engine")
    @classmethod
    def validate_engine(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized == "yourmt3":
            normalized = "mt3_infer"
        if normalized not in {"mt3_infer", "muscriptor", "native"}:
            raise ValueError(
                "transcription_engine must be 'mt3_infer', 'muscriptor', or 'native'"
            )
        return normalized

    @field_validator("mt3_model")
    @classmethod
    def validate_mt3_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized not in {"mr_mt3", "yourmt3"}:
            raise ValueError("mt3_model must be 'mr_mt3' or 'yourmt3'")
        return normalized


@router.get("")
def get_engines() -> dict:
    settings = runtime_settings(store=_store)
    return {
        "selected": settings.transcription_engine,
        "mt3_infer_cmd": settings.mt3_infer_cmd,
        "mt3_model": settings.mt3_model,
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
            "mt3_infer_cmd": payload.mt3_infer_cmd,
            "mt3_model": payload.mt3_model or "mr_mt3",
            "native_engine_cmd": payload.native_engine_cmd,
            "native_checkpoint": checkpoint,
        }
    )
    return get_engines()

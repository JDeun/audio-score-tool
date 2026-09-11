from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from .engine_release_policy import release_policy_summary
from .preflight_v2 import preflight
from .runtime_settings import runtime_settings
from .settings_store import SettingsStore
from .transcription_engine import available_engines

router = APIRouter(prefix="/api/engines", tags=["engines"])
_store = SettingsStore()


class EngineSettingsPayload(BaseModel):
    usage_mode: str = "personal"
    transcription_engine: str
    mt3_infer_cmd: str | None = None
    mt3_model: str | None = None
    muscriptor_cmd: str | None = None
    muscriptor_model: str | None = None
    native_engine_cmd: str | None = None
    native_checkpoint: str | None = None

    @field_validator("usage_mode")
    @classmethod
    def validate_usage_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"personal", "commercial"}:
            raise ValueError("usage_mode must be 'personal' or 'commercial'")
        return normalized

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

    @field_validator("muscriptor_model")
    @classmethod
    def validate_muscriptor_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized not in {"small", "medium", "large"}:
            raise ValueError("muscriptor_model must be 'small', 'medium', or 'large'")
        return normalized


def _recommendation(settings) -> dict:
    if settings.usage_mode == "personal":
        return {
            "engine": "muscriptor",
            "model": "large",
            "release_approved_default": True,
            "reason": "정확도 우선 개인/비상업 기본값",
        }
    return {
        "engine": "mt3_infer",
        "model": "yourmt3",
        "release_approved_default": False,
        "reason": (
            "상용 모드 Tier 2 비교 우선 후보. 정확한 checkpoint provenance와 #34 품질 gate를 "
            "통과하기 전에는 release-approved default가 아닙니다."
        ),
    }


@router.get("")
def get_engines() -> dict:
    settings = runtime_settings(store=_store)
    return {
        "usage_mode": settings.usage_mode,
        "selected": settings.transcription_engine,
        "mt3_infer_cmd": settings.mt3_infer_cmd,
        "mt3_model": settings.mt3_model,
        "muscriptor_cmd": settings.muscriptor_cmd,
        "muscriptor_model": settings.muscriptor_model,
        "native_checkpoint": str(settings.native_checkpoint) if settings.native_checkpoint else None,
        "native_engine_cmd": settings.native_engine_cmd,
        "engines": available_engines(settings),
        "release_policy": release_policy_summary(),
        "recommendation": _recommendation(settings),
        "preflight": preflight(settings),
    }


@router.put("")
def update_engine(payload: EngineSettingsPayload) -> dict:
    checkpoint = payload.native_checkpoint.strip() if payload.native_checkpoint else None
    if payload.usage_mode == "commercial" and payload.transcription_engine == "muscriptor":
        raise HTTPException(
            422,
            "MuScriptor 공개 weights는 CC BY-NC 4.0이므로 상용 모드에서는 사용할 수 없습니다.",
        )
    if payload.transcription_engine == "native":
        if not checkpoint:
            raise HTTPException(422, "AudioScore Native requires a project-owned checkpoint path.")
        path = Path(checkpoint).expanduser()
        if not path.is_file():
            raise HTTPException(422, f"Native checkpoint does not exist: {path}")

    _store.update(
        {
            "usage_mode": payload.usage_mode,
            "transcription_engine": payload.transcription_engine,
            "mt3_infer_cmd": payload.mt3_infer_cmd,
            "mt3_model": payload.mt3_model or "yourmt3",
            "muscriptor_cmd": payload.muscriptor_cmd,
            "muscriptor_model": payload.muscriptor_model or "large",
            "native_engine_cmd": payload.native_engine_cmd,
            "native_checkpoint": checkpoint,
        }
    )
    return get_engines()

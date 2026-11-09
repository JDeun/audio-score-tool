from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from .config import packaged_runtime
from .engine_release_policy import release_policy_summary
from .optional_feature_policy import optional_feature_summary
from .preflight_v2 import preflight
from .runtime_settings import published_managed_mt3_model, runtime_settings
from .settings_store import SettingsStore
from .transcription_engine import MuScriptorEngine, SheetSage2Engine, available_engines

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
    sheetsage2_cmd: str | None = None
    sheetsage2_snapshot: str | None = None

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
        if normalized not in {"mt3_infer", "muscriptor", "native", "sheetsage2"}:
            raise ValueError(
                "transcription_engine must be 'mt3_infer', 'muscriptor', 'native', or 'sheetsage2'"
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
    managed = published_managed_mt3_model()
    if managed:
        return {
            "engine": "mt3_infer",
            "model": managed,
            "release_approved_default": False,
            "reason": (
                "이 플랫폼에 게시·검증된 관리형 모델입니다. "
                "실제 채보 품질의 v1 승인 여부는 별도 Tier 2 게이트에서 판단합니다."
            ),
        }
    if settings.usage_mode == "personal":
        currently_runnable = MuScriptorEngine(settings).ready()
        return {
            "engine": "muscriptor",
            "model": settings.muscriptor_model,
            "currently_runnable": currently_runnable,
            # A model preference is not equivalent to a release-approved
            # checkpoint, measured real-music quality or redistribution rights.
            "release_approved_default": False,
            "reason": (
                "개인/비상업 품질 우선 연구 후보. 실제 사용 준비가 확인됐습니다."
                if currently_runnable else
                "개인/비상업 품질 우선 후보이나 실행 런타임·선택한 모델 "
                "체크포인트·MusicXML 변환기가 아직 준비되지 않았습니다."
            ),
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
        "packaged_runtime": packaged_runtime(),
        "managed_mt3_model": published_managed_mt3_model(),
        "usage_mode": settings.usage_mode,
        "selected": settings.transcription_engine,
        "mt3_infer_cmd": settings.mt3_infer_cmd,
        "mt3_model": settings.mt3_model,
        "muscriptor_cmd": settings.muscriptor_cmd,
        "muscriptor_model": settings.muscriptor_model,
        "native_checkpoint": str(settings.native_checkpoint) if settings.native_checkpoint else None,
        "native_engine_cmd": settings.native_engine_cmd,
        "sheetsage2_cmd": settings.sheetsage2_cmd,
        "sheetsage2_snapshot": str(settings.sheetsage2_snapshot) if settings.sheetsage2_snapshot else None,
        "engines": available_engines(settings),
        "release_policy": release_policy_summary(),
        "optional_feature_policy": optional_feature_summary(),
        "recommendation": _recommendation(settings),
        "preflight": preflight(settings),
    }


@router.put("")
def update_engine(payload: EngineSettingsPayload) -> dict:
    checkpoint = payload.native_checkpoint.strip() if payload.native_checkpoint else None
    if payload.usage_mode == "commercial" and payload.transcription_engine in {"muscriptor", "sheetsage2"}:
        raise HTTPException(
            422,
            f"{payload.transcription_engine} 공개 weights는 CC BY-NC 4.0이므로 상용 모드에서는 사용할 수 없습니다.",
        )
    if packaged_runtime():
        if payload.transcription_engine in {"native", "sheetsage2"}:
            raise HTTPException(
                409, f"배포 앱에서는 미승인 {payload.transcription_engine} 모델을 선택할 수 없습니다."
            )
        if any((
            payload.mt3_infer_cmd, payload.muscriptor_cmd, payload.native_engine_cmd,
            payload.sheetsage2_cmd, payload.sheetsage2_snapshot,
        )):
            raise HTTPException(
                409, "배포 앱에서는 사용자 지정 실행 명령을 사용할 수 없습니다."
            )
    current = runtime_settings(store=_store)
    if payload.transcription_engine == "sheetsage2":
        candidate = replace(current, sheetsage2_cmd=payload.sheetsage2_cmd or current.sheetsage2_cmd,
                            sheetsage2_snapshot=Path(payload.sheetsage2_snapshot).expanduser()
                            if payload.sheetsage2_snapshot else current.sheetsage2_snapshot)
        if not SheetSage2Engine(candidate).ready():
            raise HTTPException(409, "Pinned SheetSage2 runtime/checkpoints are unavailable")
    if payload.transcription_engine == "muscriptor":
        # The Model Manager's /api/models/select endpoint already rejects
        # unready variants. Keep this alternative settings route equally
        # strict; never persist a selected but unusable transcription engine.
        variant = payload.muscriptor_model or current.muscriptor_model
        candidate = replace(
            current,
            usage_mode=payload.usage_mode,
            transcription_engine="muscriptor",
            muscriptor_model=variant,
            muscriptor_cmd=(
                current.muscriptor_cmd if packaged_runtime()
                else payload.muscriptor_cmd or current.muscriptor_cmd
            ),
        )
        if not MuScriptorEngine(candidate).ready():
            raise HTTPException(
                409,
                "선택한 MuScriptor 모델을 실행할 준비가 되지 않았습니다. "
                "모델 관리자에서 해당 가중치, 실행 런타임, 내장 music21을 확인하세요.",
            )
    managed = published_managed_mt3_model()
    if (
        packaged_runtime()
        and managed
        and payload.transcription_engine == "mt3_infer"
        and payload.mt3_model not in (None, managed)
    ):
        raise HTTPException(
            422,
            f"배포된 관리형 MT3 모델은 {managed}만 지원합니다. "
            "임의 체크포인트는 이 배포판에서 사용할 수 없습니다.",
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
            # Updating one engine must not silently reset the other
            # provider's installed/default model selection.
            "mt3_model": managed or payload.mt3_model or current.mt3_model,
            "muscriptor_cmd": payload.muscriptor_cmd,
            "muscriptor_model": payload.muscriptor_model or current.muscriptor_model,
            "native_engine_cmd": payload.native_engine_cmd,
            "native_checkpoint": checkpoint,
            "sheetsage2_cmd": payload.sheetsage2_cmd or current.sheetsage2_cmd,
            "sheetsage2_snapshot": payload.sheetsage2_snapshot or (
                str(current.sheetsage2_snapshot) if current.sheetsage2_snapshot else None),
        }
    )
    return get_engines()

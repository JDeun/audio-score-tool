from __future__ import annotations

import platform

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .managed_component_catalog import artifact_for, catalog_summary
from .managed_components import (
    ComponentError,
    component_status,
    install_component_artifact,
    recover_component_staging,
)
from .preflight_v2 import preflight
from .runner import command_exists
from .runtime_settings import runtime_settings
from .system_status import huggingface_authenticated

router = APIRouter(tags=["setup-center"])

_MANAGED_COMPONENTS = {
    "transcription_engine",
    "whisperx",
    "youtube_runtime",
    "audiveris",
    "audio_validation",
}


class InstallRequest(BaseModel):
    component: str


def _platform_key() -> str:
    name = platform.system().lower()
    if name == "darwin":
        return "macos"
    if name == "windows":
        return "windows"
    return "linux"


def _managed_detail(key: str) -> tuple[dict, dict]:
    status = component_status(key)
    catalog = catalog_summary(key)
    return status, catalog


def _component(
    key: str,
    label: str,
    ready: bool,
    *,
    tier: str,
    delivery: str,
    role: str,
    required_for: list[str],
    note: str | None = None,
) -> dict:
    managed_status = None
    catalog = None
    auto_install = False
    if delivery in {"managed-component", "managed-model-runtime"}:
        managed_status, catalog = _managed_detail(key)
        ready = ready or bool(managed_status.get("ready"))
        auto_install = bool(catalog.get("published"))
    return {
        "key": key,
        "label": label,
        "ready": ready,
        "tier": tier,
        "delivery": delivery,
        "role": role,
        "required_for": required_for,
        "download_url": None,
        "note": note,
        "auto_install": auto_install,
        "install_command": None,
        "managed_status": managed_status,
        "catalog": catalog,
    }


def setup_center_status() -> dict:
    settings = runtime_settings()
    state = preflight(settings, require_lyrics=False)
    tools = state["tools"]
    hf_ready = huggingface_authenticated()
    engine_ready = bool(tools.get("transcription_engine"))
    embedded_pdf_ready = bool(tools.get("embedded_pdf"))

    components = [
        _component(
            "desktop_runtime",
            "AudioScoreTool 내장 런타임",
            embedded_pdf_ready and bool(tools.get("music21")),
            tier="core",
            delivery="embedded",
            role="MusicXML/MIDI 처리와 PDF 출판을 설치 파일 내부에서 수행합니다.",
            required_for=["musicxml", "midi", "pdf_export", "part_export"],
            note="Python, music21, Verovio, fpdf2는 packaged backend sidecar에 포함되어야 합니다.",
        ),
        _component(
            "transcription_engine",
            str(state["engine"].get("name") or "채보 엔진"),
            engine_ready,
            tier="core",
            delivery="managed-model-runtime",
            role="음원에서 MusicXML 초안을 생성합니다.",
            required_for=["audio_transcription"],
            note=(
                "시스템 pip/uvx를 사용하지 않습니다. 게시된 runtime artifact는 SHA-256 검증 후 "
                "앱 데이터 영역에 atomic install되며 실패 시 기존 runtime을 유지합니다."
            ),
        ),
        _component(
            "huggingface_auth",
            "모델 접근 인증",
            hf_ready or settings.transcription_engine != "muscriptor",
            tier="conditional",
            delivery="account-credential",
            role="라이선스/배포 정책상 앱에 포함할 수 없는 모델 가중치 접근에 사용합니다.",
            required_for=["muscriptor"],
            note="MuScriptor public weights를 사용할 때만 필요합니다.",
        ),
        _component(
            "whisperx",
            "가사 정렬 엔진",
            bool(tools.get("whisperx")),
            tier="optional",
            delivery="managed-component",
            role="가사를 인식하고 보컬 음표에 정렬합니다.",
            required_for=["lyrics"],
            note="설치된 component는 앱 관리 root 밖의 executable을 참조할 수 없습니다.",
        ),
        _component(
            "youtube_runtime",
            "YouTube 가져오기 런타임",
            command_exists(settings.yt_dlp_cmd) and command_exists(settings.ffmpeg_cmd),
            tier="optional",
            delivery="managed-component",
            role="YouTube URL에서 오디오를 가져오고 미디어를 변환합니다.",
            required_for=["youtube_import"],
            note="yt-dlp와 필요한 media runtime을 하나의 검증된 managed component로 취급합니다.",
        ),
        _component(
            "audiveris",
            "OMR 엔진",
            bool(tools.get("audiveris_optional")),
            tier="optional",
            delivery="managed-component",
            role="PDF/이미지 악보를 MusicXML로 가져옵니다.",
            required_for=["omr"],
            note="JVM/runtime을 포함한 배포 artifact가 게시된 경우에만 앱 내부 설치를 허용합니다.",
        ),
        _component(
            "audio_validation",
            "오디오 검증 도구",
            command_exists(settings.ffmpeg_cmd) and command_exists(settings.fluidsynth_cmd),
            tier="optional",
            delivery="managed-component",
            role="원음 정규화와 MIDI 재합성 비교에 사용합니다.",
            required_for=["audio_validation"],
            note="FFmpeg/FluidSynth는 핵심 편집·출판 기능을 차단하지 않습니다.",
        ),
        _component(
            "llm",
            "LLM / Vision API",
            True,
            tier="optional",
            delivery="external-service",
            role="의심 구간 설명과 OMR 시각 비교를 보조합니다.",
            required_for=["llm_validation", "vision_validation"],
            note="필수가 아니며 기본 OFF입니다. 외부 API를 사용하면 네트워크가 필요합니다.",
        ),
    ]
    core = [item for item in components if item["tier"] == "core"]
    return {
        "platform": _platform_key(),
        "core_ready": all(item["ready"] for item in core),
        "recommended_ready": all(item["ready"] for item in core),
        "components": components,
        "profiles": {
            "core": "음원/악보 입력 → 편집 → MusicXML/MIDI/PDF export",
            "optional": "YouTube, OMR, 가사 정렬, 오디오/LLM 검증",
        },
        "policy": {
            "pdf_renderer": "embedded-verovio-fpdf2",
            "musescore_required": False,
            "lilypond_required": False,
            "llm_required": False,
            "system_package_manager_required": False,
            "developer_toolchain_required": False,
            "optional_features_do_not_block_core": True,
            "desktop_release_must_not_require_manual_runtime_install": True,
            "managed_component_integrity": "sha256+atomic-state+root-containment",
            "managed_component_system_path_fallback": False,
        },
    }


@router.get("/api/setup/center")
def get_setup_center() -> dict:
    return setup_center_status()


@router.post("/api/setup/install")
def install_setup_component(payload: InstallRequest) -> dict:
    component = payload.component.strip()
    if component not in _MANAGED_COMPONENTS:
        raise HTTPException(
            409,
            (
                f"{component}: 앱 관리 설치 대상이 아닙니다. 시스템 package manager를 통한 "
                "설치는 지원하지 않습니다."
            ),
        )
    try:
        artifact = artifact_for(component)
        result = install_component_artifact(artifact)
    except ComponentError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"installed": result, "setup": setup_center_status()}


@router.post("/api/setup/recover")
def recover_setup_components() -> dict:
    return {"recovery": recover_component_staging(), "setup": setup_center_status()}

from __future__ import annotations

import platform

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .preflight_v2 import preflight
from .runner import command_exists
from .runtime_settings import runtime_settings
from .system_status import huggingface_authenticated

router = APIRouter(tags=["setup-center"])


class InstallRequest(BaseModel):
    component: str


def _platform_key() -> str:
    name = platform.system().lower()
    if name == "darwin":
        return "macos"
    if name == "windows":
        return "windows"
    return "linux"


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
        "auto_install": False,
        "install_command": None,
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
                "최종 배포에서는 시스템 pip/uvx 설치를 요구하지 않습니다. "
                "엔진과 모델은 앱 번들 또는 앱 데이터 영역의 관리형 component로 제공해야 합니다."
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
            note="최종 데스크탑 배포에서는 시스템 설치가 아니라 앱 관리 component로 제공해야 합니다.",
        ),
        _component(
            "youtube_runtime",
            "YouTube 가져오기 런타임",
            command_exists(settings.yt_dlp_cmd),
            tier="optional",
            delivery="managed-component",
            role="YouTube URL에서 오디오를 가져옵니다.",
            required_for=["youtube_import"],
            note=(
                "yt-dlp뿐 아니라 필요한 JS runtime/미디어 도구까지 앱이 함께 관리해야 하며, "
                "사용자에게 별도 설치를 요구하지 않는 것을 배포 기준으로 합니다."
            ),
        ),
        _component(
            "audiveris",
            "OMR 엔진",
            bool(tools.get("audiveris_optional")),
            tier="optional",
            delivery="managed-component",
            role="PDF/이미지 악보를 MusicXML로 가져옵니다.",
            required_for=["omr"],
            note="Java/Audiveris의 시스템 설치를 정식 배포 전제조건으로 두지 않습니다.",
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
        },
    }


@router.get("/api/setup/center")
def get_setup_center() -> dict:
    return setup_center_status()


@router.post("/api/setup/install")
def install_setup_component(payload: InstallRequest) -> dict:
    raise HTTPException(
        409,
        (
            f"{payload.component}: 시스템 package manager를 통한 자동 설치는 비활성화되었습니다. "
            "정식 데스크탑 배포에서는 필요한 component를 앱이 자체적으로 번들하거나 관리해야 합니다."
        ),
    )

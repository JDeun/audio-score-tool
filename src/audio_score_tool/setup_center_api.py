from __future__ import annotations

import platform
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .preflight_v2 import preflight
from .runner import CommandError, command_exists, run_command
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


def _installer_recipe(component: str) -> dict:
    os_key = _platform_key()
    recipes: dict[str, dict[str, tuple[str, list[str]]]] = {
        "macos": {
            "ffmpeg": ("brew", ["install", "ffmpeg"]),
            "fluidsynth": ("brew", ["install", "fluid-synth"]),
            "lilypond": ("brew", ["install", "lilypond"]),
        },
        "windows": {
            "ffmpeg": ("winget", ["install", "-e", "--id", "Gyan.FFmpeg", "--accept-package-agreements", "--accept-source-agreements"]),
        },
        "linux": {},
    }
    recipe = recipes.get(os_key, {}).get(component)
    if not recipe:
        return {"available": False, "manager": None, "command": None}
    manager, args = recipe
    return {
        "available": command_exists(manager),
        "manager": manager,
        "command": " ".join([manager, *args]),
        "args": args,
    }


def _component(
    key: str,
    label: str,
    ready: bool,
    *,
    tier: str,
    role: str,
    required_for: list[str],
    download_url: str | None = None,
    note: str | None = None,
) -> dict:
    recipe = _installer_recipe(key)
    return {
        "key": key,
        "label": label,
        "ready": ready,
        "tier": tier,
        "role": role,
        "required_for": required_for,
        "download_url": download_url,
        "note": note,
        "auto_install": recipe["available"],
        "install_command": recipe.get("command"),
    }


def setup_center_status() -> dict:
    settings = runtime_settings()
    state = preflight(settings, require_lyrics=False)
    tools = state["tools"]
    hf_ready = huggingface_authenticated()
    renderer_ready = bool(
        (tools.get("lilypond") and tools.get("musicxml2ly"))
        or tools.get("musescore_optional")
    )
    components = [
        _component(
            "transcription_engine",
            state["engine"].get("display_name") or "채보 엔진",
            bool(tools.get("transcription_engine")),
            tier="core",
            role="음원에서 MusicXML 초안을 생성합니다.",
            required_for=["audio_transcription"],
            note="선택한 엔진은 설정의 개인/상용 모드에 따라 자동 결정됩니다.",
        ),
        _component(
            "huggingface_auth",
            "Hugging Face 인증",
            hf_ready or settings.transcription_engine != "muscriptor",
            tier="core" if settings.transcription_engine == "muscriptor" else "optional",
            role="MuScriptor 공개 가중치 접근에 필요합니다.",
            required_for=["muscriptor"],
            download_url="https://huggingface.co/settings/tokens",
            note="MuScriptor를 사용하지 않으면 필요하지 않습니다.",
        ),
        _component(
            "whisperx",
            "WhisperX",
            bool(tools.get("whisperx")),
            tier="recommended",
            role="가사를 인식하고 보컬 음표에 정렬합니다.",
            required_for=["lyrics"],
            note="가사 없는 악보라면 설치하지 않아도 됩니다.",
        ),
        _component(
            "lilypond",
            "LilyPond PDF 엔진",
            renderer_ready,
            tier="recommended",
            role="출판용 PDF를 생성합니다. MuseScore는 선택적 fallback입니다.",
            required_for=["pdf_export"],
            download_url="https://lilypond.org/download.html",
        ),
        _component(
            "audiveris",
            "Audiveris OMR",
            bool(tools.get("audiveris_optional")),
            tier="optional",
            role="PDF/이미지 악보를 MusicXML로 가져옵니다.",
            required_for=["omr"],
            download_url="https://audiveris.github.io/audiveris/",
            note="음원 채보만 사용하면 설치할 필요가 없습니다.",
        ),
        _component(
            "ffmpeg",
            "FFmpeg",
            command_exists(settings.ffmpeg_cmd),
            tier="optional",
            role="Audio evidence 검증용 오디오를 정규화합니다.",
            required_for=["audio_validation"],
            download_url="https://ffmpeg.org/download.html",
        ),
        _component(
            "fluidsynth",
            "FluidSynth",
            command_exists(settings.fluidsynth_cmd),
            tier="optional",
            role="현재 악보를 검증용 오디오로 재합성합니다.",
            required_for=["audio_validation"],
            download_url="https://www.fluidsynth.org/download/",
        ),
        _component(
            "llm",
            "LLM / Vision API",
            True,
            tier="optional",
            role="의심 구간 설명과 OMR 시각 비교를 보조합니다.",
            required_for=["llm_validation", "vision_validation"],
            note="필수가 아니며 기본 OFF입니다. 로컬 모델 또는 HTTPS OpenAI-compatible API를 선택적으로 연결합니다.",
        ),
    ]
    core = [item for item in components if item["tier"] == "core"]
    recommended = [item for item in components if item["tier"] in {"core", "recommended"}]
    return {
        "platform": _platform_key(),
        "core_ready": all(item["ready"] for item in core),
        "recommended_ready": all(item["ready"] for item in recommended),
        "components": components,
        "profiles": {
            "core": "음원 → 편집 가능한 MusicXML",
            "recommended": "채보 + 가사 + PDF 출판",
            "full": "OMR 및 Audio/LLM 검증까지 포함",
        },
        "policy": {
            "llm_required": False,
            "musescore_required": False,
            "optional_features_do_not_block_core": True,
        },
    }


@router.get("/api/setup/center")
def get_setup_center() -> dict:
    return setup_center_status()


@router.post("/api/setup/install")
def install_setup_component(payload: InstallRequest) -> dict:
    recipe = _installer_recipe(payload.component)
    if not recipe["available"]:
        raise HTTPException(
            422,
            "이 운영체제에서는 해당 구성요소를 앱에서 자동 설치할 수 없습니다. 공식 다운로드를 사용하세요.",
        )
    manager = str(recipe["manager"])
    args = list(recipe["args"])
    try:
        result = run_command(manager, args)
    except CommandError as exc:
        raise HTTPException(502, f"설치 명령 실행 실패: {exc}") from exc
    return {
        "installed": True,
        "component": payload.component,
        "command": recipe["command"],
        "stdout": getattr(result, "stdout", "")[-4000:] if result is not None else "",
        "status": setup_center_status(),
    }

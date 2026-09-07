from __future__ import annotations

from .config import Settings


def setup_instructions() -> dict:
    settings = Settings()
    return {
        "runtime": {
            "recommended": (
                "MuScriptor large" if settings.usage_mode == "personal" else "YourMT3+ via MT3-Infer"
            ),
            "note": (
                "AudioScoreTool은 정확도 우선 정책을 사용합니다. 개인/비상업 모드에서는 "
                "MuScriptor-large를 우선하고, 상용 모드에서는 MuScriptor의 CC BY-NC weights를 "
                "차단한 뒤 YourMT3+를 우선 후보로 사용합니다."
            ),
        },
        "setup_center": {
            "route": "/api/setup/center",
            "policy": (
                "첫 실행 설치 도우미는 기본 채보에 필요한 항목과 선택 기능을 분리합니다. "
                "OMR, Audio evidence, LLM/Vision은 기본 채보를 막지 않습니다."
            ),
            "automatic_install": (
                "신뢰할 수 있는 OS 패키지 관리자가 확인된 구성요소만 앱에서 자동 설치합니다. "
                "지원되지 않는 항목은 공식 다운로드와 설치 명령을 제공합니다."
            ),
        },
        "python_tools": [
            {"name": "MT3-Infer", "command": settings.mt3_infer_cmd},
            {"name": "AudioScore Native", "command": settings.native_engine_cmd},
            {"name": "MuScriptor", "command": settings.muscriptor_cmd},
            {"name": "Demucs", "command": settings.demucs_cmd},
            {"name": "WhisperX", "command": settings.whisperx_cmd},
        ],
        "notation": {
            "music21": "기본 Python dependency이며 MIDI↔MusicXML 변환을 담당합니다.",
            "lilypond": "PDF 생성용 권장 renderer입니다. macOS/Homebrew 환경에서는 Setup Center에서 자동 설치할 수 있습니다.",
            "musescore": "필수가 아닙니다. 특정 MusicXML 호환성 문제를 위한 선택적 fallback입니다.",
        },
        "omr": "PDF/이미지 악보 가져오기를 사용할 때만 Audiveris가 필요합니다.",
        "validation": {
            "deterministic": "추가 설치 없이 기본 검증으로 사용합니다.",
            "audio": "선택 기능이며 FFmpeg, FluidSynth, 사용자 SoundFont가 필요합니다.",
            "llm": "선택 기능이며 기본 OFF입니다. 로컬 모델 또는 HTTPS OpenAI-compatible API를 사용할 수 있습니다.",
        },
        "hf_required": settings.transcription_engine == "muscriptor",
        "hf_login_command": "uvx hf auth login",
        "hf_note": (
            "MuScriptor 공개 가중치를 선택한 경우 Hugging Face upstream model license 수락과 "
            "인증이 필요합니다. 공개 weights는 CC BY-NC 4.0이므로 상용 모드에서는 차단됩니다."
        ),
        "mt3_note": (
            "YourMT3+는 MT3 계열 정확도 우선 후보이며 MR-MT3는 provenance가 더 단순한 fallback입니다. "
            "상용 배포 전에는 실제 고정한 YourMT3 source/checkpoint provenance를 다시 검토해야 합니다."
        ),
        "native_note": (
            "AudioScore Native는 장기적으로 모델까지 직접 소유하고 싶은 경우를 위한 R&D 경로입니다. "
            "기본 앱 사용을 위해 Native 모델을 처음부터 학습할 필요는 없습니다."
        ),
    }

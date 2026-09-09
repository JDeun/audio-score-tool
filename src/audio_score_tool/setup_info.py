from __future__ import annotations

from .config import Settings


def setup_instructions() -> dict:
    settings = Settings()
    return {
        "runtime": {
            "recommended": (
                "MuScriptor large" if settings.usage_mode == "personal" else "YourMT3+ via managed MT3 runtime"
            ),
            "note": (
                "AudioScoreTool은 정확도 우선 정책을 사용합니다. 개인/비상업 모드에서는 "
                "MuScriptor-large를 우선하고, 상용 모드에서는 MuScriptor의 CC BY-NC weights를 "
                "차단한 뒤 상업 사용이 허용된 provider를 사용합니다."
            ),
        },
        "setup_center": {
            "route": "/api/setup/center",
            "policy": (
                "Setup Center는 시스템 package manager 설치 도우미가 아니라 앱 내장 runtime과 "
                "app-managed model/component의 준비 상태를 검증합니다."
            ),
            "automatic_install": (
                "일반 사용자에게 Homebrew, winget, pip, uv/uvx 설치를 요구하지 않습니다. "
                "공식 지원 component는 AudioScoreTool이 자체 bundle/download/update lifecycle을 소유합니다."
            ),
        },
        "managed_components": [
            {"name": "AMT runtime/model", "path": settings.mt3_infer_cmd},
            {"name": "AudioScore Native", "path": settings.native_engine_cmd},
            {"name": "MuScriptor runtime", "path": settings.muscriptor_cmd},
            {"name": "Demucs", "path": settings.demucs_cmd},
            {"name": "WhisperX", "path": settings.whisperx_cmd},
            {"name": "YouTube runtime", "path": settings.yt_dlp_cmd},
            {"name": "OMR runtime", "path": settings.audiveris_cmd},
        ],
        "notation": {
            "preview": "OSMD가 앱 내 MusicXML 미리보기를 담당합니다.",
            "music21": "sidecar 기본 dependency이며 MIDI↔MusicXML 변환을 담당합니다.",
            "pdf": "Verovio SVG + fpdf2로 앱 내부에서 vector PDF를 생성합니다.",
            "policy": "MuseScore, LilyPond, musicxml2ly를 runtime 또는 fallback으로 사용하지 않습니다.",
        },
        "omr": (
            "PDF/이미지 악보 가져오기는 선택 기능입니다. Audiveris를 유지할 경우 필요한 JRE와 함께 "
            "app-managed component로 제공하며 시스템 Java 설치를 사용자에게 요구하지 않습니다."
        ),
        "validation": {
            "deterministic": "기본 앱에 내장된 검증입니다.",
            "audio": "선택 기능이며 필요한 native 도구는 app-managed component로 제공합니다.",
            "llm": "선택 기능이며 기본 OFF입니다. 로컬 모델 또는 HTTPS OpenAI-compatible API를 사용할 수 있습니다.",
        },
        "hf_required": settings.transcription_engine == "muscriptor",
        "hf_auth": "모델 라이선스 수락 후 read token을 현재 앱 세션 메모리에만 전달합니다.",
        "hf_note": (
            "MuScriptor 공개 가중치를 선택한 경우 Hugging Face upstream model license 수락과 "
            "계정 인증이 필요합니다. 모델 다운로드는 sidecar의 huggingface_hub API가 직접 수행하며 "
            "hf/uvx CLI를 실행하지 않습니다."
        ),
        "mt3_note": (
            "MT3 계열 provider는 inference runtime와 checkpoint를 하나의 signed/versioned managed artifact로 "
            "배포하는 것을 목표로 합니다. source 개발에서만 command override를 허용합니다."
        ),
        "native_note": (
            "AudioScore Native는 장기적으로 모델까지 직접 소유하기 위한 R&D 경로입니다. "
            "정식 사용자에게 학습 toolchain을 요구하지 않습니다."
        ),
    }

from __future__ import annotations

import platform

from .config import Settings


def setup_instructions() -> dict:
    system = platform.system()
    settings = Settings()
    muse = {
        "Darwin": "MuseScore 4를 설치하면 표준 앱 경로를 자동으로 찾습니다.",
        "Windows": "MuseScore 4를 설치하고 앱이 찾지 못하면 실행 파일 경로를 지정하세요.",
        "Linux": "MuseScore 4/AppImage를 설치하고 앱이 찾지 못하면 실행 파일 경로를 지정하세요.",
    }.get(system, "MuseScore 4를 설치하고 필요하면 AST_MUSESCORE_CMD를 지정하세요.")

    return {
        "runtime": {
            "recommended": "AudioScore Native / MuScriptor provider",
            "note": (
                "AudioScoreTool v0.7부터 채보 엔진은 교체 가능한 provider 구조입니다. "
                "상업 배포는 프로젝트 소유 체크포인트를 사용하는 AudioScore Native를 권장합니다."
            ),
        },
        "python_tools": [
            {"name": "AudioScore Native", "command": settings.native_engine_cmd},
            {"name": "MuScriptor", "command": settings.muscriptor_cmd},
            {"name": "Demucs", "command": settings.demucs_cmd},
            {"name": "WhisperX", "command": settings.whisperx_cmd},
        ],
        "musescore": muse,
        "hf_required": settings.transcription_engine == "muscriptor",
        "hf_login_command": "uvx hf auth login",
        "hf_note": (
            "MuScriptor 공개 가중치를 사용하는 경우에만 Hugging Face의 upstream CC BY-NC 4.0 "
            "모델 라이선스 수락과 로컬 인증이 필요합니다. AudioScore Native는 Hugging Face 인증을 "
            "요구하지 않으며 프로젝트 소유 체크포인트를 사용합니다."
        ),
        "native_note": (
            "AudioScore Native 체크포인트는 상업 사용이 명시적으로 허용된 데이터만으로 독립 학습해야 합니다. "
            "학습 manifest는 허용되지 않은 라이선스를 자동 거부합니다."
        ),
    }

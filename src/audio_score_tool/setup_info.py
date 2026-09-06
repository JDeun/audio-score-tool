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
            "recommended": "MR-MT3 via MT3-Infer",
            "note": (
                "AudioScoreTool v0.7부터 채보 엔진은 교체 가능한 provider 구조입니다. "
                "기본 권장 엔진은 별도 학습이 필요 없는 MR-MT3이며, mt3-infer가 checkpoint를 "
                "첫 사용 시 로컬 캐시에 자동 다운로드합니다."
            ),
        },
        "python_tools": [
            {"name": "MR-MT3 / MT3-Infer", "command": settings.mt3_infer_cmd},
            {"name": "AudioScore Native", "command": settings.native_engine_cmd},
            {"name": "MuScriptor", "command": settings.muscriptor_cmd},
            {"name": "Demucs", "command": settings.demucs_cmd},
            {"name": "WhisperX", "command": settings.whisperx_cmd},
        ],
        "musescore": muse,
        "hf_required": settings.transcription_engine == "muscriptor",
        "hf_login_command": "uvx hf auth login",
        "hf_note": (
            "MuScriptor 공개 가중치를 선택한 경우에만 Hugging Face의 upstream 비상업 모델 "
            "라이선스 수락과 로컬 인증이 필요합니다. MR-MT3 기본 경로에는 이 승인이 필요하지 않습니다."
        ),
        "mt3_note": (
            "MT3-Infer 0.2.0은 MIT이며 기본 MR-MT3 원 저장소와 공개 checkpoint도 MIT로 "
            "표시되어 있습니다. checkpoint는 앱에 번들하지 않고 첫 사용 시 upstream에서 내려받습니다. "
            "YourMT3+는 품질 비교용 선택지로 남기지만 upstream 라이선스 표기 차이 때문에 상용 기본값으로 "
            "고정하지 않습니다."
        ),
        "native_note": (
            "AudioScore Native는 장기적으로 모델까지 직접 소유하고 싶은 경우를 위한 R&D 경로입니다. "
            "기본 앱 사용을 위해 Native 모델을 처음부터 학습할 필요는 없습니다."
        ),
    }

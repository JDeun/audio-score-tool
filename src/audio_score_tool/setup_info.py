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
        "python_tools": [
            {"name": "MT3-Infer", "command": settings.mt3_infer_cmd},
            {"name": "AudioScore Native", "command": settings.native_engine_cmd},
            {"name": "MuScriptor", "command": settings.muscriptor_cmd},
            {"name": "Demucs", "command": settings.demucs_cmd},
            {"name": "WhisperX", "command": settings.whisperx_cmd},
        ],
        "notation": {
            "music21": "기본 Python dependency이며 MIDI↔MusicXML 변환을 담당합니다.",
            "lilypond": (
                "PDF 생성용 권장 외부 renderer입니다. lilypond와 musicxml2ly가 PATH에 없으면 "
                "설정에서 경로를 지정하세요."
            ),
            "musescore": (
                "필수가 아닙니다. LilyPond/MusicXML 변환 호환성 문제가 있을 때 사용할 수 있는 "
                "선택적 fallback입니다."
            ),
        },
        "omr": (
            "PDF/이미지 악보 가져오기를 사용하려면 Audiveris를 설치하고 필요하면 "
            "AST_AUDIVERIS_CMD 또는 앱 설정에서 경로를 지정하세요."
        ),
        "hf_required": settings.transcription_engine == "muscriptor",
        "hf_login_command": "uvx hf auth login",
        "hf_note": (
            "MuScriptor 공개 가중치를 선택한 경우 Hugging Face upstream model license 수락과 "
            "로컬 인증이 필요합니다. 공개 weights는 CC BY-NC 4.0이므로 상용 모드에서는 차단됩니다."
        ),
        "mt3_note": (
            "YourMT3+는 MT3 계열 정확도 우선 후보이며 MR-MT3는 더 빠르고 provenance가 단순한 "
            "fallback입니다. 상용 배포 전에는 실제 고정한 YourMT3 source/checkpoint provenance를 "
            "다시 검토해야 합니다."
        ),
        "native_note": (
            "AudioScore Native는 장기적으로 모델까지 직접 소유하고 싶은 경우를 위한 R&D 경로입니다. "
            "기본 앱 사용을 위해 Native 모델을 처음부터 학습할 필요는 없습니다."
        ),
    }

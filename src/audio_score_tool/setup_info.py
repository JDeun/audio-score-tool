from __future__ import annotations

import platform

from .config import Settings


def setup_instructions() -> dict:
    system = platform.system()
    settings = Settings()
    muse = {
        "Darwin": "Install MuseScore 4 from musescore.org; the standard app path is auto-detected.",
        "Windows": "Install MuseScore 4 and set its executable path below if it is not visible to the app.",
        "Linux": "Install MuseScore 4/AppImage and set its path below if it is not visible to the app.",
    }.get(system, "Install MuseScore 4 and set AST_MUSESCORE_CMD if needed.")

    return {
        "runtime": {
            "recommended": "uv / uvx",
            "note": (
                "MuScriptor officially recommends uvx for local use. AudioScoreTool "
                "automatically uses installed CLIs first and falls back to uvx when available."
            ),
        },
        "python_tools": [
            {"name": "MuScriptor", "command": settings.muscriptor_cmd},
            {"name": "Demucs", "command": settings.demucs_cmd},
            {"name": "WhisperX", "command": settings.whisperx_cmd},
        ],
        "musescore": muse,
        "hf_required": True,
        "hf_login_command": "uvx hf auth login",
        "hf_note": (
            "Accept the upstream MuScriptor CC BY-NC 4.0 model license on Hugging Face, "
            "then authenticate locally. The weights are downloaded and cached on first use. "
            "AudioScoreTool never reads or displays your token value."
        ),
    }

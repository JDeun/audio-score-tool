from __future__ import annotations

import platform


def setup_instructions() -> dict:
    system = platform.system()
    muse = {
        "Darwin": "Install MuseScore 4 from musescore.org; the app path is auto-detected.",
        "Windows": "Install MuseScore 4 and ensure MuseScore4.exe is on PATH or set AST_MUSESCORE_CMD.",
        "Linux": "Install MuseScore 4/AppImage and ensure musescore is on PATH or set AST_MUSESCORE_CMD.",
    }.get(system, "Install MuseScore 4 and set AST_MUSESCORE_CMD if it is not on PATH.")

    return {
        "python_tools": [
            {"name": "MuScriptor", "command": "pip install muscriptor"},
            {"name": "Demucs", "command": "pip install demucs"},
            {"name": "WhisperX", "command": "pip install whisperx"},
        ],
        "musescore": muse,
        "hf_required": True,
        "hf_note": (
            "MuScriptor model weights are gated. Accept the upstream Hugging Face "
            "license and authenticate locally before first inference. AudioScoreTool "
            "does not store or redistribute your token or model weights."
        ),
    }

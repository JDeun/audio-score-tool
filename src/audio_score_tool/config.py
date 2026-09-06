from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(slots=True)
class Settings:
    muscriptor_cmd: str = os.getenv("AST_MUSCRIPTOR_CMD", "muscriptor")
    demucs_cmd: str = os.getenv("AST_DEMUCS_CMD", "demucs")
    whisperx_cmd: str = os.getenv("AST_WHISPERX_CMD", "whisperx")
    musescore_cmd: str | None = os.getenv("AST_MUSESCORE_CMD")
    muscriptor_model: str = os.getenv("AST_MUSCRIPTOR_MODEL", "medium")
    whisperx_model: str = os.getenv("AST_WHISPERX_MODEL", "small")

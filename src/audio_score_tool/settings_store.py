from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any

from .paths import app_data_dir

_ALLOWED = {
    "usage_mode",
    "transcription_engine",
    "mt3_infer_cmd",
    "mt3_model",
    "yourmt3_cmd",  # v0.7 prerelease migration key; read-only compatibility.
    "muscriptor_cmd",
    "muscriptor_model",
    "native_engine_cmd",
    "native_checkpoint",
    "demucs_cmd",
    "whisperx_cmd",
    "yt_dlp_cmd",
    "audiveris_cmd",
    "lilypond_cmd",
    "musicxml2ly_cmd",
    "musescore_cmd",
    "llm_validation_enabled",
    "llm_validation_base_url",
    "llm_validation_model",
    "llm_validation_api_key_env",
    "visual_validation_enabled",
    "visual_validation_model",
    "visual_validation_max_pages",
}


class SettingsStore:
    def __init__(self, path: Path | None = None):
        self.path = path or (app_data_dir() / "settings.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def read(self) -> dict[str, str | None]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return {key: payload.get(key) for key in _ALLOWED if key in payload}

    def update(self, values: dict[str, Any]) -> dict[str, str | None]:
        with self._lock:
            current = self.read()
            for key, value in values.items():
                if key not in _ALLOWED:
                    continue
                if value is None or value == "":
                    current.pop(key, None)
                else:
                    current[key] = str(value)
            temp = self.path.with_suffix(".tmp")
            temp.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(self.path)
        return current

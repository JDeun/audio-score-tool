from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any

from .paths import app_data_dir

_ALLOWED = {"muscriptor_cmd", "demucs_cmd", "whisperx_cmd", "musescore_cmd"}


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
        current = self.read()
        for key, value in values.items():
            if key not in _ALLOWED:
                continue
            if value is None or value == "":
                current.pop(key, None)
            else:
                current[key] = str(value)
        temp = self.path.with_suffix(".tmp")
        with self._lock:
            temp.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(self.path)
        return current

from __future__ import annotations

import json
import os
import platform
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .paths import app_data_dir


def _find_executable(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found

    suffix = ".exe" if platform.system() == "Windows" else ""
    candidates = [
        Path.home() / ".local" / "bin" / f"{name}{suffix}",
        Path.home() / ".cargo" / "bin" / f"{name}{suffix}",
    ]
    if platform.system() == "Windows":
        candidates += [
            Path(os.getenv("USERPROFILE", str(Path.home()))) / ".local" / "bin" / f"{name}.exe",
        ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def _has_nvidia() -> bool:
    return _find_executable("nvidia-smi") is not None


def _uvx_command(package: str) -> str | None:
    uvx = _find_executable("uvx")
    if not uvx:
        return None
    flags: list[str] = []
    if platform.system() == "Windows" and _has_nvidia() and package in {
        "muscriptor",
        "demucs",
        "whisperx",
    }:
        flags.append("--torch-backend=cu128")
    if (
        package == "muscriptor"
        and platform.system() == "Darwin"
        and platform.machine().lower() not in {"arm64", "aarch64"}
    ):
        flags.extend(["--python", "3.12"])
    executable = f'"{uvx}"' if " " in uvx else uvx
    return " ".join([executable, *flags, package])


def _default_command(name: str) -> str:
    installed = _find_executable(name)
    if installed:
        return installed
    uvx = _uvx_command(name)
    if uvx:
        return uvx
    return name


def _saved_settings() -> dict[str, str | None]:
    path = app_data_dir() / "settings.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _saved_or_env(key: str, env_name: str, default: str | None = None) -> str | None:
    env_value = os.getenv(env_name)
    if env_value:
        return env_value
    value = _saved_settings().get(key)
    if value:
        return str(value)
    return default


def _optional_path(key: str, env_name: str) -> Path | None:
    raw = _saved_or_env(key, env_name)
    return Path(raw).expanduser() if raw else None


@dataclass(slots=True)
class Settings:
    transcription_engine: str = field(
        default_factory=lambda: _saved_or_env(
            "transcription_engine", "AST_TRANSCRIPTION_ENGINE", "muscriptor"
        )
        or "muscriptor"
    )
    muscriptor_cmd: str = field(
        default_factory=lambda: _saved_or_env("muscriptor_cmd", "AST_MUSCRIPTOR_CMD")
        or _default_command("muscriptor")
    )
    native_engine_cmd: str = field(
        default_factory=lambda: _saved_or_env("native_engine_cmd", "AST_NATIVE_ENGINE_CMD")
        or _default_command("audio-score-native")
    )
    native_checkpoint: Path | None = field(
        default_factory=lambda: _optional_path("native_checkpoint", "AST_NATIVE_CHECKPOINT")
    )
    demucs_cmd: str = field(
        default_factory=lambda: _saved_or_env("demucs_cmd", "AST_DEMUCS_CMD")
        or _default_command("demucs")
    )
    whisperx_cmd: str = field(
        default_factory=lambda: _saved_or_env("whisperx_cmd", "AST_WHISPERX_CMD")
        or _default_command("whisperx")
    )
    yt_dlp_cmd: str = field(
        default_factory=lambda: _saved_or_env("yt_dlp_cmd", "AST_YT_DLP_CMD")
        or _default_command("yt-dlp")
    )
    musescore_cmd: str | None = field(
        default_factory=lambda: _saved_or_env("musescore_cmd", "AST_MUSESCORE_CMD")
    )
    muscriptor_model: str = field(
        default_factory=lambda: os.getenv("AST_MUSCRIPTOR_MODEL", "medium")
    )
    whisperx_model: str = field(
        default_factory=lambda: os.getenv("AST_WHISPERX_MODEL", "small")
    )

from __future__ import annotations

import json
import os
import platform
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .managed_tool_resolver import registered_managed_tool
from .paths import app_data_dir

MT3_INFER_VERSION = "0.2.0"


def packaged_runtime() -> bool:
    return os.getenv("AST_PACKAGED", "").strip() == "1"


def component_dir() -> Path:
    configured = os.getenv("AST_COMPONENT_DIR")
    if configured:
        return Path(configured).expanduser()
    return app_data_dir() / "components"


def managed_executable_path(name: str) -> Path:
    registered = registered_managed_tool(name)
    if registered is not None:
        return registered
    suffix = ".exe" if platform.system() == "Windows" else ""
    return component_dir() / "bin" / f"{name}{suffix}"


def _find_executable(name: str) -> str | None:
    # A packaged desktop app must never become accidentally dependent on a user's
    # shell environment. Only executables owned by AudioScoreTool's managed component
    # directory are eligible in release mode.
    if packaged_runtime():
        managed = managed_executable_path(name)
        return str(managed) if managed.is_file() else None

    found = shutil.which(name)
    if found:
        return found

    system = platform.system()
    suffix = ".exe" if system == "Windows" else ""
    candidates = [
        Path.home() / ".local" / "bin" / f"{name}{suffix}",
        Path.home() / ".cargo" / "bin" / f"{name}{suffix}",
    ]
    if system == "Darwin":
        candidates += [
            Path("/opt/homebrew/bin") / name,
            Path("/usr/local/bin") / name,
            Path("/usr/bin") / name,
            Path("/opt/homebrew/sbin") / name,
            Path("/usr/local/sbin") / name,
        ]
    elif system == "Linux":
        candidates += [
            Path("/usr/local/bin") / name,
            Path("/usr/bin") / name,
            Path("/snap/bin") / name,
        ]
    elif system == "Windows":
        user = Path(os.getenv("USERPROFILE", str(Path.home())))
        local_app_data = Path(os.getenv("LOCALAPPDATA", str(user / "AppData" / "Local")))
        candidates += [
            user / ".local" / "bin" / f"{name}.exe",
            local_app_data / "Microsoft" / "WindowsApps" / f"{name}.exe",
            Path(os.getenv("ProgramFiles", "C:/Program Files")) / name / f"{name}.exe",
        ]

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def _has_nvidia() -> bool:
    if packaged_runtime():
        return False
    return shutil.which("nvidia-smi") is not None


def _uvx_command(package: str) -> str | None:
    if packaged_runtime():
        return None
    uvx = _find_executable("uvx")
    if not uvx:
        return None
    flags: list[str] = []
    if platform.system() == "Windows" and _has_nvidia() and package in {"muscriptor", "demucs", "whisperx"}:
        flags.append("--torch-backend=cu128")
    if package == "muscriptor" and platform.system() == "Darwin" and platform.machine().lower() not in {"arm64", "aarch64"}:
        flags.extend(["--python", "3.12"])
    executable = f'"{uvx}"' if " " in uvx else uvx
    return " ".join([executable, *flags, package])


def _packaged_command(name: str) -> str:
    # Return the deterministic managed path even before the component exists. This
    # makes command_exists() report false without falling through to the system PATH.
    return str(managed_executable_path(name))


def _default_mt3_infer_command() -> str:
    if packaged_runtime():
        return _packaged_command("mt3-infer")
    installed = _find_executable("mt3-infer")
    if installed:
        return installed
    uvx = _find_executable("uvx")
    if uvx:
        executable = f'"{uvx}"' if " " in uvx else uvx
        args = [executable]
        if platform.system() == "Windows" and _has_nvidia():
            args.append("--torch-backend=cu128")
        args.extend(["--from", f"mt3-infer[torch]=={MT3_INFER_VERSION}", "mt3-infer"])
        return " ".join(args)
    return "mt3-infer"


def _default_command(name: str) -> str:
    if packaged_runtime():
        return _packaged_command(name)
    installed = _find_executable(name)
    if installed:
        return installed
    uvx = _uvx_command(name)
    if uvx:
        return uvx
    return name


def _external_command(name: str) -> str:
    if packaged_runtime():
        return _packaged_command(name)
    return _find_executable(name) or name


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
    saved = _saved_settings()
    value = saved.get(key)
    if value:
        return str(value)
    return default


def _command_setting(key: str, env_name: str, name: str, *, uvx: bool = True) -> str:
    if packaged_runtime():
        return _packaged_command(name)
    override = _saved_or_env(key, env_name)
    if override:
        return override
    return _default_command(name) if uvx else _external_command(name)


def _optional_path(key: str, env_name: str) -> Path | None:
    raw = _saved_or_env(key, env_name)
    return Path(raw).expanduser() if raw else None


def _saved_usage_mode() -> str:
    raw = (_saved_or_env("usage_mode", "AST_USAGE_MODE", "personal") or "personal").strip().lower()
    return raw if raw in {"personal", "commercial"} else "personal"


def _saved_engine() -> str:
    explicit = _saved_or_env("transcription_engine", "AST_TRANSCRIPTION_ENGINE")
    if explicit:
        raw = explicit.strip().lower()
        return "mt3_infer" if raw == "yourmt3" else raw
    return "muscriptor" if _saved_usage_mode() == "personal" else "mt3_infer"


def _saved_mt3_model() -> str:
    return (_saved_or_env("mt3_model", "AST_MT3_MODEL", "yourmt3") or "yourmt3").strip().lower()


def _saved_muscriptor_model() -> str:
    return (_saved_or_env("muscriptor_model", "AST_MUSCRIPTOR_MODEL", "large") or "large").strip().lower()


@dataclass(slots=True)
class Settings:
    usage_mode: str = field(default_factory=_saved_usage_mode)
    transcription_engine: str = field(default_factory=_saved_engine)
    mt3_infer_cmd: str = field(
        default_factory=lambda: _packaged_command("mt3-infer")
        if packaged_runtime()
        else (
            _saved_or_env("mt3_infer_cmd", "AST_MT3_INFER_CMD")
            or _saved_or_env("yourmt3_cmd", "AST_YOURMT3_CMD")
            or _default_mt3_infer_command()
        )
    )
    mt3_model: str = field(default_factory=_saved_mt3_model)
    muscriptor_cmd: str = field(default_factory=lambda: _command_setting("muscriptor_cmd", "AST_MUSCRIPTOR_CMD", "muscriptor"))
    muscriptor_model: str = field(default_factory=_saved_muscriptor_model)
    native_engine_cmd: str = field(default_factory=lambda: _command_setting("native_engine_cmd", "AST_NATIVE_ENGINE_CMD", "audio-score-native"))
    native_checkpoint: Path | None = field(default_factory=lambda: _optional_path("native_checkpoint", "AST_NATIVE_CHECKPOINT"))
    demucs_cmd: str = field(default_factory=lambda: _command_setting("demucs_cmd", "AST_DEMUCS_CMD", "demucs"))
    whisperx_cmd: str = field(default_factory=lambda: _command_setting("whisperx_cmd", "AST_WHISPERX_CMD", "whisperx"))
    yt_dlp_cmd: str = field(default_factory=lambda: _command_setting("yt_dlp_cmd", "AST_YT_DLP_CMD", "yt-dlp"))
    audiveris_cmd: str = field(default_factory=lambda: _command_setting("audiveris_cmd", "AST_AUDIVERIS_CMD", "audiveris", uvx=False))
    ffmpeg_cmd: str = field(default_factory=lambda: _command_setting("ffmpeg_cmd", "AST_FFMPEG_CMD", "ffmpeg", uvx=False))
    fluidsynth_cmd: str = field(default_factory=lambda: _command_setting("fluidsynth_cmd", "AST_FLUIDSYNTH_CMD", "fluidsynth", uvx=False))
    validation_soundfont: Path | None = field(default_factory=lambda: _optional_path("validation_soundfont", "AST_VALIDATION_SOUNDFONT"))
    whisperx_model: str = field(default_factory=lambda: os.getenv("AST_WHISPERX_MODEL", "small"))

    @property
    def yourmt3_cmd(self) -> str:
        return self.mt3_infer_cmd

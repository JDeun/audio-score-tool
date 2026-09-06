from __future__ import annotations

import os
import platform
import shutil
from dataclasses import dataclass, field
from pathlib import Path


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
    if platform.system() == "Windows" and _has_nvidia():
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


@dataclass(slots=True)
class Settings:
    muscriptor_cmd: str = field(
        default_factory=lambda: os.getenv("AST_MUSCRIPTOR_CMD") or _default_command("muscriptor")
    )
    demucs_cmd: str = field(
        default_factory=lambda: os.getenv("AST_DEMUCS_CMD") or _default_command("demucs")
    )
    whisperx_cmd: str = field(
        default_factory=lambda: os.getenv("AST_WHISPERX_CMD") or _default_command("whisperx")
    )
    musescore_cmd: str | None = field(default_factory=lambda: os.getenv("AST_MUSESCORE_CMD"))
    muscriptor_model: str = field(
        default_factory=lambda: os.getenv("AST_MUSCRIPTOR_MODEL", "medium")
    )
    whisperx_model: str = field(
        default_factory=lambda: os.getenv("AST_WHISPERX_MODEL", "small")
    )

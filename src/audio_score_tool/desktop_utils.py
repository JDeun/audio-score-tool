from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path


def _open_path(target: Path) -> None:
    system = platform.system()
    if system == "Windows":
        os.startfile(str(target))  # type: ignore[attr-defined]
        return
    command = ["open", str(target)] if system == "Darwin" else ["xdg-open", str(target)]
    subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def reveal_in_file_manager(path: Path) -> None:
    _open_path(path if path.is_dir() else path.parent)


def open_pdf_document(path: Path) -> None:
    if path.suffix.lower() != ".pdf" or not path.is_file():
        raise OSError("A generated PDF is required")
    _open_path(path)

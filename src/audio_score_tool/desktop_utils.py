from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path


def reveal_in_file_manager(path: Path) -> None:
    target = path if path.is_dir() else path.parent
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

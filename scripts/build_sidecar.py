from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "desktop"
BIN = DESKTOP / "src-tauri" / "binaries"
DIST = ROOT / "dist-sidecar"


def target_triple() -> str:
    try:
        return subprocess.check_output(
            ["rustc", "--print", "host-tuple"],
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        machine = platform.machine().lower()
        system = platform.system()
        if system == "Darwin":
            return f"{'aarch64' if machine in {'arm64', 'aarch64'} else 'x86_64'}-apple-darwin"
        if system == "Windows":
            return "x86_64-pc-windows-msvc"
        return f"{'aarch64' if machine in {'arm64', 'aarch64'} else 'x86_64'}-unknown-linux-gnu"


def main() -> None:
    BIN.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(DIST, ignore_errors=True)
    work = ROOT / "build-sidecar"
    shutil.rmtree(work, ignore_errors=True)

    component_catalog = ROOT / "src" / "audio_score_tool" / "managed-component-catalog.json"
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--onefile",
        "--name",
        "audio-score-backend",
        "--collect-data",
        "verovio",
        "--add-data",
        f"{component_catalog}{os.pathsep}audio_score_tool",
        "--distpath",
        str(DIST),
        "--workpath",
        str(work),
        "--specpath",
        str(work),
        str(ROOT / "scripts" / "backend_entry.py"),
    ]
    subprocess.run(cmd, cwd=ROOT, check=True)

    extension = ".exe" if os.name == "nt" else ""
    built = DIST / f"audio-score-backend{extension}"
    target = BIN / f"audio-score-backend-{target_triple()}{extension}"
    shutil.copy2(built, target)
    if os.name != "nt":
        target.chmod(0o755)
    print(target)


if __name__ == "__main__":
    main()

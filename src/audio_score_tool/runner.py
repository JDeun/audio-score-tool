from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Iterable


class CommandError(RuntimeError):
    pass


def split_command(value: str) -> list[str]:
    return shlex.split(value, posix=os.name != "nt")


def command_exists(command: str) -> bool:
    first = split_command(command)[0]
    if Path(first).is_file():
        return True
    if first in {"python", "python3", "py"}:
        return shutil.which(first) is not None
    return shutil.which(first) is not None


def run_command(
    command: str,
    args: Iterable[str | Path],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    argv = [*split_command(command), *(str(a) for a in args)]
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)

    proc = subprocess.run(
        argv,
        cwd=cwd,
        env=merged_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if proc.returncode != 0:
        raise CommandError(
            f"Command failed ({proc.returncode}): {' '.join(argv)}\n\n{proc.stdout}"
        )
    return proc

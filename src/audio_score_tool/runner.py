from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from collections.abc import Iterable
from pathlib import Path


class CommandError(RuntimeError):
    pass


def split_command(value: str) -> list[str]:
    # An explicit executable path may legitimately contain spaces (notably the
    # default MuseScore macOS app bundle). Treat an existing path atomically.
    expanded = str(Path(value).expanduser())
    if Path(expanded).is_file():
        return [expanded]
    return shlex.split(value, posix=os.name != "nt")


def command_exists(command: str) -> bool:
    parts = split_command(command)
    if not parts:
        return False
    first = parts[0]
    if Path(first).is_file():
        return True
    return shutil.which(first) is not None


def run_command(
    command: str,
    args: Iterable[str | Path],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    parts = split_command(command)
    if not parts:
        raise CommandError("Command is empty.")

    argv = [*parts, *(str(a) for a in args)]
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)

    try:
        proc = subprocess.run(
            argv,
            cwd=cwd,
            env=merged_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
    except OSError as exc:
        raise CommandError(f"Could not start command: {argv[0]} ({exc})") from exc

    if proc.returncode != 0:
        raise CommandError(
            f"Command failed ({proc.returncode}): {' '.join(argv)}\n\n{proc.stdout}"
        )
    return proc

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from collections.abc import Iterable
from pathlib import Path
from threading import Event


class CommandError(RuntimeError):
    pass


class CommandCancelled(CommandError):
    pass


def split_command(value: str) -> list[str]:
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
    cancel_event: Event | None = None,
) -> subprocess.CompletedProcess[str]:
    parts = split_command(command)
    if not parts:
        raise CommandError("Command is empty.")

    argv = [*parts, *(str(a) for a in args)]
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)

    try:
        proc = subprocess.Popen(
            argv,
            cwd=cwd,
            env=merged_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    except OSError as exc:
        raise CommandError(f"Could not start command: {argv[0]} ({exc})") from exc

    output = ""
    while True:
        try:
            stdout, _ = proc.communicate(timeout=0.25)
            output = stdout or output
            break
        except subprocess.TimeoutExpired as exc:
            if exc.output:
                output = exc.output if isinstance(exc.output, str) else exc.output.decode()
            if cancel_event is not None and cancel_event.is_set():
                proc.terminate()
                try:
                    stdout, _ = proc.communicate(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    stdout, _ = proc.communicate()
                output = stdout or output
                raise CommandCancelled(
                    f"Command cancelled: {' '.join(argv)}\n\n{output}"
                )

    completed = subprocess.CompletedProcess(argv, proc.returncode, output)
    if proc.returncode != 0:
        raise CommandError(
            f"Command failed ({proc.returncode}): {' '.join(argv)}\n\n{output}"
        )
    return completed

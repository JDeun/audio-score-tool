from __future__ import annotations

import os
import platform
import shlex
import shutil
import signal
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
    parts = shlex.split(value, posix=os.name != "nt")
    if os.name == "nt":
        parts = [part[1:-1] if len(part) >= 2 and part[0] == part[-1] == '"' else part for part in parts]
    return parts


def resolve_executable(name: str) -> str | None:
    """Resolve CLI tools from PATH and common GUI-app installation locations."""
    expanded = Path(name).expanduser()
    if expanded.is_file():
        return str(expanded)
    found = shutil.which(name)
    if found:
        return found

    suffix = ".exe" if os.name == "nt" else ""
    executable = f"{name}{suffix}" if suffix and not name.lower().endswith(suffix) else name
    candidates = [
        Path.home() / ".local" / "bin" / executable,
        Path.home() / ".cargo" / "bin" / executable,
    ]
    system = platform.system()
    if system == "Darwin":
        candidates += [
            Path("/opt/homebrew/bin") / executable,
            Path("/usr/local/bin") / executable,
            Path("/opt/homebrew/sbin") / executable,
            Path("/usr/local/sbin") / executable,
            Path("/usr/bin") / executable,
        ]
    elif system == "Linux":
        candidates += [
            Path("/usr/local/bin") / executable,
            Path("/usr/bin") / executable,
            Path("/snap/bin") / executable,
        ]
    elif system == "Windows":
        userprofile = Path(os.getenv("USERPROFILE", str(Path.home())))
        localappdata = Path(os.getenv("LOCALAPPDATA", str(userprofile / "AppData" / "Local")))
        candidates += [
            userprofile / ".local" / "bin" / executable,
            localappdata / "Programs" / "Python" / "Scripts" / executable,
            localappdata / "Microsoft" / "WinGet" / "Links" / executable,
        ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def command_exists(command: str) -> bool:
    parts = split_command(command)
    if not parts:
        return False
    return resolve_executable(parts[0]) is not None


def _terminate_process_tree(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            proc.kill()
        return

    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


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
    resolved = resolve_executable(parts[0])
    if resolved:
        parts[0] = resolved

    argv = [*parts, *(str(a) for a in args)]
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)

    try:
        popen_kwargs: dict = {}
        if os.name == "nt":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True

        proc = subprocess.Popen(
            argv,
            cwd=cwd,
            env=merged_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            **popen_kwargs,
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
                _terminate_process_tree(proc)
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

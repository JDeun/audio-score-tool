from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

from audio_score_tool.runner import CommandCancelled, CommandError, run_command


def test_runner_bounds_large_output_tail():
    completed = run_command(
        sys.executable,
        ["-c", "import sys; sys.stdout.write('x' * 2000000)"],
        max_output_bytes=4096,
        timeout_seconds=15,
    )
    assert completed.returncode == 0
    assert len(completed.stdout.encode("utf-8")) < 5000
    assert "command output truncated" in completed.stdout


def test_runner_timeout_terminates_hung_process():
    started = time.monotonic()
    with pytest.raises(CommandError) as exc:
        run_command(
            sys.executable,
            ["-c", "import time; time.sleep(60)"],
            timeout_seconds=0.5,
            max_output_bytes=1024,
        )
    assert "timed out" in str(exc.value)
    assert time.monotonic() - started < 8


def test_runner_cancel_terminates_process():
    event = threading.Event()
    event.set()
    with pytest.raises(CommandCancelled):
        run_command(
            sys.executable,
            ["-c", "import time; time.sleep(60)"],
            cancel_event=event,
            timeout_seconds=10,
        )


def test_runner_never_interprets_argument_as_shell(tmp_path: Path):
    marker = tmp_path / "should-not-exist"
    hostile = f"; touch {marker}"
    completed = run_command(
        sys.executable,
        ["-c", "import sys; print(sys.argv[1])", hostile],
        timeout_seconds=10,
    )
    assert hostile in completed.stdout
    assert not marker.exists()


def test_runner_failure_does_not_echo_environment_secret():
    secret = "AST_RUNNER_SECRET_123456"
    with pytest.raises(CommandError) as exc:
        run_command(
            sys.executable,
            ["-c", "import sys; sys.exit(7)"],
            env={"PRIVATE_RUNTIME_TOKEN": secret},
            timeout_seconds=10,
        )
    assert secret not in str(exc.value)

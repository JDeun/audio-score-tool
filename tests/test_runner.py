import sys
import threading
import time
from pathlib import Path

import pytest

from audio_score_tool.runner import (
    CommandCancelled,
    CommandError,
    command_exists,
    run_command,
    split_command,
)


def test_split_command_handles_normal_command():
    assert split_command("python -m module") == ["python", "-m", "module"]


def test_command_exists_rejects_empty_command():
    assert command_exists("") is False


def test_run_command_wraps_missing_executable():
    with pytest.raises(CommandError, match="Could not start command"):
        run_command("definitely-not-an-audio-score-tool-command", [])


def test_run_command_returns_output_for_success():
    proc = run_command(
        sys.executable,
        ["-c", "print('ok')"],
        cwd=Path.cwd(),
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == "ok"


def test_run_command_bounds_output_tail():
    proc = run_command(
        sys.executable,
        ["-c", "print('A' * 20000); print('TAIL')"],
        max_output_bytes=1024,
    )
    assert "command output truncated" in proc.stdout
    assert "TAIL" in proc.stdout
    assert len(proc.stdout.encode("utf-8")) < 1200


def test_run_command_times_out_and_terminates_tree():
    with pytest.raises(CommandError, match="timed out"):
        run_command(
            sys.executable,
            ["-c", "import time; time.sleep(10)"],
            timeout_seconds=0.2,
        )


def test_run_command_can_be_cancelled():
    event = threading.Event()

    def cancel() -> None:
        time.sleep(0.2)
        event.set()

    thread = threading.Thread(target=cancel)
    thread.start()
    with pytest.raises(CommandCancelled):
        run_command(
            sys.executable,
            ["-c", "import time; time.sleep(10)"],
            cancel_event=event,
        )
    thread.join()

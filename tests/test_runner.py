from pathlib import Path

import pytest

from audio_score_tool.runner import CommandError, command_exists, run_command, split_command


def test_split_command_handles_normal_command():
    assert split_command("python -m module") == ["python", "-m", "module"]


def test_command_exists_rejects_empty_command():
    assert command_exists("") is False


def test_run_command_wraps_missing_executable():
    with pytest.raises(CommandError, match="Could not start command"):
        run_command("definitely-not-an-audio-score-tool-command", [])


def test_run_command_returns_output_for_success():
    proc = run_command(
        "python",
        ["-c", "print('ok')"],
        cwd=Path.cwd(),
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == "ok"

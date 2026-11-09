"""Optional SheetSage2 execution must obey release policy and evidence freshness.

Synthetic JSON only: no model weights, private audio, or external downloads.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from audio_score_tool import sheetsage_hybrid
from audio_score_tool.runner import CommandError
from audio_score_tool.sheetsage_hybrid import (
    SheetSageError,
    load_sheetsage_events,
    run_sheetsage_adapter,
)


def _ready(tmp_path, monkeypatch):
    monkeypatch.delenv("AST_PACKAGED", raising=False)
    monkeypatch.setattr(
        sheetsage_hybrid, "runtime_settings",
        lambda: SimpleNamespace(usage_mode="personal"),
    )
    audio = tmp_path / "source.wav"
    audio.write_bytes(b"synthetic source")
    return audio, tmp_path / "events.json"


def _payload(model="sheetsage2"):
    return {
        "schema_version": 1,
        "model": model,
        "chords": [{"time_seconds": 0.0, "label": "C:maj"}],
        "beats": [{"time_seconds": 0.0}, {"time_seconds": 0.5}],
    }


def test_success_stages_and_replaces_only_valid_new_events(tmp_path, monkeypatch):
    audio, output = _ready(tmp_path, monkeypatch)
    output.write_text('{"stale":true}')
    calls = []

    def run(command, args, **kwargs):
        calls.append((command, args, kwargs))
        assert str(args[1]) != str(output)
        Path(args[1]).write_text(json.dumps(_payload()))

    monkeypatch.setattr(sheetsage_hybrid, "run_command", run)
    result = run_sheetsage_adapter(audio, output, command="reviewed-adapter")
    assert result == _payload()
    assert json.loads(output.read_text()) == result
    assert len(calls) == 1
    assert calls[0][2]["timeout_seconds"] == 1800
    assert not list(tmp_path.glob(".sheetsage2-events-*"))


@pytest.mark.parametrize("failed_mode", ["missing", "invalid", "wrong-model", "error"])
def test_failed_run_never_reuses_old_events_or_overwrites_existing_analysis(
    tmp_path, monkeypatch, failed_mode,
):
    audio, output = _ready(tmp_path, monkeypatch)
    previous = json.dumps(_payload())
    output.write_text(previous)

    def run(_command, args, **_kwargs):
        stage = Path(args[1])
        if failed_mode == "invalid":
            stage.write_text("{invalid")
        elif failed_mode == "wrong-model":
            stage.write_text(json.dumps(_payload("sheetsage")))
        elif failed_mode == "error":
            raise CommandError("SECRET_SHOULD_NOT_LEAK")
        # missing: return 0 but never write any new results

    monkeypatch.setattr(sheetsage_hybrid, "run_command", run)
    with pytest.raises(SheetSageError) as raised:
        run_sheetsage_adapter(audio, output, command="reviewed-adapter")
    assert "SECRET_SHOULD_NOT_LEAK" not in str(raised.value)
    assert output.read_text() == previous
    assert not list(tmp_path.glob(".sheetsage2-events-*"))


def test_unreviewed_system_command_is_rejected_in_packaged_mode(tmp_path, monkeypatch):
    audio, output = _ready(tmp_path, monkeypatch)
    monkeypatch.setenv("AST_PACKAGED", "1")
    # The shared runner must reject system Python even though it exists.
    with pytest.raises(SheetSageError, match="execution failed"):
        run_sheetsage_adapter(audio, output, command=sys.executable)
    assert not output.exists()


def test_noncommercial_model_refuses_commercial_execution_before_spawn(tmp_path, monkeypatch):
    audio, output = _ready(tmp_path, monkeypatch)
    monkeypatch.setattr(
        sheetsage_hybrid, "runtime_settings",
        lambda: SimpleNamespace(usage_mode="commercial"),
    )
    monkeypatch.setattr(
        sheetsage_hybrid, "run_command",
        lambda *_args, **_kwargs: pytest.fail("commercial should not execute a NC model"),
    )
    with pytest.raises(SheetSageError, match="commercial mode"):
        run_sheetsage_adapter(audio, output, command="reviewed-adapter")
    assert not output.exists()


def test_large_or_dense_events_are_rejected_before_overlay(tmp_path, monkeypatch):
    audio, output = _ready(tmp_path, monkeypatch)
    monkeypatch.setattr(sheetsage_hybrid, "_MAX_EVENTS_JSON_BYTES", 50)
    output.write_text(json.dumps(_payload()))
    with pytest.raises(SheetSageError, match="exceeds"):
        load_sheetsage_events(output)

    monkeypatch.setattr(sheetsage_hybrid, "_MAX_EVENTS_JSON_BYTES", 16 * 1024 * 1024)
    monkeypatch.setattr(sheetsage_hybrid, "_MAX_EVENTS_PER_TYPE", 1)
    with pytest.raises(SheetSageError, match="too many events"):
        load_sheetsage_events(output)


def test_missing_source_does_not_execute_or_touch_prior_events(tmp_path, monkeypatch):
    _audio, output = _ready(tmp_path, monkeypatch)
    output.write_text("previous valid evidence")
    monkeypatch.setattr(
        sheetsage_hybrid, "run_command",
        lambda *_args, **_kwargs: pytest.fail("missing source must not spawn"),
    )
    with pytest.raises(SheetSageError, match="input audio is missing"):
        run_sheetsage_adapter(tmp_path / "absent.wav", output, command="reviewed-adapter")
    assert output.read_text() == "previous valid evidence"

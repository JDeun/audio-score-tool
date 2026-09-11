from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "audio_score_tool_build_sidecar_test_module",
    ROOT / "scripts" / "build_sidecar.py",
)
assert _SPEC is not None and _SPEC.loader is not None
_BUILD_SIDECAR = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_BUILD_SIDECAR)


def test_non_tag_build_does_not_run_release_version_guard(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.delenv("GITHUB_REF_TYPE", raising=False)
    monkeypatch.delenv("GITHUB_REF_NAME", raising=False)
    monkeypatch.setattr(_BUILD_SIDECAR.subprocess, "run", lambda cmd, **kwargs: calls.append(cmd))

    _BUILD_SIDECAR._verify_tag_version_contract()

    assert calls == []


def test_tag_build_invokes_release_version_guard(monkeypatch):
    calls: list[tuple[list[str], dict]] = []
    monkeypatch.setenv("GITHUB_REF_TYPE", "tag")
    monkeypatch.setenv("GITHUB_REF_NAME", "v0.8.0")

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))

    monkeypatch.setattr(_BUILD_SIDECAR.subprocess, "run", fake_run)

    _BUILD_SIDECAR._verify_tag_version_contract()

    assert len(calls) == 1
    cmd, kwargs = calls[0]
    assert cmd[-2:] == ["--tag", "v0.8.0"]
    assert kwargs["cwd"] == ROOT
    assert kwargs["check"] is True


def test_tag_build_without_tag_name_fails_closed(monkeypatch):
    monkeypatch.setenv("GITHUB_REF_TYPE", "tag")
    monkeypatch.delenv("GITHUB_REF_NAME", raising=False)

    with pytest.raises(RuntimeError, match="GITHUB_REF_NAME"):
        _BUILD_SIDECAR._verify_tag_version_contract()

"""Packaged Demucs wiring and fail-closed offline model identity tests.

Every byte here is a local synthetic fixture, not an actual Demucs executable,
licensed model weight or third-party recording.
"""
from __future__ import annotations

import hashlib
import os
import stat
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from audio_score_tool.api_ext import app
from audio_score_tool.config import Settings
from audio_score_tool.demucs_runtime import (
    demucs_ready,
    demucs_repo_args,
    managed_demucs_repository,
)
from audio_score_tool.managed_components import ComponentArtifact, install_component_artifact
from audio_score_tool.managed_publication_readiness import (
    _REQUIRED_TOOLS,
    OPTIONAL_COMPONENTS,
    check_publication,
)
from audio_score_tool.managed_tool_resolver import registered_managed_tool
from audio_score_tool.preflight_v2 import preflight
from audio_score_tool.runner import command_exists


def _fixture(
    tmp_path: Path,
    monkeypatch,
    *,
    owner: str = "demucs",
    missing: str | None = None,
) -> tuple[Settings, Path]:
    root = tmp_path / "components"
    archive = tmp_path / f"{owner}-fixture.zip"
    payload = {
        "bin/demucs": b"#!synthetic-fixture-only\n",
        "models/htdemucs.yaml": b"models: ['955717e8']\n",
        "models/htdemucs_6s.yaml": b"models: ['5c90dfd2']\n",
        "models/955717e8-8726e21a.th": b"synthetic-four-stem-weight",
        "models/5c90dfd2-34c22ccb.th": b"synthetic-six-stem-weight",
    }
    if missing:
        payload.pop(missing)
    with zipfile.ZipFile(archive, "w") as zf:
        for name, data in payload.items():
            member = zipfile.ZipInfo(name)
            member.external_attr = (stat.S_IFREG | (0o755 if name.startswith("bin/") else 0o644)) << 16
            zf.writestr(member, data)
    artifact = ComponentArtifact(
        component=owner,
        version="test-1",
        url="https://example.invalid/synthetic-demucs.zip",
        sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        archive="zip",
        tools={"demucs": "bin/demucs"},
    )
    install_component_artifact(artifact, root=root, local_archive=archive)
    monkeypatch.setenv("AST_PACKAGED", "1")
    monkeypatch.setenv("AST_COMPONENT_DIR", str(root))
    return Settings(), root


def test_bundled_demucs_is_optional_and_cannot_claim_unpublished_assets():
    assert "demucs" in OPTIONAL_COMPONENTS
    assert _REQUIRED_TOOLS["demucs"] == frozenset({"demucs"})
    assert check_publication("demucs", "windows-x86_64").reason == "artifact-not-published"
    assert check_publication("demucs", "macos-aarch64").reason == "artifact-not-published"


def test_offline_managed_demucs_registers_both_models_and_selected_score_uses_repo(
    tmp_path: Path, monkeypatch,
):
    from audio_score_tool import selected_stem_score as stems

    settings, root = _fixture(tmp_path, monkeypatch)
    actual = registered_managed_tool("demucs", component="demucs")
    assert actual is not None and Path(settings.demucs_cmd) == actual
    assert command_exists(settings.demucs_cmd)
    repo = managed_demucs_repository(settings)
    assert repo == root / "installed" / "demucs" / "test-1" / "models"
    assert demucs_ready(settings)
    assert demucs_repo_args(settings) == ["--repo", str(repo)]
    assert preflight(settings)["tools"]["demucs"] is True

    setup = TestClient(app).get("/api/setup/center")
    assert setup.status_code == 200
    component = next(c for c in setup.json()["components"] if c["key"] == "demucs")
    assert component["ready"] is True
    assert component["auto_install"] is False
    assert component["catalog"]["published"] is False

    class BoundaryReached(RuntimeError):
        pass

    observed = []

    def capture(command, args, **_kwargs):
        observed.append((command, list(args)))
        raise BoundaryReached("Stop at actual separator CLI boundary; no model inference")

    monkeypatch.setattr(stems, "run_command", capture)
    monkeypatch.setattr(stems, "prepare_demucs_audio", lambda source, *_a, **_k: source)
    source = tmp_path / "input.wav"
    source.write_bytes(b"synthetic-source-input")
    for mode, expected in [("lead_sheet", "htdemucs"), ("guitar_vocal", "htdemucs_6s")]:
        with pytest.raises(BoundaryReached):
            stems.transcribe_selected_stems(
                source, tmp_path / mode / "output", tmp_path / mode / "stems",
                score_mode=mode, settings=settings, engine=None,
                device="cpu", demucs_device="cpu",
            )
        cli, args = observed[-1]
        assert cli == settings.demucs_cmd
        assert args[:4] == ["-n", expected, "--repo", str(repo)]
        assert args[-1] == source
        assert "--two-stems" in args if mode == "lead_sheet" else "--two-stems" not in args


@pytest.mark.parametrize("missing", [
    "models/htdemucs.yaml",
    "models/htdemucs_6s.yaml",
    "models/955717e8-8726e21a.th",
    "models/5c90dfd2-34c22ccb.th",
])
def test_missing_offline_model_fails_closed_even_if_cli_is_registered(
    tmp_path: Path, monkeypatch, missing: str,
):
    from audio_score_tool import selected_stem_score as stems

    settings, _root = _fixture(tmp_path, monkeypatch, missing=missing)
    assert registered_managed_tool("demucs", component="demucs") is not None
    assert command_exists(settings.demucs_cmd)
    assert not demucs_ready(settings)
    assert managed_demucs_repository(settings) is None
    assert preflight(settings)["tools"]["demucs"] is False
    with pytest.raises(RuntimeError, match="offline models"):
        demucs_repo_args(settings)
    source = tmp_path / "source.wav"
    source.write_bytes(b"synthetic")
    monkeypatch.setattr(
        stems, "run_command",
        lambda *_args, **_kwargs: pytest.fail("Unapproved model must never start"),
    )
    with pytest.raises(stems.SelectedScoreError, match="Demucs"):
        stems.transcribe_selected_stems(
            source, tmp_path / "output", tmp_path / "stems",
            score_mode="lead_sheet", settings=settings, engine=None,
            device="cpu", demucs_device="cpu",
        )


@pytest.mark.parametrize("damage", ["models/htdemucs.yaml", "models/955717e8-8726e21a.th"])
def test_model_tamper_invalidates_full_managed_payload(
    tmp_path: Path, monkeypatch, damage: str,
):
    settings, root = _fixture(tmp_path, monkeypatch)
    assert demucs_ready(settings)
    (root / "installed" / "demucs" / "test-1" / damage).write_bytes(b"tampered")
    assert registered_managed_tool("demucs", component="demucs") is None
    assert not command_exists(settings.demucs_cmd)
    assert managed_demucs_repository(settings) is None
    assert preflight(settings)["tools"]["demucs"] is False


def test_unrelated_managed_provider_cannot_masquerade_as_demucs(
    tmp_path: Path, monkeypatch,
):
    settings, _root = _fixture(tmp_path, monkeypatch, owner="unrelated")
    assert registered_managed_tool("demucs", component="unrelated") is not None
    assert registered_managed_tool("demucs", component="demucs") is None
    assert not demucs_ready(settings)
    assert managed_demucs_repository(settings) is None


def test_packaged_demucs_never_uses_system_path_or_legacy_unregistered_bin(
    tmp_path: Path, monkeypatch,
):
    from audio_score_tool import demucs_runtime

    root = tmp_path / "components"
    executable = root / "bin" / ("demucs.exe" if os.name == "nt" else "demucs")
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"unregistered")
    monkeypatch.setenv("AST_PACKAGED", "1")
    monkeypatch.setenv("AST_COMPONENT_DIR", str(root))
    monkeypatch.setattr(demucs_runtime, "command_exists", lambda _command: True)
    assert not demucs_ready(Settings())
    assert managed_demucs_repository(Settings()) is None

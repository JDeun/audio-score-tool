"""Interrupted managed-component same-version replacement must preserve a verified runtime."""
from __future__ import annotations

import hashlib
import json
import shutil
import stat
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from audio_score_tool import api as api_module
from audio_score_tool import job_ingestion, setup_center_api
from audio_score_tool.api import app
from audio_score_tool.managed_components import (
    ComponentArtifact,
    ComponentIntegrityError,
    _install_backup,
    component_status,
    install_component_artifact,
    recover_component_staging,
)


def _artifact(tmp_path: Path, payload: bytes) -> tuple[ComponentArtifact, Path]:
    source = tmp_path / ("candidate-" + hashlib.sha256(payload).hexdigest()[:8] + ".zip")
    with zipfile.ZipFile(source, "w") as archive:
        executable = zipfile.ZipInfo("bin/tool")
        executable.external_attr = (stat.S_IFREG | 0o755) << 16
        archive.writestr(executable, payload)
    artifact = ComponentArtifact(
        component="fixture",
        version="1",
        url="https://example.invalid/fixture.zip",
        sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        archive="zip",
        tools={"fixture-tool": "bin/tool"},
    )
    return artifact, source


def _installed(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "components"
    first, source = _artifact(tmp_path, b"original-verified-runtime")
    assert install_component_artifact(first, root=root, local_archive=source)["ready"]
    current = root / "installed" / "fixture" / "1"
    backup = _install_backup(root, "fixture", "1")
    return root, current, backup


@pytest.mark.parametrize("new_active", [False, True])
def test_crash_before_state_commit_restores_old_verified_runtime(
    tmp_path: Path, new_active: bool,
):
    root, current, backup = _installed(tmp_path)
    current.replace(backup)
    if new_active:
        (current / "bin").mkdir(parents=True)
        (current / "bin" / "tool").write_bytes(b"replacement-not-committed")
    (root / ".staging-fixture-deadbeef").mkdir()
    (root / ".download-fixture-deadbeef").write_bytes(b"partial")

    recovery = recover_component_staging(root)
    assert recovery["restored_previous_install"] == 1
    assert recovery["removed_component_staging"] == 2
    assert recovery["pending_previous_install_backup"] == 0
    assert not backup.exists()
    status = component_status("fixture", root=root)
    assert status["ready"] is True and status["integrity"] == "verified"
    assert Path(status["tools"]["fixture-tool"]).read_bytes() == b"original-verified-runtime"

    again = recover_component_staging(root)
    assert again["restored_previous_install"] == 0
    assert again["removed_previous_install_backup"] == 0
    assert again["pending_previous_install_backup"] == 0


def test_crash_after_state_commit_keeps_new_and_removes_only_old_backup(tmp_path: Path):
    root, current, backup = _installed(tmp_path)
    saved_old = tmp_path / "saved-old-runtime"
    shutil.copytree(current, saved_old)
    replacement, archive = _artifact(tmp_path, b"new-committed-runtime")
    assert install_component_artifact(replacement, root=root, local_archive=archive)["ready"]
    saved_old.replace(backup)

    recovery = recover_component_staging(root)
    assert recovery["restored_previous_install"] == 0
    assert recovery["removed_previous_install_backup"] == 1
    assert not backup.exists()
    assert Path(component_status("fixture", root=root)["tools"]["fixture-tool"]).read_bytes() == (
        b"new-committed-runtime"
    )


def test_unverified_backup_is_not_used_or_removed_and_reinstall_is_blocked(tmp_path: Path):
    root, current, backup = _installed(tmp_path)
    current.replace(backup)
    (backup / "bin" / "tool").write_bytes(b"tampered-backup")
    (current / "bin").mkdir(parents=True)
    (current / "bin" / "tool").write_bytes(b"uncommitted-file")
    recovery = recover_component_staging(root)
    assert recovery["restored_previous_install"] == 0
    assert recovery["pending_previous_install_backup"] == 1
    assert (backup / "bin" / "tool").read_bytes() == b"tampered-backup"
    assert (current / "bin" / "tool").read_bytes() == b"uncommitted-file"
    assert component_status("fixture", root=root)["ready"] is False

    replacement, source = _artifact(tmp_path, b"new-candidate")
    with pytest.raises(ComponentIntegrityError, match="unresolved previous installation"):
        install_component_artifact(replacement, root=root, local_archive=source)
    assert (backup / "bin" / "tool").read_bytes() == b"tampered-backup"


def test_corrupt_state_keeps_the_only_previous_install_backup(tmp_path: Path):
    root, current, backup = _installed(tmp_path)
    current.replace(backup)
    (root / "state.json").write_text("{invalid-json", encoding="utf-8")
    recovery = recover_component_staging(root)
    assert recovery["pending_previous_install_backup"] == 1
    assert backup.is_dir()
    assert not current.exists()
    assert component_status("fixture", root=root)["integrity"] == "state-corrupt"


def test_symlinked_backup_never_restored_deleted_or_followed(tmp_path: Path):
    root, _current, backup = _installed(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_bytes(b"untouched")
    try:
        backup.symlink_to(outside, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("Directory symlinks are unavailable on this OS")
    recovery = recover_component_staging(root)
    assert recovery["pending_previous_install_backup"] == 1
    assert backup.is_symlink()
    assert (outside / "secret").read_bytes() == b"untouched"

    replacement, source = _artifact(tmp_path, b"replacement")
    with pytest.raises(ComponentIntegrityError, match="unresolved previous installation"):
        install_component_artifact(replacement, root=root, local_archive=source)
    assert (outside / "secret").read_bytes() == b"untouched"


def test_unknown_backup_is_not_treated_as_owned_or_removed(tmp_path: Path):
    root, _current, _backup = _installed(tmp_path)
    unknown = root / "installed" / "fixture" / ".previous-unknown-token"
    unknown.mkdir()
    (unknown / "unrelated").write_bytes(b"preserve")
    recovery = recover_component_staging(root)
    assert recovery["pending_previous_install_backup"] == 1
    assert (unknown / "unrelated").read_bytes() == b"preserve"


def test_setup_center_recovery_reports_restored_install_to_client(tmp_path: Path, monkeypatch):
    root, current, _backup = _installed(tmp_path)
    current.replace(_install_backup(root, "fixture", "1"))
    monkeypatch.setattr(
        setup_center_api,
        "recover_component_staging",
        lambda: recover_component_staging(root),
    )
    monkeypatch.setattr(
        setup_center_api, "setup_center_status", lambda: {"core_ready": False},
    )
    response = TestClient(app).post("/api/setup/recover")
    assert response.status_code == 200
    recovery = response.json()["recovery"]
    assert recovery["restored_previous_install"] == 1
    assert recovery["pending_previous_install_backup"] == 0
    assert response.json()["setup"]["core_ready"] is False


def test_report_does_not_fabricate_verified_runtime_after_bad_backup(tmp_path: Path):
    root, current, backup = _installed(tmp_path)
    current.replace(backup)
    saved_state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    saved_state["components"]["fixture"]["tool_sha256"]["fixture-tool"] = "0" * 64
    (root / "state.json").write_text(json.dumps(saved_state), encoding="utf-8")

    recovery = recover_component_staging(root)
    assert recovery["restored_previous_install"] == 0
    assert recovery["pending_previous_install_backup"] == 1
    assert backup.is_dir() and not current.exists()
    assert component_status("fixture", root=root)["ready"] is False


def _mock_product_startup(monkeypatch):
    monkeypatch.setattr(
        api_module, "recover_startup_state",
        lambda **_kwargs: {"recovery_errors": 0},
    )
    monkeypatch.setattr(
        job_ingestion, "full_reconcile_completed_jobs",
        lambda **_kwargs: {"ingested": 0},
    )
    calls = []
    monkeypatch.setattr(
        api_module.uvicorn, "run",
        lambda *_args, **_kwargs: calls.append(api_module.startup_diagnostics()),
    )
    return calls


def test_packaged_backend_startup_recovers_crashed_managed_install_before_serving(
    tmp_path: Path, monkeypatch,
):
    root, current, backup = _installed(tmp_path)
    current.replace(backup)
    monkeypatch.setenv("AST_COMPONENT_DIR", str(root))
    calls = _mock_product_startup(monkeypatch)

    with api_module._startup_lock:
        previous = dict(api_module._startup_diagnostics)
    try:
        api_module.run()
        assert len(calls) == 1
        before_serving = calls[0]
        assert before_serving["recovery_completed"] is True
        managed = before_serving["recovery"]["managed_components"]
        assert managed["restored_previous_install"] == 1
        assert managed["pending_previous_install_backup"] == 0
        assert component_status("fixture", root=root)["ready"] is True
        assert not backup.exists()
    finally:
        with api_module._startup_lock:
            api_module._startup_diagnostics.clear()
            api_module._startup_diagnostics.update(previous)


def test_packaged_backend_reports_managed_recovery_failure_without_blocking_core(
    monkeypatch,
):
    def fail_recovery():
        raise ComponentIntegrityError("synthetic protected state failure")

    monkeypatch.setattr(api_module, "recover_component_staging", fail_recovery)
    calls = _mock_product_startup(monkeypatch)
    with api_module._startup_lock:
        previous = dict(api_module._startup_diagnostics)
    try:
        api_module.run()
        assert len(calls) == 1
        diagnostics = calls[0]
        assert diagnostics["recovery_completed"] is True
        assert diagnostics["recovery"]["managed_components"] == {
            "recovery_failed": True, "error_type": "ComponentIntegrityError",
        }
        assert diagnostics["recovery"]["recovery_errors"] == 1
    finally:
        with api_module._startup_lock:
            api_module._startup_diagnostics.clear()
            api_module._startup_diagnostics.update(previous)

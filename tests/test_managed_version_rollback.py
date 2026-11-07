"""Cross-version managed runtime rollback: real local ZIPs, no third-party bytes."""
from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from audio_score_tool import managed_components, setup_center_api
from audio_score_tool.api_ext import app
from audio_score_tool.managed_components import (
    ComponentArtifact,
    ComponentIntegrityError,
    component_rollback_status,
    component_status,
    install_component_artifact,
    remove_component_artifact,
    resolve_managed_tool,
    rollback_component_artifact,
)
from audio_score_tool.managed_tool_resolver import registered_managed_tool


def _fixture(tmp_path: Path, version: str, *, component: str = "audiveris"):
    source = tmp_path / f"{component}-{version}.zip"
    with zipfile.ZipFile(source, "w") as archive:
        tool = zipfile.ZipInfo("bin/runner")
        tool.external_attr = (stat.S_IFREG | 0o755) << 16
        archive.writestr(tool, f"synthetic-{component}-{version}".encode())
    artifact = ComponentArtifact(
        component=component,
        version=version,
        url=f"https://example.invalid/{component}/{version}.zip",
        sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        archive="zip",
        tools={"audiveris" if component == "audiveris" else "test-tool": "bin/runner"},
        license="synthetic-test-only",
        provenance="original CI fixture",
    )
    return artifact, source


def _install(root: Path, tmp_path: Path, version: str, *, component: str = "audiveris"):
    artifact, source = _fixture(tmp_path, version, component=component)
    return install_component_artifact(artifact, root=root, local_archive=source)


def _current(root: Path, component: str = "audiveris") -> dict:
    return json.loads((root / "state.json").read_text(encoding="utf-8"))["components"][component]


def test_upgrade_retains_cryptographically_verified_previous_generation_and_switches_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    root = tmp_path / "managed"
    assert _install(root, tmp_path, "1")["ready"]
    v1 = root / "installed" / "audiveris" / "1" / "bin" / "runner"
    first_sha = hashlib.sha256(v1.read_bytes()).hexdigest()
    assert component_rollback_status("audiveris", root=root)["available"] is False
    assert _install(root, tmp_path, "2")["ready"]
    entry = _current(root)
    assert entry["version"] == "2"
    assert entry["rollback"]["version"] == "1"
    assert entry["rollback"]["root"] == "installed/audiveris/1"
    assert entry["rollback"]["tool_sha256"]["audiveris"] == first_sha
    assert "rollback" not in entry["rollback"]
    assert component_rollback_status("audiveris", root=root) == {
        "available": True, "version": "1", "integrity": "verified",
    }

    monkeypatch.setenv("AST_COMPONENT_DIR", str(root))
    assert registered_managed_tool("audiveris") == root / "installed/audiveris/2/bin/runner"
    rolled = rollback_component_artifact("audiveris", root=root)
    assert rolled["ready"] and rolled["version"] == "1"
    assert v1.read_bytes() == b"synthetic-audiveris-1"
    assert registered_managed_tool("audiveris") == v1
    assert resolve_managed_tool("audiveris", root=root) == v1
    assert _current(root)["version"] == "1"
    assert component_rollback_status("audiveris", root=root)["available"] is False
    # Former v2 stays on disk for forensics but is no longer registered.
    assert (root / "installed/audiveris/2/bin/runner").exists()
    with pytest.raises(ComponentIntegrityError, match="not verified"):
        rollback_component_artifact("audiveris", root=root)


def test_consecutive_upgrades_offer_only_immediate_verified_predecessor(tmp_path: Path):
    root = tmp_path / "managed"
    for version in ("1", "2", "3"):
        assert _install(root, tmp_path, version)["ready"]
    assert _current(root)["rollback"]["version"] == "2"
    assert component_rollback_status("audiveris", root=root)["version"] == "2"
    assert rollback_component_artifact("audiveris", root=root)["version"] == "2"
    assert component_rollback_status("audiveris", root=root)["available"] is False


def test_same_version_reinstall_preserves_previous_generation(tmp_path: Path):
    root = tmp_path / "managed"
    assert _install(root, tmp_path, "1")["ready"]
    assert _install(root, tmp_path, "2")["ready"]
    original = _current(root)["rollback"]
    assert _install(root, tmp_path, "2")["ready"]
    assert _current(root)["rollback"] == original
    assert rollback_component_artifact("audiveris", root=root)["version"] == "1"


def test_corrupt_previous_generation_never_activates(tmp_path: Path):
    root = tmp_path / "managed"
    assert _install(root, tmp_path, "1")["ready"]
    assert _install(root, tmp_path, "2")["ready"]
    older = root / "installed/audiveris/1/bin/runner"
    older.write_bytes(b"tampered")
    assert component_rollback_status("audiveris", root=root) == {
        "available": False, "reason": "previous-version-unverified",
    }
    with pytest.raises(ComponentIntegrityError, match="missing, damaged"):
        rollback_component_artifact("audiveris", root=root)
    assert component_status("audiveris", root=root)["version"] == "2"
    assert _current(root)["rollback"]["version"] == "1"
    assert older.read_bytes() == b"tampered"


def test_corrupt_new_active_generation_does_not_prevent_safe_rollback(tmp_path: Path):
    root = tmp_path / "managed"
    assert _install(root, tmp_path, "1")["ready"]
    assert _install(root, tmp_path, "2")["ready"]
    (root / "installed/audiveris/2/bin/runner").write_bytes(b"tampered-current")
    assert component_status("audiveris", root=root)["ready"] is False
    assert component_rollback_status("audiveris", root=root)["available"] is True
    assert rollback_component_artifact("audiveris", root=root)["version"] == "1"
    assert component_status("audiveris", root=root)["ready"] is True


def test_state_write_failure_keeps_current_version_and_rollback_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    root = tmp_path / "managed"
    assert _install(root, tmp_path, "1")["ready"]
    assert _install(root, tmp_path, "2")["ready"]
    before = (root / "state.json").read_bytes()

    def abort(_path, _body):
        raise OSError("state write interrupted")

    monkeypatch.setattr(managed_components, "_atomic_write_json", abort)
    with pytest.raises(OSError, match="state write interrupted"):
        rollback_component_artifact("audiveris", root=root)
    assert (root / "state.json").read_bytes() == before
    assert component_status("audiveris", root=root)["version"] == "2"
    assert (root / "installed/audiveris/1/bin/runner").exists()


def test_checksum_mismatch_during_next_upgrade_retains_existing_previous_version(tmp_path: Path):
    root = tmp_path / "managed"
    assert _install(root, tmp_path, "1")["ready"]
    assert _install(root, tmp_path, "2")["ready"]
    third, source = _fixture(tmp_path, "3")
    object.__setattr__(third, "sha256", "0" * 64)
    with pytest.raises(ComponentIntegrityError, match="checksum mismatch"):
        install_component_artifact(third, root=root, local_archive=source)
    assert _current(root)["version"] == "2"
    assert _current(root)["rollback"]["version"] == "1"
    assert rollback_component_artifact("audiveris", root=root)["version"] == "1"


@pytest.mark.parametrize("forgery", ["other-component", "outside-path", "same-version", "bad-hash"])
def test_forged_previous_generation_is_rejected(tmp_path: Path, forgery: str):
    root = tmp_path / "managed"
    assert _install(root, tmp_path, "1")["ready"]
    assert _install(root, tmp_path, "2")["ready"]
    state_path = root / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    previous = state["components"]["audiveris"]["rollback"]
    if forgery == "other-component":
        previous["root"] = "installed/other/1"
    elif forgery == "outside-path":
        previous["root"] = "../../secrets"
    elif forgery == "same-version":
        previous["version"] = "2"
        previous["root"] = "installed/audiveris/2"
    else:
        previous["tool_sha256"]["audiveris"] = "0" * 64
    state_path.write_text(json.dumps(state), encoding="utf-8")
    assert component_rollback_status("audiveris", root=root)["available"] is False
    with pytest.raises(ComponentIntegrityError, match="not verified"):
        rollback_component_artifact("audiveris", root=root)
    assert _current(root)["version"] == "2"


def test_symlinked_previous_version_is_never_activated(tmp_path: Path):
    root = tmp_path / "managed"
    assert _install(root, tmp_path, "1")["ready"]
    assert _install(root, tmp_path, "2")["ready"]
    old = root / "installed/audiveris/1"
    external = tmp_path / "outside"
    external.mkdir()
    (external / "bin").mkdir()
    (external / "bin/runner").write_bytes(b"unsafe")
    old.rename(tmp_path / "retained-original")
    try:
        old.symlink_to(external, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink unavailable")
    assert component_rollback_status("audiveris", root=root)["available"] is False
    with pytest.raises(ComponentIntegrityError, match="not verified"):
        rollback_component_artifact("audiveris", root=root)
    assert (external / "bin/runner").read_bytes() == b"unsafe"


def test_upgrading_from_corrupted_old_version_never_trusts_it_as_rollback(tmp_path: Path):
    root = tmp_path / "managed"
    assert _install(root, tmp_path, "1")["ready"]
    (root / "installed/audiveris/1/bin/runner").write_bytes(b"untrusted-old")
    assert _install(root, tmp_path, "2")["ready"]
    assert component_rollback_status("audiveris", root=root)["available"] is False
    assert "rollback" not in _current(root)


def test_removing_component_clears_current_and_rollback_versions(tmp_path: Path):
    root = tmp_path / "managed"
    assert _install(root, tmp_path, "1")["ready"]
    assert _install(root, tmp_path, "2")["ready"]
    assert remove_component_artifact("audiveris", root=root)["removed"]
    assert not (root / "installed/audiveris").exists()
    assert component_rollback_status("audiveris", root=root)["available"] is False


def test_setup_center_endpoints_report_verified_rollback_and_reject_unmanaged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    root = tmp_path / "managed"
    assert _install(root, tmp_path, "1")["ready"]
    assert _install(root, tmp_path, "2")["ready"]
    monkeypatch.setenv("AST_COMPONENT_DIR", str(root))

    # Fetch the same real backend readiness contract the desktop UI receives.
    status = TestClient(app).get("/api/setup/center")
    assert status.status_code == 200
    components = {item["key"]: item for item in status.json()["components"]}
    assert components["audiveris"]["managed_status"]["rollback"] == {
        "available": True, "version": "1", "integrity": "verified",
    }

    def stable_status() -> dict:
        return {"core_ready": False, "components": []}

    monkeypatch.setattr(setup_center_api, "setup_center_status", stable_status)
    client = TestClient(app)
    invalid = client.post("/api/setup/rollback", json={"component": "desktop_runtime"})
    assert invalid.status_code == 409
    restored = client.post("/api/setup/rollback", json={"component": "audiveris"})
    assert restored.status_code == 200
    assert restored.json()["rolled_back"]["version"] == "1"
    assert restored.json()["rolled_back"]["ready"] is True
    assert restored.json()["setup"]["core_ready"] is False
    assert client.post("/api/setup/rollback", json={"component": "audiveris"}).status_code == 409

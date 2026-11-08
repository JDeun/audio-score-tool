"""Whole-payload integrity: synthetic local JRE/checkpoints, never real third-party weights."""
from __future__ import annotations

import hashlib
import json
import os
import stat
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from audio_score_tool import managed_components, managed_payload_integrity
from audio_score_tool.api_ext import app
from audio_score_tool.managed_components import (
    ComponentArtifact,
    ComponentIntegrityError,
    component_rollback_status,
    component_status,
    install_component_artifact,
    recover_component_staging,
    resolve_managed_tool,
    rollback_component_artifact,
)
from audio_score_tool.managed_tool_resolver import registered_managed_tool
from audio_score_tool.runner import command_exists

_CONTENTS = {
    "bin/audiveris": b"synthetic-launcher-v1",
    "runtime/bin/java": b"synthetic-jlink-java-v1",
    "runtime/lib/modules": b"synthetic-jre-modules",
    "models/checkpoint.bin": b"synthetic-model-weights",
    "resources/templates.xml": b"<synthetic-templates />",
}


def _artifact(
    tmp_path: Path, version: str = "v1", *, contents: dict[str, bytes] | None = None,
) -> tuple[ComponentArtifact, Path]:
    source = tmp_path / f"audiveris-{version}.zip"
    with zipfile.ZipFile(source, "w") as archive:
        for path, payload in sorted((contents or _CONTENTS).items()):
            info = zipfile.ZipInfo(path)
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o755) << 16
            archive.writestr(info, payload)
    artifact = ComponentArtifact(
        component="audiveris", version=version,
        url=f"https://example.invalid/audiveris-{version}.zip",
        sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        archive="zip", tools={"audiveris": "bin/audiveris"},
        license="Synthetic-test-fixture", provenance="local test only",
    )
    return artifact, source


def _install(tmp_path: Path, *, root: Path | None = None, version: str = "v1"):
    component_root = root or tmp_path / "managed"
    artifact, source = _artifact(tmp_path, version)
    status = install_component_artifact(artifact, root=component_root, local_archive=source)
    assert status["ready"] and status["integrity"] == "verified"
    installed = component_root / "installed/audiveris" / version
    return component_root, installed, artifact, source


def _state(root: Path) -> dict:
    return json.loads((root / "state.json").read_text(encoding="utf-8"))


def test_install_inventories_all_nested_java_checkpoint_and_resource_files(tmp_path: Path):
    root, installed, artifact, _archive = _install(tmp_path)
    entry = _state(root)["components"]["audiveris"]
    assert entry["archive_sha256"] == artifact.sha256
    assert set(entry["payload_files"]) == set(_CONTENTS)
    for name, payload in _CONTENTS.items():
        assert entry["payload_files"][name] == hashlib.sha256(payload).hexdigest()
        assert installed.joinpath(*name.split("/")).read_bytes() == payload
    assert entry["tool_sha256"]["audiveris"] == entry["payload_files"]["bin/audiveris"]
    status = component_status("audiveris", root=root)
    assert status["ready"] and status["payload_file_count"] == len(_CONTENTS)


@pytest.mark.parametrize("resource", [
    "runtime/bin/java", "runtime/lib/modules",
    "models/checkpoint.bin", "resources/templates.xml",
])
def test_unchanged_launcher_is_unusable_when_any_payload_resource_is_tampered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, resource: str,
):
    root, installed, _artifact_obj, _source = _install(tmp_path)
    monkeypatch.setenv("AST_PACKAGED", "1")
    monkeypatch.setenv("AST_COMPONENT_DIR", str(root))
    tool = installed / "bin/audiveris"
    assert registered_managed_tool("audiveris") == tool
    assert command_exists(str(tool))
    original_tool = tool.read_bytes()
    target = installed.joinpath(*resource.split("/"))
    target.write_bytes(b"T" * len(target.read_bytes()))
    # A synthetic one-byte mutation should invalidate the whole bundle, not
    # only the named launcher registered under tools[].
    assert component_status("audiveris", root=root)["integrity"] == "payload-digest-mismatch"
    assert resolve_managed_tool("audiveris", root=root) is None
    assert registered_managed_tool("audiveris") is None
    assert not command_exists(str(tool))
    assert tool.read_bytes() == original_tool


@pytest.mark.parametrize(("mutation", "reason"), [
    ("remove", "payload-file-missing"),
    ("extra", "payload-unexpected-file"),
    ("symlink", "payload-unsafe-file"),
])
def test_missing_extra_and_symlinked_nested_payloads_fail_closed(
    tmp_path: Path, mutation: str, reason: str,
):
    root, installed, _item, _archive = _install(tmp_path)
    resource = installed / "runtime/lib/modules"
    if mutation == "remove":
        resource.unlink()
    elif mutation == "extra":
        (installed / "runtime/evil-library.bin").write_bytes(b"unreviewed bytes")
    else:
        other = tmp_path / "outside.bin"
        other.write_bytes(resource.read_bytes())
        resource.unlink()
        try:
            resource.symlink_to(other)
        except (OSError, NotImplementedError):
            pytest.skip("File symlinks unavailable")
    status = component_status("audiveris", root=root)
    assert status["ready"] is False and status["integrity"] == reason


def test_nested_symlinked_directory_blocks_all_managed_entrypoints(tmp_path: Path, monkeypatch):
    root, installed, _item, _archive = _install(tmp_path)
    monkeypatch.setenv("AST_COMPONENT_DIR", str(root))
    nested = installed / "runtime/lib"
    outside = tmp_path / "outside-lib"
    nested.rename(outside)
    try:
        nested.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Directory symlinks unavailable")
    status = component_status("audiveris", root=root)
    assert status["integrity"] == "payload-unsafe-file"
    assert registered_managed_tool("audiveris") is None
    assert (outside / "modules").read_bytes() == _CONTENTS["runtime/lib/modules"]


@pytest.mark.skipif(os.name == "nt", reason="FIFO creation unavailable on Windows")
def test_added_special_device_file_is_not_a_valid_managed_resource(tmp_path: Path):
    root, installed, _item, _archive = _install(tmp_path)
    os.mkfifo(installed / "unexpected-fifo")
    assert component_status("audiveris", root=root)["integrity"] == "payload-unsafe-file"


def test_legacy_tool_only_state_fails_closed_until_reinstalled_from_reviewed_archive(
    tmp_path: Path, monkeypatch,
):
    root, installed, artifact, archive = _install(tmp_path)
    state = _state(root)
    del state["components"]["audiveris"]["payload_files"]
    (root / "state.json").write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setenv("AST_COMPONENT_DIR", str(root))
    monkeypatch.setenv("AST_PACKAGED", "1")
    assert component_status("audiveris", root=root)["integrity"] == "payload-manifest-missing"
    assert registered_managed_tool("audiveris") is None
    assert not command_exists(str(installed / "bin/audiveris"))
    # Reinstall the exact same archive: the old manifest-less version is not
    # grandfathered into the trust policy. A fresh inventory is generated.
    recovered = install_component_artifact(artifact, root=root, local_archive=archive)
    assert recovered["ready"] and recovered["payload_file_count"] == len(_CONTENTS)


@pytest.mark.parametrize("mutation", ["bad-digest", "relative-traversal", "empty", "bad-type"])
def test_forged_or_missing_payload_inventory_never_validates(
    tmp_path: Path, mutation: str,
):
    root, _installed, _item, _archive = _install(tmp_path)
    state = _state(root)
    manifest = state["components"]["audiveris"]["payload_files"]
    if mutation == "bad-digest":
        manifest["runtime/bin/java"] = "0" * 64
    elif mutation == "relative-traversal":
        manifest["../outside"] = "0" * 64
    elif mutation == "empty":
        state["components"]["audiveris"]["payload_files"] = {}
    else:
        state["components"]["audiveris"]["payload_files"] = ["bin/audiveris"]
    (root / "state.json").write_text(json.dumps(state), encoding="utf-8")
    status = component_status("audiveris", root=root)
    expected = (
        "payload-digest-mismatch" if mutation == "bad-digest"
        else "payload-manifest-missing" if mutation in {"empty", "bad-type"}
        else "payload-manifest-invalid"
    )
    assert status["ready"] is False and status["integrity"] == expected


def test_payload_verification_cache_never_reuses_a_changed_file_stat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    root, installed, _item, _archive = _install(tmp_path)
    real_digest = managed_payload_integrity._digest_file
    calls: list[str] = []

    def monitored(file: Path) -> str:
        calls.append(file.name)
        return real_digest(file)

    monkeypatch.setattr(managed_payload_integrity, "_digest_file", monitored)
    assert component_status("audiveris", root=root)["ready"] is True
    assert calls == []  # successful install already populated the in-process cache
    resource = installed / "models/checkpoint.bin"
    data = resource.read_bytes()
    previous_mtime = resource.stat().st_mtime_ns
    resource.write_bytes(b"X" * len(data))
    os.utime(resource, ns=(previous_mtime, previous_mtime))  # mtime-forged; ctime changes
    assert component_status("audiveris", root=root)["integrity"] == "payload-digest-mismatch"
    assert calls  # data was actually re-read
    resource.write_bytes(data)
    assert component_status("audiveris", root=root)["ready"] is True


def test_failed_update_preserves_full_previous_payload_inventory(tmp_path: Path):
    root, installed, _item, _archive = _install(tmp_path)
    baseline = _state(root)
    next_artifact, next_archive = _artifact(tmp_path, "v2")
    object.__setattr__(next_artifact, "sha256", "0" * 64)
    with pytest.raises(ComponentIntegrityError, match="checksum mismatch"):
        install_component_artifact(next_artifact, root=root, local_archive=next_archive)
    assert _state(root) == baseline
    assert component_status("audiveris", root=root)["ready"] is True
    assert (installed / "models/checkpoint.bin").read_bytes() == _CONTENTS["models/checkpoint.bin"]


def test_corrupted_previous_jre_blocks_rollback_even_when_launcher_is_unchanged(tmp_path: Path):
    root, _installed, _item, _archive = _install(tmp_path)
    assert _install(tmp_path, root=root, version="v2")[0] == root
    assert component_rollback_status("audiveris", root=root)["available"] is True
    (root / "installed/audiveris/v1/runtime/lib/modules").write_bytes(b"corrupted-model")
    assert component_rollback_status("audiveris", root=root)["reason"] == "previous-version-unverified"
    with pytest.raises(ComponentIntegrityError, match="not verified"):
        rollback_component_artifact("audiveris", root=root)
    assert component_status("audiveris", root=root)["version"] == "v2"


def test_corrupt_active_nested_payload_can_rollback_to_fully_verified_v1(tmp_path: Path):
    root, _installed, _item, _archive = _install(tmp_path)
    _install(tmp_path, root=root, version="v2")
    (root / "installed/audiveris/v2/models/checkpoint.bin").write_bytes(b"corrupted-model")
    assert component_status("audiveris", root=root)["integrity"] == "payload-digest-mismatch"
    assert component_rollback_status("audiveris", root=root)["available"] is True
    result = rollback_component_artifact("audiveris", root=root)
    assert result["ready"] and result["version"] == "v1"


def test_interrupted_same_version_restore_rejects_corrupt_nested_java_in_backup(tmp_path: Path):
    from audio_score_tool.managed_components import _install_backup

    root, installed, _item, _archive = _install(tmp_path)
    backup = _install_backup(root, "audiveris", "v1")
    installed.rename(backup)
    (backup / "runtime/bin/java").write_bytes(b"corrupted-jre")
    report = recover_component_staging(root)
    assert report["restored_previous_install"] == 0
    assert report["pending_previous_install_backup"] == 1
    assert backup.is_dir() and not installed.exists()
    assert component_status("audiveris", root=root)["ready"] is False


def test_setup_center_shows_payload_corruption_for_real_installed_component(
    tmp_path: Path, monkeypatch,
):
    root, installed, _item, _archive = _install(tmp_path)
    monkeypatch.setenv("AST_COMPONENT_DIR", str(root))
    (installed / "runtime/lib/modules").write_bytes(b"wrong JRE module")
    response = TestClient(app).get("/api/setup/center")
    assert response.status_code == 200
    components = {row["key"]: row for row in response.json()["components"]}
    managed = components["audiveris"]["managed_status"]
    assert managed["ready"] is False
    assert managed["integrity"] == "payload-digest-mismatch"

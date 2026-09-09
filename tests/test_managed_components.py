from __future__ import annotations

import hashlib
import json
import random
import stat
import zipfile
from pathlib import Path

import pytest

from audio_score_tool.managed_components import (
    ComponentArtifact,
    ComponentIntegrityError,
    component_status,
    install_component_artifact,
    recover_component_staging,
    resolve_managed_tool,
)
from audio_score_tool.managed_tool_resolver import registered_managed_tool


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _zip_component(path: Path, *, member: str = "bin/tool", payload: bytes = b"tool") -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        info = zipfile.ZipInfo(member)
        info.external_attr = (stat.S_IFREG | 0o755) << 16
        archive.writestr(info, payload)


def _artifact(path: Path, *, version: str = "1", sha256: str | None = None) -> ComponentArtifact:
    return ComponentArtifact(
        component="fixture",
        version=version,
        url="https://example.invalid/component.zip",
        sha256=sha256 or _sha256(path),
        archive="zip",
        tools={"fixture-tool": "bin/tool"},
        max_download_bytes=1024 * 1024,
        max_uncompressed_bytes=1024 * 1024,
        license="MIT",
        provenance="test fixture",
    )


def test_managed_component_install_registers_verified_tool(tmp_path: Path, monkeypatch):
    root = tmp_path / "components"
    archive = tmp_path / "component.zip"
    _zip_component(archive)

    result = install_component_artifact(_artifact(archive), root=root, local_archive=archive)

    assert result["ready"] is True
    assert result["integrity"] == "verified"
    tool = resolve_managed_tool("fixture-tool", root=root)
    assert tool is not None and tool.is_file()

    monkeypatch.setenv("AST_COMPONENT_DIR", str(root))
    assert registered_managed_tool("fixture-tool") == tool


def test_checksum_mismatch_never_replaces_previous_component(tmp_path: Path):
    root = tmp_path / "components"
    first = tmp_path / "v1.zip"
    second = tmp_path / "v2.zip"
    _zip_component(first, payload=b"version-1")
    _zip_component(second, payload=b"version-2")
    install_component_artifact(_artifact(first, version="1"), root=root, local_archive=first)

    with pytest.raises(ComponentIntegrityError):
        install_component_artifact(
            _artifact(second, version="2", sha256="0" * 64),
            root=root,
            local_archive=second,
        )

    status = component_status("fixture", root=root)
    assert status["ready"] is True
    assert status["version"] == "1"
    assert Path(status["tools"]["fixture-tool"]).read_bytes() == b"version-1"
    assert not (root / "installed" / "fixture" / "2").exists()


def test_archive_parent_traversal_is_rejected(tmp_path: Path):
    root = tmp_path / "components"
    archive = tmp_path / "escape.zip"
    with zipfile.ZipFile(archive, "w") as writer:
        writer.writestr("../escape", b"owned")
        writer.writestr("bin/tool", b"tool")

    with pytest.raises(ComponentIntegrityError):
        install_component_artifact(_artifact(archive), root=root, local_archive=archive)

    assert not (tmp_path / "escape").exists()
    assert component_status("fixture", root=root)["ready"] is False


def test_archive_symlink_is_rejected(tmp_path: Path):
    root = tmp_path / "components"
    archive = tmp_path / "symlink.zip"
    with zipfile.ZipFile(archive, "w") as writer:
        link = zipfile.ZipInfo("bin/tool")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        writer.writestr(link, "../../outside")

    with pytest.raises(ComponentIntegrityError):
        install_component_artifact(_artifact(archive), root=root, local_archive=archive)


def test_component_state_corruption_fails_closed(tmp_path: Path):
    root = tmp_path / "components"
    root.mkdir()
    (root / "state.json").write_text("{broken", encoding="utf-8")
    status = component_status("fixture", root=root)
    assert status["ready"] is False
    assert status["integrity"] == "state-corrupt"
    assert resolve_managed_tool("fixture-tool", root=root) is None


def test_staging_recovery_removes_partial_install_and_download(tmp_path: Path):
    root = tmp_path / "components"
    staging = root / ".staging-fixture-abc"
    staging.mkdir(parents=True)
    (staging / "partial").write_text("partial", encoding="utf-8")
    download = root / ".download-fixture-abc"
    download.write_bytes(b"partial")

    result = recover_component_staging(root)

    assert result["removed_component_staging"] == 2
    assert not staging.exists()
    assert not download.exists()


def test_registered_tool_rejects_symlink_escape(tmp_path: Path, monkeypatch):
    root = tmp_path / "components"
    installed = root / "installed" / "fixture" / "1" / "bin"
    installed.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.write_bytes(b"secret")
    link = installed / "tool"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink unavailable")
    (root / "state.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "components": {
                    "fixture": {
                        "version": "1",
                        "root": "installed/fixture/1",
                        "tools": {"fixture-tool": "bin/tool"},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AST_COMPONENT_DIR", str(root))
    assert registered_managed_tool("fixture-tool") is None


def test_archive_path_fuzz_rejects_escape_shapes(tmp_path: Path):
    rng = random.Random(20260909)
    unsafe = [
        "../outside",
        "../../outside",
        "/absolute/tool",
        "bin/../../../outside",
        "..\\outside",
        "bin\\..\\..\\outside",
    ]
    for index in range(40):
        depth = rng.randint(1, 6)
        unsafe.append("/".join(["safe"] * depth + ["..", "..", f"outside-{index}"]))

    for index, member in enumerate(unsafe):
        archive = tmp_path / f"fuzz-{index}.zip"
        with zipfile.ZipFile(archive, "w") as writer:
            writer.writestr(member, b"escape")
            writer.writestr("bin/tool", b"tool")
        root = tmp_path / f"components-{index}"
        with pytest.raises(ComponentIntegrityError):
            install_component_artifact(_artifact(archive), root=root, local_archive=archive)


def test_repeated_install_soak_keeps_single_active_version(tmp_path: Path):
    root = tmp_path / "components"
    for version in range(1, 21):
        archive = tmp_path / f"v{version}.zip"
        payload = f"version-{version}".encode()
        _zip_component(archive, payload=payload)
        install_component_artifact(
            _artifact(archive, version=str(version)), root=root, local_archive=archive
        )
        status = component_status("fixture", root=root)
        assert status["ready"] is True
        assert status["version"] == str(version)
        assert Path(status["tools"]["fixture-tool"]).read_bytes() == payload
    assert not list(root.glob(".staging-*"))
    assert not list(root.glob(".download-*"))

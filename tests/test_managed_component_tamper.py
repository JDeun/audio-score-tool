from __future__ import annotations

import hashlib
import stat
import zipfile
from pathlib import Path

from audio_score_tool.managed_components import (
    ComponentArtifact,
    component_status,
    install_component_artifact,
    resolve_managed_tool,
)
from audio_score_tool.managed_tool_resolver import registered_managed_tool


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(path: Path) -> ComponentArtifact:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        info = zipfile.ZipInfo("bin/tool")
        info.external_attr = (stat.S_IFREG | 0o755) << 16
        archive.writestr(info, b"trusted-tool")
    return ComponentArtifact(
        component="fixture",
        version="1",
        url="https://example.invalid/fixture.zip",
        sha256=_sha256(path),
        archive="zip",
        tools={"fixture-tool": "bin/tool"},
        max_download_bytes=1024 * 1024,
        max_uncompressed_bytes=1024 * 1024,
    )


def test_post_install_tool_tampering_fails_closed(tmp_path: Path, monkeypatch):
    root = tmp_path / "components"
    archive = tmp_path / "fixture.zip"
    install_component_artifact(_fixture(archive), root=root, local_archive=archive)
    trusted = resolve_managed_tool("fixture-tool", root=root)
    assert trusted is not None

    trusted.write_bytes(b"tampered-after-install")

    status = component_status("fixture", root=root)
    assert status["ready"] is False
    assert status["integrity"] == "tool-digest-mismatch"
    assert resolve_managed_tool("fixture-tool", root=root) is None

    monkeypatch.setenv("AST_COMPONENT_DIR", str(root))
    assert registered_managed_tool("fixture-tool") is None

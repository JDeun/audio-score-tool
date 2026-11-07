"""Nested managed JRE launchers retain safe POSIX execute bits after ZIP install."""
from __future__ import annotations

import hashlib
import os
import stat
import zipfile
from pathlib import Path

import pytest

from audio_score_tool.managed_components import ComponentArtifact, install_component_artifact


def _info(name: str, mode: int) -> zipfile.ZipInfo:
    result = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    result.create_system = 3
    result.external_attr = (stat.S_IFREG | mode) << 16
    result.compress_type = zipfile.ZIP_STORED
    return result


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions must be tested on a POSIX host")
def test_nested_unregistered_java_is_executable_without_unsafe_permission_escalation(
    tmp_path: Path,
):
    archive = tmp_path / "local-review.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(_info("Audiveris.app/Contents/MacOS/Audiveris", 0o755), b"fake main")
        bundle.writestr(
            _info("Audiveris.app/Contents/runtime/Contents/Home/bin/java", 0o755),
            b"fake embedded java",
        )
        bundle.writestr(
            _info("Audiveris.app/Contents/app/resources.txt", 0o6666),
            b"nonexecuting resource",
        )
        bundle.writestr(
            _info("Audiveris.app/Contents/app/system-tool", 0o4755),
            b"no suid/sgid permitted",
        )
    artifact = ComponentArtifact(
        component="audiveris",
        version="5.11.0-test",
        url="https://example.invalid/never-published",
        sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        archive="zip",
        tools={"audiveris": "Audiveris.app/Contents/MacOS/Audiveris"},
        license="AGPL-3.0",
        provenance="fixture pending only",
    )
    installed = install_component_artifact(
        artifact, root=tmp_path / "components", local_archive=archive,
    )
    assert installed["ready"] is True and installed["integrity"] == "verified"
    root = tmp_path / "components/installed/audiveris/5.11.0-test/Audiveris.app/Contents"
    assert root.joinpath("MacOS/Audiveris").stat().st_mode & stat.S_IXUSR
    assert root.joinpath("runtime/Contents/Home/bin/java").stat().st_mode & stat.S_IXUSR
    assert not root.joinpath("app/resources.txt").stat().st_mode & stat.S_IXUSR
    for member in ("MacOS/Audiveris", "runtime/Contents/Home/bin/java", "app/system-tool"):
        mode = root.joinpath(member).stat().st_mode
        assert not mode & (stat.S_ISUID | stat.S_ISGID)
    assert not root.joinpath("app/system-tool").stat().st_mode & stat.S_IWOTH

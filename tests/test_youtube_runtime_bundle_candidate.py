from __future__ import annotations

import hashlib
import json
import stat
import struct
import zipfile
from pathlib import Path

import pytest

from audio_score_tool.managed_components import ComponentArtifact, install_component_artifact
from scripts import assemble_youtube_runtime_candidate as assembler

_TOOLS = ("yt-dlp", "deno", "ffmpeg", "ffprobe")


def _windows_amd64_binary(label: str) -> bytes:
    # Synthetic PE/AMD64 *header*, not an actual runnable executable.
    result = bytearray(b"MZ" + b"\x00" * 254)
    result[60:64] = (128).to_bytes(4, "little")
    result[128:134] = b"PE\x00\x00\x64\x86"
    return bytes(result) + label.encode("utf-8")


def _macho_arm64_binary(label: str) -> bytes:
    # Synthetic little-endian 64-bit ARM Mach-O header.
    return b"\xcf\xfa\xed\xfe" + struct.pack("<I", 0x0100000C) + label.encode() + b"\x00" * 32


def _macho_fat_arm64_binary() -> bytes:
    return (
        b"\xca\xfe\xba\xbe" + struct.pack(">I", 2)
        + struct.pack(">IIIII", 0x01000007, 0, 128, 20, 0)
        + struct.pack(">IIIII", 0x0100000C, 0, 256, 20, 0)
        + b"\x00" * 256
    )


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _input(tmp_path: Path, target: str = "windows-x86_64") -> dict:
    tools = {}
    suffix = ".exe" if target.startswith("windows") else ""
    for name in _TOOLS:
        content = (
            _windows_amd64_binary(name)
            if target.startswith("windows")
            else _macho_arm64_binary(name)
        )
        binary = tmp_path / (name + suffix)
        binary.write_bytes(content)
        notice = tmp_path / (name + ".license.txt")
        notice.write_text(f"synthetic {name} license notice\n", encoding="utf-8")
        license_name = (
            "GPL-3.0-or-later" if name == "yt-dlp"
            else "MIT" if name == "deno"
            else "LGPL-2.1-or-later"
        )
        revision = "ffmpeg-commit-abc" if name in {"ffmpeg", "ffprobe"} else name + "-v1"
        version = "ffmpeg-7.0" if name in {"ffmpeg", "ffprobe"} else name + "-1.0"
        tools[name] = {
            "file": str(binary),
            "sha256": _sha(content),
            "version": version,
            "upstream_revision": revision,
            "upstream_url": f"https://example.invalid/upstream/releases/tag/{version}",
            "license": license_name,
            "license_notice": str(notice),
        }
    build = tmp_path / "ffmpeg-build.txt"
    build.write_text("synthetic cross-compile, no nonfree components\n", encoding="utf-8")
    return {
        "schema": 1,
        "target": target,
        "version": "youtube-fixture-1",
        "bundle_license": "Multiple: GPL-3.0-or-later + MIT + LGPL-2.1-or-later",
        "bundle_provenance": "synthetic CI fixture only",
        "tools": tools,
        "ffmpeg_build": {
            "configure_flags": ["--disable-nonfree", "--disable-autodetect"],
            "toolchain": "synthetic-build-toolchain",
            "build_record": str(build),
        },
    }


@pytest.mark.parametrize("target", ["windows-x86_64", "macos-aarch64"])
def test_youtube_candidate_is_verified_and_never_autoapproved(tmp_path: Path, target: str):
    manifest = _input(tmp_path, target=target)
    output = tmp_path / "youtube-bundle.zip"
    report = assembler.assemble_youtube_candidate(manifest, output)

    assert output.is_file()
    assert report["redistribution_status"] == "pending"
    assert report["approval_required"] is True
    assert report["local_install_verified"] is True
    assert report["remote_archive_verified"] is False
    assert report["binaries_executed"] is False
    assert report["clean_machine_verified"] is False
    assert report["archive_sha256"] == _sha(output.read_bytes())
    suffix = ".exe" if target.startswith("windows") else ""
    expected_paths = {name: f"bin/{name}{suffix}" for name in _TOOLS}
    assert report["tool_paths"] == expected_paths

    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        assert set(expected_paths.values()) <= names
        assert {f"notices/{name}.LICENSE.txt" for name in _TOOLS} <= names
        assert "provenance/ffmpeg-build.txt" in names
        inventory = json.loads(archive.read("BUNDLE-INVENTORY.json"))
        assert inventory["redistribution_status"] == "pending"
        assert inventory["tools"]["ffmpeg"]["upstream_revision"] == "ffmpeg-commit-abc"
        for name in _TOOLS:
            info = archive.getinfo(expected_paths[name])
            assert stat.S_ISREG(info.external_attr >> 16)
            assert info.external_attr >> 16 & stat.S_IXUSR
            assert _sha(archive.read(expected_paths[name])) == manifest["tools"][name]["sha256"]

    pending = json.loads((tmp_path / "youtube-bundle.zip.pending.json").read_text())
    assert pending == report

    # The output is directly installable by the existing managed component
    # manager when used as a locally reviewed, still-unpublished candidate.
    artifact = ComponentArtifact(
        component="youtube_runtime",
        version=report["version"],
        url="https://example.invalid/test-only",
        sha256=report["archive_sha256"],
        archive="zip",
        tools=report["tool_paths"],
    )
    state = install_component_artifact(artifact, root=tmp_path / "second-rehearsal", local_archive=output)
    assert state["ready"] is True


def test_candidate_binary_bytes_are_deterministic(tmp_path: Path):
    manifest = _input(tmp_path)
    a = tmp_path / "first.zip"
    b = tmp_path / "second.zip"
    first = assembler.assemble_youtube_candidate(manifest, a)
    second = assembler.assemble_youtube_candidate(manifest, b)
    assert first["archive_sha256"] == second["archive_sha256"]
    assert a.read_bytes() == b.read_bytes()
    with pytest.raises(FileExistsError):
        assembler.assemble_youtube_candidate(manifest, a)


def test_macos_universal_binary_with_arm64_slice_is_supported(tmp_path: Path):
    manifest = _input(tmp_path, target="macos-aarch64")
    universal = _macho_fat_arm64_binary()
    source = tmp_path / "yt-dlp"
    source.write_bytes(universal)
    manifest["tools"]["yt-dlp"]["sha256"] = _sha(universal)
    report = assembler.assemble_youtube_candidate(manifest, tmp_path / "universal.zip")
    assert report["local_install_verified"] is True


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda m: m["tools"]["deno"].update(sha256="0" * 64), "SHA-256 mismatch"),
        (lambda m: m["tools"].pop("ffprobe"), "Exactly yt-dlp"),
        (lambda m: m["tools"]["yt-dlp"].update(license="Unlicense"), "GPLv3"),
        (lambda m: m["tools"]["deno"].update(license="unknown"), "explicit"),
        (lambda m: m["tools"]["yt-dlp"].update(upstream_url="https://example.invalid/latest/download"), "pinned"),
        (lambda m: m["ffmpeg_build"].update(configure_flags=["--enable-nonfree"]), "Nonfree"),
        (lambda m: m["ffmpeg_build"].update(configure_flags=["--enable-gpl"]), "GPL"),
        (lambda m: m["tools"]["ffprobe"].update(upstream_revision="other-revision"), "same pinned"),
        (lambda m: m.update(bundle_provenance="TBD"), "explicit"),
        (lambda m: m.update(target="linux-x86_64"), "Supported bundle"),
    ],
)
def test_incomplete_license_or_provenance_fails_closed(tmp_path: Path, mutation, message):
    manifest = _input(tmp_path)
    mutation(manifest)
    output = tmp_path / "rejected.zip"
    with pytest.raises(ValueError, match=message):
        assembler.assemble_youtube_candidate(manifest, output)
    assert not output.exists()
    assert not (tmp_path / "rejected.zip.pending.json").exists()


def test_source_binary_architecture_mismatch_is_rejected(tmp_path: Path):
    manifest = _input(tmp_path)
    other = _macho_arm64_binary("deno")
    path = tmp_path / "deno.exe"
    path.write_bytes(other)
    manifest["tools"]["deno"]["sha256"] = _sha(other)
    with pytest.raises(ValueError, match="format/CPU"):
        assembler.assemble_youtube_candidate(manifest, tmp_path / "bad-architecture.zip")


def test_symlinked_source_is_rejected(tmp_path: Path):
    manifest = _input(tmp_path)
    genuine = tmp_path / "deno.exe"
    alias = tmp_path / "deno-symlink.exe"
    alias.symlink_to(genuine)
    manifest["tools"]["deno"]["file"] = str(alias)
    with pytest.raises(ValueError, match="non-symlink"):
        assembler.assemble_youtube_candidate(manifest, tmp_path / "symlink.zip")


def test_source_mutation_during_archiving_is_detected_and_not_published(
    tmp_path: Path, monkeypatch,
):
    manifest = _input(tmp_path)
    original = assembler._zip_entry
    mutated = False

    def edit_during_copy(*args, **kwargs):
        nonlocal mutated
        if not mutated:
            mutated = True
            source = kwargs.get("path")
            if source is None:
                source = args[2]
            source.write_bytes(source.read_bytes() + b"tampered after pin")
        return original(*args, **kwargs)

    monkeypatch.setattr(assembler, "_zip_entry", edit_during_copy)
    output = tmp_path / "unsafe.zip"
    with pytest.raises(ValueError, match="source changed"):
        assembler.assemble_youtube_candidate(manifest, output)
    assert not output.exists()
    assert not (tmp_path / "unsafe.zip.pending.json").exists()


def test_manifest_will_not_misrepresent_ffmpeg_as_lgpl_if_gpl_enabled(tmp_path: Path):
    manifest = _input(tmp_path)
    manifest["ffmpeg_build"]["configure_flags"] = ["--enable-gpl"]
    for name in ("ffmpeg", "ffprobe"):
        manifest["tools"][name]["license"] = "GPL-2.0-or-later"
    report = assembler.assemble_youtube_candidate(manifest, tmp_path / "gpl.zip")
    assert report["tools"]["ffmpeg"]["license"] == "GPL-2.0-or-later"


def test_no_unreviewed_url_or_actual_binary_is_committed_to_repo(tmp_path: Path):
    manifest = _input(tmp_path)
    manifest["tools"]["deno"]["upstream_url"] = "http://example.invalid/v1"
    with pytest.raises(ValueError, match="pinned"):
        assembler.assemble_youtube_candidate(manifest, tmp_path / "insecure.zip")

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
from scripts import verify_youtube_official_sources as official_verifier
from scripts import verify_ffmpeg_build_provenance as ffmpeg_review

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


def _write_ffmpeg_review(manifest: dict, root: Path) -> None:
    """Synthetic cross-platform evidence, never executable or legally approved."""
    entries = {}
    for name in ("ffmpeg", "ffprobe"):
        tool = manifest["tools"][name]
        version_report = root / f"{name}-version.txt"
        version_report.write_text(
            f"{name} version {tool['version']} synthetic CI fixture\n"
            "built with synthetic-build-toolchain\n"
            + "configuration: "
            + " ".join(manifest["ffmpeg_build"]["configure_flags"])
            + "\n",
            encoding="utf-8",
        )
        entries[name] = {
            "file": tool["file"],
            "sha256": tool["sha256"],
            "version_report": str(version_report),
            "license": tool["license"],
        }
    review_manifest = {
        "schema": 1,
        "target": manifest["target"],
        "version": manifest["tools"]["ffmpeg"]["version"],
        "source_revision": manifest["tools"]["ffmpeg"]["upstream_revision"],
        "source_url": manifest["tools"]["ffmpeg"]["upstream_url"],
        "toolchain": manifest["ffmpeg_build"]["toolchain"],
        "license_notice": manifest["tools"]["ffmpeg"]["license_notice"],
        "build_record": manifest["ffmpeg_build"]["build_record"],
        "configure_flags": manifest["ffmpeg_build"]["configure_flags"],
        "external_libraries": {},
        "tools": entries,
    }
    report = ffmpeg_review.review_ffmpeg_build(review_manifest)
    attestation = root / "ffmpeg-build-review.pending.json"
    attestation.write_text(json.dumps(report), encoding="utf-8")
    manifest["ffmpeg_build"]["attestation_file"] = str(attestation)


def _bind_official_fixture(manifest: dict, root: Path) -> dict:
    """Verify synthetic pinned asset bytes through the real offline source tool.

    This deliberately uses fixture-only pins. The production CLI always uses
    release/review's committed official upstream asset hashes.
    """
    target = manifest["target"]
    suffix = ".exe" if target.startswith("windows") else ""
    yt = manifest["tools"]["yt-dlp"]
    deno = manifest["tools"]["deno"]
    yt.update({
        "version": "2026.10.26",
        "upstream_revision": "2026.10.26",
        "upstream_url": "https://github.com/yt-dlp/yt-dlp/releases/tag/2026.10.26",
    })
    deno.update({
        "version": "2.9.8",
        "upstream_revision": "v2.9.8",
        "upstream_url": "https://github.com/denoland/deno/releases/tag/v2.9.8",
    })
    upstream_deno = root / "official-deno.zip"
    with zipfile.ZipFile(upstream_deno, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("deno" + suffix, Path(deno["file"]).read_bytes())
    yt_file = Path(yt["file"])
    def pinned(repository: str, tag: str, asset: str, file: Path, extracted: str, license_review: str):
        return {
            "repository": repository, "tag": tag, "asset": asset,
            "url": f"https://github.com/{repository}/releases/download/{tag}/{asset}",
            "sha256": _sha(file.read_bytes()), "bytes": file.stat().st_size,
            "extracted_tool": extracted, "license_review": license_review,
        }
    pins = {
        "schema": 1, "approval_status": "pending",
        "targets": {target: {
            "yt-dlp": pinned(
                "yt-dlp/yt-dlp", "2026.10.26",
                "yt-dlp.exe" if suffix else "yt-dlp_macos",
                yt_file, "yt-dlp" + suffix, "GPL-3.0-or-later combined license pending",
            ),
            "deno": pinned(
                "denoland/deno", "v2.9.8",
                "deno-x86_64-pc-windows-msvc.zip" if suffix else "deno-aarch64-apple-darwin.zip",
                upstream_deno, "deno" + suffix, "MIT redistribution review pending",
            ),
        }},
    }
    pins_file = root / "fixture-official-pins.pending.json"
    pins_file.write_text(json.dumps(pins), encoding="utf-8")
    output = root / "verified-official-sources"
    evidence = official_verifier.extract_reviewed_sources(
        pin_file=pins_file, target=target,
        yt_dlp_asset=yt_file, deno_zip=upstream_deno,
        output_directory=output,
    )
    assert evidence["local_bytes_verified"] is True
    for name in ("yt-dlp", "deno"):
        manifest["tools"][name]["file"] = str(output / (name + suffix))
        manifest["tools"][name]["sha256"] = _sha((output / (name + suffix)).read_bytes())
    manifest["official_sources_evidence"] = str(output / "SOURCE-EVIDENCE.pending.json")
    manifest["_fixture_official_pins"] = str(pins_file)
    return manifest


def _assemble(manifest: dict, destination: Path) -> dict:
    return assembler.assemble_youtube_candidate(
        manifest, destination, official_pins=Path(manifest["_fixture_official_pins"])
    )


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
        revision = "a" * 40 if name in {"ffmpeg", "ffprobe"} else name + "-v1"
        version = "ffmpeg-7.0" if name in {"ffmpeg", "ffprobe"} else name + "-1.0"
        tools[name] = {
            "file": str(binary),
            "sha256": _sha(content),
            "version": version,
            "upstream_revision": revision,
            "upstream_url": (
                f"https://github.com/FFmpeg/FFmpeg/commit/{revision}"
                if name in {"ffmpeg", "ffprobe"}
                else f"https://example.invalid/upstream/releases/tag/{version}"
            ),
            "license": license_name,
            "license_notice": str(notice),
        }
    build = tmp_path / "ffmpeg-build.txt"
    build.write_text("synthetic cross-compile, no nonfree components\n", encoding="utf-8")
    manifest = {
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
    _write_ffmpeg_review(manifest, tmp_path)
    return _bind_official_fixture(manifest, tmp_path)


@pytest.mark.parametrize("target", ["windows-x86_64", "macos-aarch64"])
def test_youtube_candidate_is_verified_and_never_autoapproved(tmp_path: Path, target: str):
    manifest = _input(tmp_path, target=target)
    output = tmp_path / "youtube-bundle.zip"
    report = _assemble(manifest, output)

    assert output.is_file()
    assert report["redistribution_status"] == "pending"
    assert report["approval_required"] is True
    assert report["local_install_verified"] is True
    assert report["remote_archive_verified"] is False
    assert report["binaries_executed"] is False
    assert report["official_source_bytes_verified"] is True
    assert report["upstream_signature_verified"] is False
    assert report["official_source_evidence_sha256"] == _sha(
        Path(manifest["official_sources_evidence"]).read_bytes()
    )
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
        assert "provenance/ffmpeg-attestation.pending.json" in names
        assert "provenance/official-sources.pending.json" in names
        official = json.loads(archive.read("provenance/official-sources.pending.json"))
        assert official["redistribution_status"] == "pending"
        assert official["local_bytes_verified"] is True
        assert official["upstream_signature_verified"] is False
        inventory = json.loads(archive.read("BUNDLE-INVENTORY.json"))
        assert inventory["redistribution_status"] == "pending"
        assert inventory["tools"]["ffmpeg"]["upstream_revision"] == "a" * 40
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
    first = _assemble(manifest, a)
    second = _assemble(manifest, b)
    assert first["archive_sha256"] == second["archive_sha256"]
    assert a.read_bytes() == b.read_bytes()
    with pytest.raises(FileExistsError):
        _assemble(manifest, a)


def test_macos_universal_binary_with_arm64_slice_is_supported(tmp_path: Path):
    manifest = _input(tmp_path, target="macos-aarch64")
    universal = _macho_fat_arm64_binary()
    source = Path(manifest["tools"]["yt-dlp"]["file"])
    source.write_bytes(universal)
    manifest["tools"]["yt-dlp"]["sha256"] = _sha(universal)
    # The synthetic review pin and evidence must follow this deliberately
    # replaced universal fixture, just as a real re-reviewed release would.
    pins_path = Path(manifest["_fixture_official_pins"])
    pinned = json.loads(pins_path.read_text(encoding="utf-8"))
    pinned["targets"]["macos-aarch64"]["yt-dlp"]["sha256"] = _sha(universal)
    pinned["targets"]["macos-aarch64"]["yt-dlp"]["bytes"] = len(universal)
    pins_path.write_text(json.dumps(pinned), encoding="utf-8")
    evidence_path = Path(manifest["official_sources_evidence"])
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["inputs"]["yt-dlp"]["source_sha256"] = _sha(universal)
    evidence["inputs"]["yt-dlp"]["tool_sha256"] = _sha(universal)
    evidence["inputs"]["yt-dlp"]["source_bytes"] = len(universal)
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    report = _assemble(manifest, tmp_path / "universal.zip")
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
        _assemble(manifest, output)
    assert not output.exists()
    assert not (tmp_path / "rejected.zip.pending.json").exists()


def test_source_binary_architecture_mismatch_is_rejected(tmp_path: Path):
    manifest = _input(tmp_path)
    other = _macho_arm64_binary("deno")
    path = tmp_path / "deno.exe"
    path.write_bytes(other)
    manifest["tools"]["deno"]["sha256"] = _sha(other)
    with pytest.raises(ValueError, match="format/CPU"):
        _assemble(manifest, tmp_path / "bad-architecture.zip")


def test_symlinked_source_is_rejected(tmp_path: Path):
    manifest = _input(tmp_path)
    genuine = tmp_path / "deno.exe"
    alias = tmp_path / "deno-symlink.exe"
    alias.symlink_to(genuine)
    manifest["tools"]["deno"]["file"] = str(alias)
    with pytest.raises(ValueError, match="non-symlink"):
        _assemble(manifest, tmp_path / "symlink.zip")


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
        _assemble(manifest, output)
    assert not output.exists()
    assert not (tmp_path / "unsafe.zip.pending.json").exists()


def test_manifest_will_not_misrepresent_ffmpeg_as_lgpl_if_gpl_enabled(tmp_path: Path):
    manifest = _input(tmp_path)
    manifest["ffmpeg_build"]["configure_flags"] = ["--enable-gpl"]
    for name in ("ffmpeg", "ffprobe"):
        manifest["tools"][name]["license"] = "GPL-2.0-or-later"
    _write_ffmpeg_review(manifest, tmp_path)
    report = _assemble(manifest, tmp_path / "gpl.zip")
    assert report["tools"]["ffmpeg"]["license"] == "GPL-2.0-or-later"


def test_no_unreviewed_url_or_actual_binary_is_committed_to_repo(tmp_path: Path):
    manifest = _input(tmp_path)
    manifest["tools"]["deno"]["upstream_url"] = "http://example.invalid/v1"
    with pytest.raises(ValueError, match="pinned"):
        _assemble(manifest, tmp_path / "insecure.zip")


def test_missing_or_inconsistent_ffmpeg_review_blocks_bundle(tmp_path: Path):
    manifest = _input(tmp_path)
    attestation = manifest["ffmpeg_build"].pop("attestation_file")
    with pytest.raises(ValueError, match="attestation_file"):
        _assemble(manifest, tmp_path / "missing.zip")

    manifest["ffmpeg_build"]["attestation_file"] = attestation
    review = json.loads(Path(attestation).read_text(encoding="utf-8"))
    review["tools"]["ffmpeg"]["file_sha256"] = "0" * 64
    Path(attestation).write_text(json.dumps(review), encoding="utf-8")
    with pytest.raises(ValueError, match="attestation hash/license"):
        _assemble(manifest, tmp_path / "tampered.zip")


def test_ffmpeg_review_for_another_platform_cannot_be_reused(tmp_path: Path):
    manifest = _input(tmp_path)
    attestation = Path(manifest["ffmpeg_build"]["attestation_file"])
    review = json.loads(attestation.read_text(encoding="utf-8"))
    review["target"] = "macos-aarch64"
    attestation.write_text(json.dumps(review), encoding="utf-8")
    with pytest.raises(ValueError, match="validated pending review"):
        _assemble(manifest, tmp_path / "wrong-platform.zip")


def test_ffmpeg_manifest_config_drift_after_review_fails(tmp_path: Path):
    manifest = _input(tmp_path)
    manifest["ffmpeg_build"]["configure_flags"].append("--disable-doc")
    with pytest.raises(ValueError, match="provenance/configuration differs"):
        _assemble(manifest, tmp_path / "config-drift.zip")

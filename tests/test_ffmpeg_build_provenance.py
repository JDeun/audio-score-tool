from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import pytest

from scripts import verify_ffmpeg_build_provenance as attestation


def _fake_pe_amd64(tag: str) -> bytes:
    # Header-only fixture: not an executable, deliberately not run by tests.
    data = bytearray(b"MZ" + b"\x00" * 254)
    data[60:64] = (128).to_bytes(4, "little")
    data[128:134] = b"PE\x00\x00\x64\x86"
    return bytes(data) + tag.encode()


def _fake_macho_arm64(tag: str) -> bytes:
    return b"\xcf\xfa\xed\xfe" + struct.pack("<I", 0x0100000C) + tag.encode() + b"\0" * 32


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _fixture(
    tmp_path: Path, *,
    target: str = "windows-x86_64",
    flags: list[str] | None = None,
    external: dict | None = None,
    license_name: str = "LGPL-2.1-or-later",
) -> dict:
    version = "7.1.1"
    flags = flags if flags is not None else [
        "--disable-nonfree", "--disable-autodetect", "--enable-ffmpeg", "--enable-ffprobe",
    ]
    tools = {}
    for name in ("ffmpeg", "ffprobe"):
        suffix = ".exe" if target == "windows-x86_64" else ""
        binary = tmp_path / (name + suffix)
        contents = (
            _fake_pe_amd64(name) if target == "windows-x86_64"
            else _fake_macho_arm64(name)
        )
        binary.write_bytes(contents)
        report = tmp_path / (name + "-version.txt")
        report.write_text(
            f"{name} version {version} Copyright (c) FFmpeg developers\n"
            "built with synthetic-test-compiler\n"
            + "configuration: " + " ".join(flags) + "\n"
            + "libavutil 59. 39.100 / 59. 39.100\n",
            encoding="utf-8",
        )
        tools[name] = {
            "file": str(binary),
            "sha256": _digest(contents),
            "version_report": str(report),
            "license": license_name,
        }
    license_notice = tmp_path / "FFmpeg-LICENSE.txt"
    license_notice.write_text("Synthetic test license notice\n", encoding="utf-8")
    record = tmp_path / "ffmpeg-build.txt"
    record.write_text("Synthetic reproducibility review material\n", encoding="utf-8")
    revision = "a" * 40
    return {
        "schema": 1,
        "target": target,
        "version": version,
        "source_revision": revision,
        "source_url": f"https://github.com/FFmpeg/FFmpeg/commit/{revision}",
        "toolchain": "synthetic-clang-test-17.0",
        "license_notice": str(license_notice),
        "build_record": str(record),
        "configure_flags": flags,
        "external_libraries": external if external is not None else {},
        "tools": tools,
    }


@pytest.mark.parametrize("target", ("windows-x86_64", "macos-aarch64"))
def test_consistent_pinned_binary_pair_is_pending_not_approved(tmp_path: Path, target: str):
    manifest = _fixture(tmp_path, target=target)
    result = attestation.review_ffmpeg_build(manifest)
    assert result["target"] == target
    assert result["inferred_license"] == "LGPL-2.1-or-later"
    assert result["source_revision"] == "a" * 40
    assert set(result["tools"]) == {"ffmpeg", "ffprobe"}
    assert result["local_binary_sha256_verified"] is True
    assert result["supplied_version_reports_consistent"] is True
    assert result["version_reports_cryptographically_bound_to_binaries"] is False
    assert result["binary_execution_verified"] is False
    assert result["reproducible_rebuild_verified"] is False
    assert result["linked_libraries_independently_inspected"] is False
    assert result["redistribution_status"] == "pending"
    assert result["legal_review_status"] == "pending"
    assert result["approval_required"] is True


def test_source_commit_and_url_are_exactly_pinned(tmp_path: Path):
    manifest = _fixture(tmp_path)
    manifest["source_url"] = "https://github.com/FFmpeg/FFmpeg"
    with pytest.raises(attestation.FFmpegAttestationError, match="exact official commit"):
        attestation.review_ffmpeg_build(manifest)


def test_binary_checksum_and_architecture_are_both_checked(tmp_path: Path):
    manifest = _fixture(tmp_path)
    manifest["tools"]["ffmpeg"]["sha256"] = "0" * 64
    with pytest.raises(attestation.FFmpegAttestationError, match="SHA-256 mismatch"):
        attestation.review_ffmpeg_build(manifest)

    manifest = _fixture(tmp_path)
    ffprobe = Path(manifest["tools"]["ffprobe"]["file"])
    mac = _fake_macho_arm64("ffprobe")
    ffprobe.write_bytes(mac)
    manifest["tools"]["ffprobe"]["sha256"] = _digest(mac)
    with pytest.raises(attestation.FFmpegAttestationError, match="format/CPU"):
        attestation.review_ffmpeg_build(manifest)


def test_version_report_mismatch_and_contradictory_build_flags_fail(tmp_path: Path):
    manifest = _fixture(tmp_path)
    report = Path(manifest["tools"]["ffprobe"]["version_report"])
    report.write_text(report.read_text().replace("7.1.1", "6.0"), encoding="utf-8")
    with pytest.raises(attestation.FFmpegAttestationError, match="version output"):
        attestation.review_ffmpeg_build(manifest)

    manifest = _fixture(tmp_path)
    report = Path(manifest["tools"]["ffprobe"]["version_report"])
    report.write_text(report.read_text().replace("--enable-ffprobe", "--disable-ffprobe"), encoding="utf-8")
    with pytest.raises(attestation.FFmpegAttestationError, match="configuration and manifest disagree"):
        attestation.review_ffmpeg_build(manifest)


def test_nonfree_and_disabled_required_program_are_blocked(tmp_path: Path):
    for flags, message in [
        (["--enable-nonfree"], "nonfree"),
        (["--disable-programs"], "Required FFmpeg program"),
        (["--disable-ffprobe"], "Required FFmpeg program"),
    ]:
        manifest = _fixture(tmp_path, flags=flags)
        with pytest.raises(attestation.FFmpegAttestationError, match=message):
            attestation.review_ffmpeg_build(manifest)


def test_gpl_and_lgpl3_configurations_have_correct_licenses(tmp_path: Path):
    gpl_flags = ["--enable-gpl", "--enable-libx264"]
    x264 = {
        "libx264": {
            "license_family": "GPL-2.0-or-later",
            "version": "synthetic-1",
            "upstream_revision": "pinned-x264-revision",
            "source_url": "https://example.invalid/x264/commit/a",
            "review_status": "pending",
        }
    }
    gpl = _fixture(tmp_path, flags=gpl_flags, external=x264, license_name="GPL-2.0-or-later")
    assert attestation.review_ffmpeg_build(gpl)["inferred_license"] == "GPL-2.0-or-later"

    lgpl3 = _fixture(
        tmp_path, flags=["--enable-version3", "--enable-liblensfun"],
        external={
            "liblensfun": {
                "license_family": "LGPL-3.0-or-later", "version": "synthetic-1",
                "upstream_revision": "pinned", "source_url": "https://example.invalid/lensfun",
                "review_status": "pending",
            }
        },
        license_name="LGPL-3.0-or-later",
    )
    assert attestation.review_ffmpeg_build(lgpl3)["inferred_license"] == "LGPL-3.0-or-later"


def test_gpl_external_library_cannot_be_mislabeled_lgpl(tmp_path: Path):
    manifest = _fixture(
        tmp_path, flags=["--enable-libx264"],
        external={"libx264": {
            "license_family": "GPL-2.0-or-later", "version": "synthetic",
            "upstream_revision": "pin", "source_url": "https://example.invalid/x264",
            "review_status": "pending",
        }},
    )
    with pytest.raises(attestation.FFmpegAttestationError, match="enable-gpl required"):
        attestation.review_ffmpeg_build(manifest)


def test_inventory_must_match_every_external_enable_flag(tmp_path: Path):
    manifest = _fixture(tmp_path, flags=["--enable-libfoo"])
    with pytest.raises(attestation.FFmpegAttestationError, match="inventory mismatch"):
        attestation.review_ffmpeg_build(manifest)


def test_build_manifest_cannot_claim_redistribution_approval(tmp_path: Path):
    manifest = _fixture(
        tmp_path, flags=["--enable-libfoo"],
        external={"libfoo": {
            "license_family": "MIT", "version": "v1", "upstream_revision": "source-pin",
            "source_url": "https://example.invalid/libfoo", "review_status": "approved",
        }},
    )
    with pytest.raises(attestation.FFmpegAttestationError, match="cannot approve"):
        attestation.review_ffmpeg_build(manifest)


def test_failed_review_creates_no_output_and_successful_reports_are_exclusive(tmp_path: Path):
    manifest = _fixture(tmp_path)
    report = attestation.review_ffmpeg_build(manifest)
    target = tmp_path / "FFmpeg-review.pending.json"
    attestation.write_report(target, report)
    assert json.loads(target.read_text(encoding="utf-8")) == report
    with pytest.raises(FileExistsError):
        attestation.write_report(target, report)
    with pytest.raises(attestation.FFmpegAttestationError, match="bundled managed catalog"):
        attestation.write_report(attestation._BUNDLED_CATALOG, report)

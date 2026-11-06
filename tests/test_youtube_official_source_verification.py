from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from pathlib import Path

import pytest

from scripts import verify_youtube_official_sources as verifier


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _inputs(tmp_path: Path, target: str = "windows-x86_64") -> tuple[Path, Path, Path]:
    exe = ".exe" if target.startswith("windows") else ""
    yt = tmp_path / f"yt-dlp{exe}"
    yt.write_bytes(b"owned-fixture-yt-dlp-binary")
    archive = tmp_path / "official-deno.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as out:
        out.writestr(f"deno{exe}", b"owned-fixture-deno-binary")
    pinned = {
        "schema": 1,
        "approval_status": "pending",
        "targets": {
            target: {
                "yt-dlp": {
                    "repository": "yt-dlp/yt-dlp",
                    "tag": "2026.10.26",
                    "asset": f"yt-dlp{exe}",
                    "url": f"https://github.com/yt-dlp/yt-dlp/releases/download/2026.10.26/yt-dlp{exe}",
                    "sha256": _sha(yt.read_bytes()),
                    "bytes": yt.stat().st_size,
                    "extracted_tool": f"yt-dlp{exe}",
                    "license_review": "GPL-3.0-or-later pending approval",
                },
                "deno": {
                    "repository": "denoland/deno",
                    "tag": "v2.9.8",
                    "asset": "official-deno.zip",
                    "url": "https://github.com/denoland/deno/releases/download/v2.9.8/official-deno.zip",
                    "sha256": _sha(archive.read_bytes()),
                    "bytes": archive.stat().st_size,
                    "extracted_tool": f"deno{exe}",
                    "license_review": "MIT pending review",
                },
            }
        },
    }
    manifest = tmp_path / "pinned.json"
    manifest.write_text(json.dumps(pinned), encoding="utf-8")
    return manifest, yt, archive


@pytest.mark.parametrize("target", ["windows-x86_64", "macos-aarch64"])
def test_verified_source_assets_are_local_only_and_unapproved(tmp_path: Path, target: str):
    manifest, yt, deno = _inputs(tmp_path, target)
    output = tmp_path / "verified-sources"
    report = verifier.extract_reviewed_sources(
        pin_file=manifest,
        target=target,
        yt_dlp_asset=yt,
        deno_zip=deno,
        output_directory=output,
    )
    suffix = ".exe" if target.startswith("windows") else ""
    assert (output / ("yt-dlp" + suffix)).read_bytes() == yt.read_bytes()
    assert (output / ("deno" + suffix)).read_bytes() == b"owned-fixture-deno-binary"
    assert report["redistribution_status"] == "pending"
    assert report["local_bytes_verified"] is True
    assert report["upstream_signature_verified"] is False
    assert report["binaries_executed"] is False
    assert report["remote_archive_published"] is False
    assert report["approval_required"] is True
    assert report["inputs"]["deno"]["tool_sha256"] == _sha(b"owned-fixture-deno-binary")
    assert set(report["unresolved"]) >= {"ffmpeg", "ffprobe"}
    assert json.loads((output / "SOURCE-EVIDENCE.pending.json").read_text()) == report


def test_hash_mismatch_refuses_source_copy_and_keeps_destination_absent(tmp_path: Path):
    manifest, yt, deno = _inputs(tmp_path)
    yt.write_bytes(b"new-unverified-bytes")
    output = tmp_path / "unverified"
    with pytest.raises(ValueError, match="byte size mismatch|SHA-256 mismatch"):
        verifier.extract_reviewed_sources(
            pin_file=manifest, target="windows-x86_64",
            yt_dlp_asset=yt, deno_zip=deno, output_directory=output,
        )
    assert not output.exists()


def test_corrupted_zip_never_writes_a_published_candidate(tmp_path: Path):
    manifest, yt, deno = _inputs(tmp_path)
    deno.write_bytes(b"corrupt ZIP")
    payload = json.loads(manifest.read_text())
    item = payload["targets"]["windows-x86_64"]["deno"]
    item["bytes"] = deno.stat().st_size
    item["sha256"] = _sha(deno.read_bytes())
    manifest.write_text(json.dumps(payload))
    output = tmp_path / "bad-output"
    with pytest.raises(zipfile.BadZipFile):
        verifier.extract_reviewed_sources(
            pin_file=manifest, target="windows-x86_64",
            yt_dlp_asset=yt, deno_zip=deno, output_directory=output,
        )
    assert not output.exists()


@pytest.mark.parametrize("malicious_name", ["../deno.exe", "/tmp/deno.exe", "bin/deno.exe"])
def test_deno_zip_rejects_paths_outside_single_expected_executable(
    tmp_path: Path, malicious_name: str,
):
    manifest, yt, deno = _inputs(tmp_path)
    with zipfile.ZipFile(deno, "w") as archive:
        archive.writestr(malicious_name, b"fake-binary")
    payload = json.loads(manifest.read_text())
    item = payload["targets"]["windows-x86_64"]["deno"]
    item["sha256"] = _sha(deno.read_bytes())
    item["bytes"] = deno.stat().st_size
    manifest.write_text(json.dumps(payload))
    output = tmp_path / "untrusted"
    with pytest.raises(ValueError, match="unsafe or unexpected"):
        verifier.extract_reviewed_sources(
            pin_file=manifest, target="windows-x86_64",
            yt_dlp_asset=yt, deno_zip=deno, output_directory=output,
        )
    assert not output.exists()


def test_zip_symlink_entry_is_refused(tmp_path: Path):
    manifest, yt, deno = _inputs(tmp_path)
    with zipfile.ZipFile(deno, "w") as archive:
        info = zipfile.ZipInfo("deno.exe")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, b"../../outside")
    payload = json.loads(manifest.read_text())
    payload["targets"]["windows-x86_64"]["deno"]["sha256"] = _sha(deno.read_bytes())
    payload["targets"]["windows-x86_64"]["deno"]["bytes"] = deno.stat().st_size
    manifest.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="unsafe"):
        verifier.extract_reviewed_sources(
            pin_file=manifest, target="windows-x86_64", yt_dlp_asset=yt,
            deno_zip=deno, output_directory=tmp_path / "reject-symlink",
        )


def test_output_is_non_overwriting_and_original_inputs_are_untouched(tmp_path: Path):
    manifest, yt, deno = _inputs(tmp_path)
    output = tmp_path / "verified"
    before = (yt.read_bytes(), deno.read_bytes())
    verifier.extract_reviewed_sources(
        pin_file=manifest, target="windows-x86_64",
        yt_dlp_asset=yt, deno_zip=deno, output_directory=output,
    )
    with pytest.raises(FileExistsError):
        verifier.extract_reviewed_sources(
            pin_file=manifest, target="windows-x86_64",
            yt_dlp_asset=yt, deno_zip=deno, output_directory=output,
        )
    assert (yt.read_bytes(), deno.read_bytes()) == before


def test_repository_review_pins_identify_exact_assets_but_remain_pending():
    pin = json.loads(verifier.DEFAULT_PINS.read_text(encoding="utf-8"))
    assert pin["approval_status"] == "pending"
    assert pin["publication_catalog_modified"] is False
    assert pin["missing_by_design"] == ["ffmpeg", "ffprobe"]
    assert set(pin["targets"]) == set(verifier.TARGETS)
    for target, values in pin["targets"].items():
        assert set(values) == {"yt-dlp", "deno"}
        for item in values.values():
            assert item["url"].startswith("https://github.com/")
            assert item["tag"] in item["url"]
            assert item["asset"] in item["url"]
            assert len(item["sha256"]) == 64
            assert item["bytes"] > 0

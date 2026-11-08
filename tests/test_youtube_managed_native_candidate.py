"""Native managed ZIP release-review contracts, with no network or third-party files."""
from __future__ import annotations

import json
import stat
import zipfile
from pathlib import Path

import pytest

from audio_score_tool.managed_components import ComponentIntegrityError
from scripts import verify_youtube_managed_candidate_native as native


def _review_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    youtube = tmp_path / "youtube"
    ffmpeg = tmp_path / "ffmpeg"
    reports = tmp_path / "ffmpeg-review"
    for path in (youtube, ffmpeg, reports):
        path.mkdir()
    binaries = {}
    for name in ("yt-dlp", "deno", "ffmpeg", "ffprobe"):
        path = (youtube if name in {"yt-dlp", "deno"} else ffmpeg) / name
        path.write_bytes(f"synthetic-reviewed-{name}".encode())
        binaries[name] = path
    yt_pins = tmp_path / "youtube-pins.json"
    pinned = {
        "yt-dlp": {"tag": "2026.10.26", "url": "https://example.invalid/yt-dlp"},
        "deno": {"tag": "v2.9.8", "url": "https://example.invalid/deno"},
    }
    yt_pins.write_text(json.dumps({"targets": {"macos-aarch64": pinned}}))
    (youtube / "SOURCE-EVIDENCE.pending.json").write_text(json.dumps({
        "inputs": {
            "yt-dlp": {"tag": "2026.10.26"},
            "deno": {"tag": "v2.9.8"},
        },
    }))
    commit = "a" * 40
    source_url = f"https://github.com/FFmpeg/FFmpeg/commit/{commit}"
    ff_pin = tmp_path / "ffmpeg-pin.json"
    ff_pin.write_text(json.dumps({
        "source_commit": commit,
        "source_url": source_url,
        "license_family_review": "LGPL-2.1-or-later",
    }))
    notice = ffmpeg / "LICENSE.md"
    notice.write_text("Original upstream FFmpeg license for synthetic test\n")
    build_record = reports / "build-record.txt"
    build_record.write_text("synthetic original native toolchain test\n")
    attest = {
        "schema": 1,
        "component": "youtube_runtime.ffmpeg",
        "target": "macos-aarch64",
        "redistribution_status": "pending",
        "source_revision": commit,
        "source_url": source_url,
        "build_record_sha256": native._digest(build_record),
        "license_notice_sha256": native._digest(notice),
        "inferred_license": "LGPL-2.1-or-later",
        "configure_flags": ["--disable-nonfree", "--disable-gpl"],
        "toolchain": "synthetic-compiler-v1",
        "version": "9.0.2",
        "tools": {
            name: {"file_sha256": native._digest(binaries[name])}
            for name in ("ffmpeg", "ffprobe")
        },
    }
    attestation_path = reports / "FFMPEG-BUILD-REVIEW.pending.json"
    attestation_path.write_text(json.dumps(attest))
    receipt = reports / "NATIVE-FFMPEG-EVIDENCE.pending.json"
    receipt.write_text(json.dumps({
        "offline_attestation_sha256": native._digest(attestation_path),
    }))
    monkeypatch.setattr(native, "_validate_sources", lambda *_args, **_kw: {
        "files": binaries,
        "digests": {name: native._digest(path) for name, path in binaries.items()},
    })
    return youtube, ffmpeg, receipt, yt_pins, ff_pin, attest


def test_native_candidate_manifest_binds_exact_official_and_ffmpeg_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    youtube, ffmpeg, receipt, yt_pins, ff_pin, attestation = _review_inputs(
        tmp_path, monkeypatch,
    )
    manifest = native.make_native_candidate_manifest(
        target="macos-aarch64", youtube_dir=youtube, ffmpeg_dir=ffmpeg,
        ffmpeg_receipt=receipt, notice_dir=tmp_path / "notices",
        youtube_pins=yt_pins, ffmpeg_pin=ff_pin,
    )
    assert manifest["schema"] == 1
    assert manifest["target"] == "macos-aarch64"
    assert manifest["version"] == "yt2026.10.26-deno2.9.8-ffmpeg9.0.2-qa1"
    assert set(manifest["tools"]) == {"yt-dlp", "deno", "ffmpeg", "ffprobe"}
    assert manifest["tools"]["yt-dlp"]["license"] == "GPL-3.0-or-later"
    assert manifest["tools"]["deno"]["license"] == "MIT"
    assert manifest["tools"]["ffmpeg"]["license"] == "LGPL-2.1-or-later"
    assert manifest["tools"]["ffprobe"]["upstream_revision"] == "a" * 40
    assert manifest["ffmpeg_build"]["configure_flags"] == attestation["configure_flags"]
    assert manifest["ffmpeg_build"]["toolchain"] == "synthetic-compiler-v1"
    for name in ("yt-dlp", "deno"):
        notice = Path(manifest["tools"][name]["license_notice"])
        assert "NOT APPROVED FOR DISTRIBUTION" in notice.read_text()
    assert manifest["tools"]["ffmpeg"]["license_notice"] == str(
        (ffmpeg / "LICENSE.md").resolve()
    )


@pytest.mark.parametrize("change", [
    "bad-ffmpeg-hash",
    "wrong-attestation-sha",
    "wrong-build-record-hash",
    "wrong-license-review",
])
def test_native_candidate_rejects_false_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str,
):
    youtube, ffmpeg, receipt, yt_pins, ff_pin, attest = _review_inputs(
        tmp_path, monkeypatch,
    )
    evidence = receipt.parent / "FFMPEG-BUILD-REVIEW.pending.json"
    if change == "bad-ffmpeg-hash":
        attest["tools"]["ffprobe"]["file_sha256"] = "0" * 64
    elif change == "wrong-build-record-hash":
        attest["build_record_sha256"] = "0" * 64
    elif change == "wrong-license-review":
        attest["inferred_license"] = "Unknown"
    else:
        receipt.write_text(json.dumps({"offline_attestation_sha256": "0" * 64}))
    if change != "wrong-attestation-sha":
        evidence.write_text(json.dumps(attest))
        receipt.write_text(json.dumps({
            "offline_attestation_sha256": native._digest(evidence),
        }))
    with pytest.raises(native.NativeManagedYouTubeError):
        native.make_native_candidate_manifest(
            target="macos-aarch64", youtube_dir=youtube, ffmpeg_dir=ffmpeg,
            ffmpeg_receipt=receipt, notice_dir=tmp_path / "notices",
            youtube_pins=yt_pins, ffmpeg_pin=ff_pin,
        )


def _synthetic_zip(tmp_path: Path) -> tuple[Path, dict]:
    archive = tmp_path / "synthetic-review-only.zip"
    tools = {name: f"bin/{name}" for name in ("yt-dlp", "deno", "ffmpeg", "ffprobe")}
    with zipfile.ZipFile(archive, "w") as output:
        for name, relative in tools.items():
            info = zipfile.ZipInfo(relative)
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o755) << 16
            output.writestr(info, f"synthetic executable {name}".encode())
            output.writestr(f"notices/{name}.txt", f"local QA notice: {name}")
        output.writestr("provenance/official.pending.json", "{}")
        output.writestr("BUNDLE-INVENTORY.json", "{}")
    return archive, {
        "target": "macos-aarch64",
        "component": "youtube_runtime",
        "version": "synthetic-1",
        "redistribution_status": "pending",
        "archive_sha256": native._digest(archive),
        "bundle_license": "synthetic-QA",
        "bundle_provenance": "locally generated QA fixture",
        "tool_paths": tools,
    }


def test_real_installer_and_product_readiness_with_mocked_native_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    archive, receipt = _synthetic_zip(tmp_path)
    used = []

    def mock_binary(command, args, **kwargs):
        used.append((Path(command).name, kwargs.get("label"), kwargs.get("env", {}).get("PATH")))
        if kwargs.get("label") == "managed-yt-dlp-native-media-handoff":
            output = args[args.index("--output") + 1].replace("%(ext)s", "flac")
            Path(output).write_bytes(b"fLaC" + b"fixture " * 300)
            return "synthetic output"
        if kwargs.get("label") == "managed-ffprobe-native-flac":
            return json.dumps({"streams": [{"codec_name": "flac", "sample_rate": "44100"}]})
        raise AssertionError("Unexpected external invocation")

    monkeypatch.setattr(native, "_run_binary", mock_binary)
    monkeypatch.setattr(
        native, "_verify_youtube_cli_tools",
        lambda tools, _root: used.append(("all-cli", sorted(tools), "")),
    )
    proof = native._smoke_installed_candidate(archive, receipt, target="macos-aarch64")
    assert proof["product_installer_sha256_verified"] is True
    assert proof["full_payload_sha256_verified"] is True
    assert proof["packaged_resolver_no_system_path"] is True
    assert proof["synthetic_media_handoff_verified"] is True
    assert len(used) == 3
    assert used[0][0] == "all-cli"
    assert used[1][2] == used[2][2] == ""


def test_corrupt_managed_bundle_rejected_before_any_process_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    archive, receipt = _synthetic_zip(tmp_path)
    receipt["archive_sha256"] = "0" * 64
    monkeypatch.setattr(
        native, "_verify_youtube_cli_tools",
        lambda *_args: (_ for _ in ()).throw(AssertionError("Unverified process started")),
    )
    with pytest.raises(ComponentIntegrityError, match="checksum mismatch"):
        native._smoke_installed_candidate(archive, receipt, target="macos-aarch64")


def test_native_review_workflow_does_not_publish_unapproved_zip():
    content = (
        Path(__file__).resolve().parents[1]
        / ".github/workflows/ffmpeg-native-build-review.yml"
    ).read_text()
    assert "verify_youtube_managed_candidate_native.py" in content
    upload = content.split("- name: Upload metadata-only FFmpeg provenance evidence", 1)[1]
    assert "MANAGED-YOUTUBE-NATIVE-E2E.pending.json" in upload
    assert "YOUTUBE-MANAGED-NATIVE-QA-ONLY.zip.pending.json" in upload
    assert "/YOUTUBE-MANAGED-NATIVE-QA-ONLY.zip\n" not in upload

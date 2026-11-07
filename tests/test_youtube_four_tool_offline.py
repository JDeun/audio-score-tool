"""Owned local fixtures for #29 four-tool review, with no upstream binaries or music."""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import pytest

from scripts import smoke_youtube_four_tool_offline as smoke


def _sha(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()


def _binary(target: str, name: str) -> bytes:
    if target == "windows-x86_64":
        contents = bytearray(b"MZ" + b"\0" * 254)
        contents[60:64] = (128).to_bytes(4, "little")
        contents[128:134] = b"PE\0\0\x64\x86"
        return bytes(contents) + name.encode()
    return b"\xcf\xfa\xed\xfe" + struct.pack("<I", 0x0100000C) + name.encode() + b"\0" * 32


def _fixture(tmp_path: Path, monkeypatch, target: str = "windows-x86_64"):
    monkeypatch.setattr(smoke, "_native_target", lambda chosen: chosen == target)
    original = tmp_path / "official"
    original.mkdir()
    ffmpeg_dir = tmp_path / "ffmpeg-src"
    ffmpeg_dir.mkdir()
    suffix = ".exe" if target == "windows-x86_64" else ""
    pins = {}
    receipts = {}
    downloaded = {}
    hashes = {}
    for name, repo, tag, asset in [
        ("yt-dlp", "yt-dlp/yt-dlp", "2026.10.26", "yt-dlp.exe" if suffix else "yt-dlp_macos"),
        (
            "deno", "denoland/deno", "v2.9.8",
            "deno-x86_64-pc-windows-msvc.zip" if suffix else "deno-aarch64-apple-darwin.zip",
        ),
    ]:
        data = _binary(target, name)
        source = original / (name + suffix)
        source.write_bytes(data)
        source_bytes = f"synthetic-official-{name}".encode()
        pins[name] = {
            "repository": repo, "tag": tag, "asset": asset,
            "url": f"https://github.com/{repo}/releases/download/{tag}/{asset}",
            "sha256": _sha(source_bytes), "bytes": len(source_bytes),
            "license_review": f"{name} review pending",
        }
        receipts[name] = {
            "repository": repo, "tag": tag, "asset": asset,
            "upstream_url": pins[name]["url"],
            "source_sha256": pins[name]["sha256"], "source_bytes": pins[name]["bytes"],
            "tool_sha256": _sha(data), "license_review": pins[name]["license_review"],
        }
        downloaded[name] = {
            "official_tag": tag, "pinned_asset_sha256": pins[name]["sha256"],
            "extracted_tool_sha256": _sha(data),
        }
        hashes[name] = _sha(data)
    official_report = {
        "schema": 1, "component": "youtube_runtime", "target": target,
        "local_bytes_verified": True, "redistribution_status": "pending",
        "upstream_signature_verified": False, "inputs": receipts,
    }
    downloaded_report = {
        "schema": 1, "target": target, "approval_status": "pending",
        "official_asset_bytes_sha256_verified": True,
        "native_binary_startup_verified": True,
        "redistribution_approved": False, "catalog_modified": False,
        "sources": downloaded,
    }
    (original / "SOURCE-EVIDENCE.pending.json").write_text(json.dumps(official_report))
    (original / "DOWNLOAD-EVIDENCE.pending.json").write_text(json.dumps(downloaded_report))
    yt_pin = tmp_path / "official-pins.json"
    yt_pin.write_text(json.dumps({"approval_status": "pending", "targets": {target: pins}}))
    ff_pin = tmp_path / "ffmpeg-pin.json"
    ff_pin.write_text(json.dumps({
        "schema": 1, "redistribution_status": "pending",
        "source_commit": "a" * 40, "catalog_published": False,
    }))
    tools = {}
    for name in ("ffmpeg", "ffprobe"):
        data = _binary(target, name)
        (ffmpeg_dir / (name + suffix)).write_bytes(data)
        tools[name] = {
            "binary_sha256": _sha(data), "native_executed": True,
        }
        hashes[name] = _sha(data)
    native = {
        "schema": 1, "component": "youtube_runtime.ffmpeg", "target": target,
        "binary_execution_verified": True, "synthetic_pcm_wav_produced": True,
        "redistribution_status": "pending", "approval_required": True,
        "catalog_published": False, "source_commit": "a" * 40,
        "source_pin_sha256": _sha(ff_pin.read_bytes()), "tools": tools,
    }
    native_file = tmp_path / "ffmpeg-proof.json"
    native_file.write_text(json.dumps(native))
    return original, ffmpeg_dir, native_file, yt_pin, ff_pin, hashes


@pytest.mark.parametrize("target", ("windows-x86_64", "macos-aarch64"))
def test_four_tool_handoff_uses_absolute_paths_and_is_metadata_only(
    tmp_path: Path, monkeypatch, target: str,
):
    youtube_dir, ffmpeg_dir, proof, yt_pin, ff_pin, hashes = _fixture(tmp_path, monkeypatch, target)
    calls = []

    def mock_run(executable, args, *, cwd, env, label, timeout=45):
        calls.append((executable, args, cwd, env, label, timeout))
        assert executable.is_absolute() and executable.parent.name == "bin"
        assert env["PATH"] == "" and env["PYTHONNOUSERSITE"] == "1"
        assert "HOME" in env and "XDG_CONFIG_HOME" in env
        assert timeout <= 80
        if label == "yt-dlp":
            assert args[:2] == ["--ignore-config", "--no-remote-components"]
            return "2026.10.26\n"
        if label == "deno":
            return "deno 2.9.8\n"
        if label == "yt-dlp-local-ffmpeg-handoff":
            assert "--ignore-config" in args
            assert "--no-remote-components" in args
            assert "--no-cache-dir" in args
            assert "--force-generic-extractor" in args
            assert "--ffmpeg-location" in args
            assert "--js-runtimes" in args
            assert args[args.index("--js-runtimes") + 1].startswith("deno:")
            assert str(executable.parent) == args[args.index("--ffmpeg-location") + 1]
            assert args[-1].startswith("http://127.0.0.1:")
            pattern = args[args.index("--output") + 1]
            Path(pattern.replace("%(ext)s", "flac")).write_bytes(b"fLaC" + b"x" * 2048)
            return ""
        if label == "ffprobe-converted-audio":
            assert args[args.index("-of") + 1] == "json"
            return json.dumps({"streams": [{"codec_name": "flac", "sample_rate": "44100"}]})
        raise AssertionError(f"Unexpected CLI tool {label}")

    monkeypatch.setattr(smoke, "_run_binary", mock_run)
    out = tmp_path / "FOUR-TOOL-OFFLINE-EVIDENCE.pending.json"
    receipt = smoke.verify_offline_four_tool(
        target=target, youtube_dir=youtube_dir, ffmpeg_dir=ffmpeg_dir,
        ffmpeg_receipt=proof, output_receipt=out,
        youtube_pins=yt_pin, ffmpeg_pin=ff_pin,
    )
    assert len(calls) == 4
    assert receipt["target"] == target
    assert receipt["isolated_four_tool_bin_verified"] is True
    assert receipt["yt_dlp_ffmpeg_flac_handoff_verified"] is True
    assert receipt["ffprobe_converted_audio_verified"] is True
    assert receipt["system_path_fallback"] is False
    assert receipt["redistribution_status"] == "pending"
    assert receipt["deno_youtube_js_challenge_verified"] is False
    assert receipt["real_youtube_download_verified"] is False
    assert receipt["binary_artifacts_published"] is False
    assert receipt["tool_sha256"] == hashes
    assert receipt == json.loads(out.read_text())


def test_tampered_ffprobe_is_rejected_before_copied_execution(tmp_path: Path, monkeypatch):
    sources, ff_dir, proof, yt_pin, ff_pin, _ = _fixture(tmp_path, monkeypatch)
    (ff_dir / "ffprobe.exe").write_bytes(b"tampered")
    monkeypatch.setattr(smoke, "_run_binary", lambda *_a, **_kw: pytest.fail(
        "No unverified executable should be spawned"
    ))
    with pytest.raises(smoke.OfflineFourToolError, match="SHA differs"):
        smoke.verify_offline_four_tool(
            target="windows-x86_64", youtube_dir=sources, ffmpeg_dir=ff_dir,
            ffmpeg_receipt=proof, output_receipt=tmp_path / "untrusted.json",
            youtube_pins=yt_pin, ffmpeg_pin=ff_pin,
        )


def test_review_receipt_cannot_claim_redistribution_approval(tmp_path: Path, monkeypatch):
    sources, ff_dir, proof, yt_pin, ff_pin, _ = _fixture(tmp_path, monkeypatch)
    raw = json.loads(proof.read_text())
    raw["redistribution_status"] = "approved"
    proof.write_text(json.dumps(raw))
    with pytest.raises(smoke.OfflineFourToolError, match="proof receipts"):
        smoke.verify_offline_four_tool(
            target="windows-x86_64", youtube_dir=sources, ffmpeg_dir=ff_dir,
            ffmpeg_receipt=proof, output_receipt=tmp_path / "untrusted.json",
            youtube_pins=yt_pin, ffmpeg_pin=ff_pin,
        )


def test_wrong_runner_target_is_rejected_before_any_tool_is_copied(tmp_path: Path, monkeypatch):
    sources, ff_dir, proof, yt_pin, ff_pin, _ = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(smoke, "_native_target", lambda _target: False)
    with pytest.raises(smoke.OfflineFourToolError, match="native OS"):
        smoke.verify_offline_four_tool(
            target="windows-x86_64", youtube_dir=sources, ffmpeg_dir=ff_dir,
            ffmpeg_receipt=proof, output_receipt=tmp_path / "untrusted.json",
            youtube_pins=yt_pin, ffmpeg_pin=ff_pin,
        )


def test_source_pin_tampering_is_rejected(tmp_path: Path, monkeypatch):
    sources, ff_dir, proof, yt_pin, ff_pin, _ = _fixture(tmp_path, monkeypatch)
    document = json.loads(yt_pin.read_text())
    document["targets"]["windows-x86_64"]["deno"]["sha256"] = "0" * 64
    yt_pin.write_text(json.dumps(document))
    with pytest.raises(smoke.OfflineFourToolError, match="official source evidence"):
        smoke.verify_offline_four_tool(
            target="windows-x86_64", youtube_dir=sources, ffmpeg_dir=ff_dir,
            ffmpeg_receipt=proof, output_receipt=tmp_path / "untrusted.json",
            youtube_pins=yt_pin, ffmpeg_pin=ff_pin,
        )


def test_missing_native_ffmpeg_proof_fails_closed(tmp_path: Path, monkeypatch):
    sources, ff_dir, proof, yt_pin, ff_pin, _ = _fixture(tmp_path, monkeypatch)
    proof.unlink()
    with pytest.raises(smoke.OfflineFourToolError, match="native FFmpeg"):
        smoke.verify_offline_four_tool(
            target="windows-x86_64", youtube_dir=sources, ffmpeg_dir=ff_dir,
            ffmpeg_receipt=proof, output_receipt=tmp_path / "untrusted.json",
            youtube_pins=yt_pin, ffmpeg_pin=ff_pin,
        )


def test_unexpected_cli_output_is_not_accepted(tmp_path: Path, monkeypatch):
    sources, ff_dir, proof, yt_pin, ff_pin, _ = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(smoke, "_run_binary", lambda *_a, **_kw: "wrong-version")
    with pytest.raises(smoke.OfflineFourToolError, match="isolated CLI version"):
        smoke.verify_offline_four_tool(
            target="windows-x86_64", youtube_dir=sources, ffmpeg_dir=ff_dir,
            ffmpeg_receipt=proof, output_receipt=tmp_path / "untrusted.json",
            youtube_pins=yt_pin, ffmpeg_pin=ff_pin,
        )


def test_workflow_requires_actual_native_four_tool_smoke_without_media_upload():
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github/workflows/ffmpeg-native-build-review.yml"
    ).read_text(encoding="utf-8")
    assert "scripts/fetch_youtube_official_assets.py" in workflow
    assert "scripts/smoke_youtube_four_tool_offline.py" in workflow
    assert "FOUR-TOOL-OFFLINE-EVIDENCE.pending.json" in workflow
    assert "windows-2025" in workflow and "macos-15" in workflow
    assert "actions/upload-artifact@" in workflow
    assert ".exe" not in workflow.split("Upload metadata-only FFmpeg provenance evidence")[1]
    assert "desktop-packages.yml" not in workflow

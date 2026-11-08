"""Native four-tool YouTube *managed ZIP* product acceptance (unapproved).

Builds the same real Windows/macOS ZIP that the app's Setup Center installer
accepts. All binaries are pinned to independently verified upstream/native
source bytes. Nothing executable is uploaded as an Actions artifact or marked
approved. The media input is a synthetic loopback WAV, never a YouTube video.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from audio_score_tool.config import Settings
from audio_score_tool.managed_components import ComponentArtifact, install_component_artifact
from audio_score_tool.managed_tool_resolver import registered_managed_tool
from audio_score_tool.youtube import youtube_tool_status
from scripts.assemble_youtube_runtime_candidate import assemble_youtube_candidate
from scripts.smoke_packaged_sidecar import _verify_youtube_cli_tools
from scripts.smoke_youtube_four_tool_offline import (
    _digest,
    _run_binary,
    _serve_owned_wav,
    _synthetic_wav,
    _validate_sources,
)
from scripts.verify_ffmpeg_native_build import DEFAULT_PIN as FFMPEG_PIN
from scripts.verify_youtube_native_cli import PINS as YOUTUBE_PINS


class NativeManagedYouTubeError(ValueError):
    """Official source or product-managed runtime did not meet release QA."""


def _read_json(path: Path, label: str) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise NativeManagedYouTubeError(f"{label}: missing or unsafe review receipt")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError, UnicodeError) as exc:
        raise NativeManagedYouTubeError(f"{label}: unreadable review evidence") from exc
    if not isinstance(value, dict):
        raise NativeManagedYouTubeError(f"{label}: evidence must be a JSON object")
    return value


def _pending_notices(destination: Path, official: dict) -> dict[str, Path]:
    """Preliminary QA disclosures; explicitly NOT final redistributable notices."""
    if destination.exists():
        raise NativeManagedYouTubeError("Unapproved notice staging already exists")
    destination.mkdir()
    notices: dict[str, Path] = {}
    sources = {
        "yt-dlp": (
            "GPL-3.0-or-later (combined standalone PyInstaller binary; pending full dependency review)",
            "https://github.com/yt-dlp/yt-dlp",
        ),
        "deno": ("MIT (pending full distribution notice review)", "https://github.com/denoland/deno"),
    }
    for name, (license_family, upstream) in sources.items():
        origin = official.get("inputs", {}).get(name, {})
        if not isinstance(origin, dict):
            raise NativeManagedYouTubeError(f"{name}: official license provenance missing")
        version = origin.get("tag")
        if not isinstance(version, str) or not version:
            raise NativeManagedYouTubeError(f"{name}: pinned source version missing")
        path = destination / f"{name}.LICENSE.pending.txt"
        path.write_text(
            "QA REVIEW COPY ONLY — NOT APPROVED FOR DISTRIBUTION\n"
            f"Product: {name}\nPinned release: {version}\n"
            f"License family under review: {license_family}\n"
            f"Official upstream: {upstream}\n"
            "Verify all combined-work dependencies, actual license text, "
            "attributions and corresponding-source delivery before publication.\n",
            encoding="utf-8",
        )
        notices[name] = path
    return notices


def make_native_candidate_manifest(
    *,
    target: str,
    youtube_dir: Path,
    ffmpeg_dir: Path,
    ffmpeg_receipt: Path,
    notice_dir: Path,
    youtube_pins: Path = YOUTUBE_PINS,
    ffmpeg_pin: Path = FFMPEG_PIN,
) -> dict:
    """Bind one candidate to independent real upstream and native FFmpeg proofs."""
    sources = _validate_sources(
        target, youtube_dir, ffmpeg_dir, ffmpeg_receipt, youtube_pins, ffmpeg_pin,
    )
    official = _read_json(youtube_dir / "SOURCE-EVIDENCE.pending.json", "YouTube official")
    yt_pins = _read_json(youtube_pins, "YouTube upstream pins")["targets"][target]
    ff_pin = _read_json(ffmpeg_pin, "FFmpeg native build pin")
    ff_native = _read_json(ffmpeg_receipt, "native FFmpeg execution")
    attestation_path = ffmpeg_receipt.parent / "FFMPEG-BUILD-REVIEW.pending.json"
    attestation = _read_json(attestation_path, "FFmpeg build provenance")
    build_record = ffmpeg_receipt.parent / "build-record.txt"
    ff_notice = ffmpeg_dir / "LICENSE.md"
    if (
        attestation.get("schema") != 1
        or attestation.get("component") != "youtube_runtime.ffmpeg"
        or attestation.get("target") != target
        or attestation.get("redistribution_status") != "pending"
        or ff_native.get("offline_attestation_sha256") != _digest(attestation_path)
        or attestation.get("source_revision") != ff_pin["source_commit"]
        or attestation.get("source_url") != ff_pin["source_url"]
        or attestation.get("build_record_sha256") != _digest(build_record)
        or attestation.get("license_notice_sha256") != _digest(ff_notice)
        or attestation.get("inferred_license") != ff_pin["license_family_review"]
        or set(attestation.get("tools", {})) != {"ffmpeg", "ffprobe"}
    ):
        raise NativeManagedYouTubeError("Native FFmpeg build and license evidence do not match")
    for name in ("ffmpeg", "ffprobe"):
        if attestation["tools"][name].get("file_sha256") != sources["digests"][name]:
            raise NativeManagedYouTubeError(f"{name}: native binary differs from attestation")

    notices = _pending_notices(notice_dir, official)
    yt_version = yt_pins["yt-dlp"]["tag"]
    deno_tag = yt_pins["deno"]["tag"]
    ff_version = attestation["version"]
    if not all(isinstance(version, str) and version for version in (
        yt_version, deno_tag, ff_version,
    )):
        raise NativeManagedYouTubeError("Pinned native runtime version missing")
    name = f"yt{yt_version}-deno{deno_tag.removeprefix('v')}-ffmpeg{ff_version}-qa1"
    if any(value in name for value in ("/", "\\", " ", "..")):
        raise NativeManagedYouTubeError("Unsafe candidate component version")

    tools = {}
    for tool in ("yt-dlp", "deno"):
        pin = yt_pins[tool]
        tools[tool] = {
            "file": str(sources["files"][tool].resolve()),
            "sha256": sources["digests"][tool],
            "version": pin["tag"].removeprefix("v") if tool == "deno" else pin["tag"],
            "upstream_revision": pin["tag"],
            "upstream_url": pin["url"],
            "license": "GPL-3.0-or-later" if tool == "yt-dlp" else "MIT",
            "license_notice": str(notices[tool].resolve()),
        }
    for tool in ("ffmpeg", "ffprobe"):
        tools[tool] = {
            "file": str(sources["files"][tool].resolve()),
            "sha256": sources["digests"][tool],
            "version": ff_version,
            "upstream_revision": ff_pin["source_commit"],
            "upstream_url": ff_pin["source_url"],
            "license": attestation["inferred_license"],
            "license_notice": str(ff_notice.resolve()),
        }
    return {
        "schema": 1,
        "target": target,
        "version": name,
        "bundle_license": "GPL-3.0-or-later / MIT / LGPL-2.1-or-later (review pending)",
        "bundle_provenance": (
            f"Official yt-dlp {yt_version}; Deno {deno_tag}; "
            f"FFmpeg {ff_pin['source_commit']} native source build, QA-only"
        ),
        "official_sources_evidence": str(
            (youtube_dir / "SOURCE-EVIDENCE.pending.json").resolve()
        ),
        "tools": tools,
        "ffmpeg_build": {
            "configure_flags": attestation["configure_flags"],
            "toolchain": attestation["toolchain"],
            "build_record": str(build_record.resolve()),
            "attestation_file": str(attestation_path.resolve()),
        },
    }


def _smoke_installed_candidate(bundle: Path, receipt: dict, *, target: str) -> dict:
    """Exercise real packaged resolver + same product managed installer + media handoff."""
    if receipt.get("target") != target or receipt.get("redistribution_status") != "pending":
        raise NativeManagedYouTubeError("Only the exact unapproved native candidate is testable")
    with tempfile.TemporaryDirectory(prefix="ast-native-youtube-product-") as temp:
        root = Path(temp).resolve()
        managed = root / "components"
        paths = receipt["tool_paths"]
        artifact = ComponentArtifact(
            component="youtube_runtime", version=receipt["version"],
            url="https://example.invalid/qa-never-published.zip",
            sha256=receipt["archive_sha256"], archive="zip",
            tools=paths, license=receipt["bundle_license"],
            provenance=receipt["bundle_provenance"],
        )
        installed = install_component_artifact(
            artifact, root=managed, local_archive=bundle,
        )
        if installed.get("ready") is not True or installed.get("integrity") != "verified":
            raise NativeManagedYouTubeError("Native ZIP was not installed/verified by product")
        if installed.get("payload_file_count", 0) < 10:
            raise NativeManagedYouTubeError("Full bundled runtime resources were not registered")
        tools = installed["tools"]
        if set(tools) != {"yt-dlp", "deno", "ffmpeg", "ffprobe"}:
            raise NativeManagedYouTubeError("Installed YouTube tool registry is incomplete")

        with patch.dict(os.environ, {
            "AST_PACKAGED": "1",
            "AST_COMPONENT_DIR": str(managed),
            "AST_USAGE_MODE": "commercial",
        }):
            readiness = youtube_tool_status(Settings())
            if readiness.get("ready") is not True:
                raise NativeManagedYouTubeError("Packaged YouTube product path is not ready")
            for tool in tools:
                if registered_managed_tool(tool, component="youtube_runtime") != Path(tools[tool]):
                    raise NativeManagedYouTubeError(f"{tool}: component resolver selected wrong owner")
            _verify_youtube_cli_tools(tools, managed)

            env = os.environ.copy()
            env.update({
                "PATH": "", "PYTHONNOUSERSITE": "1",
                "HOME": str(root), "XDG_CONFIG_HOME": str(root),
                "APPDATA": str(root),
                "HTTP_PROXY": "", "HTTPS_PROXY": "", "ALL_PROXY": "",
                "NO_PROXY": "127.0.0.1,localhost",
            })
            audio = root / "original-generated.wav"
            _synthetic_wav(audio)
            server, task = _serve_owned_wav(audio)
            try:
                converted = root / "converted"
                converted.mkdir()
                url = f"http://127.0.0.1:{server.server_address[1]}/original-sine.wav"
                _run_binary(
                    Path(tools["yt-dlp"]),
                    [
                        "--ignore-config", "--no-remote-components", "--no-cache-dir",
                        "--force-generic-extractor", "--no-playlist", "--no-progress",
                        "--js-runtimes", f"deno:{tools['deno']}",
                        "--ffmpeg-location", str(Path(tools["ffmpeg"]).parent),
                        "--extract-audio", "--audio-format", "flac",
                        "--output", str(converted / "original.%(ext)s"), url,
                    ],
                    cwd=root, env=env, label="managed-yt-dlp-native-media-handoff", timeout=80,
                )
            finally:
                server.shutdown()
                server.server_close()
                task.join(timeout=5)
            flac = list(converted.glob("*.flac"))
            if len(flac) != 1 or flac[0].read_bytes()[:4] != b"fLaC":
                raise NativeManagedYouTubeError("Installed managed yt-dlp failed FFmpeg media conversion")
            output = _run_binary(
                Path(tools["ffprobe"]),
                ["-v", "error", "-select_streams", "a:0",
                 "-show_entries", "stream=codec_name,sample_rate",
                 "-of", "json", str(flac[0])],
                cwd=root, env=env, label="managed-ffprobe-native-flac", timeout=20,
            )
            streams = json.loads(output)["streams"]
            if (
                len(streams) != 1 or streams[0].get("codec_name") != "flac"
                or streams[0].get("sample_rate") != "44100"
            ):
                raise NativeManagedYouTubeError("Installed FFprobe did not validate exported FLAC")
        return {
            "product_installer_sha256_verified": True,
            "full_payload_sha256_verified": True,
            "packaged_resolver_no_system_path": True,
            "all_four_native_cli_versions_verified": True,
            "synthetic_media_handoff_verified": True,
            "synthetic_flac_sha256": _digest(flac[0]),
            "installed_payload_file_count": installed["payload_file_count"],
        }


def verify_native_managed_candidate(
    *, target: str,
    youtube_dir: Path,
    ffmpeg_dir: Path,
    ffmpeg_receipt: Path,
    destination: Path,
) -> dict:
    if not destination.parent.is_dir() or destination.exists() or destination.is_symlink():
        raise NativeManagedYouTubeError("Candidate QA output must be a new directory")
    with tempfile.TemporaryDirectory(prefix="ast-youtube-bundle-review-", dir=destination.parent) as temp:
        staging = Path(temp)
        manifest = make_native_candidate_manifest(
            target=target, youtube_dir=youtube_dir, ffmpeg_dir=ffmpeg_dir,
            ffmpeg_receipt=ffmpeg_receipt, notice_dir=staging / "notices",
        )
        candidate = staging / "YOUTUBE-MANAGED-NATIVE-QA-ONLY.zip"
        review = assemble_youtube_candidate(manifest, candidate)
        if _digest(candidate) != review["archive_sha256"]:
            raise NativeManagedYouTubeError("Generated managed candidate bytes drifted")
        proof = _smoke_installed_candidate(candidate, review, target=target)
        evidence = {
            "schema": 1, "component": "youtube_runtime", "target": target,
            "version": review["version"],
            "archive_sha256": review["archive_sha256"],
            "archive_bytes": candidate.stat().st_size,
            "native_source_receipt_sha256": _digest(
                youtube_dir / "SOURCE-EVIDENCE.pending.json"
            ),
            "ffmpeg_native_receipt_sha256": _digest(ffmpeg_receipt),
            "source_sha256": {
                name: review["tools"][name]["sha256"]
                for name in ("yt-dlp", "deno", "ffmpeg", "ffprobe")
            },
            **proof,
            "official_youtube_extractor_verified": False,
            "actual_youtube_video_download_verified": False,
            "clean_machine_installer_verified": False,
            "remote_archive_published": False,
            "redistribution_status": "pending",
            "third_party_notices_approved": False,
            "approval_required": True,
        }
        (staging / "MANAGED-YOUTUBE-NATIVE-E2E.pending.json").write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8",
        )
        staging.rename(destination)
        return evidence


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify actual native YouTube managed ZIP install offline (never publish)."
    )
    parser.add_argument("--target", choices=("windows-x86_64", "macos-aarch64"), required=True)
    parser.add_argument("--youtube-dir", type=Path, required=True)
    parser.add_argument("--ffmpeg-dir", type=Path, required=True)
    parser.add_argument("--ffmpeg-receipt", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = verify_native_managed_candidate(
            target=args.target, youtube_dir=args.youtube_dir,
            ffmpeg_dir=args.ffmpeg_dir, ffmpeg_receipt=args.ffmpeg_receipt,
            destination=args.output_dir,
        )
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        parser.exit(2, f"Native managed YouTube candidate rejected: {exc}\n")
    print(json.dumps({
        "target": result["target"],
        "product_installer_sha256_verified": result["product_installer_sha256_verified"],
        "synthetic_media_handoff_verified": result["synthetic_media_handoff_verified"],
        "remote_archive_published": False,
        "redistribution_status": "pending",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

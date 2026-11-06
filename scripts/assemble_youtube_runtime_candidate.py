"""Assemble an offline, unapproved YouTube runtime candidate for one target OS.

The input manifest pins all four LOCAL binary digests and their license notices.
The command never downloads, executes or redistributes anything. Its zip output
must go through separate license review, real URL publication and #29 acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from audio_score_tool.managed_components import (
    ComponentArtifact,
    ComponentError,
    install_component_artifact,
)

_TOOLS = ("yt-dlp", "deno", "ffmpeg", "ffprobe")
_TARGETS = {"windows-x86_64", "macos-aarch64"}
_SAFE_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_PLACEHOLDERS = {"", "tbd", "pending", "unknown", "latest", "unreviewed", "runtime-specific"}
_MAX_NOTICE_BYTES = 4 * 1024 * 1024


def _nonplaceholder(value: object, field: str) -> str:
    if not isinstance(value, str) or value.strip().lower() in _PLACEHOLDERS:
        raise ValueError(f"{field} must be an explicit, reviewed value.")
    return value.strip()


def _read_local(path_text: object, *, label: str, limit: int | None = None) -> Path:
    value = _nonplaceholder(path_text, label)
    path = Path(value)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be an absolute regular non-symlink file.")
    if path.stat().st_size <= 0 or (limit and path.stat().st_size > limit):
        raise ValueError(f"{label} is empty or exceeds its allowed size.")
    return path


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pe_x86_64(path: Path) -> bool:
    with path.open("rb") as source:
        header = source.read(64)
        if len(header) != 64 or header[:2] != b"MZ":
            return False
        offset = int.from_bytes(header[60:64], "little")
        if offset < 64 or offset > 4096:
            return False
        source.seek(offset)
        signature = source.read(6)
        return signature[:4] == b"PE\x00\x00" and signature[4:6] == b"\x64\x86"


def _macho_arm64(path: Path) -> bool:
    with path.open("rb") as source:
        magic = source.read(4)
        # Thin Mach-O 64-bit (little or big endian).
        if magic in {b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf"}:
            endian = "little" if magic == b"\xcf\xfa\xed\xfe" else "big"
            return int.from_bytes(source.read(4), endian) == 0x0100000C
        # Universal/fat Mach-O (32-bit or 64-bit fat headers).
        if magic not in {b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca",
                         b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca"}:
            return False
        endian = "big" if magic in {b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf"} else "little"
        stride = 32 if magic in {b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca"} else 20
        count = int.from_bytes(source.read(4), endian)
        if count < 1 or count > 16:
            return False
        arch_entries = source.read(count * stride)
        if len(arch_entries) != count * stride:
            return False
        return any(
            int.from_bytes(arch_entries[index * stride: index * stride + 4], endian)
            == 0x0100000C
            for index in range(count)
        )


def _ensure_binary_architecture(path: Path, target: str, name: str) -> None:
    valid = _pe_x86_64(path) if target == "windows-x86_64" else _macho_arm64(path)
    if not valid:
        raise ValueError(f"{name}: binary format/CPU does not match {target}.")


def _manifest_source(value: Any, *, tool: str, target: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{tool}: complete source metadata is required.")
    source = _read_local(value.get("file"), label=f"{tool}.file")
    _ensure_binary_architecture(source, target, tool)
    expected = _nonplaceholder(value.get("sha256"), f"{tool}.sha256").lower()
    if not _SHA256.fullmatch(expected):
        raise ValueError(f"{tool}: invalid pinned SHA-256.")
    if (actual := _digest(source)) != expected:
        raise ValueError(f"{tool}: SHA-256 mismatch (expected {expected}, got {actual}).")
    notice = _read_local(
        value.get("license_notice"), label=f"{tool}.license_notice", limit=_MAX_NOTICE_BYTES
    )
    if b"\x00" in notice.read_bytes():
        raise ValueError(f"{tool}: license notice is not plain text.")
    version = _nonplaceholder(value.get("version"), f"{tool}.version")
    revision = _nonplaceholder(value.get("upstream_revision"), f"{tool}.upstream_revision")
    license_name = _nonplaceholder(value.get("license"), f"{tool}.license")
    source_url = _nonplaceholder(value.get("upstream_url"), f"{tool}.upstream_url")
    if (
        not source_url.startswith("https://")
        or "/latest" in source_url.lower()
        or "@" in source_url.split("/", 3)[2]
    ):
        raise ValueError(f"{tool}: use a pinned, credential-free upstream HTTPS reference.")
    # Official PyInstaller yt-dlp executables contain GPLv3+ dependencies.
    if tool == "yt-dlp" and "GPL-3" not in license_name.upper():
        raise ValueError("yt-dlp standalone executable requires GPLv3+ combined-work review.")
    if tool == "deno" and "MIT" not in license_name.upper():
        raise ValueError("Deno license evidence must identify MIT.")
    return {
        "path": source,
        "notice": notice,
        "version": version,
        "upstream_revision": revision,
        "upstream_url": source_url,
        "license": license_name,
        "sha256": expected,
        "notice_sha256": _digest(notice),
    }


def _ffmpeg_build(
    value: Any, sources: dict[str, dict[str, Any]], target: str
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Exact FFmpeg build provenance is required.")
    if (
        sources["ffmpeg"]["upstream_revision"] != sources["ffprobe"]["upstream_revision"]
        or sources["ffmpeg"]["version"] != sources["ffprobe"]["version"]
    ):
        raise ValueError("FFmpeg and ffprobe must come from the same pinned build/revision.")
    flags = value.get("configure_flags")
    if not isinstance(flags, list) or not flags or not all(isinstance(x, str) for x in flags):
        raise ValueError("ffmpeg_build.configure_flags must be a nonempty list.")
    flags = [x.strip() for x in flags]
    if any(not x.startswith("--") or " " in x or not x for x in flags):
        raise ValueError("FFmpeg flags must be individual configure arguments.")
    if any(x.lower() == "--enable-nonfree" for x in flags):
        raise ValueError("Nonfree FFmpeg builds must not be bundled.")
    if any(x.lower() == "--enable-gpl" for x in flags):
        if any(not sources[tool]["license"].upper().startswith("GPL-") for tool in ("ffmpeg", "ffprobe")):
            raise ValueError("FFmpeg --enable-gpl needs a GPL license declaration.")
    evidence = _read_local(
        value.get("build_record"), label="ffmpeg_build.build_record", limit=_MAX_NOTICE_BYTES
    )
    toolchain = _nonplaceholder(value.get("toolchain"), "ffmpeg_build.toolchain")
    # A declared build record is not a verification. Require the independently
    # generated pending review from verify_ffmpeg_build_provenance.py and match
    # its exact local tool hashes, source revision, configure and license facts.
    attestation_file = _read_local(
        value.get("attestation_file"),
        label="ffmpeg_build.attestation_file",
        limit=_MAX_NOTICE_BYTES,
    )
    try:
        report = json.loads(attestation_file.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("FFmpeg attestation report is unreadable.") from exc
    if not isinstance(report, dict):
        raise ValueError("FFmpeg attestation report must be an object.")
    if (
        report.get("schema") != 1
        or report.get("component") != "youtube_runtime.ffmpeg"
        or report.get("target") != target
        or report.get("redistribution_status") != "pending"
        or report.get("legal_review_status") != "pending"
        or report.get("approval_required") is not True
        or report.get("local_binary_sha256_verified") is not True
        or report.get("supplied_version_reports_consistent") is not True
    ):
        raise ValueError("FFmpeg attestation is not a validated pending review for this target.")
    if (
        report.get("version") != sources["ffmpeg"]["version"]
        or report.get("source_revision") != sources["ffmpeg"]["upstream_revision"]
        or set(report.get("configure_flags") or []) != set(flags)
        or report.get("toolchain") != toolchain
        or report.get("build_record_sha256") != _digest(evidence)
    ):
        raise ValueError("FFmpeg attestation provenance/configuration differs from bundle inputs.")
    verified = report.get("tools")
    if not isinstance(verified, dict) or set(verified) != {"ffmpeg", "ffprobe"}:
        raise ValueError("FFmpeg attestation tool inventory is incomplete.")
    for name in ("ffmpeg", "ffprobe"):
        if (
            not isinstance(verified[name], dict)
            or verified[name].get("file_sha256") != sources[name]["sha256"]
            or report.get("inferred_license") != sources[name]["license"]
        ):
            raise ValueError(f"{name}: FFmpeg attestation hash/license differs from bundle input.")
    if report.get("license_notice_sha256") not in {
        sources["ffmpeg"]["notice_sha256"],
        sources["ffprobe"]["notice_sha256"],
    }:
        raise ValueError("FFmpeg attestation license notice does not match bundle inputs.")
    return {
        "configure_flags": flags,
        "toolchain": toolchain,
        "build_record": evidence,
        "build_record_sha256": _digest(evidence),
        "attestation_file": attestation_file,
        "attestation_sha256": _digest(attestation_file),
    }


def _zip_entry(
    archive: zipfile.ZipFile, name: str, path: Path, *, executable: bool, expected_sha256: str
) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | (0o755 if executable else 0o644)) << 16
    info.compress_type = zipfile.ZIP_STORED
    with archive.open(info, "w", force_zip64=True) as output, path.open("rb") as source:
        digest = hashlib.sha256()
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
            output.write(chunk)
    # Recheck against the pinned source hash: mutation during packaging fails closed.
    if digest.hexdigest() != expected_sha256:
        raise ValueError(f"{name}: source changed during archive creation.")


def _zip_text(archive: zipfile.ZipFile, name: str, payload: dict[str, Any]) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    info.compress_type = zipfile.ZIP_STORED
    archive.writestr(info, json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


def assemble_youtube_candidate(manifest: dict[str, Any], destination: Path) -> dict[str, Any]:
    """Produce an immutable local ZIP + pending evidence without publishing it."""
    if not isinstance(manifest, dict) or manifest.get("schema") != 1:
        raise ValueError("Expected YouTube bundle manifest schema 1.")
    target = manifest.get("target")
    if target not in _TARGETS:
        raise ValueError("Supported bundle targets: windows-x86_64, macos-aarch64.")
    version = _nonplaceholder(manifest.get("version"), "version")
    if not _SAFE_VERSION.fullmatch(version):
        raise ValueError("Bundle version is not a safe component identifier.")
    raw_sources = manifest.get("tools")
    if not isinstance(raw_sources, dict) or set(raw_sources) != set(_TOOLS):
        raise ValueError("Exactly yt-dlp, deno, ffmpeg and ffprobe source entries are required.")

    sources = {
        name: _manifest_source(raw_sources[name], tool=name, target=target)
        for name in _TOOLS
    }
    ffmpeg = _ffmpeg_build(manifest.get("ffmpeg_build"), sources, target)
    license_summary = _nonplaceholder(manifest.get("bundle_license"), "bundle_license")
    provenance = _nonplaceholder(manifest.get("bundle_provenance"), "bundle_provenance")
    pending_path = destination.with_name(destination.name + ".pending.json")
    if destination.exists() or pending_path.exists():
        raise FileExistsError("Refusing to overwrite an existing bundle or pending evidence.")
    if destination.suffix.lower() != ".zip":
        raise ValueError("YouTube managed bundles must use ZIP archives.")
    if not destination.parent.is_dir():
        raise ValueError("Bundle output directory does not exist.")

    suffix = ".exe" if target.startswith("windows-") else ""
    paths = {name: f"bin/{name}{suffix}" for name in _TOOLS}
    inventory = {
        name: {
            "relative_path": paths[name],
            "sha256": sources[name]["sha256"],
            "version": sources[name]["version"],
            "upstream_url": sources[name]["upstream_url"],
            "upstream_revision": sources[name]["upstream_revision"],
            "license": sources[name]["license"],
            "license_notice_sha256": sources[name]["notice_sha256"],
        }
        for name in _TOOLS
    }
    inventory["ffmpeg-build"] = {
        "configure_flags": ffmpeg["configure_flags"],
        "toolchain": ffmpeg["toolchain"],
        "build_record_sha256": ffmpeg["build_record_sha256"],
        "attestation_sha256": ffmpeg["attestation_sha256"],
    }

    tmp = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".youtube-candidate-", suffix=".zip.tmp",
            dir=destination.parent, delete=False,
        ) as handle:
            tmp = Path(handle.name)
        with zipfile.ZipFile(tmp, "w", allowZip64=True) as archive:
            for name in _TOOLS:
                _zip_entry(
                    archive, paths[name], sources[name]["path"],
                    executable=True, expected_sha256=sources[name]["sha256"],
                )
            for name in _TOOLS:
                _zip_entry(
                    archive, f"notices/{name}.LICENSE.txt",
                    sources[name]["notice"], executable=False,
                    expected_sha256=sources[name]["notice_sha256"],
                )
            _zip_entry(
                archive, "provenance/ffmpeg-build.txt",
                ffmpeg["build_record"], executable=False,
                expected_sha256=ffmpeg["build_record_sha256"],
            )
            _zip_entry(
                archive, "provenance/ffmpeg-attestation.pending.json",
                ffmpeg["attestation_file"], executable=False,
                expected_sha256=ffmpeg["attestation_sha256"],
            )
            _zip_text(archive, "BUNDLE-INVENTORY.json", {
                "schema": 1, "target": target, "version": version,
                "tools": inventory, "redistribution_status": "pending",
            })
        # Reuse the exact product installer in a temporary isolated root.
        archive_digest = _digest(tmp)
        artifact = ComponentArtifact(
            component="youtube_runtime", version=version,
            url="https://example.invalid/local-verification-only",
            sha256=archive_digest, archive="zip", tools=paths,
            license=license_summary, provenance=provenance,
        )
        with tempfile.TemporaryDirectory(prefix="youtube-bundle-verify-") as directory:
            result = install_component_artifact(
                artifact, root=Path(directory), local_archive=tmp
            )
            if result.get("integrity") != "verified" or not result.get("ready"):
                raise RuntimeError("Local isolated managed install failed.")

        report = {
            "schema": 1, "target": target, "component": "youtube_runtime",
            "version": version, "archive_sha256": archive_digest,
            "archive_filename": destination.name,
            "bundle_license": license_summary,
            "bundle_provenance": provenance,
            "tools": inventory,
            "tool_paths": paths,
            "redistribution_status": "pending",
            "local_install_verified": True,
            "binaries_executed": False,
            "remote_archive_verified": False,
            "clean_machine_verified": False,
            "approval_required": True,
        }
        # Exclusive creation prevents accidental replacement of prior evidence.
        with pending_path.open("x", encoding="utf-8") as output:
            json.dump(report, output, ensure_ascii=False, sort_keys=True, indent=2)
            output.write("\n")
        try:
            os.link(tmp, destination)
        except Exception:
            pending_path.unlink(missing_ok=True)
            raise
        return report
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a pending YouTube runtime bundle, offline.")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        report = assemble_youtube_candidate(manifest, args.output)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, ComponentError) as exc:
        parser.exit(2, f"YouTube bundle candidate rejected: {exc}\n")
    print(f"Verified local candidate: {args.output} (sha256={report['archive_sha256']})")
    print(f"Redistribution approval remains {report['redistribution_status']}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

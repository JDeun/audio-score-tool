"""Offline FFmpeg/ffprobe build evidence review.

This validates provided -version reports and pinned binaries without executing
third-party code. Text logs are not cryptographically bound to binary bytes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
from pathlib import Path
from typing import Any

from scripts.assemble_youtube_runtime_candidate import _ensure_binary_architecture

_TARGETS = {"windows-x86_64", "macos-aarch64"}
_TOOLS = ("ffmpeg", "ffprobe")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_GPL_2_LIBS = {"libx264", "libx265", "libxvid", "libxavs", "libxavs2",
               "libvidstab", "librubberband", "libdavs", "libcdio"}
_GPL_3_LIBS = {"libsmbclient"}
_LGPL_3_LIBS = {"liblensfun", "libaribb24", "libgmp"}
_MAX_REPORT = 4 * 1024 * 1024
_UNREVIEWED = {"", "unknown", "pending", "unreviewed", "runtime-specific", "latest"}
_ROOT = Path(__file__).resolve().parents[1]
_BUNDLED_CATALOG = _ROOT / "src/audio_score_tool/managed-component-catalog.json"


class FFmpegAttestationError(ValueError):
    """The submitted build evidence is incomplete or inconsistent."""


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or value.strip().lower() in _UNREVIEWED:
        raise FFmpegAttestationError(f"{label}: explicit pinned value required.")
    return value.strip()


def _file(value: object, label: str, *, max_bytes: int | None = None) -> Path:
    path = Path(_text(value, label))
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise FFmpegAttestationError(f"{label}: absolute regular non-symlink file required.")
    size = path.stat().st_size
    if not size or (max_bytes is not None and size > max_bytes):
        raise FFmpegAttestationError(f"{label}: empty or oversized file.")
    return path


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _configuration(path: Path, tool: str, version: str) -> tuple[str, ...]:
    raw = path.read_bytes()
    if b"\x00" in raw:
        raise FFmpegAttestationError(f"{tool}: binary report contents.")
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FFmpegAttestationError(f"{tool}: report is not UTF-8.") from exc
    lines = content.splitlines()
    if not lines or not re.match(rf"^{tool} version {re.escape(version)}(?:\s|$)", lines[0]):
        raise FFmpegAttestationError(f"{tool}: version output does not match pin.")
    config = [line.strip().removeprefix("configuration:").strip()
              for line in lines if line.strip().startswith("configuration:")]
    if len(config) != 1:
        raise FFmpegAttestationError(f"{tool}: exactly one configuration line required.")
    try:
        flags = tuple(shlex.split(config[0]))
    except ValueError as exc:
        raise FFmpegAttestationError(f"{tool}: malformed configuration.") from exc
    if not flags or any(not flag.startswith("--") for flag in flags):
        raise FFmpegAttestationError(f"{tool}: invalid configure flags.")
    if len(flags) != len(set(flags)):
        raise FFmpegAttestationError(f"{tool}: repeated configure flags.")
    return flags


def _license(flags: tuple[str, ...], external: dict[str, Any]) -> str:
    enabled = set(flags)
    if "--enable-nonfree" in enabled:
        raise FFmpegAttestationError("nonfree FFmpeg cannot be redistributed.")
    if enabled & {"--disable-programs", "--disable-ffmpeg", "--disable-ffprobe"}:
        raise FFmpegAttestationError("Required FFmpeg program disabled.")
    if {"--enable-gpl", "--disable-gpl"} <= enabled:
        raise FFmpegAttestationError("Contradictory GPL flags.")
    if {"--enable-version3", "--disable-version3"} <= enabled:
        raise FFmpegAttestationError("Contradictory version3 flags.")

    enabled_libs = {flag.removeprefix("--enable-")
                    for flag in enabled if flag.startswith("--enable-lib")}
    if set(external) != enabled_libs:
        raise FFmpegAttestationError(
            f"External library inventory mismatch: "
            f"missing={sorted(enabled_libs - set(external))}, "
            f"extra={sorted(set(external) - enabled_libs)}."
        )
    gpl = "--enable-gpl" in enabled
    version3 = "--enable-version3" in enabled
    for name, item in external.items():
        if not isinstance(item, dict):
            raise FFmpegAttestationError(f"{name}: missing library evidence.")
        family = _text(item.get("license_family"), f"{name}.license_family")
        _text(item.get("version"), f"{name}.version")
        _text(item.get("upstream_revision"), f"{name}.upstream_revision")
        url = _text(item.get("source_url"), f"{name}.source_url")
        if not url.startswith("https://"):
            raise FFmpegAttestationError(f"{name}: HTTPS upstream URL required.")
        if item.get("review_status") != "pending":
            raise FFmpegAttestationError(
                f"{name}: automated tool cannot approve redistribution."
            )
        requires_gpl = name in (_GPL_2_LIBS | _GPL_3_LIBS) or family.startswith("GPL-")
        requires_v3 = name in (_GPL_3_LIBS | _LGPL_3_LIBS) or family.startswith(
            ("GPL-3", "LGPL-3", "Apache-2")
        )
        if requires_gpl and not gpl:
            raise FFmpegAttestationError(f"{name}: --enable-gpl required.")
        if requires_v3 and not version3:
            raise FFmpegAttestationError(f"{name}: --enable-version3 required.")
        if family not in {
            "LGPL-2.1-or-later", "LGPL-3.0-or-later",
            "GPL-2.0-or-later", "GPL-3.0-or-later",
            "MIT", "BSD-3-Clause", "Apache-2.0",
        }:
            raise FFmpegAttestationError(f"{name}: unreviewed license family.")

    return (
        "GPL-3.0-or-later" if version3 else "GPL-2.0-or-later"
    ) if gpl else (
        "LGPL-3.0-or-later" if version3 else "LGPL-2.1-or-later"
    )


def review_ffmpeg_build(manifest: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(manifest, dict) or manifest.get("schema") != 1:
        raise FFmpegAttestationError("FFmpeg build manifest schema 1 required.")
    target = manifest.get("target")
    if target not in _TARGETS:
        raise FFmpegAttestationError("Unsupported Windows/macOS target.")
    version = _text(manifest.get("version"), "version")
    commit = _text(manifest.get("source_revision"), "source_revision").lower()
    if not _COMMIT.fullmatch(commit):
        raise FFmpegAttestationError("FFmpeg source revision must be a full 40-hex commit.")
    source_url = f"https://github.com/FFmpeg/FFmpeg/commit/{commit}"
    if manifest.get("source_url") != source_url:
        raise FFmpegAttestationError("FFmpeg source URL must pin the exact official commit.")
    compiler = _text(manifest.get("toolchain"), "toolchain")
    notice = _file(manifest.get("license_notice"), "license_notice", max_bytes=_MAX_REPORT)
    record = _file(manifest.get("build_record"), "build_record", max_bytes=_MAX_REPORT)
    if b"\x00" in notice.read_bytes() or b"\x00" in record.read_bytes():
        raise FFmpegAttestationError("License/build record must be text.")

    tools = manifest.get("tools")
    if not isinstance(tools, dict) or set(tools) != set(_TOOLS):
        raise FFmpegAttestationError("Both ffmpeg and ffprobe are required.")
    expected = manifest.get("configure_flags")
    if not isinstance(expected, list) or not expected or any(
        not isinstance(x, str) or not x.startswith("--") for x in expected
    ) or len(set(expected)) != len(expected):
        raise FFmpegAttestationError("Unique explicit configure flags are required.")
    external = manifest.get("external_libraries")
    if not isinstance(external, dict):
        raise FFmpegAttestationError("Explicit external library inventory required.")

    checks: dict[str, Any] = {}
    configs = []
    for name in _TOOLS:
        entry = tools[name]
        if not isinstance(entry, dict):
            raise FFmpegAttestationError(f"{name}: missing binary metadata.")
        binary = _file(entry.get("file"), f"{name}.file")
        try:
            _ensure_binary_architecture(binary, target, name)
        except ValueError as exc:
            raise FFmpegAttestationError(str(exc)) from exc
        pinned = _text(entry.get("sha256"), f"{name}.sha256").lower()
        if not _SHA256.fullmatch(pinned) or _digest(binary) != pinned:
            raise FFmpegAttestationError(f"{name}: binary SHA-256 mismatch.")
        report = _file(entry.get("version_report"), f"{name}.version_report", max_bytes=_MAX_REPORT)
        configs.append(_configuration(report, name, version))
        checks[name] = {
            "file_sha256": pinned, "version_report_sha256": _digest(report),
            "filename": binary.name, "binary_architecture_checked": True,
        }
    if set(configs[0]) != set(configs[1]) or set(configs[0]) != set(expected):
        raise FFmpegAttestationError("FFmpeg/ffprobe configuration and manifest disagree.")
    inferred = _license(tuple(expected), external)
    for name in _TOOLS:
        declared = _text(tools[name].get("license"), f"{name}.license")
        if declared != inferred:
            raise FFmpegAttestationError(f"{name}: declared license differs from {inferred}.")

    return {
        "schema": 1, "component": "youtube_runtime.ffmpeg",
        "target": target, "version": version,
        "source_revision": commit, "source_url": source_url,
        "toolchain": compiler, "configure_flags": expected,
        "inferred_license": inferred,
        "external_libraries": external,
        "tools": checks,
        "license_notice_sha256": _digest(notice),
        "build_record_sha256": _digest(record),
        "local_binary_sha256_verified": True,
        "supplied_version_reports_consistent": True,
        "version_reports_cryptographically_bound_to_binaries": False,
        "binary_execution_verified": False,
        "reproducible_rebuild_verified": False,
        "linked_libraries_independently_inspected": False,
        "redistribution_status": "pending",
        "legal_review_status": "pending",
        "approval_required": True,
    }


def write_report(path: Path, result: dict[str, Any]) -> None:
    if path.resolve() == _BUNDLED_CATALOG.resolve():
        raise FFmpegAttestationError("Cannot overwrite the bundled managed catalog.")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as output:
        json.dump(result, output, indent=2, ensure_ascii=False, sort_keys=True)
        output.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check pinned FFmpeg binary/build evidence without executing binaries."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = review_ffmpeg_build(json.loads(args.manifest.read_text(encoding="utf-8")))
        write_report(args.output, report)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.exit(2, f"FFmpeg evidence rejected: {exc}\n")
    print(f"FFmpeg local evidence consistent, redistribution pending: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

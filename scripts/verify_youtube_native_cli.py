"""Verify native startup of already SHA-verified official yt-dlp/Deno assets.

This runs only --version, with absolute paths and an empty PATH, on the
matching Windows/macOS architecture. It does NOT download YouTube content,
verify upstream signatures, approve redistribution or package binaries.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PINS = ROOT / "release/review/youtube-official-source-pins-2026-11-06.json"
_TOOLS = ("yt-dlp", "deno")
_TARGETS = ("windows-x86_64", "macos-aarch64")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _platform_matches(target: str) -> bool:
    system = platform.system().lower()
    machine = platform.machine().lower()
    return (
        (target == "windows-x86_64" and system == "windows" and machine in {"amd64", "x86_64"})
        or (target == "macos-aarch64" and system == "darwin" and machine in {"arm64", "aarch64"})
    )


def _read_evidence(source_dir: Path, target: str) -> tuple[dict, dict, Path]:
    source_file = source_dir / "SOURCE-EVIDENCE.pending.json"
    if source_file.is_symlink() or not source_file.is_file():
        raise ValueError("Verified official source evidence is missing or symlinked.")
    if source_file.stat().st_size > 256 * 1024:
        raise ValueError("Official source evidence exceeds its maximum size.")
    try:
        report = json.loads(source_file.read_text(encoding="utf-8"))
        pins = json.loads(PINS.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Official source evidence or committed pins are unreadable.") from exc
    if (
        not isinstance(report, dict)
        or report.get("schema") != 1
        or report.get("component") != "youtube_runtime"
        or report.get("target") != target
        or report.get("local_bytes_verified") is not True
        or report.get("upstream_signature_verified") is not False
        or report.get("binaries_executed") is not False
        or report.get("redistribution_status") != "pending"
        or report.get("approval_required") is not True
    ):
        raise ValueError("Expected a locally verified, unapproved official source report.")
    if (
        not isinstance(pins, dict)
        or pins.get("schema") != 1
        or pins.get("approval_status") != "pending"
        or not isinstance(pins.get("targets"), dict)
        or not isinstance(pins["targets"].get(target), dict)
        or not isinstance(report.get("inputs"), dict)
    ):
        raise ValueError("Committed official source pins are invalid.")
    expected = pins["targets"][target]
    if set(expected) != set(_TOOLS) or set(report["inputs"]) != set(_TOOLS):
        raise ValueError("Official source evidence must cover yt-dlp and Deno.")
    for name in _TOOLS:
        reviewed = expected[name]
        item = report["inputs"][name]
        if not isinstance(reviewed, dict) or not isinstance(item, dict):
            raise ValueError(f"{name}: source evidence entry is malformed.")
        fields = {
            "repository": "repository", "tag": "tag",
            "asset": "asset", "upstream_url": "url",
            "source_sha256": "sha256", "source_bytes": "bytes",
            "license_review": "license_review",
        }
        if any(item.get(receipt) != reviewed.get(pin) for receipt, pin in fields.items()):
            raise ValueError(f"{name}: official source receipt differs from committed pins.")
    return report, expected, source_file


def verify_native_startup(source_dir: Path, target: str) -> dict:
    if target not in _TARGETS or not _platform_matches(target):
        raise ValueError("Native CLI check must run on the exact target OS/CPU architecture.")
    root = source_dir.resolve()
    if source_dir.is_symlink() or not root.is_dir():
        raise ValueError("Verified source directory must be a regular directory.")
    pending = root / "NATIVE-CLI-EVIDENCE.pending.json"
    if pending.exists() or pending.is_symlink():
        raise FileExistsError("Refusing to replace existing native CLI evidence.")
    report, pins, evidence_file = _read_evidence(root, target)
    suffix = ".exe" if target.startswith("windows-") else ""
    tools = {}
    env = os.environ.copy()
    env["PATH"] = ""
    env["PYTHONNOUSERSITE"] = "1"
    for name in _TOOLS:
        binary = root / (name + suffix)
        expected_sha = report["inputs"][name].get("tool_sha256")
        if binary.is_symlink() or not binary.is_file() or binary.resolve().parent != root:
            raise ValueError(f"{name}: verified official executable is missing or unsafe.")
        if not isinstance(expected_sha, str) or _sha256(binary) != expected_sha:
            raise ValueError(f"{name}: native executable SHA-256 differs from verified extraction.")
        expected_version = str(pins[name]["tag"]).removeprefix("v") if name == "deno" else str(pins[name]["tag"])
        try:
            result = subprocess.run(
                [str(binary.resolve()), "--version"],
                cwd=str(root),
                env=env,
                shell=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"{name}: managed CLI failed to start on the native runner.") from exc
        if result.returncode != 0 or not result.stdout.strip():
            raise RuntimeError(f"{name}: managed CLI failed native --version startup.")
        first = result.stdout.strip().splitlines()[0].strip()
        actual_version = first if name == "yt-dlp" else (
            first.split()[1]
            if len(first.split()) >= 2 and first.split()[0].lower() == "deno"
            else ""
        )
        if actual_version != expected_version:
            raise ValueError(f"{name}: actual native CLI version differs from committed release pin.")
        if _sha256(binary) != expected_sha:
            raise ValueError(f"{name}: executable changed during native CLI startup.")
        tools[name] = {
            "sha256": expected_sha, "version": actual_version,
            "argv": ["--version"], "exit_code": 0,
        }

    evidence = {
        "schema": 1,
        "component": "youtube_runtime",
        "target": target,
        "runner_os": platform.system(),
        "runner_arch": platform.machine(),
        "official_source_evidence_sha256": _sha256(evidence_file),
        "official_pins_sha256": _sha256(PINS),
        "tools": tools,
        "native_cli_startup_verified": True,
        "source_asset_bytes_verified": True,
        "ffmpeg_native_verified": False,
        "youtube_download_verified": False,
        "clean_machine_installer_verified": False,
        "upstream_signature_verified": False,
        "redistribution_status": "pending",
        "approval_required": True,
    }
    with pending.open("x", encoding="utf-8") as output:
        json.dump(evidence, output, ensure_ascii=False, sort_keys=True, indent=2)
        output.write("\n")
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe native yt-dlp/Deno CLI startup, without PATH fallback.")
    parser.add_argument("--target", choices=_TARGETS, required=True)
    parser.add_argument("--source-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = verify_native_startup(args.source_dir, args.target)
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(2, f"Native official YouTube CLI verification rejected: {exc}\n")
    print(json.dumps({
        "target": result["target"],
        "native_cli_startup_verified": result["native_cli_startup_verified"],
        "tool_versions": {name: tool["version"] for name, tool in result["tools"].items()},
        "redistribution_status": "pending",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

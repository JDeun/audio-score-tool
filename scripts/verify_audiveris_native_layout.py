"""Inspect and smoke an extracted official Audiveris MSI/DMG on the native runner.

The MSI administrative image / mounted DMG is NOT an AudioScoreTool managed
component. No binary, source archive or Java runtime is copied into a public
artifact. This proof is limited to verified launcher/JRE layout and -version.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
from pathlib import Path
from typing import Any

from scripts.verify_audiveris_official_installer import (
    DEFAULT_PINS,
    AudiverisReviewError,
    _pin,
    _sha256,
)

_MAX_CAPTURE = 128 * 1024


def _platform_matches(target: str) -> bool:
    machine = platform.machine().lower()
    return (
        (target == "windows-x86_64" and platform.system() == "Windows"
         and machine in {"amd64", "x86_64"})
        or (target == "macos-aarch64" and platform.system() == "Darwin"
            and machine in {"arm64", "aarch64"})
    )


def _verified_path(path: Path, root: Path, label: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise AudiverisReviewError(f"{label}: executable is missing or symlinked.")
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise AudiverisReviewError(f"{label}: executable escapes the reviewed installer image.")
    return resolved


def _find_runtime(root: Path, target: str) -> tuple[Path, Path, Path]:
    if root.is_symlink() or not root.is_dir():
        raise AudiverisReviewError("Mounted/extracted installer root is missing or unsafe.")
    root = root.resolve()
    if target == "windows-x86_64":
        launchers = [
            _verified_path(file, root, "Audiveris launcher")
            for file in root.rglob("Audiveris.exe")
            if file.is_file() and not file.is_symlink()
        ]
        java_candidates = [
            file for file in root.rglob("java.exe")
            if file.parent.name.lower() == "bin"
            and any(part.lower() in {"runtime", "jre", "jdk"} for part in file.parts)
            and file.is_file() and not file.is_symlink()
        ]
        java = (
            _verified_path(java_candidates[0], root, "Bundled Java runtime")
            if len(java_candidates) == 1 else None
        )
    else:
        apps = [
            app for app in root.rglob("Audiveris.app")
            if app.is_dir() and not app.is_symlink()
        ]
        if len(apps) != 1:
            raise AudiverisReviewError("Expected exactly one Audiveris.app in the reviewed macOS DMG.")
        app = apps[0]
        launchers = [_verified_path(app / "Contents/MacOS/Audiveris", root, "Audiveris launcher")]
        java_candidates = [
            candidate for candidate in app.rglob("java")
            if candidate.parent.name == "bin" and "runtime" in candidate.parts
            and candidate.is_file() and not candidate.is_symlink()
        ]
        java = (
            _verified_path(java_candidates[0], root, "Bundled Java runtime")
            if len(java_candidates) == 1 else None
        )
    if len(launchers) != 1 or java is None:
        raise AudiverisReviewError(
            "Official Audiveris installer must contain one native launcher and one embedded JRE."
        )
    release = java.parent.parent / "release"
    if not release.is_file() or release.is_symlink() or not release.resolve().is_relative_to(root):
        raise AudiverisReviewError("Bundled JRE release metadata is missing or unsafe.")
    return launchers[0], java, release


def _native_version(executable: Path, root: Path, label: str) -> str:
    env = os.environ.copy()
    env.update({
        "PATH": "",
        "PYTHONNOUSERSITE": "1",
        "HOME": str(root),
        "USERPROFILE": str(root),
        "APPDATA": str(root),
        "XDG_CONFIG_HOME": str(root),
    })
    try:
        finished = subprocess.run(
            [str(executable), "-version"],
            cwd=str(root), env=env, shell=False,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=90 if label == "audiveris" else 30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AudiverisReviewError(f"{label}: bundled native -version command could not run.") from exc
    if finished.returncode != 0:
        raise AudiverisReviewError(f"{label}: bundled native -version exited unsuccessfully ({finished.returncode}).")
    stdout = finished.stdout + "\n" + finished.stderr
    if not stdout.strip() or len(stdout.encode("utf-8")) > _MAX_CAPTURE:
        raise AudiverisReviewError(f"{label}: native -version output is empty or unbounded.")
    return stdout


def verify_native_layout(
    *,
    target: str,
    installer: Path,
    source_receipt: Path,
    extracted_root: Path,
    destination: Path,
    pin_file: Path = DEFAULT_PINS,
) -> dict[str, Any]:
    if not _platform_matches(target):
        raise AudiverisReviewError("Native installer review must run on its target OS/CPU.")
    pin, record = _pin(pin_file, target)
    receipt = json.loads(source_receipt.read_text(encoding="utf-8"))
    if (
        not isinstance(receipt, dict)
        or receipt.get("schema") != 1
        or receipt.get("component") != "audiveris"
        or receipt.get("target") != target
        or receipt.get("tag") != pin["tag"]
        or receipt.get("asset") != record["asset"]
        or receipt.get("asset_bytes") != record["bytes"]
        or receipt.get("asset_sha256") != record["sha256"]
        or receipt.get("review_pin_sha256") != _sha256(pin_file)
        or receipt.get("original_installer_bytes_verified") is not True
        or receipt.get("redistribution_status") != "pending"
        or receipt.get("native_cli_execution_verified") is not False
    ):
        raise AudiverisReviewError("Audiveris source-byte receipt is missing or inconsistent.")
    if (
        installer.is_symlink() or not installer.is_file()
        or installer.stat().st_size != record["bytes"]
        or _sha256(installer) != record["sha256"]
    ):
        raise AudiverisReviewError("Audiveris source installer has changed since byte verification.")
    if not destination.parent.is_dir() or destination.exists() or destination.is_symlink():
        raise AudiverisReviewError("Native layout report must be a new file in an existing directory.")
    launcher, java, release = _find_runtime(extracted_root, target)
    launcher_sha = _sha256(launcher)
    java_sha = _sha256(java)
    java_info = release.read_text(encoding="utf-8", errors="replace")
    if "JAVA_VERSION=" not in java_info or "MODULES=" not in java_info:
        raise AudiverisReviewError("Bundled JRE release manifest lacks Java version/modules.")
    java_version = _native_version(java, extracted_root, "embedded-jre")
    audiveris_version = _native_version(launcher, extracted_root, "audiveris")
    if re.search(r"(?<![\d.])5\.11\.0(?![\d.])", audiveris_version) is None:
        raise AudiverisReviewError("Audiveris launcher did not report the pinned 5.11.0 release.")
    if "version" not in java_version.lower() and "openjdk" not in java_version.lower():
        raise AudiverisReviewError("Bundled JRE native version output is unrecognized.")
    if _sha256(launcher) != launcher_sha or _sha256(java) != java_sha:
        raise AudiverisReviewError("Audiveris or embedded JRE executable mutated during startup.")
    root = extracted_root.resolve()
    evidence = {
        "schema": 1, "component": "audiveris", "target": target,
        "source_tag": pin["tag"],
        "source_commit": pin["source_commit"],
        "review_pin_sha256": _sha256(pin_file),
        "source_receipt_sha256": _sha256(source_receipt),
        "installer_sha256": record["sha256"],
        "installer_kind": record["archive_kind"],
        "launcher_relative_path": launcher.relative_to(root).as_posix(),
        "launcher_sha256": launcher_sha,
        "jre_relative_path": java.relative_to(root).as_posix(),
        "jre_sha256": java_sha,
        "jre_release_manifest_sha256": _sha256(release),
        "jre_declared_java_version": next(
            (line.split("=", 1)[1].strip('"') for line in java_info.splitlines()
             if line.startswith("JAVA_VERSION=")), "unknown"
        ),
        "embedded_jre_present": True,
        "embedded_java_executed_without_path": True,
        "audiveris_cli_executed_without_path": True,
        "audiveris_version_verified": True,
        "verified_launcher_uses_embedded_java": False,  # not proved by independent child-process tracing
        "portable_managed_zip_verified": False,
        "omr_musicxml_transcription_verified": False,
        "ocr_languages_installed_verified": False,
        "agpl_source_notice_compliance_verified": False,
        "upstream_signature_verified": False,
        "redistribution_status": "pending",
        "legal_review_status": "pending",
        "approval_required": True,
    }
    with destination.open("x", encoding="utf-8") as output:
        json.dump(evidence, output, indent=2, sort_keys=True, ensure_ascii=False)
        output.write("\n")
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description="Native Audiveris MSI/DMG launcher+JRE review.")
    parser.add_argument("--target", choices=("windows-x86_64", "macos-aarch64"), required=True)
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--source-receipt", type=Path, required=True)
    parser.add_argument("--extracted-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = verify_native_layout(
            target=args.target, installer=args.installer,
            source_receipt=args.source_receipt,
            extracted_root=args.extracted_root, destination=args.output,
        )
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(2, f"Audiveris native installer review rejected: {exc}\n")
    print(json.dumps({
        "target": result["target"],
        "embedded_jre_present": result["embedded_jre_present"],
        "audiveris_version_verified": result["audiveris_version_verified"],
        "portable_managed_zip_verified": False,
        "redistribution_status": "pending",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

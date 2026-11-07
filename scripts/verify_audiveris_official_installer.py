"""Review the exact bytes of Audiveris official MSI/DMG release assets, offline.

This does not install software, execute Java, verify a signature, create an
app-managed archive, infer AGPL compliance, or publish an executable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

DEFAULT_PINS = (
    Path(__file__).resolve().parents[1]
    / "release/review/audiveris-official-installer-pins-2026-11-07.json"
)
_TARGETS = {"windows-x86_64", "macos-aarch64"}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_MAX_INSTALLER_BYTES = 256 * 1024 * 1024
_MSI_HEADER = bytes.fromhex("d0cf11e0a1b11ae1")


class AudiverisReviewError(ValueError):
    """Official Audiveris release asset does not match reviewed evidence."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _pin(pin_file: Path, target: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if target not in _TARGETS:
        raise AudiverisReviewError("Unsupported official Audiveris target.")
    if pin_file.is_symlink() or not pin_file.is_file():
        raise AudiverisReviewError("Audiveris review pins are missing or unsafe.")
    try:
        pin = json.loads(pin_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise AudiverisReviewError("Cannot read official Audiveris review pins.") from exc
    if (
        not isinstance(pin, dict)
        or pin.get("schema") != 1
        or pin.get("repository") != "Audiveris/audiveris"
        or pin.get("tag") != "5.11.0"
        or not isinstance(pin.get("source_commit"), str)
        or _COMMIT.fullmatch(pin["source_commit"]) is None
        or pin.get("source_url") != (
            f"https://github.com/Audiveris/audiveris/commit/{pin['source_commit']}"
        )
        or pin.get("license_family") != "AGPL-3.0"
        or pin.get("redistribution_status") != "pending"
        or pin.get("legal_review_status") != "pending"
        or pin.get("commercial_redistribution_approved") is not False
        or pin.get("portable_managed_archive_available") is not False
        or pin.get("java_runtime_verified") is not False
        or pin.get("packaged_omr_recognition_verified") is not False
        or not isinstance(pin.get("sources"), dict)
        or set(pin["sources"]) != _TARGETS
    ):
        raise AudiverisReviewError("Audiveris source/release/legal status pin is not an unapproved official review.")
    item = pin["sources"][target]
    if not isinstance(item, dict):
        raise AudiverisReviewError("Audiveris target pin is malformed.")
    ext = "msi" if target == "windows-x86_64" else "dmg"
    name = (
        f"Audiveris-5.11.0-windowsConsole-x86_64.{ext}"
        if target == "windows-x86_64"
        else f"Audiveris-5.11.0-macosx-arm64.{ext}"
    )
    size = item.get("bytes")
    sha = item.get("sha256")
    if (
        item.get("asset") != name
        or item.get("url") != f"https://github.com/Audiveris/audiveris/releases/download/5.11.0/{name}"
        or item.get("archive_kind") != ext
        or item.get("runner") != ("windows-2025" if ext == "msi" else "macos-15")
        or item.get("expected_launcher") != ("Audiveris.exe" if ext == "msi" else "Audiveris")
        or item.get("expected_jre_binary") != ("java.exe" if ext == "msi" else "java")
        or type(size) is not int
        or size <= 512
        or size > _MAX_INSTALLER_BYTES
        or not isinstance(sha, str)
        or _SHA256.fullmatch(sha) is None
    ):
        raise AudiverisReviewError("Audiveris asset name, source URL, binary layout or pinned size/SHA is invalid.")
    return pin, item


def _assert_container_signature(path: Path, target: str) -> None:
    with path.open("rb") as source:
        if target == "windows-x86_64":
            if source.read(len(_MSI_HEADER)) != _MSI_HEADER:
                raise AudiverisReviewError("Windows installer is not an MSI OLE compound document.")
        else:
            source.seek(-512, 2)
            # Apple UDIF disk images store their koly trailer in the last 512 bytes.
            if source.read(4) != b"koly":
                raise AudiverisReviewError("macOS installer lacks a valid UDIF/DMG koly trailer.")


def verify_official_installer(
    installer: Path,
    target: str,
    *,
    pin_file: Path = DEFAULT_PINS,
    output: Path,
) -> dict[str, Any]:
    pin, record = _pin(pin_file, target)
    if (
        not installer.is_absolute()
        or installer.is_symlink()
        or not installer.is_file()
        or installer.name != record["asset"]
    ):
        raise AudiverisReviewError("Official installer must be the exact absolute, non-symlinked asset.")
    if not output.parent.is_dir() or output.exists() or output.is_symlink():
        raise AudiverisReviewError("Pending evidence must be a new file under an existing directory.")
    size = installer.stat().st_size
    if size != record["bytes"]:
        raise AudiverisReviewError("Official Audiveris installer size differs from the release pin.")
    _assert_container_signature(installer, target)
    actual = _sha256(installer)
    if actual != record["sha256"]:
        raise AudiverisReviewError("Official Audiveris installer SHA-256 differs from the release pin.")
    evidence = {
        "schema": 1,
        "component": "audiveris",
        "target": target,
        "tag": pin["tag"],
        "source_commit": pin["source_commit"],
        "source_url": pin["source_url"],
        "asset": record["asset"],
        "upstream_asset_url": record["url"],
        "archive_kind": record["archive_kind"],
        "asset_sha256": actual,
        "asset_bytes": size,
        "review_pin_sha256": _sha256(pin_file),
        "original_installer_bytes_verified": True,
        "installer_container_magic_verified": True,
        "embedded_jre_verified": False,
        "native_cli_execution_verified": False,
        "managed_portable_zip_verified": False,
        "ocr_languages_verified": False,
        "agpl_source_notice_compliance_verified": False,
        "upstream_signature_verified": False,
        "redistribution_status": "pending",
        "legal_review_status": "pending",
        "approval_required": True,
    }
    with output.open("x", encoding="utf-8") as target_file:
        json.dump(evidence, target_file, ensure_ascii=False, indent=2, sort_keys=True)
        target_file.write("\n")
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline review of official Audiveris MSI/DMG bytes.")
    parser.add_argument("--installer", required=True, type=Path)
    parser.add_argument("--target", required=True, choices=sorted(_TARGETS))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--pins", default=DEFAULT_PINS, type=Path)
    args = parser.parse_args()
    try:
        result = verify_official_installer(
            args.installer, args.target, pin_file=args.pins, output=args.output,
        )
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Audiveris official installer review rejected: {exc}\n")
    print(json.dumps({
        "target": result["target"],
        "asset_sha256": result["asset_sha256"],
        "original_installer_bytes_verified": True,
        "redistribution_status": "pending",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Build a pending, locally verified Audiveris/JRE managed ZIP from MSI/DMG.

Only verified official source assets AND a successful native launcher/JRE
review receipt may be used. Archive remains on a disposable CI runner; only
pending JSON may be uploaded. Never changes bundled catalog or approves AGPL.

The archive is deliberately symlink-free because managed_components' safe ZIP
extractor rejects symlinks. If upstream's app image requires links, fail
closed rather than silently flatten a signed macOS framework image.
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
from scripts.verify_audiveris_native_layout import (
    _find_runtime,
    _native_version,
    _platform_matches,
)
from scripts.verify_audiveris_official_installer import (
    DEFAULT_PINS,
    AudiverisReviewError,
    _pin,
    _sha256,
)

_VERSION = "5.11.0-review-1"
_MAX_FILES = 4090  # reserve ZIP slots for provenance
_MAX_UNCOMPRESSED = 4 * 1024**3
_MAX_READ_JSON = 1024 * 1024
_MAX_NOTICE = 8 * 1024 * 1024


def _receipt(path: Path, name: str) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_READ_JSON:
        raise AudiverisReviewError(f"{name}: trusted pending receipt must be a regular bounded file.")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise AudiverisReviewError(f"{name}: pending receipt cannot be decoded.") from exc
    if not isinstance(value, dict):
        raise AudiverisReviewError(f"{name}: pending receipt must be an object.")
    return value


def _validated_origin(
    *,
    target: str,
    installer: Path,
    source_receipt: Path,
    native_receipt: Path,
    extracted_root: Path,
    pin_file: Path,
) -> dict[str, Any]:
    if not _platform_matches(target):
        raise AudiverisReviewError("Portable candidate review must run on its native OS/CPU.")
    pin, record = _pin(pin_file, target)
    src = _receipt(source_receipt, "Audiveris source")
    native = _receipt(native_receipt, "Audiveris native")
    if not installer.is_absolute() or installer.is_symlink() or not installer.is_file():
        raise AudiverisReviewError("Pinned Audiveris installer must be an absolute regular file.")
    if installer.name != record["asset"] or installer.stat().st_size != record["bytes"]:
        raise AudiverisReviewError("Pinned Audiveris installer name/size differs from official release.")
    if _sha256(installer) != record["sha256"]:
        raise AudiverisReviewError("Pinned Audiveris installer SHA-256 differs from official release.")

    if any([
        src.get("schema") != 1,
        src.get("component") != "audiveris",
        src.get("target") != target,
        src.get("tag") != pin["tag"],
        src.get("source_commit") != pin["source_commit"],
        src.get("asset") != record["asset"],
        src.get("asset_sha256") != record["sha256"],
        src.get("asset_bytes") != record["bytes"],
        src.get("review_pin_sha256") != _sha256(pin_file),
        src.get("original_installer_bytes_verified") is not True,
        src.get("redistribution_status") != "pending",
        src.get("managed_portable_zip_verified") is not False,
        native.get("schema") != 1,
        native.get("component") != "audiveris",
        native.get("target") != target,
        native.get("source_tag") != pin["tag"],
        native.get("source_commit") != pin["source_commit"],
        native.get("installer_sha256") != record["sha256"],
        native.get("review_pin_sha256") != _sha256(pin_file),
        native.get("source_receipt_sha256") != _sha256(source_receipt),
        native.get("embedded_jre_present") is not True,
        native.get("embedded_java_executed_without_path") is not True,
        native.get("audiveris_cli_executed_without_path") is not True,
        native.get("audiveris_version_verified") is not True,
        native.get("portable_managed_zip_verified") is not False,
        native.get("omr_musicxml_transcription_verified") is not False,
        native.get("redistribution_status") != "pending",
        native.get("approval_required") is not True,
    ]):
        raise AudiverisReviewError("Audiveris official/native receipt differs from reviewed source or falsely approves distribution.")

    if extracted_root.is_symlink() or not extracted_root.is_dir():
        raise AudiverisReviewError("Extracted official Audiveris application root is unsafe.")
    root = extracted_root.resolve()
    launcher, java, release = _find_runtime(root, target)
    if any([
        launcher.relative_to(root).as_posix() != native.get("launcher_relative_path"),
        java.relative_to(root).as_posix() != native.get("jre_relative_path"),
        _sha256(launcher) != native.get("launcher_sha256"),
        _sha256(java) != native.get("jre_sha256"),
        _sha256(release) != native.get("jre_release_manifest_sha256"),
    ]):
        raise AudiverisReviewError("Audiveris launcher, embedded JRE or release manifest drifted since native validation.")
    if target == "windows-x86_64":
        source_image = launcher.parent
        if source_image.name != "Audiveris":
            raise AudiverisReviewError("Unexpected Windows Audiveris MSI administrative image layout.")
    else:
        source_image = launcher.parents[2]
        if source_image.name != "Audiveris.app":
            raise AudiverisReviewError("Unexpected macOS Audiveris application bundle layout.")
    if not java.is_relative_to(source_image) or not release.is_relative_to(source_image):
        raise AudiverisReviewError("Audiveris launcher/JRE are not in the same app-owned tree.")
    return {
        "source_image": source_image,
        "launcher": launcher,
        "java": java,
        "source_receipt_sha256": _sha256(source_receipt),
        "native_receipt_sha256": _sha256(native_receipt),
        "pins_sha256": _sha256(pin_file),
        "pin": pin,
        "record": record,
        "native": native,
    }


def _tree_files(root: Path) -> list[tuple[Path, str, int, bool]]:
    """Inventory a full app image without following unsafe links or devices.

    Some Apple jpackage images have *file* symlinks for internal license
    notices. Resolve only internal regular-file links, then copy their bytes
    as ordinary ZIP members (the production installer forbids links).
    Never traverse a directory symlink or read any link outside the app.
    """
    files: list[tuple[Path, str, int, bool]] = []
    total = 0
    canonical = root.resolve()
    for directory, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        base = Path(directory)
        for dirname in sorted(dirnames):
            path = base / dirname
            mode = path.lstat().st_mode
            if not stat.S_ISDIR(mode) or path.is_symlink():
                raise AudiverisReviewError(
                    f"Audiveris image contains an unsupported directory link/type: {path.name}"
                )
        for filename in sorted(filenames):
            path = base / filename
            was_link = path.is_symlink()
            source = path
            if was_link:
                try:
                    source = path.resolve(strict=True)
                except (OSError, RuntimeError) as exc:
                    raise AudiverisReviewError(
                        f"Audiveris image contains a missing/looped file symlink: {path.name}"
                    ) from exc
                if (
                    not source.is_relative_to(canonical)
                    or source.is_symlink()
                    or not source.is_file()
                ):
                    raise AudiverisReviewError(
                        f"Audiveris image contains an external/non-regular file symlink: {path.name}"
                    )
            info = source.lstat()
            if not stat.S_ISREG(info.st_mode):
                raise AudiverisReviewError(
                    f"Audiveris image contains an unsupported file link/type: {path.name}"
                )
            rel = path.relative_to(root.parent).as_posix()
            if any(part in {"", ".", ".."} for part in path.relative_to(root.parent).parts):
                raise AudiverisReviewError("Audiveris candidate member path is unsafe.")
            if "\n" in rel or "\r" in rel or "\\" in rel:
                raise AudiverisReviewError("Audiveris candidate member name contains unsafe characters.")
            total += info.st_size
            if total > _MAX_UNCOMPRESSED or len(files) + 4 > _MAX_FILES:
                raise AudiverisReviewError("Audiveris image exceeds managed ZIP member or expanded size limits.")
            files.append((source, rel, info.st_mode, was_link))
    if not files:
        raise AudiverisReviewError("Audiveris application image is empty.")
    files.sort(key=lambda row: row[1])
    return files


def _write_file(zipped: zipfile.ZipFile, name: str, path: Path, *, mode: int) -> str:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | (0o755 if mode & stat.S_IXUSR else 0o644)) << 16
    # Stored bytes avoid app image resources inflating a compression bomb or
    # a false positive on installer's strict per-entry compression ratio cap.
    info.compress_type = zipfile.ZIP_STORED
    digest = hashlib.sha256()
    with path.open("rb") as source, zipped.open(info, "w") as dest:
        while data := source.read(1024 * 1024):
            digest.update(data)
            dest.write(data)
    return digest.hexdigest()


def _write_evidence(zipped: zipfile.ZipFile, name: str, value: dict) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    info.compress_type = zipfile.ZIP_STORED
    zipped.writestr(info, json.dumps(value, sort_keys=True, indent=2) + "\n")


def assemble_portable_candidate(
    *,
    target: str,
    installer: Path,
    source_receipt: Path,
    native_receipt: Path,
    extracted_root: Path,
    destination: Path,
    pin_file: Path = DEFAULT_PINS,
) -> dict[str, Any]:
    if destination.suffix.lower() != ".zip" or not destination.parent.is_dir():
        raise AudiverisReviewError("Portable candidate output must be a ZIP in an existing directory.")
    pending_path = destination.with_name(destination.name + ".pending.json")
    if destination.exists() or destination.is_symlink() or pending_path.exists() or pending_path.is_symlink():
        raise FileExistsError("Portable candidate ZIP or pending report already exists.")
    origin = _validated_origin(
        target=target, installer=installer,
        source_receipt=source_receipt, native_receipt=native_receipt,
        extracted_root=extracted_root, pin_file=pin_file,
    )
    files = _tree_files(origin["source_image"])
    relative_tool = origin["launcher"].relative_to(origin["source_image"].parent).as_posix()
    relative_java = origin["java"].relative_to(origin["source_image"].parent).as_posix()
    tmp_archive = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".audiveris-review-", suffix=".zip.tmp",
            dir=destination.parent, delete=False,
        ) as output:
            tmp_archive = Path(output.name)
        members: dict[str, str] = {}
        with zipfile.ZipFile(tmp_archive, "w", allowZip64=True) as bundle:
            for path, rel, mode, _was_link in files:
                members[rel] = _write_file(bundle, rel, path, mode=mode)
            # Same provenance as the original MSI/DMG, not a synthetic legal approval.
            _write_evidence(bundle, "provenance/SOURCE-EVIDENCE.pending.json", _receipt(source_receipt, "source"))
            _write_evidence(bundle, "provenance/NATIVE-EVIDENCE.pending.json", _receipt(native_receipt, "native"))
            _write_evidence(bundle, "BUNDLE-INVENTORY.pending.json", {
                "schema": 1, "target": target, "component": "audiveris",
                "version": _VERSION, "member_sha256": members,
                "tool": {"audiveris": relative_tool},
                "embedded_java_path": relative_java,
                "redistribution_status": "pending",
                "approval_required": True,
            })
        archive_digest = _sha256(tmp_archive)
        # ZIP is now installed using the EXACT product installation code,
        # not an ad-hoc extractor (no catalog update/remote publication).
        artifact = ComponentArtifact(
            component="audiveris", version=_VERSION,
            url="https://example.invalid/unpublished-local-review-only",
            sha256=archive_digest, archive="zip",
            tools={"audiveris": relative_tool},
            max_download_bytes=1024**3,
            max_uncompressed_bytes=_MAX_UNCOMPRESSED,
            license="AGPL-3.0",
            provenance="Audiveris 5.11.0 exact official MSI/DMG and bundled jlink JRE (unapproved)",
        )
        with tempfile.TemporaryDirectory(prefix="ast-audiveris-managed-review-") as temp:
            root = Path(temp)
            installed = install_component_artifact(
                artifact, root=root, local_archive=tmp_archive,
            )
            if installed.get("ready") is not True or installed.get("integrity") != "verified":
                raise AudiverisReviewError("Managed installer did not accept the local Audiveris ZIP.")
            # Normalize NTFS 8.3 RUNNER~1 versus long-profile path aliases
            # before deriving paths from separately resolved native binaries.
            installed_root = (root / "installed" / "audiveris" / _VERSION).resolve()
            launcher, java, release = _find_runtime(installed_root, target)
            if any([
                launcher.relative_to(installed_root).as_posix() != relative_tool,
                java.relative_to(installed_root).as_posix() != relative_java,
                _sha256(launcher) != origin["native"]["launcher_sha256"],
                _sha256(java) != origin["native"]["jre_sha256"],
                _sha256(release) != origin["native"]["jre_release_manifest_sha256"],
            ]):
                raise AudiverisReviewError("Managed ZIP changed the verified Audiveris/JRE runtime files.")
            java_version = _native_version(java, installed_root, "embedded-jre")
            launcher_version = _native_version(launcher, installed_root, "audiveris")
            if "version" not in java_version.lower() and "openjdk" not in java_version.lower():
                raise AudiverisReviewError("Relocated embedded Java version output is invalid.")
            if re.search(r"(?<![\d.])5\.11\.0(?![\d.])", launcher_version) is None:
                raise AudiverisReviewError("Relocated Audiveris executable did not report 5.11.0.")
        # Finalize only after successful byte verification AND relocated execution.
        report = {
            "schema": 1,
            "component": "audiveris", "target": target, "version": _VERSION,
            "source_asset_sha256": origin["record"]["sha256"],
            "source_commit": origin["pin"]["source_commit"],
            "source_receipt_sha256": origin["source_receipt_sha256"],
            "native_receipt_sha256": origin["native_receipt_sha256"],
            "review_pin_sha256": origin["pins_sha256"],
            "archive_sha256": archive_digest,
            "tool_path": relative_tool,
            "embedded_jre_path": relative_java,
            "launcher_sha256": origin["native"]["launcher_sha256"],
            "java_sha256": origin["native"]["jre_sha256"],
            "member_count": len(files),
            "internal_file_symlinks_materialized": sum(1 for row in files if row[3]),
            "external_symlinks_followed": False,
            "archive_members_sha256": hashlib.sha256(
                json.dumps(members, sort_keys=True).encode("utf-8")
            ).hexdigest(),
            "local_managed_zip_install_verified": True,
            "relocated_audiveris_version_verified": True,
            "relocated_embedded_jre_version_verified": True,
            "full_omr_to_musicxml_verified": False,
            "verified_launcher_uses_embedded_java": False,
            "macos_codesign_notarization_verified": False,
            "third_party_source_notices_approved": False,
            "redistribution_status": "pending",
            "legal_review_status": "pending",
            "remote_artifact_published": False,
            "clean_machine_verified": False,
            "approval_required": True,
        }
        with pending_path.open("x", encoding="utf-8") as output:
            json.dump(report, output, ensure_ascii=False, sort_keys=True, indent=2)
            output.write("\n")
        try:
            os.link(tmp_archive, destination)
        except Exception:
            pending_path.unlink(missing_ok=True)
            raise
        return report
    finally:
        if tmp_archive is not None:
            tmp_archive.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Repackage official Audiveris into an unapproved local managed ZIP for runtime QA.")
    parser.add_argument("--target", choices=["windows-x86_64", "macos-aarch64"], required=True)
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--source-receipt", type=Path, required=True)
    parser.add_argument("--native-receipt", type=Path, required=True)
    parser.add_argument("--extracted-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = assemble_portable_candidate(
            target=args.target, installer=args.installer,
            source_receipt=args.source_receipt, native_receipt=args.native_receipt,
            extracted_root=args.extracted_root, destination=args.output,
        )
    except (OSError, ValueError, ComponentError) as exc:
        parser.exit(2, f"Portable Audiveris candidate rejected: {exc}\n")
    print(json.dumps({
        "target": result["target"],
        "local_managed_zip_install_verified": True,
        "relocated_audiveris_version_verified": True,
        "redistribution_status": "pending",
        "remote_artifact_published": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

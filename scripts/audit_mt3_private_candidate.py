"""Offline audit of a PRIVATE native MR-MT3 release-candidate ZIP.

This verifies byte identity against the *same local* frozen-runtime QA receipt,
not a legal license, signed attestation, complete SBOM, or release approval.
Never loads the PyTorch checkpoint, extracts executable files, accesses the
network, publishes artifacts, or edits production catalog/approval JSON.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO

from scripts import verify_mt3_frozen_native as native

_ROOT = Path(__file__).resolve().parents[1]
_SHA256 = re.compile(r"[a-f0-9]{64}\Z")
_MAX_META = 64 * 1024
_BLOCKERS = (
    "independent-model-commercial-and-redistribution-rights-review",
    "exact-upstream-checkpoint-revision-and-source-provenance-review",
    "complete-frozen-binary-transitive-dependency-sbom-and-license-notices",
    "corresponding-source-and-notice-hosting-review",
    "reviewed-public-https-artifact-and-independent-approval-receipt",
    "clean-machine-desktop-install-update-and-uninstall-acceptance",
    "tier2-commercial-quality-baseline-approval",
    "signed-notarized-updater-release-acceptance",
)


class PrivateCandidateAuditError(ValueError):
    """A private artifact, pinned model or its native QA receipt is inconsistent."""


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise PrivateCandidateAuditError(message)


def _valid_sha(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _sha256_file(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def _sha256_member(source: BinaryIO) -> str:
    digest = hashlib.sha256()
    for block in iter(lambda: source.read(1024 * 1024), b""):
        digest.update(block)
    return digest.hexdigest()


def _validate_native_receipt(proof: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    _expect(proof.get("schema") == 1, "Native QA receipt schema is unsupported")
    target = proof.get("target")
    _expect(target in native._TARGETS, "Native QA receipt target is unsupported")
    _expect(proof.get("model_adapter") == "mr_mt3", "Native QA receipt must use MR-MT3")
    _expect(proof.get("packages") == native._EXPECTED, "Native QA builder pins do not match")
    for key in (
        "whole_payload_sha256_verified", "managed_installer_verified",
        "registered_executable_verified", "native_host_python_not_required_for_startup",
        "actual_model_inference_verified", "model_checkpoint_included",
        "private_candidate_staged_locally",
    ):
        _expect(proof.get(key) is True, f"Native QA has not verified {key}")
    for key in (
        "windows_macos_clean_machine_verified", "model_license_approved",
        "runtime_redistribution_approved", "binaries_uploaded",
    ):
        _expect(proof.get(key) is False, f"Native QA receipt must retain {key}=false")
    _expect(proof.get("redistribution_status") == "pending", "Native QA must remain pending")
    _expect(_valid_sha(proof.get("native_executable_sha256")), "Native executable SHA-256 is missing")
    _expect(_valid_sha(proof.get("private_archive_sha256")), "Native initial archive hash is missing")
    _expect(
        proof.get("private_candidate_filename")
        == f"MT3-MRMT3-{target}-UNAPPROVED.zip",
        "Native receipt's staged filename does not match its platform",
    )

    real = proof.get("real_native_inference")
    _expect(isinstance(real, dict), "Native QA real-model inference receipt is missing")
    _expect(real.get("model") == "mr_mt3", "Native model ID must be mr_mt3")
    for key in (
        "actual_model_weights_verified", "managed_archive_and_full_payload_verified",
        "registered_native_frozen_executable_verified", "actual_cpu_model_inference_verified",
        "product_midi_to_musicxml_verified",
        "no_ambient_python_or_path_required_by_frozen_cli",
    ):
        _expect(real.get(key) is True, f"Real native inference has not verified {key}")
    for key in (
        "model_redistribution_approved", "model_weights_published", "clean_machine_install_verified",
    ):
        _expect(real.get(key) is False, f"Real inference receipt must retain {key}=false")
    _expect(real.get("redistribution_status") == "pending", "Real inference must remain pending")
    _expect(real.get("checkpoint_sha256") == native._MR_MT3_SHA256, "Model weight SHA-256 is not pinned")
    _expect(real.get("checkpoint_source") == native._MR_MT3_SOURCE, "Checkpoint source has drifted")
    _expect(
        real.get("frozen_executable_sha256") == proof["native_executable_sha256"],
        "Real inference executable differs from native CLI QA",
    )
    _expect(_valid_sha(real.get("private_real_archive_sha256")), "Real archive SHA-256 is missing")
    byte_count = real.get("private_real_archive_bytes")
    _expect(type(byte_count) is int and 0 < byte_count <= native._MAX_ARCHIVE,
            "Real archive byte size is invalid")
    notes = real.get("note_counts")
    _expect(isinstance(notes, dict), "Real inference note counts are missing")
    for key in ("midi_notes", "notes", "parts"):
        value = notes.get(key)
        _expect(type(value) is int and value > 0, f"Real inference {key} must be positive")
    for key in ("audio_sha256", "midi_sha256", "musicxml_sha256"):
        _expect(_valid_sha(real.get(key)), f"Real inference {key} is missing")
    return target, real


def audit_private_candidate(archive: Path, proof: dict[str, Any]) -> dict[str, Any]:
    """Bind a private, unapproved native ZIP to the actual-model QA receipt.

    Every member is hashed by streaming: never extract or deserialize the
    third-party pickle, and reject unexpected members/symlinks/compression.
    Neither a ZIP nor a JSON receipt can independently prove a license grant.
    """
    _expect(isinstance(proof, dict), "Native QA receipt must be an object")
    target, real = _validate_native_receipt(proof)
    _expect(archive.is_file() and not archive.is_symlink(),
            "A regular, non-symlink private ZIP is required")
    _expect(archive.name == proof["private_candidate_filename"],
            "Private archive filename does not match the native QA receipt")
    size = archive.stat().st_size
    _expect(size == real["private_real_archive_bytes"], "Private archive size drifted")
    _expect(size <= native._MAX_ARCHIVE, "Private archive is too large")
    archive_sha = _sha256_file(archive)
    _expect(archive_sha == real["private_real_archive_sha256"],
            "Private archive bytes differ from native real inference QA")

    executable = f"bin/mt3-infer{'.exe' if target.startswith('windows-') else ''}"
    members = {
        executable,
        "checkpoints/mr_mt3/mt3.pth",
        "provenance/frozen-native-qa.pending.json",
    }
    sha_by_path: dict[str, str] = {}
    sizes: dict[str, int] = {}
    try:
        with zipfile.ZipFile(archive, "r") as bundle:
            actual = bundle.infolist()
            _expect(len(actual) == 3 and {entry.filename for entry in actual} == members,
                    "Private ZIP must contain exactly the reviewed CLI, weight and pending manifest")
            for info in actual:
                _expect(not info.is_dir() and not (info.flag_bits & 1),
                        "Private ZIP cannot contain directories or encrypted members")
                _expect(info.compress_type == zipfile.ZIP_STORED,
                        "Private ZIP must use the original uncompressed archive layout")
                mode = info.external_attr >> 16
                _expect(info.create_system == 3 and stat.S_IFMT(mode) == stat.S_IFREG,
                        "Private ZIP may only contain regular, non-linked files")
                if info.filename == "provenance/frozen-native-qa.pending.json":
                    _expect(0 < info.file_size <= _MAX_META, "Private manifest is too large")
                elif info.filename == "checkpoints/mr_mt3/mt3.pth":
                    _expect(1024 * 1024 <= info.file_size <= 1024**3,
                            "Private model checkpoint size is implausible")
                else:
                    _expect(1024 * 1024 <= info.file_size <= native._MAX_ARCHIVE // 2,
                            "Private frozen executable size is implausible")
                sizes[info.filename] = info.file_size
                with bundle.open(info, "r") as stream:
                    sha_by_path[info.filename] = _sha256_member(stream)
            manifest_data = bundle.read("provenance/frozen-native-qa.pending.json")
    except (OSError, EOFError, RuntimeError, zipfile.BadZipFile) as exc:
        raise PrivateCandidateAuditError("Private candidate ZIP cannot be verified") from exc

    _expect(sha_by_path[executable] == proof["native_executable_sha256"],
            "Private frozen executable differs from tested native executable")
    _expect(sha_by_path["checkpoints/mr_mt3/mt3.pth"] == native._MR_MT3_SHA256,
            "Private model checkpoint differs from SHA-pinned real inference")
    try:
        manifest = json.loads(manifest_data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PrivateCandidateAuditError("Private provenance manifest is not valid JSON") from exc
    _expect(isinstance(manifest, dict) and manifest.get("schema") == 1,
            "Private provenance manifest schema is invalid")
    for name, value in {
        "target": target,
        "component": "transcription_engine",
        "model_adapter": "mr_mt3",
        "build_method": "PyInstaller onefile native QA",
        "mt3_wrapper_sha256": proof["native_executable_sha256"],
        "upstream": "https://github.com/openmirlab/mt3-infer/tree/v0.2.0",
        "model_weights_included": True,
        "checkpoint_sha256": native._MR_MT3_SHA256,
        "checkpoint_source": native._MR_MT3_SOURCE,
        "checkpoint_license_review": "pending",
        "redistribution_status": "pending",
        "approval_required": True,
    }.items():
        _expect(type(manifest.get(name)) is type(value) and manifest.get(name) == value,
                f"Private manifest {name} does not match the approved-for-QA identity")
    _expect(manifest.get("packages") == native._EXPECTED,
            "Private manifest builder package versions do not match QA receipt")

    return {
        "schema_version": "1",
        "purpose": "private-native-mr-mt3-release-review",
        "component": "transcription_engine",
        "model": "mr_mt3",
        "target": target,
        "private_candidate_filename": archive.name,
        "archive_sha256": archive_sha,
        "archive_bytes": size,
        "member_sha256": dict(sorted(sha_by_path.items())),
        "member_bytes": dict(sorted(sizes.items())),
        "tool_sha256": {"mt3-infer": sha_by_path[executable]},
        "model_checkpoint_sha256": native._MR_MT3_SHA256,
        "provenance_manifest_sha256": sha_by_path["provenance/frozen-native-qa.pending.json"],
        "builder_package_versions": dict(sorted(native._EXPECTED.items())),
        "builder_packages_are_complete_frozen_sbom": False,
        "native_qa_receipt_canonical_sha256": hashlib.sha256(
            json.dumps(proof, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "verified_native_inference_counts": dict(real["note_counts"]),
        "local_bytes_match_native_qa": True,
        "checkpoint_not_deserialized_by_audit": True,
        "remote_artifact_verified": False,
        "license_independently_approved": False,
        "clean_machine_verified": False,
        "redistribution_status": "pending",
        "approval_required": True,
        "publication_ready": False,
        "release_blockers": list(_BLOCKERS),
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def write_pending_audit(report: dict[str, Any], output: Path) -> None:
    """Write metadata only, owner-readable, with no-clobber outside the repo."""
    parent = output.expanduser().absolute().parent
    _expect(parent.is_dir() and not parent.is_symlink(),
            "An existing private output directory is required")
    resolved = parent.resolve()
    _expect(not resolved.is_relative_to(_ROOT.resolve()),
            "Private audit output must stay outside the Git checkout")
    _expect(not output.is_symlink() and not output.exists(),
            "Refusing to overwrite an existing audit file")
    # O_EXCL prevents a race with an existing file or symlink. The audit is
    # metadata-only, never the model or the executable.
    fd = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(report, handle, sort_keys=True, ensure_ascii=False, indent=2)
            handle.write("\n")
    except BaseException:
        Path(output).unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Offline PRIVATE MR-MT3 ZIP/QA proof audit; never grants release approval."
    )
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--native-proof", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        _expect(args.native_proof.is_file() and not args.native_proof.is_symlink(),
                "Native QA receipt must be a regular file")
        _expect(args.native_proof.stat().st_size <= 128 * 1024,
                "Native QA receipt file is unexpectedly large")
        proof = json.loads(args.native_proof.read_text(encoding="utf-8"))
        result = audit_private_candidate(args.archive, proof)
        write_pending_audit(result, args.output)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        parser.exit(2, f"Private native candidate audit rejected: {exc}\n")
    print(json.dumps({
        "target": result["target"], "local_bytes_match_native_qa": True,
        "release_blockers": len(result["release_blockers"]),
        "redistribution_status": "pending", "publication_ready": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Summarize real native MT3 frozen-run QA receipts into a license review queue.

Accept only successful, SHA-bound, still-unapproved Windows/macOS model QA
metadata. Distinguish PyInstaller CArchive 'b' typecode entries (which include
ordinary .py source/data on Windows) from recognizable native shared-library
filenames. The latter are *review candidates*, not an audited dependency
closure, source/owner assignment, license grant, or complete SBOM.

No model, executable, archive extraction, subprocess, or network access.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.collect_mt3_frozen_inventory import _canonical_sha, _safe_archive_name

_TARGETS = ("windows-x86_64", "macos-aarch64")
_HASH = re.compile(r"[a-f0-9]{64}\Z")
_NAMED_LIBRARY = re.compile(
    r"(?:\.dll|\.pyd|\.dylib|\.exe|\.bundle|\.so(?:\.\d+)*)$", re.IGNORECASE,
)
_WEIGHT_SHA = "b8a3807ed265059abd25ad7f68142c06c35e8f6144dcaa45bd55946a3745398f"
_MAX_PROOF_BYTES = 8 * 1024 * 1024


class MT3LicenseTriageError(ValueError):
    """An input receipt or derived release-review metric is not trustworthy."""


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise MT3LicenseTriageError(reason)


def _is_sha(value: object) -> bool:
    return isinstance(value, str) and _HASH.fullmatch(value) is not None


def _candidate_native_library(name: str) -> bool:
    """Filename-only conservative review category, not binary format detection."""
    return bool(
        _NAMED_LIBRARY.search(name)
        or ".framework/" in name.lower()
        or name.lower().endswith(".framework")
    )


def _scope(name: str) -> str:
    """Source-owner *hint* only; never attribute a license based on a path."""
    parts = name.split("/")
    if len(parts) == 1:
        return "(top-level)"
    if parts[0].lower() in {"torch", "numpy", "scipy", "torchaudio", "torchvision"}:
        if len(parts) >= 3 and parts[1].lower() in {"lib", "libs"}:
            return "/".join(parts[:2])
    if parts[0].lower().endswith(".libs"):
        return parts[0]
    if parts[0] == "Python.framework":
        return "Python.framework"
    return parts[0]


def _builder_distributions(data: dict[str, Any]) -> list[dict[str, Any]]:
    distributions = data.get("distributions")
    _require(isinstance(distributions, list) and 0 < len(distributions) <= 3000,
             "Builder distribution metadata is missing")
    _require(data.get("distribution_count") == len(distributions),
             "Builder distribution count differs from listed packages")
    _require(
        data.get("coverage_scope")
        == "builder_environment_not_bundled_runtime_dependency_closure",
        "Builder packages were incorrectly represented as shipped dependency closure",
    )
    normalized = set()
    for entry in distributions:
        _require(isinstance(entry, dict), "Builder package has invalid shape")
        name, version = entry.get("name"), entry.get("version")
        _require(
            isinstance(name, str) and 0 < len(name) <= 200
            and isinstance(version, str) and 0 < len(version) <= 100,
            "Builder package name/version is invalid",
        )
        key = re.sub(r"[-_.]+", "-", name).lower()
        _require(key not in normalized, "Duplicate builder package metadata")
        normalized.add(key)
        _require(entry.get("license_independently_reviewed") is False,
                 "Unreviewed builder license was reported as approved")
        notice = entry.get("local_notice_digests")
        _require(isinstance(notice, list) and len(notice) <= 16,
                 "Builder package notice evidence is missing")
        for item in notice:
            _require(isinstance(item, dict) and _is_sha(item.get("sha256"))
                     and isinstance(item.get("name"), str),
                     "Builder notice SHA-256 metadata is invalid")
    return distributions


def analyze_native_proof(proof: dict[str, Any]) -> dict[str, Any]:
    """One platform: verify the snapshot, then build a conservative review queue."""
    _require(isinstance(proof, dict) and proof.get("schema") == 1,
             "Native QA receipt has an invalid schema")
    target = proof.get("target")
    _require(isinstance(target, str) and target in _TARGETS,
             "Native QA target is not a stable platform")
    _require(
        proof.get("actual_model_inference_verified") is True
        and proof.get("whole_payload_sha256_verified") is True
        and proof.get("managed_installer_verified") is True
        and proof.get("runtime_redistribution_approved") is False
        and proof.get("model_license_approved") is False
        and proof.get("binaries_uploaded") is False
        and proof.get("redistribution_status") == "pending",
        "Native QA is incomplete or falsely approved",
    )
    real = proof.get("real_native_inference")
    _require(isinstance(real, dict)
             and real.get("actual_cpu_model_inference_verified") is True
             and real.get("product_midi_to_musicxml_verified") is True
             and real.get("checkpoint_sha256") == _WEIGHT_SHA,
             "Real model inference or checkpoint provenance is not verified")
    native_sha = proof.get("native_executable_sha256")
    _require(_is_sha(native_sha), "Native executable SHA-256 is missing")

    inventory = proof.get("frozen_dependency_inventory")
    _require(isinstance(inventory, dict) and inventory.get("schema_version") == "1",
             "Native frozen inventory is missing")
    snapshot = inventory.get("snapshot")
    _require(isinstance(snapshot, dict) and snapshot.get("schema_version") == "1",
             "Native frozen inventory snapshot is missing")
    _require(_is_sha(inventory.get("inventory_sha256"))
             and _canonical_sha(snapshot) == inventory["inventory_sha256"],
             "Native frozen inventory SHA-256 changed")
    _require(
        snapshot.get("frozen_executable_sha256") == native_sha
        and snapshot.get("target") == target
        and snapshot.get("inventory_is_complete_distributable_sbom") is False
        and snapshot.get("native_library_dependency_closure_independently_verified") is False
        and snapshot.get("third_party_license_approval") is False
        and snapshot.get("redistribution_status") == "pending"
        and inventory.get("legal_reviewer_signoff") is False
        and inventory.get("third_party_license_approval") is False
        and inventory.get("redistribution_status") == "pending",
        "Native inventory target/approval does not match reviewed executable",
    )
    frozen, builder = snapshot.get("frozen_archive"), snapshot.get("builder")
    _require(isinstance(frozen, dict) and isinstance(builder, dict),
             "Frozen package and builder metadata are required")
    entries = frozen.get("archive_entries")
    pyz = frozen.get("pyz_modules")
    binary_type = frozen.get("native_binary_entries")
    _require(
        isinstance(entries, list) and isinstance(pyz, list)
        and isinstance(binary_type, list) and 0 < len(entries) <= 100000,
        "Frozen archive lists are missing or too large",
    )
    _require(
        type(frozen.get("archive_entry_count")) is int
        and frozen["archive_entry_count"] == len(entries)
        and type(frozen.get("pyz_module_count")) is int
        and frozen["pyz_module_count"] == len(pyz)
        and type(frozen.get("native_binary_entry_count")) is int
        and frozen["native_binary_entry_count"] == len(binary_type),
        "Frozen archive entry counts do not match source inventory",
    )
    seen, b_items = set(), set()
    actual_native = []
    for item in entries:
        _require(isinstance(item, dict), "Frozen TOC entry must be an object")
        name = item.get("name")
        try:
            safe = _safe_archive_name(name)
        except ValueError as exc:
            raise MT3LicenseTriageError("Frozen entry has unsafe metadata") from exc
        _require(safe not in seen, "Frozen TOC entries contain a duplicate filename")
        seen.add(safe)
        kind = item.get("typecode")
        _require(isinstance(kind, str) and len(kind) == 1
                 and type(item.get("uncompressed_bytes")) is int
                 and item["uncompressed_bytes"] >= 0,
                 "Frozen TOC entry metadata is incomplete")
        if kind == "b":
            b_items.add(safe)
            if _candidate_native_library(safe):
                actual_native.append(safe)
    _require(b_items == set(binary_type),
             "Legacy CArchive BINARY list differs from typecode entries")
    _require(len(binary_type) == len(b_items) and len(pyz) > 0,
             "Frozen TOC contains duplicate or missing binary/module entries")
    dists = _builder_distributions(builder)
    missing_notice = sorted(x["name"] for x in dists if not x["local_notice_digests"])
    missing_spdx = sorted(
        x["name"] for x in dists if not x.get("license_expression")
    )
    no_expression_or_label = sorted(
        x["name"] for x in dists
        if not x.get("license_expression")
        and not x.get("license_metadata_label")
    )
    scopes = Counter(_scope(x) for x in actual_native)
    # Keep actual recorded metadata and notice hashes in the report so legal
    # reviewers can identify each distribution requiring primary-source review.
    # Never treat labels/classifiers as a license grant or bundled file mapping.
    distribution_review_queue = [
        {
            "name": item["name"],
            "version": item["version"],
            "license_expression": item.get("license_expression"),
            "legacy_license_label": item.get("license_metadata_label"),
            "legacy_license_text_sha256": item.get("license_metadata_text_sha256"),
            "license_classifiers": item.get("license_classifiers", []),
            "available_notice_file_digests": item["local_notice_digests"],
            "distribution_confirmed_in_frozen_binary": False,
            "independent_license_signoff": False,
        }
        for item in sorted(dists, key=lambda item: item["name"].lower())
    ]
    return {
        "target": target,
        "native_executable_sha256": native_sha,
        "frozen_inventory_sha256": inventory["inventory_sha256"],
        "checkpoint_sha256": real["checkpoint_sha256"],
        "model_inference_verified": True,
        "embedded_archive_entry_count": len(entries),
        "pyz_module_count": len(pyz),
        # Historical field native_binary_entry_count counts all PyInstaller
        # BINARY typecodes, including non-native source/data files on Windows.
        "pyinstaller_binary_typecode_entry_count": len(binary_type),
        "recognizable_native_library_filename_count": len(actual_native),
        "binary_typecode_entries_without_native_library_filename": (
            len(binary_type) - len(actual_native)
        ),
        "native_library_file_review_queue": sorted(actual_native),
        "path_scope_is_verified_source_owner": False,
        "native_library_scope_counts": dict(sorted(scopes.items())),
        "builder_distribution_count": len(dists),
        "builder_distribution_license_review_queue": distribution_review_queue,
        "builder_distribution_names_and_versions": {
            x["name"]: x["version"] for x in sorted(dists, key=lambda x: x["name"].lower())
        },
        "builder_distribution_missing_notice_file_digests": missing_notice,
        "builder_distribution_missing_spdx_expression": missing_spdx,
        "builder_distribution_missing_spdx_and_legacy_license_label": (
            no_expression_or_label
        ),
        "all_builder_distributions_are_bundled": False,
        "license_reviewer_signoff": False,
        "complete_binary_dependency_closure_verified": False,
        "publication_ready": False,
    }


def triage_platforms(windows: dict[str, Any], macos: dict[str, Any]) -> dict[str, Any]:
    reports = {
        item["target"]: item
        for item in (analyze_native_proof(windows), analyze_native_proof(macos))
    }
    _require(set(reports) == set(_TARGETS),
             "Expected exactly one Windows and one macOS native receipt")
    releases = reports["windows-x86_64"], reports["macos-aarch64"]
    _require(releases[0]["checkpoint_sha256"] == releases[1]["checkpoint_sha256"],
             "Windows/macOS model weights do not match")
    versions = [r["builder_distribution_names_and_versions"] for r in releases]
    common = set(versions[0]) & set(versions[1])
    drift = [
        {"name": name, "windows_version": versions[0][name], "macos_version": versions[1][name]}
        for name in sorted(common)
        if versions[0][name] != versions[1][name]
    ]
    return {
        "schema_version": "1",
        "purpose": "native-mt3-cross-platform-third-party-license-review",
        "targets": list(_TARGETS),
        "platforms": reports,
        "cross_platform_builder_package_version_drift": drift,
        "windows_only_builder_packages": sorted(set(versions[0]) - set(versions[1])),
        "macos_only_builder_packages": sorted(set(versions[1]) - set(versions[0])),
        "review_priorities": [
            "Map every listed native library file to the exact upstream source, "
            "bundled version, dynamic dependencies and license obligations",
            "Review embedded source/data carried under PyInstaller BINARY typecodes, "
            "especially Windows; these are not all native shared libraries",
            "Inspect package license notices missing from builder .dist-info; "
            "do not infer missing legal permission from missing local metadata",
            "Verify actual MR-MT3 checkpoint commit/revision and independent "
            "commercial redistribution/license evidence",
            "Produce a complete file-level notice/corresponding-source SBOM and "
            "obtain independent legal sign-off before publication",
        ],
        "source_proof_is_independently_signed": False,
        "native_library_detection_is_binary_format_verified": False,
        "builder_package_inventory_is_bundled_dependency_closure": False,
        "model_redistribution_approved": False,
        "third_party_license_review_approved": False,
        "complete_sbom_verified": False,
        "redistribution_status": "pending",
        "publication_ready": False,
    }


def _read_receipt(path: Path) -> dict[str, Any]:
    _require(path.is_file() and not path.is_symlink(),
             "A regular native QA receipt JSON is required")
    _require(0 < path.stat().st_size <= _MAX_PROOF_BYTES,
             "Native QA receipt is unexpectedly large")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MT3LicenseTriageError("Native QA receipt is invalid JSON") from exc


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Summarize private MT3 native QA into a pending legal dependency review queue"
    )
    parser.add_argument("--windows-proof", type=Path, required=True)
    parser.add_argument("--macos-proof", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = triage_platforms(
            _read_receipt(args.windows_proof), _read_receipt(args.macos_proof),
        )
        # A triage summary contains only source metadata, never executable/model
        # bytes. Still prohibit silent replacement of reviewed output.
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, sort_keys=True, ensure_ascii=False, indent=2)
            stream.write("\n")
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(2, f"Native MT3 license triage rejected: {exc}\n")
    print(json.dumps({
        "platforms": [x["target"] for x in report["platforms"].values()],
        "pending_license_review": True,
        "publication_ready": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

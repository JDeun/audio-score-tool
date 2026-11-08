"""Synthetic, offline tests for native MT3 CArchive/license review triage."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts import triage_mt3_frozen_dependencies as triage
from scripts.collect_mt3_frozen_inventory import _canonical_sha


def _proof(target: str) -> dict:
    windows = target.startswith("windows")
    native = "torch/lib/torch_cpu.dll" if windows else "torch/lib/libtorch_cpu.dylib"
    cext = "torch/_C.cp311-win_amd64.pyd" if windows else "torch/_C.cpython-311-darwin.so"
    python_source = "transformers/models/t5/modeling_t5.py"
    entries = [
        {"name": "PYZ.pyz", "typecode": "z", "uncompressed_bytes": 100},
        {"name": native, "typecode": "b", "uncompressed_bytes": 250},
        {"name": cext, "typecode": "b", "uncompressed_bytes": 150},
        {"name": python_source, "typecode": "b", "uncompressed_bytes": 70},
        {"name": "PIL/FONTS/font.ttf", "typecode": "b", "uncompressed_bytes": 50},
    ]
    frozen = {
        "archive_entry_count": len(entries),
        "pyz_module_count": 2,
        # Important: "native_binary_entry_count" in the old inventory
        # counts all type-b CArchive members, *not* native libraries.
        "native_binary_entry_count": 4,
        "archive_entries": entries,
        "pyz_modules": ["torch._C", "mt3_infer.adapters.mr_mt3"],
        "native_binary_entries": [native, cext, python_source, "PIL/FONTS/font.ttf"],
    }
    packages = [
        {
            "name": "torch", "version": "2.7.1",
            "license_expression": None,
            "license_metadata_label": "BSD-3-Clause",
            "local_notice_digests": [{"name": "license", "sha256": "1" * 64}],
            "license_independently_reviewed": False,
        },
        {
            "name": "tokenizers", "version": "0.22.2",
            "license_expression": None,
            "license_metadata_label": None,
            "local_notice_digests": [],
            "license_independently_reviewed": False,
        },
        {
            "name": "mt3-infer", "version": "0.2.0",
            "license_expression": "MIT",
            "license_metadata_label": None,
            "local_notice_digests": [{"name": "license", "sha256": "2" * 64}],
            "license_independently_reviewed": False,
        },
    ]
    snapshot = {
        "schema_version": "1", "target": target,
        "frozen_executable_sha256": "c" * 64,
        "inventory_is_complete_distributable_sbom": False,
        "native_library_dependency_closure_independently_verified": False,
        "third_party_license_approval": False,
        "redistribution_status": "pending",
        "frozen_archive": frozen,
        "builder": {
            "distribution_count": len(packages),
            "distributions": packages,
            "coverage_scope": "builder_environment_not_bundled_runtime_dependency_closure",
        },
    }
    return {
        "schema": 1, "target": target,
        "native_executable_sha256": "c" * 64,
        "whole_payload_sha256_verified": True,
        "actual_model_inference_verified": True,
        "managed_installer_verified": True,
        "runtime_redistribution_approved": False,
        "model_license_approved": False,
        "binaries_uploaded": False,
        "redistribution_status": "pending",
        "real_native_inference": {
            "actual_cpu_model_inference_verified": True,
            "product_midi_to_musicxml_verified": True,
            "checkpoint_sha256": triage._WEIGHT_SHA,
        },
        "frozen_dependency_inventory": {
            "schema_version": "1",
            "inventory_sha256": _canonical_sha(snapshot),
            "snapshot": snapshot,
            "legal_reviewer_signoff": False,
            "third_party_license_approval": False,
            "redistribution_status": "pending",
        },
    }


def test_binary_typecodes_are_not_misreported_as_native_libraries():
    reviewed = triage.analyze_native_proof(_proof("windows-x86_64"))
    assert reviewed["pyinstaller_binary_typecode_entry_count"] == 4
    assert reviewed["recognizable_native_library_filename_count"] == 2
    assert reviewed["binary_typecode_entries_without_native_library_filename"] == 2
    assert reviewed["path_scope_is_verified_source_owner"] is False
    assert reviewed["native_library_scope_counts"] == {"torch": 1, "torch/lib": 1}
    assert "PIL/FONTS/font.ttf" not in reviewed["native_library_file_review_queue"]
    assert "transformers/models/t5/modeling_t5.py" not in reviewed["native_library_file_review_queue"]
    assert "tokenizers" in reviewed["builder_distribution_missing_notice_file_digests"]
    assert "tokenizers" in reviewed["builder_distribution_missing_spdx_expression"]
    review_items = reviewed["builder_distribution_license_review_queue"]
    tokenizers = next(x for x in review_items if x["name"] == "tokenizers")
    torch = next(x for x in review_items if x["name"] == "torch")
    assert tokenizers["available_notice_file_digests"] == []
    assert tokenizers["independent_license_signoff"] is False
    assert torch["available_notice_file_digests"] == [
        {"name": "license", "sha256": "1" * 64}
    ]
    assert torch["distribution_confirmed_in_frozen_binary"] is False
    assert reviewed["all_builder_distributions_are_bundled"] is False
    assert reviewed["publication_ready"] is False


def test_cross_platform_triage_prioritizes_unverified_licenses_and_supports_diff():
    windows = _proof("windows-x86_64")
    macos = _proof("macos-aarch64")
    reviewed = triage.triage_platforms(windows, macos)
    assert reviewed["targets"] == ["windows-x86_64", "macos-aarch64"]
    assert reviewed["cross_platform_builder_package_version_drift"] == []
    assert reviewed["publication_ready"] is False
    assert reviewed["complete_sbom_verified"] is False
    assert reviewed["third_party_license_review_approved"] is False
    assert reviewed["source_proof_is_independently_signed"] is False
    assert "tokenizers" in reviewed["platforms"]["macos-aarch64"][
        "builder_distribution_missing_notice_file_digests"
    ]
    assert reviewed["platforms"]["windows-x86_64"][
        "recognizable_native_library_filename_count"
    ] == 2
    macos["frozen_dependency_inventory"]["snapshot"]["builder"]["distributions"][0][
        "version"
    ] = "2.7.2"
    macos["frozen_dependency_inventory"]["inventory_sha256"] = _canonical_sha(
        macos["frozen_dependency_inventory"]["snapshot"]
    )
    changed = triage.triage_platforms(windows, macos)
    assert changed["cross_platform_builder_package_version_drift"] == [
        {"name": "torch", "windows_version": "2.7.1", "macos_version": "2.7.2"}
    ]


@pytest.mark.parametrize("name,expected", (
    ("torch/lib/torch_cpu.dll", True),
    ("scipy/_lib/_ccallback.cp311-win_amd64.pyd", True),
    ("torch/lib/libtorch_cpu.dylib", True),
    ("numpy/core/_multiarray_umath.cpython-311-darwin.so", True),
    ("libpango.so.1.2", True),
    ("Python.framework/Versions/3.11/Python", True),
    ("torch/lib/libtbb.a", False),
    ("torch/_dynamo/trace_rules.py", False),
    ("tzdata/zoneinfo/US/Eastern", False),
    ("font.ttf", False),
    ("torch/lib/torch_cpu.dll.txt", False),
))
def test_native_file_detection_is_filename_classification_only(name, expected):
    assert triage._candidate_native_library(name) is expected


@pytest.mark.parametrize("tamper", (
    "inventory_hash", "executable_hash", "approval", "model_hash", "model_result",
    "wrong_builder_scope", "entry_count", "wrong_binary_type", "duplicate_binary",
    "invalid_entry_path", "duplicate_package", "false_license_signoff",
))
def test_fail_closed_on_modified_or_false_native_license_evidence(tamper):
    proof = _proof("windows-x86_64")
    inventory = proof["frozen_dependency_inventory"]
    snap = inventory["snapshot"]
    if tamper == "inventory_hash":
        inventory["inventory_sha256"] = "a" * 64
    elif tamper == "executable_hash":
        snap["frozen_executable_sha256"] = "b" * 64
        inventory["inventory_sha256"] = _canonical_sha(snap)
    elif tamper == "approval":
        proof["runtime_redistribution_approved"] = True
    elif tamper == "model_hash":
        proof["real_native_inference"]["checkpoint_sha256"] = "f" * 64
    elif tamper == "model_result":
        proof["actual_model_inference_verified"] = False
    elif tamper == "wrong_builder_scope":
        snap["builder"]["coverage_scope"] = "complete_shipped_dependency_closure"
    elif tamper == "entry_count":
        snap["frozen_archive"]["archive_entry_count"] += 1
    elif tamper == "wrong_binary_type":
        snap["frozen_archive"]["archive_entries"][1]["typecode"] = "x"
    elif tamper == "duplicate_binary":
        snap["frozen_archive"]["native_binary_entries"].append(
            "torch/lib/torch_cpu.dll"
        )
        snap["frozen_archive"]["native_binary_entry_count"] += 1
    elif tamper == "invalid_entry_path":
        snap["frozen_archive"]["archive_entries"][1]["name"] = "../escape.dll"
    elif tamper == "duplicate_package":
        snap["builder"]["distributions"].append(
            copy.deepcopy(snap["builder"]["distributions"][0])
        )
        snap["builder"]["distribution_count"] += 1
    elif tamper == "false_license_signoff":
        snap["builder"]["distributions"][0]["license_independently_reviewed"] = True
    if tamper not in {"inventory_hash", "approval", "model_hash", "model_result"}:
        inventory["inventory_sha256"] = _canonical_sha(snap)
    with pytest.raises(triage.MT3LicenseTriageError):
        triage.analyze_native_proof(proof)


def test_rejects_duplicate_platform_receipts_and_model_weight_drift():
    windows = _proof("windows-x86_64")
    with pytest.raises(triage.MT3LicenseTriageError, match="one Windows"):
        triage.triage_platforms(windows, copy.deepcopy(windows))
    macos = _proof("macos-aarch64")
    macos["real_native_inference"]["checkpoint_sha256"] = "0" * 64
    with pytest.raises(triage.MT3LicenseTriageError):
        triage.triage_platforms(windows, macos)


def test_read_receipt_limit_and_cli_report_is_no_clobber(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    windows = tmp_path / "windows.pending.json"
    macos = tmp_path / "macos.pending.json"
    out = tmp_path / "review.json"
    windows.write_text(json.dumps(_proof("windows-x86_64")), encoding="utf-8")
    macos.write_text(json.dumps(_proof("macos-aarch64")), encoding="utf-8")
    assert triage._read_receipt(windows)["target"] == "windows-x86_64"
    monkeypatch.setattr(
        "sys.argv", [
            "triage_mt3_frozen_dependencies.py",
            "--windows-proof", str(windows), "--macos-proof", str(macos),
            "--output", str(out),
        ],
    )
    assert triage.main() == 0
    j = json.loads(out.read_text(encoding="utf-8"))
    assert j["publication_ready"] is False
    assert j["redistribution_status"] == "pending"
    assert j["platforms"]["windows-x86_64"]["recognizable_native_library_filename_count"] == 2
    with pytest.raises(SystemExit) as error:
        triage.main()
    assert error.value.code == 2
    assert out.is_file()


def test_without_receipt_or_modified_proof_is_rejected(tmp_path: Path):
    missing = tmp_path / "does-not-exist.json"
    with pytest.raises(triage.MT3LicenseTriageError):
        triage._read_receipt(missing)
    malformed = tmp_path / "corrupt.json"
    malformed.write_text('{"broken":', encoding="utf-8")
    with pytest.raises(triage.MT3LicenseTriageError):
        triage._read_receipt(malformed)


def test_historical_native_license_review_record_is_metadata_only_and_pending():
    review = (
        Path(__file__).resolve().parents[1]
        / "release/review/mt3-native-third-party-pending-2026-11-08.json"
    )
    data = json.loads(review.read_text(encoding="utf-8"))
    assert data["schema"] == 1
    assert data["source"]["workflow_run"].endswith("/42453842931")
    assert data["redistribution_status"] == "pending"
    assert data["reviewed_license_or_model_redistribution_rights"] is False
    assert data["full_sbom_verified"] is False
    assert data["model_checkpoint_upstream_revision_pinned"] is False
    assert data["production_catalog_published"] is False
    assert set(data["targets"]) == {"windows-x86_64", "macos-aarch64"}
    for target in data["targets"].values():
        assert target["pyinstaller_binary_typecode_entries"] == (
            target["native_library_filename_candidates"]
            + target["binary_typecode_items_not_identified_as_native_libraries"]
        )
        assert target["builder_distributions_without_local_license_notice_file_digest"] == [
            "tokenizers"
        ]
        for key in (
            "native_receipt_sha256", "frozen_inventory_sha256", "frozen_executable_sha256",
        ):
            assert triage._is_sha(target[key])
        assert target["frozen_executable_bytes"] > 1024 * 1024


def _proof_with_wheel_path_owner_hints(target: str) -> dict:
    """Synthetic owner hints: one exact match, one unresolved native file."""
    proof = _proof(target)
    snap = proof["frozen_dependency_inventory"]["snapshot"]
    names = [
        row["name"] for row in snap["frozen_archive"]["archive_entries"]
        if row["typecode"] == "b" and triage._candidate_native_library(row["name"])
    ]
    rows = []
    for i, name in enumerate(sorted(names)):
        match = (
            [{
                "distribution": "torch", "version": "2.7.1",
                "record_relative_path": name,
                "wheel_record_sha256": None, "wheel_record_bytes": None,
                "record_sha256_matches_embedded_payload": False,
                "binary_source_independently_verified": False,
                "license_independently_approved": False,
            }] if i == 0 else []
        )
        rows.append({
            "archive_path": name,
            "match_status": "single_record_path_match" if match else "unmatched",
            "wheel_record_matches": match,
        })
    snap["native_file_record_hints"] = {
        "schema_version": "1",
        "mapping_basis": "wheel-RECORD-exact-relative-path-only",
        "target": target,
        "native_filename_candidate_count": len(names),
        "matched_candidate_count": 1,
        "ambiguous_candidate_count": 0,
        "unmatched_candidate_count": len(names) - 1,
        "ignored_nonrelative_wheel_record_paths": 0,
        "native_file_review_queue": rows,
        "binary_payload_equals_record_hash_verified": False,
        "dynamic_library_dependency_closure_verified": False,
        "source_owner_independently_verified": False,
        "license_independently_approved": False,
        "redistribution_status": "pending",
    }
    proof["frozen_dependency_inventory"]["inventory_sha256"] = _canonical_sha(snap)
    return proof


def test_wheel_record_filename_source_hints_preserve_unresolved_files():
    observed = triage.analyze_native_proof(
        _proof_with_wheel_path_owner_hints("windows-x86_64"),
    )
    assert observed["wheel_record_mapping_available"] is True
    assert observed["wheel_record_single_path_match_count"] == 1
    assert observed["wheel_record_unmatched_count"] == 1
    assert observed["wheel_record_ambiguous_count"] == 0
    assert observed["wheel_record_single_path_match_by_distribution"] == {"torch": 1}
    assert observed["wheel_record_source_owner_verified"] is False
    assert all(
        row["match_status"] in {"single_record_path_match", "unmatched"}
        for row in observed["wheel_record_file_review_queue"]
    )


def test_old_native_qa_receipt_does_not_falsely_claim_file_mapping():
    report = triage.analyze_native_proof(_proof("macos-aarch64"))
    assert report["wheel_record_mapping_available"] is False
    assert report["wheel_record_single_path_match_count"] is None
    assert report["wheel_record_file_review_queue"] is None
    assert report["wheel_record_source_owner_verified"] is False


@pytest.mark.parametrize("field,change", (
    ("matched_candidate_count", 2),
    ("unmatched_candidate_count", 0),
    ("source_owner_independently_verified", True),
    ("license_independently_approved", True),
    ("binary_payload_equals_record_hash_verified", True),
    ("native_file_review_queue", []),
))
def test_wheel_path_hints_with_inconsistent_or_approved_status_are_rejected(field, change):
    proof = _proof_with_wheel_path_owner_hints("windows-x86_64")
    inv = proof["frozen_dependency_inventory"]
    inv["snapshot"]["native_file_record_hints"][field] = change
    inv["inventory_sha256"] = _canonical_sha(inv["snapshot"])
    with pytest.raises(triage.MT3LicenseTriageError):
        triage.analyze_native_proof(proof)


def test_wheel_path_hint_cannot_assign_uninstalled_or_mismatched_package():
    proof = _proof_with_wheel_path_owner_hints("windows-x86_64")
    inv = proof["frozen_dependency_inventory"]
    rows = inv["snapshot"]["native_file_record_hints"]["native_file_review_queue"]
    match = rows[0]["wheel_record_matches"][0]
    match["distribution"] = "other-uninstalled-distribution"
    inv["inventory_sha256"] = _canonical_sha(inv["snapshot"])
    with pytest.raises(triage.MT3LicenseTriageError, match="missing or duplicated"):
        triage.analyze_native_proof(proof)




def test_real_native_byte_evidence_is_checked_against_source_record_metadata():
    proof = _proof_with_wheel_path_owner_hints("windows-x86_64")
    snap = proof["frozen_dependency_inventory"]["snapshot"]
    matches = snap["native_file_record_hints"]["native_file_review_queue"]
    records = []
    for row in matches:
        record = row["wheel_record_matches"]
        if record:
            record[0]["wheel_record_sha256"] = "a" * 64
        records.append({
            "archive_path": row["archive_path"],
            "uncompressed_bytes": next(
                entry["uncompressed_bytes"] for entry in snap["frozen_archive"]["archive_entries"]
                if entry["name"] == row["archive_path"]
            ),
            "embedded_sha256": "a" * 64 if record else "b" * 64,
            "record_sha256": "a" * 64 if record else None,
            "record_distribution_hint": "torch" if record else None,
            "comparison": "exact_record_sha256_match" if record else "unmatched",
        })
    counts = {
        "exact_record_sha256_match": 1, "wheel_record_sha256_mismatch": 0,
        "wheel_record_sha256_missing": 0, "ambiguous": 0,
        "unmatched": 1, "size_limit_not_hashed": 0,
    }
    snap["native_file_byte_evidence"] = {
        "schema_version": "1",
        "basis": "actual-PyInstaller-CArchive-member-sha256-vs-builder-wheel-RECORD",
        "target": "windows-x86_64",
        "native_filename_candidate_count": 2,
        "uncompressed_bytes_read": sum(x["uncompressed_bytes"] for x in records),
        "counts": counts,
        "entries": records,
        "all_native_library_bytes_hashed": True,
        "source_owner_independently_verified": False,
        "native_loader_dependency_closure_verified": False,
        "complete_sbom_verified": False,
        "license_independently_approved": False,
        "redistribution_status": "pending",
    }
    proof["frozen_dependency_inventory"]["inventory_sha256"] = _canonical_sha(snap)
    report = triage.analyze_native_proof(proof)
    assert report["native_byte_evidence_available"] is True
    assert report["native_byte_comparison_counts"]["exact_record_sha256_match"] == 1
    assert report["native_byte_comparison_counts"]["unmatched"] == 1
    assert report["native_byte_record_identity_verified"] is False

    snap["native_file_byte_evidence"]["entries"][0]["comparison"] = "unmatched"
    proof["frozen_dependency_inventory"]["inventory_sha256"] = _canonical_sha(snap)
    with pytest.raises(triage.MT3LicenseTriageError, match="contradicts"):
        triage.analyze_native_proof(proof)


def test_historical_receipt_has_no_false_byte_verification():
    old = triage.analyze_native_proof(_proof("macos-aarch64"))
    assert old["native_byte_evidence_available"] is False
    assert old["native_byte_comparison_counts"] is None
    assert old["native_byte_record_identity_verified"] is False

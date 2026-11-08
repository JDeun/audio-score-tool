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

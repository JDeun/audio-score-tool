"""Local-only release review of immutable native MT3 metadata receipts."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from scripts import aggregate_mt3_native_release_review as aggregate
from scripts.collect_mt3_frozen_inventory import _canonical_sha
from scripts.fetch_pinned_mrmt3_checkpoint import (
    CHECKPOINT_SHA256, MODEL_REPO, MODEL_REVISION, SOURCE_URL,
)


def _source() -> dict:
    return {
        "schema_version": "1",
        "model": "mr_mt3",
        "upstream_repository": MODEL_REPO,
        "upstream_revision": MODEL_REVISION,
        "upstream_source_url": SOURCE_URL,
        "checkpoint_sha256": CHECKPOINT_SHA256,
        "checkpoint_bytes": 175_000_000,
        "immutable_revision_requested": True,
        "checkpoint_sha256_verified": True,
        "model_checkpoint_deserialized": False,
        "model_redistribution_approved": False,
        "release_catalog_modified": False,
        "redistribution_status": "pending",
    }


def _native(target: str, *, byte_match: bool = False) -> dict:
    filename = "torch/lib/torch_cpu.dll" if target.startswith("windows") else "torch/lib/libtorch_cpu.dylib"
    exact = hashlib.sha256(b"synthetic native bytes").hexdigest()
    recorded = exact if byte_match else None
    comparison = "exact_record_sha256_match" if byte_match else "wheel_record_sha256_missing"
    files = [
        {"name": "PYZ.pyz", "typecode": "z", "uncompressed_bytes": 1024},
        {"name": filename, "typecode": "b", "uncompressed_bytes": 22},
    ]
    frozen = {
        "archive_entry_count": len(files), "archive_entries": files,
        "pyz_module_count": 1, "pyz_modules": ["torch"],
        "native_binary_entry_count": 1, "native_binary_entries": [filename],
    }
    match = {
        "distribution": "torch", "version": "2.7.1",
        "record_relative_path": filename,
        "wheel_record_sha256": recorded,
        "wheel_record_bytes": 22,
        "record_sha256_matches_embedded_payload": False,
        "binary_source_independently_verified": False,
        "license_independently_approved": False,
    }
    hints = {
        "schema_version": "1",
        "mapping_basis": "wheel-RECORD-exact-relative-path-only",
        "target": target,
        "native_filename_candidate_count": 1,
        "matched_candidate_count": 1, "ambiguous_candidate_count": 0,
        "unmatched_candidate_count": 0, "ignored_nonrelative_wheel_record_paths": 0,
        "native_file_review_queue": [
            {"archive_path": filename, "match_status": "single_record_path_match",
             "wheel_record_matches": [match]},
        ],
        "binary_payload_equals_record_hash_verified": False,
        "dynamic_library_dependency_closure_verified": False,
        "source_owner_independently_verified": False,
        "license_independently_approved": False,
        "redistribution_status": "pending",
    }
    bytes_proof = {
        "schema_version": "1",
        "basis": "actual-PyInstaller-CArchive-member-sha256-vs-builder-wheel-RECORD",
        "target": target,
        "native_filename_candidate_count": 1,
        "uncompressed_bytes_read": 22,
        "counts": {
            "exact_record_sha256_match": 1 if byte_match else 0,
            "wheel_record_sha256_mismatch": 0,
            "wheel_record_sha256_missing": 0 if byte_match else 1,
            "ambiguous": 0, "unmatched": 0, "size_limit_not_hashed": 0,
        },
        "entries": [{
            "archive_path": filename,
            "uncompressed_bytes": 22,
            "embedded_sha256": exact,
            "record_sha256": recorded,
            "record_distribution_hint": "torch",
            "comparison": comparison,
        }],
        "all_native_library_bytes_hashed": True,
        "source_owner_independently_verified": False,
        "native_loader_dependency_closure_verified": False,
        "complete_sbom_verified": False,
        "license_independently_approved": False,
        "redistribution_status": "pending",
    }
    snapshot = {
        "schema_version": "1", "target": target,
        "frozen_executable_sha256": "f" * 64,
        "frozen_archive": frozen,
        "builder": {
            "distribution_count": 1,
            "coverage_scope": "builder_environment_not_bundled_runtime_dependency_closure",
            "distributions": [{
                "name": "torch", "version": "2.7.1", "license_expression": None,
                "license_metadata_label": "BSD-3-Clause", "license_classifiers": [],
                "local_notice_digests": [], "license_independently_reviewed": False,
            }],
        },
        "native_file_record_hints": hints,
        "native_file_byte_evidence": bytes_proof,
        "inventory_is_complete_distributable_sbom": False,
        "native_library_dependency_closure_independently_verified": False,
        "third_party_license_approval": False,
        "redistribution_status": "pending",
    }
    return {
        "schema": 1, "target": target,
        "model_adapter": "mr_mt3",
        "private_candidate_staged_locally": False,
        "native_executable_sha256": "f" * 64,
        "whole_payload_sha256_verified": True,
        "managed_installer_verified": True,
        "actual_model_inference_verified": True,
        "runtime_redistribution_approved": False,
        "model_license_approved": False,
        "binaries_uploaded": False,
        "redistribution_status": "pending",
        "real_native_inference": {
            "model": "mr_mt3",
            "actual_cpu_model_inference_verified": True,
            "product_midi_to_musicxml_verified": True,
            "checkpoint_sha256": CHECKPOINT_SHA256,
            "checkpoint_source": SOURCE_URL,
            "checkpoint_source_revision": MODEL_REVISION,
            "model_redistribution_approved": False,
            "model_weights_published": False,
            "redistribution_status": "pending",
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


def _evidence() -> tuple[dict, dict, dict, dict]:
    return _native("windows-x86_64"), _native("macos-aarch64", byte_match=True), _source(), _source()


def test_two_targets_require_review_and_keep_original_evidence_pinned():
    report = aggregate.aggregate_native_review(*_evidence())
    assert report["targets"] == ["windows-x86_64", "macos-aarch64"]
    assert report["source_receipts_bound_to_native_qa"] is True
    assert report["native_file_comparison_counts"] == {
        "exact_record_sha256_match": 1, "wheel_record_sha256_missing": 1,
    }
    assert report["native_unresolved_file_count"] == 1
    assert report["native_file_priority_review_queue"][0]["target"] == "windows-x86_64"
    assert report["native_file_priority_review_queue"][0]["reason"] == "wheel_record_sha256_missing"
    assert report["third_party_review"]["platforms"]["macos-aarch64"]["native_byte_evidence_available"]
    assert report["verified_source_receipts"]["windows-x86_64"]["missing_builder_notice_metadata"] == ["torch"]
    assert report["production_catalog_published"] is False
    assert report["license_independently_approved"] is False
    assert report["redistribution_status"] == "pending"


@pytest.mark.parametrize(("target", "part", "mutation"), [
    ("windows", "source", lambda p: p.update(upstream_revision="main")),
    ("macos", "source", lambda p: p.update(checkpoint_sha256="f" * 64)),
    ("windows", "source", lambda p: p.update(model_redistribution_approved=True)),
    ("macos", "native", lambda p: p["real_native_inference"].update(checkpoint_source_revision="main")),
    ("windows", "native", lambda p: p.update(binaries_uploaded=True)),
    ("windows", "native", lambda p: p["frozen_dependency_inventory"].pop("inventory_sha256")),
    ("macos", "native", lambda p: p["frozen_dependency_inventory"]["snapshot"].pop("native_file_byte_evidence")),
    ("windows", "native", lambda p: p["frozen_dependency_inventory"]["snapshot"]["native_file_byte_evidence"]["counts"].update(
        exact_record_sha256_match=100,
    )),
])
def test_invalid_or_unapproved_cross_platform_proof_fails_closed(target, part, mutation):
    w, m, ws, ms = copy.deepcopy(_evidence())
    selected = {
        ("windows", "source"): ws, ("macos", "source"): ms,
        ("windows", "native"): w, ("macos", "native"): m,
    }[(target, part)]
    mutation(selected)
    # If only the nested data changed, rebind the *claimed* snapshot digest,
    # so the rejection must also detect inconsistent evidence semantics.
    if part == "native" and "snapshot" in selected["frozen_dependency_inventory"]:
        inv = selected["frozen_dependency_inventory"]
        if "inventory_sha256" in inv:
            inv["inventory_sha256"] = _canonical_sha(inv["snapshot"])
    with pytest.raises(aggregate.NativeReleaseReviewError):
        aggregate.aggregate_native_review(w, m, ws, ms)


def test_missing_native_receipt_file_and_cli_no_clobber(tmp_path, monkeypatch, capsys):
    w, m, ws, ms = _evidence()
    paths = [tmp_path / f"proof{i}.json" for i in range(4)]
    for path, proof in zip(paths, [w, m, ws, ms]):
        path.write_text(json.dumps(proof), encoding="utf-8")
    destination = tmp_path / "review.pending.json"
    monkeypatch.setattr("sys.argv", [
        "aggregate_mt3_native_release_review.py",
        "--windows-native", str(paths[0]), "--macos-native", str(paths[1]),
        "--windows-source", str(paths[2]), "--macos-source", str(paths[3]),
        "--output", str(destination),
    ])
    assert aggregate.main() == 0
    assert json.loads(destination.read_text())["redistribution_status"] == "pending"
    assert "publication_ready" in json.dumps(json.loads(destination.read_text()))
    assert "unresolved_native_files" in capsys.readouterr().out
    with pytest.raises(SystemExit) as exc:
        aggregate.main()
    assert exc.value.code == 2
    paths[0].unlink()
    with pytest.raises(aggregate.NativeReleaseReviewError, match="regular"):
        aggregate._read_json(paths[0])

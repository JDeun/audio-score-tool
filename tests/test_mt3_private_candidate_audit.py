"""Synthetic offline contracts for private frozen MR-MT3 candidate/proof audit.

No real copyrighted model is downloaded, loaded or redistributed by these tests.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
import zipfile
from pathlib import Path

import pytest

from scripts import audit_mt3_private_candidate as audit
from scripts import prepare_managed_artifact_candidate as candidate
from scripts import verify_mt3_frozen_native as native
from scripts.collect_mt3_frozen_inventory import _canonical_sha


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _zip_member(writer: zipfile.ZipFile, name: str, data: bytes, *, zipped=False, symlink=False):
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.create_system = 3
    info.external_attr = (
        (stat.S_IFLNK | 0o777) if symlink else (stat.S_IFREG | 0o755)
    ) << 16
    info.compress_type = zipfile.ZIP_DEFLATED if zipped else zipfile.ZIP_STORED
    writer.writestr(info, data)


def _fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    target: str = "macos-aarch64",
    extra: str | None = None,
    compressed: bool = False,
    linked: bool = False,
    bad_manifest: bool = False,
    bad_checkpoint: bool = False,
):
    executable = f"bin/mt3-infer{'.exe' if target.startswith('windows') else ''}"
    binary = b"MZ" + b"frozen-not-a-real-executable" * 42000
    checkpoint = b"original-synthetic-checkpoint" * 45000
    model_sha = _sha(checkpoint)
    monkeypatch.setattr(native, "_MR_MT3_SHA256", model_sha)
    monkeypatch.setattr(candidate, "_MR_MT3_WEIGHT_SHA256", model_sha)
    snapshot = {
        "schema_version": "1",
        "target": target,
        "frozen_executable_sha256": _sha(binary),
        "frozen_archive": {
            "archive_entry_count": 3,
            "native_binary_entry_count": 1,
            "pyz_module_count": 5,
        },
        "builder": {"distribution_count": 3},
        "inventory_is_complete_distributable_sbom": False,
        "native_library_dependency_closure_independently_verified": False,
        "third_party_license_approval": False,
        "redistribution_status": "pending",
    }
    inventory = {
        "schema_version": "1",
        "inventory_sha256": _canonical_sha(snapshot),
        "snapshot": snapshot,
        "legal_reviewer_signoff": False,
        "third_party_license_approval": False,
        "redistribution_status": "pending",
    }
    manifest = {
        "schema": 1,
        "target": "windows-x86_64" if bad_manifest else target,
        "component": "transcription_engine",
        "model_adapter": "mr_mt3",
        "build_method": "PyInstaller onefile native QA",
        "packages": dict(native._EXPECTED),
        "mt3_wrapper_sha256": _sha(binary),
        "frozen_inventory_sha256": inventory["inventory_sha256"],
        "upstream": "https://github.com/openmirlab/mt3-infer/tree/v0.2.0",
        "model_weights_included": True,
        "checkpoint_sha256": model_sha,
        "checkpoint_source": native._MR_MT3_SOURCE,
        "checkpoint_license_review": "pending",
        "redistribution_status": "pending",
        "approval_required": True,
    }
    archive = tmp_path / f"MT3-MRMT3-{target}-UNAPPROVED.zip"
    with zipfile.ZipFile(archive, "w", allowZip64=True) as bundle:
        _zip_member(bundle, executable, binary, zipped=compressed, symlink=linked)
        _zip_member(
            bundle, "checkpoints/mr_mt3/mt3.pth",
            b"x" * len(checkpoint) if bad_checkpoint else checkpoint,
        )
        _zip_member(
            bundle, "provenance/frozen-native-qa.pending.json",
            (json.dumps(manifest, sort_keys=True) + "\n").encode(),
        )
        if extra:
            _zip_member(bundle, extra, b"unreviewed")
    archive_sha = audit._sha256_file(archive)
    proof = {
        "schema": 1,
        "target": target,
        "model_adapter": "mr_mt3",
        "packages": dict(native._EXPECTED),
        "native_executable_sha256": _sha(binary),
        "frozen_dependency_inventory": inventory,
        "private_archive_sha256": "b" * 64,
        "whole_payload_sha256_verified": True,
        "managed_installer_verified": True,
        "registered_executable_verified": True,
        "native_host_python_not_required_for_startup": True,
        "actual_model_inference_verified": True,
        "model_checkpoint_included": True,
        "private_candidate_staged_locally": True,
        "private_candidate_filename": archive.name,
        "windows_macos_clean_machine_verified": False,
        "model_license_approved": False,
        "runtime_redistribution_approved": False,
        "binaries_uploaded": False,
        "redistribution_status": "pending",
        "real_native_inference": {
            "model": "mr_mt3",
            "actual_model_weights_verified": True,
            "managed_archive_and_full_payload_verified": True,
            "registered_native_frozen_executable_verified": True,
            "actual_cpu_model_inference_verified": True,
            "product_midi_to_musicxml_verified": True,
            "no_ambient_python_or_path_required_by_frozen_cli": True,
            "model_redistribution_approved": False,
            "model_weights_published": False,
            "clean_machine_install_verified": False,
            "redistribution_status": "pending",
            "checkpoint_sha256": model_sha,
            "checkpoint_source": native._MR_MT3_SOURCE,
            "frozen_executable_sha256": _sha(binary),
            "private_real_archive_sha256": archive_sha,
            "private_real_archive_bytes": archive.stat().st_size,
            "note_counts": {"midi_notes": 5, "notes": 5, "parts": 1},
            "audio_sha256": "a" * 64,
            "midi_sha256": "c" * 64,
            "musicxml_sha256": "d" * 64,
        },
    }
    return archive, proof


@pytest.mark.parametrize("target", ("windows-x86_64", "macos-aarch64"))
def test_native_candidate_streams_exact_bytes_and_remains_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str,
):
    archive, proof = _fixture(tmp_path, monkeypatch, target=target)
    report = audit.audit_private_candidate(archive, proof)
    assert report["target"] == target
    assert report["local_bytes_match_native_qa"] is True
    assert report["archive_sha256"] == audit._sha256_file(archive)
    assert report["model_checkpoint_sha256"] == native._MR_MT3_SHA256
    assert report["tool_sha256"]["mt3-infer"] == proof["native_executable_sha256"]
    assert report["frozen_inventory_sha256"] == proof["frozen_dependency_inventory"]["inventory_sha256"]
    assert report["builder_distribution_inventory_count"] == 3
    assert report["native_qa_receipt_canonical_sha256"]
    assert report["publication_ready"] is False
    assert report["approval_required"] is True
    assert report["redistribution_status"] == "pending"
    assert report["builder_packages_are_complete_frozen_sbom"] is False
    assert report["checkpoint_not_deserialized_by_audit"] is True
    assert report["release_blockers"]
    assert "license_independently_approved" in report
    assert "archive" not in json.dumps(report).lower() or "archive_sha256" in report
    assert not any(str(tmp_path) in str(v) for v in report.values())


@pytest.mark.parametrize("kind", (
    "bad_archive_sha", "false_model_inference", "no_staging",
    "license_preapproved", "published_weights", "bad_counts", "bad_target",
    "wrong_model_sha", "bad_builder", "invalid_model_proof",
))
def test_native_candidate_rejects_misleading_or_forged_qa(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str,
):
    archive, proof = _fixture(tmp_path, monkeypatch)
    real = proof["real_native_inference"]
    if kind == "bad_archive_sha":
        real["private_real_archive_sha256"] = "0" * 64
    elif kind == "false_model_inference":
        proof["actual_model_inference_verified"] = False
    elif kind == "no_staging":
        proof["private_candidate_staged_locally"] = False
    elif kind == "license_preapproved":
        proof["model_license_approved"] = True
    elif kind == "published_weights":
        real["model_weights_published"] = True
    elif kind == "bad_counts":
        real["note_counts"]["parts"] = 0
    elif kind == "bad_target":
        proof["target"] = {"malicious": "unhashable"}
    elif kind == "wrong_model_sha":
        real["checkpoint_sha256"] = "0" * 64
    elif kind == "bad_builder":
        proof["packages"]["torch"] = "1.0.0"
    else:
        real["product_midi_to_musicxml_verified"] = False
    with pytest.raises(audit.PrivateCandidateAuditError):
        audit.audit_private_candidate(archive, proof)


@pytest.mark.parametrize("kind", (
    "extra_file", "compressed_exe", "linked_exe",
    "drift_manifest", "drift_checkpoint", "modified_receipt_exe",
))
def test_native_candidate_rejects_unauthorized_zip_contents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str,
):
    archive, proof = _fixture(
        tmp_path, monkeypatch,
        extra="../outside" if kind == "extra_file" else None,
        compressed=kind == "compressed_exe",
        linked=kind == "linked_exe",
        bad_manifest=kind == "drift_manifest",
        bad_checkpoint=kind == "drift_checkpoint",
    )
    if kind == "modified_receipt_exe":
        proof["native_executable_sha256"] = "f" * 64
        proof["real_native_inference"]["frozen_executable_sha256"] = "f" * 64
    with pytest.raises(audit.PrivateCandidateAuditError):
        audit.audit_private_candidate(archive, proof)
    assert not (tmp_path / "outside").exists()


def test_pending_audit_private_output_no_clobber_and_no_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    archive, proof = _fixture(tmp_path, monkeypatch)
    report = audit.audit_private_candidate(archive, proof)
    output = tmp_path / "native-review.pending.json"
    audit.write_pending_audit(report, output)
    parsed = json.loads(output.read_text(encoding="utf-8"))
    assert parsed["archive_sha256"] == report["archive_sha256"]
    assert parsed["publication_ready"] is False
    assert parsed["redistribution_status"] == "pending"
    assert "MZfrozen-not" not in output.read_text(encoding="utf-8")
    if os.name != "nt":
        assert output.stat().st_mode & 0o077 == 0
    with pytest.raises(audit.PrivateCandidateAuditError, match="overwrite"):
        audit.write_pending_audit(report, output)
    assert json.loads(output.read_text(encoding="utf-8")) == parsed
    with pytest.raises(audit.PrivateCandidateAuditError, match="outside"):
        audit.write_pending_audit(report, audit._ROOT / "docs" / "danger.json")


def _draft(archive: Path, *, native_audit: dict | None = None, target="macos-aarch64"):
    return candidate.draft_candidate(
        archive_path=archive,
        component="transcription_engine",
        version="mt3-0.2.0-private-audit",
        target=target,
        url="https://example.invalid/private-unapproved.zip",
        archive_format="zip",
        tools={"mt3-infer": f"bin/mt3-infer{'.exe' if target.startswith('windows') else ''}"},
        license_name="independent-review-not-yet-approved",
        provenance="private synthetic candidate pending legal review",
        upstream_revision="upstream-tag-v0.2.0-unapproved",
        native_audit=native_audit,
    )


@pytest.mark.parametrize("target", ("windows-x86_64", "macos-aarch64"))
def test_stable_amt_candidate_requires_bound_native_audit_and_real_model_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str,
):
    archive, proof = _fixture(tmp_path, monkeypatch, target=target)
    with pytest.raises(ValueError, match="requires a private native inference audit"):
        _draft(archive, target=target)
    worksheet = audit.audit_private_candidate(archive, proof)
    draft = _draft(archive, target=target, native_audit=worksheet)
    bound = draft["local_validation"]["native_inference_audit"]
    assert bound["model_checkpoint_sha256"] == native._MR_MT3_SHA256
    assert bound["native_inference_verified_by_local_receipt"] is True
    assert bound["frozen_inventory_sha256"] == worksheet["frozen_inventory_sha256"]
    assert bound["inventory_is_complete_distributable_sbom"] is False
    assert bound["tool_sha256"] == draft["local_validation"]["tool_sha256"]
    assert draft["local_validation"]["clean_machine_verified"] is False
    assert draft["candidate"]["redistribution_status"] == "pending"
    assert draft["approval_required"] is True


def test_candidate_rejects_bogus_or_approved_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    archive, proof = _fixture(tmp_path, monkeypatch)
    report = audit.audit_private_candidate(archive, proof)
    tampered = copy.deepcopy(report)
    tampered["publication_ready"] = True
    with pytest.raises(ValueError, match="audit"):
        _draft(archive, native_audit=tampered)
    tampered = copy.deepcopy(report)
    tampered["tool_sha256"]["mt3-infer"] = "f" * 64
    with pytest.raises(ValueError, match="audit|tool"):
        _draft(archive, native_audit=tampered)
    tampered = copy.deepcopy(report)
    tampered["model_checkpoint_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="audit"):
        _draft(archive, native_audit=tampered)
    tampered = copy.deepcopy(report)
    tampered["archive_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="audit"):
        _draft(archive, native_audit=tampered)


def test_unrelated_optional_component_does_not_accept_native_amt_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    archive, proof = _fixture(tmp_path, monkeypatch)
    report = audit.audit_private_candidate(archive, proof)
    with pytest.raises(ValueError, match="only valid"):
        candidate.draft_candidate(
            archive_path=archive,
            component="whisperx", version="test-only",
            target="macos-aarch64",
            url="https://example.invalid/unapproved-whisperx.zip",
            archive_format="zip",
            tools={"mt3-infer": "bin/mt3-infer"},
            license_name="review-required", provenance="synthetic test",
            upstream_revision="test", native_audit=report,
        )


@pytest.mark.parametrize("tamper", (
    "missing", "changed_sha", "different_binary", "claimed_complete",
    "claimed_approved", "changed_manifest", "empty_modules",
))
def test_native_inventory_must_match_frozen_file_and_pending_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tamper: str,
):
    archive, proof = _fixture(tmp_path, monkeypatch)
    inv = proof["frozen_dependency_inventory"]
    if tamper == "missing":
        proof.pop("frozen_dependency_inventory")
    elif tamper == "changed_sha":
        inv["inventory_sha256"] = "f" * 64
    elif tamper == "different_binary":
        inv["snapshot"]["frozen_executable_sha256"] = "f" * 64
        inv["inventory_sha256"] = _canonical_sha(inv["snapshot"])
    elif tamper == "claimed_complete":
        inv["snapshot"]["inventory_is_complete_distributable_sbom"] = True
        inv["inventory_sha256"] = _canonical_sha(inv["snapshot"])
    elif tamper == "claimed_approved":
        inv["legal_reviewer_signoff"] = True
    elif tamper == "changed_manifest":
        # The native binary/payload SHA stays unchanged. A mismatched
        # inventory value inside the ZIP must not be accepted anyway.
        inv["inventory_sha256"] = "1" * 64
    elif tamper == "empty_modules":
        inv["snapshot"]["frozen_archive"]["pyz_module_count"] = 0
        inv["inventory_sha256"] = _canonical_sha(inv["snapshot"])
    with pytest.raises(audit.PrivateCandidateAuditError):
        audit.audit_private_candidate(archive, proof)


def test_draft_requires_frozen_inventory_fields_to_remain_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    archive, proof = _fixture(tmp_path, monkeypatch)
    report = audit.audit_private_candidate(archive, proof)
    for changed in (
        ("frozen_inventory_sha256", "0" * 64),
        ("builder_distribution_inventory_count", 0),
        ("embedded_native_binary_entries", 0),
        ("embedded_pyz_modules", 0),
    ):
        modified = copy.deepcopy(report)
        modified[changed[0]] = changed[1]
        with pytest.raises(ValueError, match="audit"):
            _draft(archive, native_audit=modified)


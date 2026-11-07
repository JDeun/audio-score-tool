"""No upstream binary or OCR model is executed by these deterministic tests."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import verify_audiveris_official_installer as verifier


def _fake_asset(tmp_path: Path, target: str) -> tuple[Path, Path]:
    pins = json.loads(verifier.DEFAULT_PINS.read_text(encoding="utf-8"))
    item = pins["sources"][target]
    archive = tmp_path / item["asset"]
    payload = (
        verifier._MSI_HEADER + b"\0" * 700
        if target == "windows-x86_64"
        else b"owned-fake-DMG-padding" * 40 + b"koly" + b"\0" * 508
    )
    archive.write_bytes(payload)
    item["bytes"] = len(payload)
    item["sha256"] = hashlib.sha256(payload).hexdigest()
    pin_file = tmp_path / "review-pins.json"
    pin_file.write_text(json.dumps(pins), encoding="utf-8")
    return archive, pin_file


@pytest.mark.parametrize("target", ["windows-x86_64", "macos-aarch64"])
def test_official_installer_bytes_and_magic_are_verified_but_unapproved(tmp_path: Path, target: str):
    installer, pins = _fake_asset(tmp_path, target)
    evidence_path = tmp_path / "audiveris.pending.json"
    result = verifier.verify_official_installer(
        installer, target, pin_file=pins, output=evidence_path,
    )
    assert result["target"] == target
    assert result["component"] == "audiveris"
    assert result["tag"] == "5.11.0"
    assert result["original_installer_bytes_verified"] is True
    assert result["installer_container_magic_verified"] is True
    assert result["asset_sha256"] == hashlib.sha256(installer.read_bytes()).hexdigest()
    assert result["embedded_jre_verified"] is False
    assert result["native_cli_execution_verified"] is False
    assert result["managed_portable_zip_verified"] is False
    assert result["agpl_source_notice_compliance_verified"] is False
    assert result["redistribution_status"] == "pending"
    assert result["approval_required"] is True
    assert json.loads(evidence_path.read_text(encoding="utf-8")) == result


@pytest.mark.parametrize("target", ["windows-x86_64", "macos-aarch64"])
def test_official_asset_size_and_hash_mismatch_never_publishes(tmp_path: Path, target: str):
    installer, pins = _fake_asset(tmp_path, target)
    installer.write_bytes(installer.read_bytes() + b"modified")
    output = tmp_path / "untrusted.json"
    with pytest.raises(verifier.AudiverisReviewError, match="size"):
        verifier.verify_official_installer(installer, target, pin_file=pins, output=output)
    assert not output.exists()
    installer, pins = _fake_asset(tmp_path, target)
    pin = json.loads(pins.read_text(encoding="utf-8"))
    pin["sources"][target]["sha256"] = "f" * 64
    pins.write_text(json.dumps(pin), encoding="utf-8")
    with pytest.raises(verifier.AudiverisReviewError, match="SHA-256"):
        verifier.verify_official_installer(installer, target, pin_file=pins, output=output)
    assert not output.exists()


@pytest.mark.parametrize("target", ["windows-x86_64", "macos-aarch64"])
def test_wrong_container_signature_is_rejected_before_any_evidence(tmp_path: Path, target: str):
    installer, pins = _fake_asset(tmp_path, target)
    old = installer.read_bytes()
    corrupted = b"!" * len(verifier._MSI_HEADER) + old[8:] if target == "windows-x86_64" else old[:-512] + b"fail" + old[-508:]
    installer.write_bytes(corrupted)
    pin = json.loads(pins.read_text(encoding="utf-8"))
    pin["sources"][target]["sha256"] = hashlib.sha256(corrupted).hexdigest()
    pins.write_text(json.dumps(pin), encoding="utf-8")
    with pytest.raises(verifier.AudiverisReviewError, match="MSI|DMG"):
        verifier.verify_official_installer(
            installer, target, pin_file=pins, output=tmp_path / "rejected.json",
        )


@pytest.mark.parametrize("field,value", [
    ("redistribution_status", "approved"),
    ("legal_review_status", "approved"),
    ("commercial_redistribution_approved", True),
    ("portable_managed_archive_available", True),
    ("java_runtime_verified", True),
    ("packaged_omr_recognition_verified", True),
])
def test_review_pin_cannot_self_approve_or_claim_unverified_readiness(
    tmp_path: Path, field: str, value,
):
    installer, pins = _fake_asset(tmp_path, "windows-x86_64")
    pin = json.loads(pins.read_text(encoding="utf-8"))
    pin[field] = value
    pins.write_text(json.dumps(pin), encoding="utf-8")
    with pytest.raises(verifier.AudiverisReviewError, match="unapproved official review"):
        verifier.verify_official_installer(
            installer, "windows-x86_64", pin_file=pins, output=tmp_path / "blocked.json",
        )


def test_asset_source_url_and_windows_console_variant_are_exactly_pinned(tmp_path: Path):
    installer, pins = _fake_asset(tmp_path, "windows-x86_64")
    pin = json.loads(pins.read_text(encoding="utf-8"))
    pin["sources"]["windows-x86_64"]["url"] = pin["sources"]["windows-x86_64"]["url"].replace(
        "windowsConsole-", "windows-",
    )
    pins.write_text(json.dumps(pin), encoding="utf-8")
    with pytest.raises(verifier.AudiverisReviewError, match="asset name, source URL"):
        verifier.verify_official_installer(
            installer, "windows-x86_64", pin_file=pins, output=tmp_path / "blocked.json",
        )


def test_review_output_will_never_overwrite_existing_evidence(tmp_path: Path):
    installer, pins = _fake_asset(tmp_path, "windows-x86_64")
    output = tmp_path / "review.json"
    output.write_text("original human review", encoding="utf-8")
    with pytest.raises(verifier.AudiverisReviewError, match="new file"):
        verifier.verify_official_installer(installer, "windows-x86_64", pin_file=pins, output=output)
    assert output.read_text(encoding="utf-8") == "original human review"


def test_symlink_asset_never_enters_review(tmp_path: Path):
    installer, pins = _fake_asset(tmp_path, "windows-x86_64")
    alias = tmp_path / "alternate" / installer.name
    alias.parent.mkdir()
    try:
        alias.symlink_to(installer)
    except OSError:
        pytest.skip("Symlinks unavailable on this runner")
    with pytest.raises(verifier.AudiverisReviewError, match="non-symlinked"):
        verifier.verify_official_installer(alias, "windows-x86_64", pin_file=pins, output=tmp_path / "blocked.json")


def test_repository_pin_is_explicit_and_is_not_a_catalog_release():
    pin = json.loads(verifier.DEFAULT_PINS.read_text(encoding="utf-8"))
    assert pin["tag"] == "5.11.0"
    assert pin["source_commit"] == "9e1e55cd2746037d059345881c53e6a6754bffbd"
    assert set(pin["sources"]) == verifier._TARGETS
    assert pin["commercial_redistribution_approved"] is False
    assert pin["portable_managed_archive_available"] is False
    assert pin["redistribution_status"] == "pending"
    assert pin["java_runtime_verified"] is False
    assert pin["packaged_omr_recognition_verified"] is False

"""Owned synthetic jpackage fixtures, not actual redistributed Audiveris/JRE."""
from __future__ import annotations

import hashlib
import json
import os
import stat
import zipfile
from pathlib import Path

import pytest

from scripts import assemble_audiveris_portable_candidate as candidate
from scripts import verify_audiveris_native_layout as native
from scripts import verify_audiveris_official_installer as official

_VERSION = "5.11.0-review-1"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _fixture(tmp_path: Path, monkeypatch, target: str):
    pin = json.loads(official.DEFAULT_PINS.read_text(encoding="utf-8"))
    record = pin["sources"][target]
    payload = (
        official._MSI_HEADER + b"\x02" * 700
        if target == "windows-x86_64"
        else b"fake-macos-binary-installer" * 22 + b"koly" + b"\0" * 508
    )
    record["bytes"] = len(payload)
    record["sha256"] = _sha(payload)
    review_pin = tmp_path / "official-pins.json"
    review_pin.write_text(json.dumps(pin), encoding="utf-8")

    source_installer = tmp_path / record["asset"]
    source_installer.write_bytes(payload)
    source_receipt = tmp_path / "SOURCE-EVIDENCE.pending.json"
    official.verify_official_installer(
        source_installer, target, output=source_receipt, pin_file=review_pin,
    )
    extracted = tmp_path / "extracted"
    extracted.mkdir()
    if target == "windows-x86_64":
        launcher = extracted / "Audiveris" / "Audiveris.exe"
        java = extracted / "Audiveris/runtime/bin/java.exe"
        extra = extracted / "Audiveris/app/audiveris.jar"
    else:
        launcher = extracted / "Audiveris.app/Contents/MacOS/Audiveris"
        java = extracted / "Audiveris.app/Contents/runtime/Contents/Home/bin/java"
        extra = extracted / "Audiveris.app/Contents/app/audiveris.jar"
    for path, contents in (
        (launcher, b"synthetic-audiveris-launcher"),
        (java, b"synthetic-owned-JRE"),
        (extra, b"synthetic-jar-only"),
        (java.parent.parent / "release",
         b'JAVA_VERSION="25.0.2"\nMODULES="java.base java.desktop"\n'),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
        if path in {launcher, java} and os.name != "nt":
            path.chmod(path.stat().st_mode | stat.S_IXUSR)

    monkeypatch.setattr(native, "_platform_matches", lambda t: t == target)
    monkeypatch.setattr(candidate, "_platform_matches", lambda t: t == target)
    def fake_version(path, _root, label):
        assert path.is_file() and path.is_absolute()
        assert label in {"audiveris", "embedded-jre"}
        return (
            "Audiveris\n- Version: 5.11.0\n"
            if label == "audiveris" else 'openjdk version "25.0.2"\n'
        )
    monkeypatch.setattr(native, "_native_version", fake_version)
    monkeypatch.setattr(candidate, "_native_version", fake_version)
    native_receipt = tmp_path / "NATIVE-EVIDENCE.pending.json"
    native.verify_native_layout(
        target=target, installer=source_installer,
        source_receipt=source_receipt, extracted_root=extracted,
        destination=native_receipt, pin_file=review_pin,
    )
    return {
        "target": target, "installer": source_installer, "source_receipt": source_receipt,
        "native_receipt": native_receipt, "extracted_root": extracted,
        "pin_file": review_pin, "launcher": launcher, "java": java, "extra": extra,
        "destination": tmp_path / "audiveris-local-only.zip",
    }


def _assemble(a: dict) -> dict:
    return candidate.assemble_portable_candidate(**{
        key: a[key] for key in (
            "target", "installer", "source_receipt", "native_receipt",
            "extracted_root", "destination", "pin_file",
        )
    })


@pytest.mark.parametrize("target", ["windows-x86_64", "macos-aarch64"])
def test_actual_managed_installer_rehearsal_with_complete_owned_tree_is_pending_only(
    tmp_path: Path, monkeypatch, target: str,
):
    a = _fixture(tmp_path, monkeypatch, target)
    result = _assemble(a)
    assert result["target"] == target
    assert result["component"] == "audiveris"
    assert result["version"] == _VERSION
    assert result["local_managed_zip_install_verified"] is True
    assert result["relocated_audiveris_version_verified"] is True
    assert result["relocated_embedded_jre_version_verified"] is True
    assert result["full_omr_to_musicxml_verified"] is False
    assert result["verified_launcher_uses_embedded_java"] is False
    assert result["remote_artifact_published"] is False
    assert result["redistribution_status"] == "pending"
    assert result["approval_required"] is True
    assert result["member_count"] == 4
    assert _sha(a["destination"].read_bytes()) == result["archive_sha256"]
    assert json.loads(
        a["destination"].with_name(a["destination"].name + ".pending.json").read_text()
    ) == result
    with zipfile.ZipFile(a["destination"]) as archive:
        assert len(archive.namelist()) == 7
        paths = archive.namelist()
        assert result["tool_path"] in paths
        assert result["embedded_jre_path"] in paths
        assert "BUNDLE-INVENTORY.pending.json" in paths
        assert archive.getinfo(result["embedded_jre_path"]).create_system == 3
        assert all(".." not in Path(path).parts for path in paths)
    # Review does not update the actual managed catalog, install root or OS.
    assert a["launcher"].read_bytes() == b"synthetic-audiveris-launcher"


def test_repackaging_without_native_review_is_rejected(tmp_path: Path, monkeypatch):
    a = _fixture(tmp_path, monkeypatch, "windows-x86_64")
    a["native_receipt"].unlink()
    with pytest.raises(official.AudiverisReviewError, match="native"):
        _assemble(a)
    assert not a["destination"].exists()


def test_tampered_unreviewed_embedded_java_is_rejected(tmp_path: Path, monkeypatch):
    a = _fixture(tmp_path, monkeypatch, "macos-aarch64")
    a["java"].write_bytes(b"modified")
    with pytest.raises(official.AudiverisReviewError, match="drifted"):
        _assemble(a)
    assert not a["destination"].exists()


def test_modified_release_installer_is_rejected_before_local_install(tmp_path: Path, monkeypatch):
    a = _fixture(tmp_path, monkeypatch, "windows-x86_64")
    a["installer"].write_bytes(a["installer"].read_bytes() + b"tamper")
    with pytest.raises(official.AudiverisReviewError, match="name/size"):
        _assemble(a)
    assert not a["destination"].exists()


def test_symlink_or_unusual_file_in_app_tree_is_a_blocker_not_an_escape(
    tmp_path: Path, monkeypatch,
):
    a = _fixture(tmp_path, monkeypatch, "macos-aarch64")
    link = a["extra"].parent / "unsafe.jar"
    outside = tmp_path / "outside-data"
    outside.write_bytes(b"secret")
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Symlink unavailable on this runner")
    with pytest.raises(official.AudiverisReviewError, match="external/non-regular file symlink"):
        _assemble(a)
    assert not a["destination"].exists()
    assert outside.read_bytes() == b"secret"


def test_internal_file_link_is_safely_materialized_without_any_zip_symlinks(
    tmp_path: Path, monkeypatch,
):
    a = _fixture(tmp_path, monkeypatch, "macos-aarch64")
    link = a["extra"].parent / "ADDITIONAL_LICENSE_INFO"
    try:
        link.symlink_to(a["extra"].name)
    except OSError:
        pytest.skip("Symlinks unavailable on this runner")
    result = _assemble(a)
    assert result["internal_file_symlinks_materialized"] == 1
    assert result["external_symlinks_followed"] is False
    with zipfile.ZipFile(a["destination"]) as archive:
        name = "Audiveris.app/Contents/app/ADDITIONAL_LICENSE_INFO"
        assert archive.read(name) == a["extra"].read_bytes()
        assert stat.S_ISREG(archive.getinfo(name).external_attr >> 16)
        assert all(
            not stat.S_ISLNK(info.external_attr >> 16)
            for info in archive.infolist()
        )


def test_pending_receipt_cannot_claim_agpl_approval(tmp_path: Path, monkeypatch):
    a = _fixture(tmp_path, monkeypatch, "windows-x86_64")
    native_report = json.loads(a["native_receipt"].read_text(encoding="utf-8"))
    native_report["redistribution_status"] = "approved"
    a["native_receipt"].write_text(json.dumps(native_report), encoding="utf-8")
    with pytest.raises(official.AudiverisReviewError, match="falsely approves"):
        _assemble(a)
    assert not a["destination"].exists()


def test_preexisting_destination_is_never_overwritten(tmp_path: Path, monkeypatch):
    a = _fixture(tmp_path, monkeypatch, "windows-x86_64")
    a["destination"].write_bytes(b"existing-human-copy")
    with pytest.raises(FileExistsError, match="already exists"):
        _assemble(a)
    assert a["destination"].read_bytes() == b"existing-human-copy"


def test_wrong_native_architecture_is_rejected_before_repacking(tmp_path: Path, monkeypatch):
    a = _fixture(tmp_path, monkeypatch, "windows-x86_64")
    monkeypatch.setattr(candidate, "_platform_matches", lambda _t: False)
    with pytest.raises(official.AudiverisReviewError, match="native OS"):
        _assemble(a)


def test_malicious_symlink_directory_is_never_walked(tmp_path: Path, monkeypatch):
    a = _fixture(tmp_path, monkeypatch, "macos-aarch64")
    link = a["extra"].parent / "outside"
    try:
        link.symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip("Symlink unavailable")
    with pytest.raises(official.AudiverisReviewError, match="unsupported directory link"):
        _assemble(a)
    assert not a["destination"].exists()

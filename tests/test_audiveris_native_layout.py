"""Native Audiveris launcher/JRE contract tests use fake bytes and mocked subprocess."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import verify_audiveris_native_layout as native
from scripts.verify_audiveris_official_installer import (
    _MSI_HEADER,
    DEFAULT_PINS,
    verify_official_installer,
)


def _fake_asset(tmp_path: Path, target: str) -> tuple[Path, Path]:
    # Independent fixture: no tests/ package imports or externally downloaded bytes.
    pin = json.loads(DEFAULT_PINS.read_text(encoding="utf-8"))
    item = pin["sources"][target]
    source = tmp_path / item["asset"]
    payload = (
        _MSI_HEADER + b"\0" * 700
        if target == "windows-x86_64"
        else b"fixture-DMG-padding" * 40 + b"koly" + b"\0" * 508
    )
    source.write_bytes(payload)
    item["bytes"] = len(payload)
    item["sha256"] = hashlib.sha256(payload).hexdigest()
    pin_file = tmp_path / "pins.json"
    pin_file.write_text(json.dumps(pin), encoding="utf-8")
    return source, pin_file


def _fixture(tmp_path: Path, monkeypatch, target: str = "windows-x86_64"):
    installer, pin_file = _fake_asset(tmp_path, target)
    receipt = tmp_path / "SOURCE-EVIDENCE.pending.json"
    verify_official_installer(installer, target, pin_file=pin_file, output=receipt)
    extracted = tmp_path / "installer-extracted"
    extracted.mkdir()
    if target == "windows-x86_64":
        launcher = extracted / "Audiveris" / "Audiveris.exe"
        java = extracted / "Audiveris" / "runtime" / "bin" / "java.exe"
    else:
        launcher = extracted / "Audiveris.app" / "Contents" / "MacOS" / "Audiveris"
        java = (
            extracted / "Audiveris.app" / "Contents" / "runtime"
            / "Contents" / "Home" / "bin" / "java"
        )
    launcher.parent.mkdir(parents=True)
    java.parent.mkdir(parents=True)
    launcher.write_bytes(b"fixture-launcher")
    java.write_bytes(b"fixture-java")
    (java.parent.parent / "release").write_text(
        'JAVA_VERSION="25.0.2"\nMODULES="java.base java.desktop jdk.localedata"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(native, "_platform_matches", lambda arg: arg == target)
    calls = []
    def cli_version(binary, root, label):
        calls.append((binary, root, label))
        return (
            "Audiveris\n- Version:      5.11.0\n"
            if label == "audiveris"
            else 'openjdk version "25.0.2"\n'
        )
    monkeypatch.setattr(native, "_native_version", cli_version)
    return installer, pin_file, receipt, extracted, launcher, java, calls


@pytest.mark.parametrize("target", ["windows-x86_64", "macos-aarch64"])
def test_native_installer_launcher_and_bundled_jre_proof_is_pending_only(
    tmp_path: Path, monkeypatch, target: str,
):
    installer, pin_file, receipt, extracted, launcher, java, calls = _fixture(
        tmp_path, monkeypatch, target
    )
    result_file = tmp_path / "NATIVE-EVIDENCE.pending.json"
    report = native.verify_native_layout(
        target=target, installer=installer, source_receipt=receipt,
        extracted_root=extracted, destination=result_file, pin_file=pin_file,
    )
    assert [c[2] for c in calls] == ["embedded-jre", "audiveris"]
    assert report["launcher_sha256"] == native._sha256(launcher)
    assert report["jre_sha256"] == native._sha256(java)
    assert report["jre_declared_java_version"] == "25.0.2"
    assert report["embedded_jre_present"] is True
    assert report["embedded_java_executed_without_path"] is True
    assert report["audiveris_cli_executed_without_path"] is True
    assert report["audiveris_version_verified"] is True
    assert report["verified_launcher_uses_embedded_java"] is False
    assert report["portable_managed_zip_verified"] is False
    assert report["omr_musicxml_transcription_verified"] is False
    assert report["ocr_languages_installed_verified"] is False
    assert report["redistribution_status"] == "pending"
    assert report["agpl_source_notice_compliance_verified"] is False
    assert report["approval_required"] is True
    assert json.loads(result_file.read_text(encoding="utf-8")) == report


def test_missing_embedded_java_is_rejected_before_cli(tmp_path: Path, monkeypatch):
    installer, pin, receipt, root, _launcher, java, calls = _fixture(tmp_path, monkeypatch)
    java.unlink()
    with pytest.raises(native.AudiverisReviewError, match="embedded JRE"):
        native.verify_native_layout(
            target="windows-x86_64", installer=installer, source_receipt=receipt,
            extracted_root=root, destination=tmp_path / "rejected.json", pin_file=pin,
        )
    assert not calls


def test_modified_upstream_installer_is_rejected_before_cli(tmp_path: Path, monkeypatch):
    installer, pin, receipt, root, _launcher, _java, calls = _fixture(tmp_path, monkeypatch)
    installer.write_bytes(installer.read_bytes() + b"attack")
    with pytest.raises(native.AudiverisReviewError, match="changed since byte verification"):
        native.verify_native_layout(
            target="windows-x86_64", installer=installer, source_receipt=receipt,
            extracted_root=root, destination=tmp_path / "rejected.json", pin_file=pin,
        )
    assert not calls


def test_review_receipt_cannot_promote_approval(tmp_path: Path, monkeypatch):
    installer, pin, receipt, root, _launcher, _java, calls = _fixture(tmp_path, monkeypatch)
    report = json.loads(receipt.read_text(encoding="utf-8"))
    report["redistribution_status"] = "approved"
    receipt.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(native.AudiverisReviewError, match="missing or inconsistent"):
        native.verify_native_layout(
            target="windows-x86_64", installer=installer, source_receipt=receipt,
            extracted_root=root, destination=tmp_path / "rejected.json", pin_file=pin,
        )
    assert not calls


def test_wrong_native_os_never_uses_third_party_binary(tmp_path: Path, monkeypatch):
    installer, pin, receipt, root, _launcher, _java, calls = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(native, "_platform_matches", lambda _target: False)
    with pytest.raises(native.AudiverisReviewError, match="target OS"):
        native.verify_native_layout(
            target="windows-x86_64", installer=installer, source_receipt=receipt,
            extracted_root=root, destination=tmp_path / "rejected.json", pin_file=pin,
        )
    assert not calls


def test_launcher_version_mismatch_does_not_generate_receipt(tmp_path: Path, monkeypatch):
    installer, pin, receipt, root, _launcher, _java, _calls = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(native, "_native_version", lambda _b, _r, label: (
        "Audiveris 5.10.2" if label == "audiveris" else "openjdk version 25"
    ))
    with pytest.raises(native.AudiverisReviewError, match="pinned 5.11.0"):
        native.verify_native_layout(
            target="windows-x86_64", installer=installer, source_receipt=receipt,
            extracted_root=root, destination=tmp_path / "rejected.json", pin_file=pin,
        )
    assert not (tmp_path / "rejected.json").exists()


def test_symlinked_launcher_is_never_invoked(tmp_path: Path, monkeypatch):
    installer, pin, receipt, root, launcher, _java, calls = _fixture(tmp_path, monkeypatch)
    launcher.unlink()
    outside = tmp_path / "outside"
    outside.write_bytes(b"outside-launcher")
    try:
        launcher.symlink_to(outside)
    except OSError:
        pytest.skip("Symlinks unavailable")
    with pytest.raises(native.AudiverisReviewError, match="one native launcher"):
        native.verify_native_layout(
            target="windows-x86_64", installer=installer, source_receipt=receipt,
            extracted_root=root, destination=tmp_path / "rejected.json", pin_file=pin,
        )
    assert not calls
    assert outside.read_bytes() == b"outside-launcher"


def test_jre_release_metadata_must_be_complete(tmp_path: Path, monkeypatch):
    installer, pin, receipt, root, _launcher, java, calls = _fixture(tmp_path, monkeypatch)
    (java.parent.parent / "release").write_text('JAVA_VERSION="25"\n', encoding="utf-8")
    with pytest.raises(native.AudiverisReviewError, match="version/modules"):
        native.verify_native_layout(
            target="windows-x86_64", installer=installer, source_receipt=receipt,
            extracted_root=root, destination=tmp_path / "rejected.json", pin_file=pin,
        )
    assert not calls


def test_native_launch_command_has_no_path_fallback(tmp_path: Path, monkeypatch):
    executable = tmp_path / "Audiveris.exe"
    executable.write_bytes(b"fake")
    seen = {}
    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        return type("Result", (), {
            "returncode": 0,
            "stdout": "Audiveris\nVersion 5.11.0\n",
            "stderr": "",
        })()
    monkeypatch.setattr(native.subprocess, "run", fake_run)
    output = native._native_version(executable, tmp_path, "audiveris")
    assert "5.11.0" in output
    assert seen["argv"] == [str(executable), "-version"]
    assert seen["kwargs"]["env"]["PATH"] == ""
    assert seen["kwargs"]["shell"] is False
    assert seen["kwargs"]["timeout"] <= 90

def test_windows_jvm_keeps_shell_folder_paths_but_has_no_path_fallback(
    tmp_path: Path, monkeypatch,
):
    launcher = tmp_path / "Audiveris.exe"
    launcher.write_bytes(b"fake")
    monkeypatch.setenv("USERPROFILE", r"C:\Users\runneradmin")
    monkeypatch.setenv("APPDATA", r"C:\Users\runneradmin\AppData\Roaming")
    monkeypatch.setattr(native.platform, "system", lambda: "Windows")
    observed = {}

    def run(_argv, **kwargs):
        observed.update(kwargs)
        return type("Result", (), {
            "returncode": 0, "stdout": "Audiveris Version: 5.11.0", "stderr": "",
        })()

    monkeypatch.setattr(native.subprocess, "run", run)
    native._native_version(launcher, tmp_path, "audiveris")
    assert observed["env"]["PATH"] == ""
    assert observed["env"]["USERPROFILE"] == r"C:\Users\runneradmin"
    assert observed["env"]["APPDATA"] == r"C:\Users\runneradmin\AppData\Roaming"
    assert observed["shell"] is False


def test_macos_uses_isolated_home_without_ambient_executables(
    tmp_path: Path, monkeypatch,
):
    java = tmp_path / "java"
    java.write_bytes(b"fake")
    monkeypatch.setattr(native.platform, "system", lambda: "Darwin")
    observed = {}

    def run(_argv, **kwargs):
        observed.update(kwargs)
        return type("Result", (), {
            "returncode": 0, "stdout": "", "stderr": 'openjdk version "25.0.2"',
        })()

    monkeypatch.setattr(native.subprocess, "run", run)
    native._native_version(java, tmp_path, "embedded-jre")
    assert observed["env"]["PATH"] == ""
    assert observed["env"]["HOME"] == str(tmp_path)
    assert observed["env"]["XDG_CONFIG_HOME"] == str(tmp_path)


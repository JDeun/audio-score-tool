"""Synthetic contract tests; real FFmpeg source binaries run only in native review CI."""
from __future__ import annotations

import json
import struct
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import verify_ffmpeg_native_build as native


def _fake_pe() -> bytes:
    data = bytearray(b"MZ" + b"\x00" * 254)
    data[60:64] = (128).to_bytes(4, "little")
    data[128:134] = b"PE\x00\x00\x64\x86"
    return bytes(data) + b"synthetic-test-fixture"


def _fake_macho() -> bytes:
    return b"\xcf\xfa\xed\xfe" + struct.pack("<I", 0x0100000C) + b"synthetic-test-fixture"


def _fixture(tmp_path: Path, monkeypatch, target: str = "windows-x86_64"):
    pin = json.loads(native.DEFAULT_PIN.read_text(encoding="utf-8"))
    pin_file = tmp_path / "pin.json"
    pin_file.write_text(json.dumps(pin), encoding="utf-8")
    source = tmp_path / "ffmpeg-src"
    source.mkdir()
    (source / "LICENSE.md").write_text("Test-only LGPL text, not genuine FFmpeg license\n")
    suffix = ".exe" if target == "windows-x86_64" else ""
    binary = _fake_pe() if suffix else _fake_macho()
    for name in ("ffmpeg", "ffprobe"):
        (source / (name + suffix)).write_bytes(binary + name.encode())

    monkeypatch.setattr(
        native.platform, "system",
        lambda: "Windows" if target == "windows-x86_64" else "Darwin",
    )
    monkeypatch.setattr(
        native.platform, "machine",
        lambda: "AMD64" if target == "windows-x86_64" else "arm64",
    )
    calls: list[tuple[str, list[str]]] = []

    def fake_run(argv, *, cwd, env=None, timeout=30, label):
        calls.append((label, argv))
        if label == "git-source":
            return pin["source_commit"] + "\n"
        assert Path(argv[0]).is_absolute(), "Executable may not be taken from PATH"
        assert str(Path(argv[0]).parent) == str(source)
        assert env["PATH"] == ""
        assert env["PYTHONNOUSERSITE"] == "1"
        if label in {"ffmpeg-version", "ffprobe-version"}:
            name = label.removesuffix("-version")
            return (
                f"{name} version {pin['version']} Copyright (c) CI-owned-fixture\n"
                "built with owned-test-compiler 1.0\n"
                "configuration: " + " ".join(
                    [*pin["configure_flags"], *pin["target_configure_flags"][target]]
                ) + "\n"
                "libavutil 1.0.0 / 1.0.0\n"
            )
        if label == "synthetic-PCM-generation":
            assert argv[1:4] == ["-hide_banner", "-loglevel", "error"]
            assert "-nostdin" in argv and "-f" in argv and "lavfi" in argv
            assert "sine=frequency=440:sample_rate=44100:duration=0.25" in argv
            Path(argv[-1]).write_bytes(b"synthetic PCM" * 300)
            return ""
        if label == "synthetic-PCM-probe":
            return json.dumps({"streams": [{"codec_name": "pcm_s16le", "sample_rate": "44100"}]})
        raise AssertionError(f"Unexpected native probe: {label}")

    monkeypatch.setattr(native, "_run", fake_run)
    return pin, pin_file, source, calls


@pytest.mark.parametrize("target", ["windows-x86_64", "macos-aarch64"])
def test_local_native_review_binds_real_bytes_versions_and_offline_attestation(
    tmp_path: Path, monkeypatch, target: str,
):
    pin, pin_file, source, calls = _fixture(tmp_path, monkeypatch, target)
    destination = tmp_path / "evidence"
    evidence = native.verify_native_build(
        source=source, target=target, destination=destination, pin_file=pin_file,
    )
    assert [entry[0] for entry in calls] == [
        "git-source", "ffmpeg-version", "ffprobe-version",
        "synthetic-PCM-generation", "synthetic-PCM-probe",
    ]
    assert evidence["source_commit"] == pin["source_commit"]
    assert evidence["configure_flags"] == [
        *pin["configure_flags"], *pin["target_configure_flags"][target]
    ]
    assert evidence["binary_execution_verified"] is True
    assert evidence["synthetic_pcm_wav_produced"] is True
    assert evidence["synthetic_audio_codec"] == "pcm_s16le"
    assert evidence["synthetic_audio_sample_rate"] == 44100
    assert evidence["redistribution_status"] == "pending"
    assert evidence["reproducible_rebuild_verified"] is False
    assert evidence["system_linkage_independently_inspected"] is False
    assert evidence["source_signature_verified"] is False
    assert evidence["catalog_published"] is False
    assert set(evidence["tools"]) == {"ffmpeg", "ffprobe"}
    assert json.loads((destination / "NATIVE-FFMPEG-EVIDENCE.pending.json").read_text()) == evidence
    offline = json.loads((destination / "FFMPEG-BUILD-REVIEW.pending.json").read_text())
    assert offline["inferred_license"] == "LGPL-2.1-or-later"
    assert offline["binary_execution_verified"] is False  # Offline reviewer stays honest
    assert offline["redistribution_status"] == "pending"
    assert offline["source_revision"] == pin["source_commit"]


def test_wrong_host_never_runs_ffmpeg(tmp_path: Path, monkeypatch):
    _pin, pin_file, source, calls = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(native.platform, "machine", lambda: "aarch64")
    with pytest.raises(native.FFmpegNativeReviewError, match="exact target OS/CPU"):
        native.verify_native_build(
            source=source, target="windows-x86_64",
            destination=tmp_path / "unsafe", pin_file=pin_file,
        )
    assert calls == []


def test_changed_checkout_commit_is_refused_before_binary_execution(tmp_path: Path, monkeypatch):
    _pin, pin_file, source, calls = _fixture(tmp_path, monkeypatch)
    original = native._run

    def wrong_commit(argv, **kwargs):
        if kwargs["label"] == "git-source":
            return "0" * 40
        return original(argv, **kwargs)

    monkeypatch.setattr(native, "_run", wrong_commit)
    with pytest.raises(native.FFmpegNativeReviewError, match="pinned official commit"):
        native.verify_native_build(
            source=source, target="windows-x86_64",
            destination=tmp_path / "unsafe", pin_file=pin_file,
        )
    assert calls == []
    assert not (tmp_path / "unsafe").exists()


def test_version_output_is_checked_against_official_tag(tmp_path: Path, monkeypatch):
    pin, pin_file, source, _ = _fixture(tmp_path, monkeypatch)
    original = native._run

    def stale_version(argv, **kwargs):
        result = original(argv, **kwargs)
        if kwargs["label"] == "ffmpeg-version":
            return result.replace(pin["version"], "n8.0.0", 1)
        return result

    monkeypatch.setattr(native, "_run", stale_version)
    with pytest.raises(native.FFmpegNativeReviewError, match="native version differs"):
        native.verify_native_build(
            source=source, target="windows-x86_64",
            destination=tmp_path / "unsafe", pin_file=pin_file,
        )
    assert not (tmp_path / "unsafe").exists()


def test_actual_configure_flag_drift_fails_before_audio_probe(tmp_path: Path, monkeypatch):
    _pin, pin_file, source, calls = _fixture(tmp_path, monkeypatch)
    original = native._run

    def changed_flags(argv, **kwargs):
        result = original(argv, **kwargs)
        if kwargs["label"] == "ffprobe-version":
            return result.replace("--disable-autodetect", "--enable-autodetect")
        return result

    monkeypatch.setattr(native, "_run", changed_flags)
    with pytest.raises(native.FFmpegNativeReviewError, match="configure flags differ"):
        native.verify_native_build(
            source=source, target="windows-x86_64",
            destination=tmp_path / "unsafe", pin_file=pin_file,
        )
    assert all("synthetic" not in label for label, _ in calls)


def test_mutated_native_tool_bytes_after_probe_are_rejected(tmp_path: Path, monkeypatch):
    _pin, pin_file, source, _ = _fixture(tmp_path, monkeypatch)
    original = native._run

    def modify_ffmpeg(argv, **kwargs):
        result = original(argv, **kwargs)
        if kwargs["label"] == "ffmpeg-version":
            binary = source / "ffmpeg.exe"
            binary.write_bytes(binary.read_bytes() + b"tampered")
        return result

    monkeypatch.setattr(native, "_run", modify_ffmpeg)
    with pytest.raises(native.FFmpegNativeReviewError, match="changed during native version probe"):
        native.verify_native_build(
            source=source, target="windows-x86_64",
            destination=tmp_path / "unsafe", pin_file=pin_file,
        )


def test_invalid_pcm_probe_does_not_publish_any_evidence(tmp_path: Path, monkeypatch):
    _pin, pin_file, source, _ = _fixture(tmp_path, monkeypatch)
    original = native._run

    def wrong_codec(argv, **kwargs):
        if kwargs["label"] == "synthetic-PCM-probe":
            return json.dumps({"streams": [{"codec_name": "aac", "sample_rate": "44100"}]})
        return original(argv, **kwargs)

    monkeypatch.setattr(native, "_run", wrong_codec)
    with pytest.raises(native.FFmpegNativeReviewError, match="PCM codec/rate"):
        native.verify_native_build(
            source=source, target="windows-x86_64",
            destination=tmp_path / "unsafe", pin_file=pin_file,
        )
    assert not (tmp_path / "unsafe").exists()


def test_bad_source_license_status_is_refused_without_execution(tmp_path: Path, monkeypatch):
    pin, pin_file, source, calls = _fixture(tmp_path, monkeypatch)
    pin["redistribution_status"] = "approved"
    pin_file.write_text(json.dumps(pin), encoding="utf-8")
    with pytest.raises(native.FFmpegNativeReviewError, match="unapproved pinned"):
        native.verify_native_build(
            source=source, target="windows-x86_64",
            destination=tmp_path / "unsafe", pin_file=pin_file,
        )
    assert calls == []


def test_existing_review_receipt_directory_cannot_be_overwritten(tmp_path: Path, monkeypatch):
    _pin, pin_file, source, calls = _fixture(tmp_path, monkeypatch)
    existing = tmp_path / "evidence"
    existing.mkdir()
    (existing / "human-review.txt").write_text("preserve")
    with pytest.raises(native.FFmpegNativeReviewError, match="Evidence output directory"):
        native.verify_native_build(
            source=source, target="windows-x86_64",
            destination=existing, pin_file=pin_file,
        )
    assert calls == []
    assert (existing / "human-review.txt").read_text() == "preserve"


@pytest.mark.parametrize("exception", [
    OSError("binary cannot execute"),
    subprocess.TimeoutExpired("ffmpeg", 20),
])
def test_command_launch_error_or_timeout_is_bounded(exception, tmp_path: Path, monkeypatch):
    cwd = tmp_path
    def failed(*_args, **_kwargs):
        raise exception
    monkeypatch.setattr(native.subprocess, "run", failed)
    with pytest.raises(native.FFmpegNativeReviewError, match="native process could not complete"):
        native._run(["/absolute/ffmpeg", "-version"], cwd=cwd, label="ffmpeg-version")


def test_nonzero_ffmpeg_exit_is_rejected(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        native.subprocess, "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="bad", returncode=1),
    )
    with pytest.raises(native.FFmpegNativeReviewError, match="native process failed"):
        native._run(["/absolute/ffmpeg", "-version"], cwd=tmp_path, label="ffmpeg-version")


def test_native_review_workflow_is_scoped_and_does_not_publish_binaries():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/ffmpeg-native-build-review.yml").read_text()
    assert "windows-2025" in workflow
    assert "macos-15" in workflow
    assert "946fcce07b6dcd0331c8cc609192aeff5e1924f8" in workflow
    assert "scripts/verify_ffmpeg_native_build.py" in workflow
    assert "--disable-gpl" in workflow
    assert "--disable-nonfree" in workflow
    assert "--disable-autodetect" in workflow
    assert "NATIVE-FFMPEG-EVIDENCE.pending.json" in workflow
    assert "FFMPEG-BUILD-REVIEW.pending.json" in workflow
    assert "actions/upload-artifact@" in workflow
    assert "desktop-packages.yml" not in workflow
    assert "ffmpeg.exe" not in workflow.split("Upload metadata-only FFmpeg provenance evidence")[1]
    assert "tier2-actual-models.yml" not in workflow


def test_windows_dynamic_runtime_dependency_must_fail_preflight(tmp_path: Path, monkeypatch):
    pin, pin_file, source, calls = _fixture(tmp_path, monkeypatch)
    pin["target_configure_flags"]["windows-x86_64"] = []
    pin_file.write_text(json.dumps(pin), encoding="utf-8")
    with pytest.raises(native.FFmpegNativeReviewError, match="statically link MinGW"):
        native.verify_native_build(
            source=source, target="windows-x86_64",
            destination=tmp_path / "unsafe", pin_file=pin_file,
        )
    assert calls == []


def test_macos_rejects_unreviewed_fully_static_linker_setting(tmp_path: Path, monkeypatch):
    pin, pin_file, source, calls = _fixture(tmp_path, monkeypatch, "macos-aarch64")
    pin["target_configure_flags"]["macos-aarch64"] = ["--extra-ldflags=-static"]
    pin_file.write_text(json.dumps(pin), encoding="utf-8")
    with pytest.raises(native.FFmpegNativeReviewError, match="macOS must not claim"):
        native.verify_native_build(
            source=source, target="macos-aarch64",
            destination=tmp_path / "unsafe", pin_file=pin_file,
        )
    assert calls == []

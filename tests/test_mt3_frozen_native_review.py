"""Private native MT3 PyInstaller build review: synthetic offline unit contracts."""
from __future__ import annotations

import hashlib
import json
import os
import runpy
import subprocess
import sys
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

from audio_score_tool.managed_tool_resolver import registered_managed_tool
from scripts import verify_mt3_frozen_native as qa


def test_review_freezer_collects_upstream_registry_and_lazy_mr_mt3_adapter(tmp_path: Path):
    cmd = qa.pyinstaller_command(
        dist=tmp_path / "dist", work=tmp_path / "work", specs=tmp_path / "spec",
    )
    assert cmd[:3] == [qa.sys.executable, "-m", "PyInstaller"]
    assert "--onefile" in cmd and "--noupx" in cmd
    assert "mt3_infer" in cmd
    assert "mt3_infer.adapters.mr_mt3" in cmd
    assert "mt3_infer.models.mr_mt3.t5" in cmd
    assert "transformers.models.t5.modeling_t5" in cmd
    assert "tensorflow" in cmd and "jax" in cmd and "flax" in cmd
    assert str(qa._ENTRY) == cmd[-1]
    assert "--windowed" not in cmd


def test_pinned_build_metadata_rejects_missing_or_drifting_versions(monkeypatch):
    monkeypatch.setattr(
        qa, "version", lambda name: "1.0.0" if name == "torch" else qa._EXPECTED[name],
    )
    with pytest.raises(qa.FrozenMT3ReviewError, match="torch"):
        qa._pinned_packages()
    monkeypatch.setattr(qa, "version", lambda name: qa._EXPECTED[name])
    assert qa._pinned_packages() == qa._EXPECTED


def test_qa_zip_contains_only_frozen_binary_and_explicit_pending_provenance(tmp_path: Path):
    binary = tmp_path / "original-native.bin"
    binary.write_bytes(b"MZ" + b"synthetic" * 240)
    archive = tmp_path / "private-qa.zip"
    proof = {"schema": 1, "redistribution_status": "pending"}
    qa._private_zip(archive, binary, proof)
    with zipfile.ZipFile(archive) as zipped:
        contents = set(zipped.namelist())
        assert f"bin/mt3-infer{'.exe' if os.name == 'nt' else ''}" in contents
        assert "provenance/frozen-native-qa.pending.json" in contents
        extracted = zipped.read(
            f"bin/mt3-infer{'.exe' if os.name == 'nt' else ''}"
        )
        assert extracted == binary.read_bytes()
        parsed = json.loads(zipped.read("provenance/frozen-native-qa.pending.json"))
        assert parsed["redistribution_status"] == "pending"
        assert len(contents) == 2
        assert all(x.compress_type == zipfile.ZIP_STORED for x in zipped.infolist())


def test_real_product_installer_is_used_for_synthetic_native_binary_without_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(qa, "_native_target", lambda *_args: None)
    monkeypatch.setattr(qa, "_pinned_packages", lambda: dict(qa._EXPECTED))
    calls = []

    def fake_pyinstaller(cmd, *, cwd, check):
        calls.append("freeze")
        assert check and cwd == qa._ROOT
        path = Path(cmd[cmd.index("--distpath") + 1])
        path.mkdir(parents=True)
        fake = path / f"mt3-infer{'.exe' if os.name == 'nt' else ''}"
        fake.write_bytes(b"fake-frozen-executable" * 60000)
        return subprocess.CompletedProcess(cmd, 0)

    def fake_native_probe(root: Path, managed_name: str, *, model: str):
        calls.append("verify-real-registered-owner")
        assert model == "mr_mt3"
        assert os.getenv("AST_PACKAGED") == "1"
        assert os.getenv("PATH") == ""
        executable = registered_managed_tool(
            "mt3-infer", component="transcription_engine",
        )
        assert executable is not None and executable.name == managed_name
        assert executable.read_bytes() == b"fake-frozen-executable" * 60000
        return {
            "version": True, "models": True, "transcribe-help": True,
            "checkpoint_download_disabled": True,
            "system_path_fallback_disabled": True,
        }

    monkeypatch.setattr(qa.subprocess, "run", fake_pyinstaller)
    monkeypatch.setattr(qa, "_probe_managed_native", fake_native_probe)
    proof = qa.build_and_verify_native(
        target="macos-aarch64",
        destination=tmp_path / "private-runtime-report.pending.json",
    )
    assert calls == ["freeze", "verify-real-registered-owner"]
    assert proof["target"] == "macos-aarch64"
    assert proof["managed_installer_verified"] is True
    assert proof["whole_payload_sha256_verified"] is True
    assert proof["native_host_python_not_required_for_startup"] is True
    assert proof["actual_model_inference_verified"] is False
    assert proof["runtime_redistribution_approved"] is False
    assert proof["model_checkpoint_included"] is False
    assert proof["binaries_uploaded"] is False
    assert proof["redistribution_status"] == "pending"
    assert len(proof["native_executable_sha256"]) == 64
    assert proof["native_executable_sha256"] == hashlib.sha256(
        b"fake-frozen-executable" * 60000,
    ).hexdigest()
    assert not (tmp_path / "private-runtime-report.pending.json").exists()


def test_failed_native_build_never_emits_success_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(qa, "_native_target", lambda *_args: None)
    monkeypatch.setattr(qa, "_pinned_packages", lambda: dict(qa._EXPECTED))

    def failing_build(cmd, *, cwd, check):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(qa.subprocess, "run", failing_build)
    with pytest.raises(subprocess.CalledProcessError):
        qa.build_and_verify_native(
            target="windows-x86_64", destination=tmp_path / "missing-proof.json",
        )
    assert not (tmp_path / "missing-proof.json").exists()


def test_native_review_workflow_prohibits_binary_uploads():
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github/workflows/mt3-frozen-native-review.yml"
    ).read_text(encoding="utf-8")
    assert "windows-2025" in workflow and "macos-15" in workflow
    assert "torch==2.7.1" in workflow
    assert "mt3-infer[torch]==0.2.0" in workflow
    assert "verify_mt3_frozen_native.py" in workflow
    uploader = workflow.split("Publish only pending JSON, not the frozen executable", 1)[1]
    assert "pending.json" in uploader
    assert "*.exe" not in uploader
    assert "*.zip" not in uploader
    assert "MT3-FROZEN-NATIVE-QA" in uploader

@pytest.mark.parametrize(
    ("failure_kind", "accepted"),
    [
        ("expected_checkpoint", True),
        ("unrelated_file", False),
        ("wrong_checkpoint", False),
        ("checkpoint_suffix", False),
    ],
)
def test_native_probe_rejects_unrelated_missing_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
    accepted: bool,
):
    """A missing DLL/resource cannot masquerade as an absent model checkpoint."""
    native = tmp_path / "mt3-infer"
    native.write_bytes(b"private-frozen-cli")
    monkeypatch.setattr(
        qa, "registered_managed_tool", lambda *_args, **_kw: native,
    )
    expected_path = (
        tmp_path / "intentionally-absent-checkpoints" / "mr_mt3" / "mt3.pth"
    )
    failures = {
        "expected_checkpoint": (
            f"Transcribing with mr_mt3...\\n"
            f"Transcription failed: Checkpoint not found: {expected_path}"
        ),
        "unrelated_file": "OSError: libtorch_cpu.dll: No such file or directory",
        "wrong_checkpoint": (
            f"Transcription failed: Checkpoint not found: {tmp_path / 'other.pth'}"
        ),
        "checkpoint_suffix": (
            f"Checkpoint not found: {expected_path}.unexpected"
        ),
    }

    def fake_command(command, args, *, env, timeout_seconds):
        assert command == str(native) and timeout_seconds == 180
        assert env["PATH"] == ""
        assert env["PYTHONPATH"] == "" and env["PYTHONHOME"] == ""
        assert env["PYTHONIOENCODING"] == "utf-8" and env["PYTHONUTF8"] == "1"
        assert env["HF_HUB_OFFLINE"] == "1"
        if args == ["--version"]:
            output = "mt3-infer 0.2.0"
        elif args == ["list"]:
            output = "Models: mr_mt3"
        elif args == ["transcribe", "--help"]:
            output = "Usage: transcribe --no-download"
        else:
            assert args[0] == "transcribe" and "--no-download" in args
            raise qa.CommandError(failures[failure_kind])
        return subprocess.CompletedProcess(args, 0, stdout=output)

    monkeypatch.setattr(qa, "run_command", fake_command)
    if accepted:
        proof = qa._probe_managed_native(tmp_path, native.name, model="mr_mt3")
        assert proof["checkpoint_download_disabled"] is True
        assert proof["dynamic_mr_mt3_adapter_reached"] is True
    else:
        with pytest.raises(
            qa.FrozenMT3ReviewError, match="other than its absent checkpoint",
        ):
            qa._probe_managed_native(tmp_path, native.name, model="mr_mt3")
    assert not expected_path.exists()


@pytest.mark.parametrize(
    ("platform_name", "frozen", "expected"),
    [
        ("win32", True, True),
        ("win32", False, False),
        ("darwin", True, False),
    ],
)
def test_native_entrypoint_sets_utf8_for_isolated_windows_frozen_cli(
    monkeypatch: pytest.MonkeyPatch,
    platform_name: str,
    frozen: bool,
    expected: bool,
):
    """Frozen Python ignores PYTHONIOENCODING; stdio must be set in the entry."""
    class RecordingStream:
        def __init__(self):
            self.calls = []

        def reconfigure(self, **kwargs):
            self.calls.append(kwargs)

    stdout = RecordingStream()
    stderr = RecordingStream()
    package = ModuleType("mt3_infer")
    package.__path__ = []
    cli = ModuleType("mt3_infer.cli")
    cli.main = lambda: 0

    with monkeypatch.context() as mp:
        mp.setitem(sys.modules, "mt3_infer", package)
        mp.setitem(sys.modules, "mt3_infer.cli", cli)
        mp.setattr(sys, "platform", platform_name)
        mp.setattr(sys, "frozen", frozen, raising=False)
        mp.setattr(sys, "stdout", stdout)
        mp.setattr(sys, "stderr", stderr)
        result = runpy.run_path(str(qa._ENTRY), run_name="native_mt3_entry_test")
        assert result["main"]() == 0

    expected_calls = [{"encoding": "utf-8", "errors": "backslashreplace"}] if expected else []
    assert stdout.calls == expected_calls
    assert stderr.calls == expected_calls

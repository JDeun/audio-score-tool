"""Private native MT3 PyInstaller build review: synthetic offline unit contracts."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import zipfile
from pathlib import Path

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

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

def test_native_entrypoint_sets_utf8_for_isolated_windows_frozen_cli(
    monkeypatch: pytest.MonkeyPatch,
):
    """The frozen app must configure Unicode output without Python env options."""
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
        mp.setattr(sys, "platform", "win32")
        mp.setattr(sys, "frozen", True, raising=False)
        mp.setattr(sys, "stdout", stdout)
        mp.setattr(sys, "stderr", stderr)
        with pytest.raises(SystemExit) as result:
            runpy.run_path(str(qa._ENTRY), run_name="__main__")
        assert result.value.code == 0

    for stream in (stdout, stderr):
        assert len(stream.calls) == 1
        assert stream.calls[0]["encoding"] == "utf-8"
        assert stream.calls[0]["errors"] in {"replace", "backslashreplace"}


def test_native_review_private_archive_with_real_weights(tmp_path: Path):
    """Real weights remain runner-local but must be inventoried inside managed ZIP."""
    binary = tmp_path / "mt3-infer.bin"
    binary.write_bytes(b"MZ" + b"synthetic-frozen")
    weight = tmp_path / "mt3.pth"
    weight.write_bytes(b"test-checkpoint" * 1000)
    archive = tmp_path / "not-for-publication.zip"
    qa._private_zip(
        archive, binary, {"redistribution_status": "pending"}, checkpoint=weight,
    )
    with zipfile.ZipFile(archive) as package:
        assert sorted(package.namelist()) == sorted([
            f"bin/mt3-infer{'.exe' if os.name == 'nt' else ''}",
            "provenance/frozen-native-qa.pending.json",
            "checkpoints/mr_mt3/mt3.pth",
        ])
        assert package.read("checkpoints/mr_mt3/mt3.pth") == weight.read_bytes()
        assert package.read("bin/mt3-infer" + (".exe" if os.name == "nt" else "")) == binary.read_bytes()
        assert all(info.compress_type == zipfile.ZIP_STORED for info in package.infolist())


def test_native_checkpoint_requires_exact_reviewed_bytes_and_refuses_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    root = tmp_path / "review-only"
    selected = root / "mr_mt3"
    selected.mkdir(parents=True)
    weight = selected / "mt3.pth"
    bytes_original = b"a" * (1024 * 1024)
    weight.write_bytes(bytes_original)
    monkeypatch.setattr(qa, "_MR_MT3_SHA256", hashlib.sha256(bytes_original).hexdigest())
    assert qa._trusted_checkpoint(root) == weight

    weight.write_bytes(b"b" * len(bytes_original))
    with pytest.raises(qa.FrozenMT3ReviewError, match="SHA-256"):
        qa._trusted_checkpoint(root)

    weight.unlink()
    other = tmp_path / "untrusted.pth"
    other.write_bytes(bytes_original)
    weight.symlink_to(other)
    with pytest.raises(qa.FrozenMT3ReviewError, match="missing or linked"):
        qa._trusted_checkpoint(root)


def test_native_model_evidence_is_explicitly_opt_in_and_never_approved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    checkpoint = tmp_path / "runner-only-checkpoint.pth"
    checkpoint.write_bytes(b"fake-source-weight")
    download_root = tmp_path / "review-checkpoints"
    download_root.mkdir()
    monkeypatch.setattr(qa, "_trusted_checkpoint", lambda root: checkpoint)
    monkeypatch.setattr(qa, "_native_target", lambda *_args: None)
    monkeypatch.setattr(qa, "_pinned_packages", lambda: dict(qa._EXPECTED))
    called = []

    def build(cmd, *, cwd, check):
        assert check and cwd == qa._ROOT
        binary_dir = Path(cmd[cmd.index("--distpath") + 1])
        binary_dir.mkdir(parents=True)
        (binary_dir / f"mt3-infer{'.exe' if os.name == 'nt' else ''}").write_bytes(
            b"MZ" + b"native-frozen-fixture" * 70000,
        )
        called.append("build")
        return subprocess.CompletedProcess(cmd, 0)

    def simple_probe(*_args, **_kwargs):
        called.append("missing-checkpoint-probe")
        return {"checkpoint_download_disabled": True}

    def actual_probe(*, base, binary, managed, checkpoint, manifest, executable_sha):
        called.append("real-model-probe")
        assert checkpoint.read_bytes() == b"fake-source-weight"
        assert binary.is_file() and managed.is_dir() and base.is_dir()
        assert executable_sha == qa._sha256(binary)
        assert manifest["model_weights_included"] is False
        return {"actual_cpu_model_inference_verified": True, "note_counts": {"notes": 12}}

    monkeypatch.setattr(qa.subprocess, "run", build)
    monkeypatch.setattr(qa, "_probe_managed_native", simple_probe)
    monkeypatch.setattr(qa, "_probe_native_real_inference", actual_probe)
    result = qa.build_and_verify_native(
        target="macos-aarch64",
        destination=tmp_path / "private-real-model.pending.json",
        checkpoint_directory=download_root,
    )
    assert called == ["build", "missing-checkpoint-probe", "real-model-probe"]
    assert result["actual_model_inference_verified"] is True
    assert result["real_native_inference"]["note_counts"]["notes"] == 12
    assert result["runtime_redistribution_approved"] is False
    assert result["binaries_uploaded"] is False
    assert result["windows_macos_clean_machine_verified"] is False
    assert not (tmp_path / "private-real-model.pending.json").exists()


def test_native_workflow_runs_real_model_and_uploads_only_pending_json():
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github/workflows/mt3-frozen-native-review.yml"
    ).read_text(encoding="utf-8")
    assert "python -X utf8 -m mt3_infer.cli download mr_mt3" in workflow
    assert "PYTHONIOENCODING: utf-8" in workflow and "PYTHONUTF8: '1'" in workflow
    assert "--checkpoint-dir" in workflow
    assert qa._MR_MT3_SHA256 in workflow
    assert "music21==10.5.0" in workflow
    upload_step = workflow.split("Publish only pending JSON, not the frozen executable", 1)[1]
    assert "MT3-FROZEN-NATIVE-QA" in upload_step
    assert ".pending.json" in upload_step
    assert ".pth" not in upload_step and ".zip" not in upload_step and "*.exe" not in upload_step

def test_private_native_candidate_staging_is_atomic_and_not_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """An operator may retain verified bytes, but never overwrite or use CI."""
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    staging_dir = tmp_path / "operator-private"
    staging_dir.mkdir()
    destination = qa._private_candidate_destination(
        staging_dir, target="macos-aarch64",
    )
    source = tmp_path / "real-private-qa.zip"
    source.write_bytes(b"private-unapproved-model-archive" * 40)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()

    qa._stage_private_candidate(source, destination, expected_sha256=digest)
    assert destination.read_bytes() == source.read_bytes()
    assert destination.name == "MT3-MRMT3-macos-aarch64-UNAPPROVED.zip"
    if os.name != "nt":
        assert destination.stat().st_mode & 0o077 == 0
    assert not list(staging_dir.glob(".mt3-unapproved-*"))
    with pytest.raises(qa.FrozenMT3ReviewError, match="already exists"):
        qa._private_candidate_destination(staging_dir, target="macos-aarch64")
    with pytest.raises(qa.FrozenMT3ReviewError, match="already exists"):
        qa._stage_private_candidate(source, destination, expected_sha256=digest)
    assert destination.read_bytes() == source.read_bytes()


def test_private_candidate_rejects_ci_repo_path_and_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    staging_dir = tmp_path / "operator-private"
    staging_dir.mkdir()
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    with pytest.raises(qa.FrozenMT3ReviewError, match="GitHub Actions"):
        qa._private_candidate_destination(staging_dir, target="macos-aarch64")

    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    with pytest.raises(qa.FrozenMT3ReviewError, match="outside the repository"):
        qa._private_candidate_destination(qa._ROOT / "scripts", target="macos-aarch64")
    with pytest.raises(qa.FrozenMT3ReviewError, match="already exist"):
        qa._private_candidate_destination(tmp_path / "missing", target="macos-aarch64")
    alias = tmp_path / "symlink-dir"
    alias.symlink_to(staging_dir, target_is_directory=True)
    with pytest.raises(qa.FrozenMT3ReviewError, match="linked"):
        qa._private_candidate_destination(alias, target="macos-aarch64")


def test_private_candidate_failed_checksum_does_not_leave_partial_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    source = tmp_path / "private-source.zip"
    source.write_bytes(b"unapproved-artifact")
    destination = tmp_path / "private-staged.zip"
    with pytest.raises(qa.FrozenMT3ReviewError, match="changed after"):
        qa._stage_private_candidate(source, destination, expected_sha256="0" * 64)
    assert not destination.exists()
    assert not list(tmp_path.glob(".mt3-unapproved-*"))


def test_private_staging_requires_real_checkpoint_before_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(qa, "_native_target", lambda _target: None)
    monkeypatch.setattr(qa, "_pinned_packages", lambda: dict(qa._EXPECTED))
    staging_dir = tmp_path / "private-candidates"
    staging_dir.mkdir()
    with pytest.raises(qa.FrozenMT3ReviewError, match="actual verified model"):
        qa.build_and_verify_native(
            target="macos-aarch64",
            destination=tmp_path / "unused.pending.json",
            private_candidate_dir=staging_dir,
        )
    assert list(staging_dir.iterdir()) == []


def test_operator_private_candidate_only_staged_after_successful_native_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    checkpoint = tmp_path / "reviewed-weight.pth"
    checkpoint.write_bytes(b"private-source-weight")
    root = tmp_path / "runner-only"
    root.mkdir()
    destination_dir = tmp_path / "operator-private"
    destination_dir.mkdir()
    monkeypatch.setattr(qa, "_native_target", lambda _target: None)
    monkeypatch.setattr(qa, "_pinned_packages", lambda: dict(qa._EXPECTED))
    monkeypatch.setattr(qa, "_trusted_checkpoint", lambda _root: checkpoint)

    def fake_build(cmd, *, cwd, check):
        assert cwd == qa._ROOT and check
        dist = Path(cmd[cmd.index("--distpath") + 1])
        dist.mkdir(parents=True)
        (dist / f"mt3-infer{'.exe' if os.name == 'nt' else ''}").write_bytes(
            b"MZ" + b"synthetic-frozen-review-binary" * 60000
        )
        return subprocess.CompletedProcess(cmd, 0)

    def fake_probe(*_args, **_kwargs):
        return {"checkpoint_download_disabled": True}

    def verified_model(*, base, binary, managed, checkpoint, manifest, executable_sha):
        assert managed.is_dir() and binary.is_file()
        assert checkpoint.read_bytes() == b"private-source-weight"
        assert executable_sha == qa._sha256(binary)
        private_archive = base / "MT3-REAL-WEIGHTS-NOT-PUBLISHED.zip"
        private_archive.write_bytes(b"private-verified-native-plus-model")
        return {
            "private_real_archive_sha256": qa._sha256(private_archive),
            "actual_cpu_model_inference_verified": True,
        }

    monkeypatch.setattr(qa.subprocess, "run", fake_build)
    monkeypatch.setattr(qa, "_probe_managed_native", fake_probe)
    monkeypatch.setattr(qa, "_probe_native_real_inference", verified_model)
    proof = qa.build_and_verify_native(
        target="macos-aarch64",
        destination=tmp_path / "proof.pending.json",
        checkpoint_directory=root,
        private_candidate_dir=destination_dir,
    )
    staged = destination_dir / "MT3-MRMT3-macos-aarch64-UNAPPROVED.zip"
    assert staged.read_bytes() == b"private-verified-native-plus-model"
    assert proof["private_candidate_staged_locally"] is True
    assert proof["private_candidate_filename"] == staged.name
    assert proof["runtime_redistribution_approved"] is False
    assert proof["binaries_uploaded"] is False
    assert not (tmp_path / "proof.pending.json").exists()


def test_ci_workflow_never_invokes_private_archive_staging():
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github/workflows/mt3-frozen-native-review.yml"
    ).read_text(encoding="utf-8")
    assert "--private-candidate-dir" not in workflow
    assert "pending.json" in workflow
    assert "MT3-REAL-WEIGHTS-NOT-PUBLISHED.zip" not in workflow


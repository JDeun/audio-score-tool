"""Build and smoke a PRIVATE frozen MT3-Infer CPU executable on native OS.

Uses PyInstaller + pinned mt3-infer/PyTorch from the review runner. The product
installer must accept the resulting one-file CLI as an owned managed tool, and
that CLI must start with PATH empty and no ambient Python installation.

This is *only* executable portability QA: it intentionally contains no
model weights and never publishes binary/model archives or declares a release
license, notarization, real model inference, or clean-machine acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import stat
import subprocess
import sys
import tempfile
import wave
import zipfile
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from unittest.mock import patch

from audio_score_tool.managed_components import (
    ComponentArtifact,
    component_status,
    install_component_artifact,
)
from audio_score_tool.managed_tool_resolver import registered_managed_tool
from audio_score_tool.runner import CommandError, run_command

_ROOT = Path(__file__).resolve().parents[1]
_ENTRY = _ROOT / "scripts/mt3_frozen_entry.py"
_MODEL = "mr_mt3"
_EXPECTED = {
    "mt3-infer": "0.2.0",
    "torch": "2.7.1",
    "torchaudio": "2.7.1",
    "transformers": "4.57.6",
    "PyInstaller": "6.17.0",
}
_TARGETS = {"windows-x86_64", "macos-aarch64"}
_MAX_ARCHIVE = 6 * 1024**3


class FrozenMT3ReviewError(ValueError):
    """A built binary, owner registry, or native launch failed QA."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _native_target(target: str) -> None:
    machine = platform.machine().lower()
    matched = (
        (target == "windows-x86_64" and os.name == "nt" and machine in {"amd64", "x86_64"})
        or (target == "macos-aarch64" and sys.platform == "darwin"
            and machine in {"arm64", "aarch64"})
    )
    if not matched:
        raise FrozenMT3ReviewError("Frozen QA must run on the exact native OS/CPU")


def _pinned_packages() -> dict[str, str]:
    pinned = {}
    for name, expected in _EXPECTED.items():
        try:
            observed = version(name)
        except PackageNotFoundError as exc:
            raise FrozenMT3ReviewError(f"{name}: pinned native package is absent") from exc
        if observed != expected:
            raise FrozenMT3ReviewError(
                f"{name}: expected pinned {expected}, found {observed}"
            )
        pinned[name] = observed
    return pinned


def pyinstaller_command(*, dist: Path, work: Path, specs: Path) -> list[str]:
    """Explicit hidden imports for MT3's importlib registry and T5 weights."""
    if not _ENTRY.is_file():
        raise FrozenMT3ReviewError("Frozen CLI entrypoint is unavailable")
    return [
        sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm",
        "--onefile", "--noupx", "--console",
        "--name", "mt3-infer",
        "--collect-data", "mt3_infer",
        "--copy-metadata", "mt3-infer",
        "--copy-metadata", "torch",
        "--copy-metadata", "torchaudio",
        "--copy-metadata", "transformers",
        "--hidden-import", "mt3_infer.adapters.mr_mt3",
        "--hidden-import", "mt3_infer.models.mr_mt3.t5",
        "--hidden-import", "transformers.models.t5.modeling_t5",
        "--exclude-module", "tensorflow",
        "--exclude-module", "jax",
        "--exclude-module", "flax",
        "--exclude-module", "pytorch_lightning",
        "--distpath", str(dist),
        "--workpath", str(work),
        "--specpath", str(specs),
        str(_ENTRY),
    ]


def _original_wav(path: Path) -> None:
    """A tiny locally authored WAV; a missing checkpoint must prevent inference."""
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(b"\x00\x00" * 16000)


def _private_zip(archive: Path, frozen: Path, metadata: dict) -> None:
    with zipfile.ZipFile(archive, "w", allowZip64=True) as bundle:
        tool = zipfile.ZipInfo(
            f"bin/mt3-infer{'.exe' if os.name == 'nt' else ''}",
            date_time=(1980, 1, 1, 0, 0, 0),
        )
        tool.create_system = 3
        tool.external_attr = (stat.S_IFREG | 0o755) << 16
        tool.compress_type = zipfile.ZIP_STORED
        with frozen.open("rb") as src, bundle.open(tool, "w", force_zip64=True) as target:
            for chunk in iter(lambda: src.read(1024 * 1024), b""):
                target.write(chunk)
        manifest = zipfile.ZipInfo(
            "provenance/frozen-native-qa.pending.json", date_time=(1980, 1, 1, 0, 0, 0),
        )
        manifest.create_system = 3
        manifest.external_attr = (stat.S_IFREG | 0o644) << 16
        bundle.writestr(manifest, json.dumps(metadata, sort_keys=True, indent=2) + "\n")


def _probe_managed_native(root: Path, managed_name: str, *, model: str) -> dict:
    """Run actual product-registered CLI with no ambient Python or checkpoint."""
    tool = registered_managed_tool("mt3-infer", component="transcription_engine")
    if tool is None or not tool.is_file() or tool.name != managed_name:
        raise FrozenMT3ReviewError("Native frozen MT3 tool is not registered by its owner")
    env = {
        "PATH": "",
        # A frozen binary must not depend on the runner's Python import path.
        "PYTHONPATH": "",
        "PYTHONHOME": "",
        "PYTHONNOUSERSITE": "1",
        # The upstream CLI prints Unicode markers, including on Windows.
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_DATASETS_OFFLINE": "1",
        "MT3_CHECKPOINT_DIR": str(root / "intentionally-absent-checkpoints"),
    }
    run = {}
    for label, arguments in {
        "version": ["--version"],
        "models": ["list"],
        "transcribe-help": ["transcribe", "--help"],
    }.items():
        try:
            result = run_command(str(tool), arguments, env=env, timeout_seconds=180)
        except CommandError as exc:
            raise FrozenMT3ReviewError(
                f"Frozen native MT3 CLI startup failed: {label}"
            ) from exc
        output = result.stdout.lower()
        if (
            (label == "version" and "0.2.0" not in output)
            or (label == "models" and "mr_mt3" not in output)
            or (label == "transcribe-help" and "--no-download" not in output)
        ):
            raise FrozenMT3ReviewError(f"Frozen CLI {label} did not expose pinned model data")
        run[label] = True

    # An untrusted or missing checkpoint must fail *without* implicit network
    # acquisition. This exercises importlib adapter loading, torch and torchaudio
    # code paths beyond a superficial --version smoke.
    audio = root / "original-qa.wav"
    _original_wav(audio)
    missing_result = root / "should-not-exist.mid"
    try:
        run_command(
            str(tool),
            [
                "transcribe", str(audio), "-o", str(missing_result),
                "-m", model, "--device", "cpu", "--no-download", "--verbose",
            ],
            env=env,
            timeout_seconds=180,
        )
    except CommandError as exc:
        # The pinned upstream MR-MT3 adapter emits this exact exception only
        # after the audio, model registry, dynamic adapter and torch paths work.
        # Do not accept generic "no such file" errors: they can indicate a
        # missing bundled DLL, shared library, model resource or import.
        expected_checkpoint = (
            root / "intentionally-absent-checkpoints" / "mr_mt3" / "mt3.pth"
        )
        expected_error = f"Checkpoint not found: {expected_checkpoint}".casefold()
        if not any(
            line.strip().casefold().endswith(expected_error)
            for line in str(exc).splitlines()
        ):
            raise FrozenMT3ReviewError(
                "Frozen MT3 inference failed for a reason other than its absent checkpoint"
            ) from exc
    else:
        raise FrozenMT3ReviewError("Frozen MT3 unexpectedly inferred without model weights")
    if missing_result.exists() or (root / "intentionally-absent-checkpoints").exists():
        raise FrozenMT3ReviewError("Frozen CLI created unreviewed checkpoint or MIDI data")
    return {
        **run, "checkpoint_download_disabled": True,
        "dynamic_mr_mt3_adapter_reached": True,
        "system_path_fallback_disabled": True,
    }


def build_and_verify_native(*, target: str, destination: Path) -> dict:
    _native_target(target)
    packages = _pinned_packages()
    if not destination.parent.is_dir() or destination.exists() or destination.is_symlink():
        raise FrozenMT3ReviewError("Native QA evidence must be a new file")
    with tempfile.TemporaryDirectory(prefix="ast-mt3-frozen-review-") as private:
        base = Path(private).resolve()
        dist = base / "dist"
        work = base / "work"
        specs = base / "specs"
        cmd = pyinstaller_command(dist=dist, work=work, specs=specs)
        subprocess.run(cmd, cwd=_ROOT, check=True)
        extension = ".exe" if os.name == "nt" else ""
        binary = dist / f"mt3-infer{extension}"
        if binary.is_symlink() or not binary.is_file() or binary.stat().st_size < 1024 * 1024:
            raise FrozenMT3ReviewError("Native bundled PyInstaller executable was not produced")
        if binary.stat().st_size > _MAX_ARCHIVE // 2:
            raise FrozenMT3ReviewError("Native MT3 runtime exceeds safe archive budget")
        executable_sha = _sha256(binary)
        manifest = {
            "schema": 1, "target": target, "model_adapter": _MODEL,
            "component": "transcription_engine",
            "build_method": "PyInstaller onefile native QA",
            "packages": packages,
            "mt3_wrapper_sha256": executable_sha,
            "upstream": "https://github.com/openmirlab/mt3-infer/tree/v0.2.0",
            "model_weights_included": False,
            "redistribution_status": "pending", "approval_required": True,
        }
        archive = base / "MT3-NATIVE-UNAPPROVED.zip"
        _private_zip(archive, binary, manifest)
        archive_sha = _sha256(archive)
        tool_key = f"bin/mt3-infer{extension}"
        artifact = ComponentArtifact(
            component="transcription_engine",
            version="mt3-0.2.0-mr-mt3-native-qa1",
            url="https://example.invalid/qa-not-published.zip",
            sha256=archive_sha, archive="zip",
            tools={"mt3-infer": tool_key},
            license="MT3-Infer MIT / bundled third-party notices pending review",
            provenance="Native frozen runtime for release QA, no checkpoint",
            max_download_bytes=_MAX_ARCHIVE,
            max_uncompressed_bytes=_MAX_ARCHIVE,
        )
        managed = base / "managed"
        installed = install_component_artifact(
            artifact, root=managed, local_archive=archive,
        )
        if installed.get("ready") is not True or installed.get("integrity") != "verified":
            raise FrozenMT3ReviewError("Real native frozen runtime failed the product installer")
        with patch.dict(os.environ, {
            "AST_PACKAGED": "1", "AST_COMPONENT_DIR": str(managed), "PATH": "",
        }):
            probes = _probe_managed_native(base, f"mt3-infer{extension}", model=_MODEL)
            end_status = component_status("transcription_engine", root=managed)
            if not end_status.get("ready"):
                raise FrozenMT3ReviewError("Frozen CLI mutated its installed runtime")
        if _sha256(binary) != executable_sha:
            raise FrozenMT3ReviewError("Frozen CLI changed after native probes")
        return {
            "schema": 1, "target": target, "model_adapter": _MODEL,
            "packages": packages,
            "native_executable_sha256": executable_sha,
            "native_executable_bytes": binary.stat().st_size,
            "private_archive_sha256": archive_sha,
            "private_archive_bytes": archive.stat().st_size,
            "whole_payload_sha256_verified": True,
            "managed_installer_verified": True,
            "registered_executable_verified": True,
            "native_host_python_not_required_for_startup": True,
            "actual_model_inference_verified": False,
            "model_checkpoint_included": False,
            "windows_macos_clean_machine_verified": False,
            "model_license_approved": False,
            "runtime_redistribution_approved": False,
            "binaries_uploaded": False,
            "redistribution_status": "pending",
            "checked_at_utc": datetime.now(timezone.utc).isoformat(),
            "probes": probes,
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Private Windows/macOS MT3 PyInstaller executable QA, no binary uploads."
    )
    parser.add_argument("--target", choices=sorted(_TARGETS), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        proof = build_and_verify_native(target=args.target, destination=args.output)
        with args.output.open("x", encoding="utf-8") as report:
            json.dump(proof, report, sort_keys=True, indent=2)
            report.write("\n")
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(2, f"Frozen MT3 native QA failed: {exc}\n")
    print(json.dumps({
        "target": proof["target"],
        "managed_installer_verified": proof["managed_installer_verified"],
        "native_host_python_not_required_for_startup": proof["native_host_python_not_required_for_startup"],
        "actual_model_inference_verified": False,
        "redistribution_status": "pending",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

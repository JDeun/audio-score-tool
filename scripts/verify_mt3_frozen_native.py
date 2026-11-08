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
import shutil
import stat
import subprocess
import sys
import tempfile
import wave
import zipfile
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from threading import Event, Timer
from unittest.mock import patch

from audio_score_tool.managed_components import (
    ComponentArtifact,
    component_status,
    install_component_artifact,
)
from audio_score_tool.managed_tool_resolver import (
    registered_managed_component_root,
    registered_managed_tool,
)
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
# Exact upstream v0.2.0 registry checkpoint, independently validated by its
# download utility. Only this hash may be unpickled by the private QA runner.
_MR_MT3_SHA256 = "b8a3807ed265059abd25ad7f68142c06c35e8f6144dcaa45bd55946a3745398f"
_MR_MT3_SOURCE = "https://huggingface.co/gudgud1014/MR-MT3/resolve/main/mt3.pth"


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


def _private_zip(
    archive: Path, frozen: Path, metadata: dict, *, checkpoint: Path | None = None,
) -> None:
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
        if checkpoint is not None:
            weight = zipfile.ZipInfo(
                "checkpoints/mr_mt3/mt3.pth", date_time=(1980, 1, 1, 0, 0, 0),
            )
            weight.create_system = 3
            weight.external_attr = (stat.S_IFREG | 0o644) << 16
            weight.compress_type = zipfile.ZIP_STORED
            with checkpoint.open("rb") as src, bundle.open(weight, "w", force_zip64=True) as dest:
                for chunk in iter(lambda: src.read(1024 * 1024), b""):
                    dest.write(chunk)


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
            # A native PyInstaller failure must preserve the bounded stderr/stdout
            # tail so CI can distinguish registry, import, Unicode and DLL errors.
            # The probe has no credentials and run_command already limits output.
            detail = str(exc)[-6000:]
            raise FrozenMT3ReviewError(
                f"Frozen native MT3 CLI startup failed: {label}\n{detail}"
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



def _trusted_checkpoint(directory: Path) -> Path:
    """Allow only the exact known MR-MT3 weight bytes, never an arbitrary pickle.

    This hash is pinned in upstream MT3-Infer v0.2.0's checkpoint registry.
    Checking the blob *before* installing/loading is essential: torch.load in
    the vendored adapter uses weights_only=False for this legacy checkpoint.
    """
    directory = directory.expanduser()
    model_dir = directory / "mr_mt3"
    weight = model_dir / "mt3.pth"
    if (
        directory.is_symlink() or not directory.is_dir()
        or model_dir.is_symlink() or not model_dir.is_dir()
        or weight.is_symlink() or not weight.is_file()
    ):
        raise FrozenMT3ReviewError("Exact app-reviewed MR-MT3 checkpoint path is missing or linked")
    size = weight.stat().st_size
    if not 1024 * 1024 <= size <= 1024**3:
        raise FrozenMT3ReviewError("Pinned MR-MT3 checkpoint has an implausible size")
    if _sha256(weight) != _MR_MT3_SHA256:
        raise FrozenMT3ReviewError("MR-MT3 checkpoint SHA-256 does not match pinned upstream bytes")
    return weight


def _probe_native_real_inference(
    *, base: Path, binary: Path, managed: Path, checkpoint: Path,
    manifest: dict, executable_sha: str,
) -> dict:
    """Install genuine weights with the frozen binary, then use product AMT E2E.

    The actual upstream checkpoint and frozen executable never leave the runner.
    This proves native product inference, not licenses or clean-machine release.
    """
    from audio_score_tool.config import Settings
    from audio_score_tool.transcription_engine import MT3InferEngine
    from scripts.generate_tier2_smoke_audio import generate_fixture
    from scripts.run_tier2_model_smoke import verify_model_outputs

    private_archive = base / "MT3-REAL-WEIGHTS-NOT-PUBLISHED.zip"
    proof = {
        **manifest,
        "model_weights_included": True,
        "checkpoint_sha256": _MR_MT3_SHA256,
        "checkpoint_source": _MR_MT3_SOURCE,
        "checkpoint_license_review": "pending",
    }
    _private_zip(private_archive, binary, proof, checkpoint=checkpoint)
    if _sha256(checkpoint) != _MR_MT3_SHA256 or _sha256(binary) != executable_sha:
        raise FrozenMT3ReviewError("Private inputs changed during checkpoint packaging")
    archive_sha = _sha256(private_archive)
    extension = ".exe" if os.name == "nt" else ""
    artifact = ComponentArtifact(
        component="transcription_engine",
        version="mt3-0.2.0-mr-mt3-native-real-qa2",
        url="https://example.invalid/NOT-PUBLISHED-MR-MT3.zip",
        sha256=archive_sha,
        archive="zip",
        tools={"mt3-infer": f"bin/mt3-infer{extension}"},
        license="unapproved-native-mr-mt3-real-checkpoint-QA",
        provenance="Pinned upstream MT3-Infer model; private integration test only",
        max_download_bytes=_MAX_ARCHIVE,
        max_uncompressed_bytes=_MAX_ARCHIVE,
    )
    result = install_component_artifact(artifact, root=managed, local_archive=private_archive)
    if (
        result.get("ready") is not True or result.get("integrity") != "verified"
        or result.get("payload_file_count") != 3
    ):
        raise FrozenMT3ReviewError("Production installer rejected the actual private model payload")
    fixture = generate_fixture(base / "original-composed-qa.wav")
    if not fixture.is_file() or fixture.stat().st_size < 100_000:
        raise FrozenMT3ReviewError("Original composed inference fixture is missing")
    output = base / "real-score-output"
    with patch.dict(os.environ, {
        "AST_PACKAGED": "1",
        "AST_COMPONENT_DIR": str(managed),
        "PATH": "",
        "PYTHONPATH": "",
        "PYTHONHOME": "",
        "MT3_CHECKPOINT_DIR": str(base / "untrusted-ambient-cache"),
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_DATASETS_OFFLINE": "1",
    }):
        tool = registered_managed_tool("mt3-infer", component="transcription_engine")
        installed_root = registered_managed_component_root(
            "transcription_engine", required_tool="mt3-infer",
        )
        if tool is None or installed_root is None or tool.name != f"mt3-infer{extension}":
            raise FrozenMT3ReviewError("The true frozen model does not use the owned managed CLI")
        if _sha256(tool) != executable_sha:
            raise FrozenMT3ReviewError("Managed executable bytes differ from reviewed native binary")
        installed_weight = installed_root / "checkpoints" / "mr_mt3" / "mt3.pth"
        if _sha256(installed_weight) != _MR_MT3_SHA256:
            raise FrozenMT3ReviewError("The installed model is not the verified upstream checkpoint")
        engine = MT3InferEngine(Settings(
            mt3_model="mr_mt3", transcription_engine="mt3_infer", usage_mode="commercial",
        ))
        if not engine.ready():
            raise FrozenMT3ReviewError("Real model payload is not ready through the product engine")
        cancelled = Event()
        deadline = Timer(1800, cancelled.set)
        deadline.daemon = True
        deadline.start()
        try:
            artifacts = engine.transcribe(
                fixture, output, device="cpu", cancel_event=cancelled,
            )
        finally:
            deadline.cancel()
        notes = verify_model_outputs(artifacts.midi_path, artifacts.musicxml_path)
        if notes["midi_notes"] <= 0 or notes["notes"] <= 0 or notes["parts"] <= 0:
            raise FrozenMT3ReviewError("Real native model returned an empty or malformed score")
        after = component_status("transcription_engine", root=managed)
        if after.get("ready") is not True or after.get("integrity") != "verified":
            raise FrozenMT3ReviewError("Native inference changed or corrupted its owned model payload")
    return {
        "model": "mr_mt3",
        "checkpoint_sha256": _MR_MT3_SHA256,
        "checkpoint_source": _MR_MT3_SOURCE,
        "frozen_executable_sha256": executable_sha,
        "private_real_archive_sha256": archive_sha,
        "private_real_archive_bytes": private_archive.stat().st_size,
        "actual_model_weights_verified": True,
        "managed_archive_and_full_payload_verified": True,
        "registered_native_frozen_executable_verified": True,
        "actual_cpu_model_inference_verified": True,
        "product_midi_to_musicxml_verified": True,
        "no_ambient_python_or_path_required_by_frozen_cli": True,
        "audio_sha256": _sha256(fixture),
        "midi_sha256": _sha256(artifacts.midi_path),
        "musicxml_sha256": _sha256(artifacts.musicxml_path),
        "note_counts": notes,
        "model_redistribution_approved": False,
        "model_weights_published": False,
        "clean_machine_install_verified": False,
        "redistribution_status": "pending",
    }



def _private_candidate_destination(directory: Path, *, target: str) -> Path:
    """Opt-in private storage only; never keep unapproved weights in public CI.

    The target is not a public release location. Staging remains separate from
    the Git checkout so an accidental git add cannot publish pretrained files.
    """
    if os.environ.get("GITHUB_ACTIONS", "").strip().lower() == "true":
        raise FrozenMT3ReviewError("GitHub Actions may not retain unapproved model archives")
    if target not in _TARGETS:
        raise FrozenMT3ReviewError("Private candidate target is unsupported")
    raw = directory.expanduser().absolute()
    if not raw.is_dir() or raw.is_symlink():
        raise FrozenMT3ReviewError("Private candidate directory must already exist and not be linked")
    # Reject symlinks at every ancestor, not only the leaf directory.
    for ancestor in (raw, *raw.parents):
        if ancestor.is_symlink():
            raise FrozenMT3ReviewError("Private candidate directory traverses a symlink")
    destination_root = raw.resolve()
    if destination_root.is_relative_to(_ROOT.resolve()):
        raise FrozenMT3ReviewError("Private model artifacts must remain outside the repository")
    if not os.access(destination_root, os.W_OK):
        raise FrozenMT3ReviewError("Private candidate directory is not writable")
    destination = destination_root / f"MT3-MRMT3-{target}-UNAPPROVED.zip"
    if destination.exists() or destination.is_symlink():
        raise FrozenMT3ReviewError("Private candidate already exists; refusing overwrite")
    return destination


def _stage_private_candidate(
    archive: Path, destination: Path, *, expected_sha256: str,
) -> None:
    """Copy verified archive to private storage, atomically without overwrite.

    A same-directory temporary file is written with owner-only permissions.
    A hard link installs the final name exclusively; there is never a partial
    final candidate or an overwrite of an operator's existing file.
    """
    if archive.is_symlink() or not archive.is_file():
        raise FrozenMT3ReviewError("Verified private archive is unavailable")
    if _sha256(archive) != expected_sha256:
        raise FrozenMT3ReviewError("Private archive changed after real model inference")
    fd, temporary = tempfile.mkstemp(prefix=".mt3-unapproved-", dir=destination.parent)
    temporary_path = Path(temporary)
    linked = False
    try:
        with os.fdopen(fd, "wb") as output, archive.open("rb") as source:
            shutil.copyfileobj(source, output, 1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        if _sha256(temporary_path) != expected_sha256:
            raise FrozenMT3ReviewError("Staged candidate SHA-256 mismatch")
        if destination.exists() or destination.is_symlink():
            raise FrozenMT3ReviewError("Private candidate already exists; refusing overwrite")
        # Both paths are on the same filesystem. os.link does not replace an
        # existing destination, including on Windows; os.replace would.
        os.link(temporary_path, destination)
        linked = True
        if _sha256(destination) != expected_sha256:
            raise FrozenMT3ReviewError("Staged candidate changed after linking")
    except BaseException:
        if linked:
            destination.unlink(missing_ok=True)
        raise
    finally:
        temporary_path.unlink(missing_ok=True)


def build_and_verify_native(
    *, target: str, destination: Path, checkpoint_directory: Path | None = None,
    private_candidate_dir: Path | None = None,
) -> dict:
    _native_target(target)
    packages = _pinned_packages()
    if private_candidate_dir is not None and checkpoint_directory is None:
        raise FrozenMT3ReviewError(
            "Private release staging requires an actual verified model checkpoint"
        )
    private_destination = (
        _private_candidate_destination(private_candidate_dir, target=target)
        if private_candidate_dir is not None else None
    )
    checkpoint = _trusted_checkpoint(checkpoint_directory) if checkpoint_directory is not None else None
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
        real_evidence = (
            _probe_native_real_inference(
                base=base, binary=binary, managed=managed,
                checkpoint=checkpoint, manifest=manifest, executable_sha=executable_sha,
            )
            if checkpoint is not None else None
        )
        if _sha256(binary) != executable_sha:
            raise FrozenMT3ReviewError("Frozen CLI changed after native probes")
        # Only after native inference and full managed payload verification may
        # an operator deliberately retain an unapproved archive, outside git.
        # CI never supplies this option and GITHUB_ACTIONS is explicitly denied.
        if private_destination is not None:
            if real_evidence is None:
                raise FrozenMT3ReviewError("Unverified model cannot be staged")
            _stage_private_candidate(
                base / "MT3-REAL-WEIGHTS-NOT-PUBLISHED.zip",
                private_destination,
                expected_sha256=real_evidence["private_real_archive_sha256"],
            )
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
            "actual_model_inference_verified": real_evidence is not None,
            "model_checkpoint_included": real_evidence is not None,
            "real_native_inference": real_evidence,
            "windows_macos_clean_machine_verified": False,
            "model_license_approved": False,
            "runtime_redistribution_approved": False,
            "binaries_uploaded": False,
            "private_candidate_staged_locally": private_destination is not None,
            "private_candidate_filename": (
                private_destination.name if private_destination is not None else None
            ),
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
    parser.add_argument(
        "--checkpoint-dir", type=Path,
        help="Private, runner-local MR-MT3 download root; enables actual native score inference",
    )
    parser.add_argument(
        "--private-candidate-dir", type=Path,
        help=(
            "Operator-only: existing private directory outside the repository to retain "
            "the fully verified, UNAPPROVED native model ZIP. Forbidden in GitHub Actions."
        ),
    )
    args = parser.parse_args()
    try:
        proof = build_and_verify_native(
            target=args.target, destination=args.output,
            checkpoint_directory=args.checkpoint_dir,
            private_candidate_dir=args.private_candidate_dir,
        )
        with args.output.open("x", encoding="utf-8") as report:
            json.dump(proof, report, sort_keys=True, indent=2)
            report.write("\n")
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(2, f"Frozen MT3 native QA failed: {exc}\n")
    print(json.dumps({
        "target": proof["target"],
        "managed_installer_verified": proof["managed_installer_verified"],
        "native_host_python_not_required_for_startup": proof["native_host_python_not_required_for_startup"],
        "actual_model_inference_verified": proof["actual_model_inference_verified"],
        "redistribution_status": "pending",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

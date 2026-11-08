"""Real-checkpoint managed MT3 inference QA, without publishing model weights.

Run on the pinned Linux Tier-2 runner *after* its first real inference populated
MT3_CHECKPOINT_DIR. The model/launcher ZIP is private and temporary. Reuse the
actual production managed installer, registered command resolver, and MT3 engine
for a second inference with network-dependent model fetching disabled.

IMPORTANT: The QA launcher is copied from the runner's existing Python
environment. This is NOT a self-contained Windows/macOS distribution, proof of
model redistribution rights, or signed release acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

from audio_score_tool.config import Settings
from audio_score_tool.managed_components import (
    ComponentArtifact,
    component_status,
    install_component_artifact,
)
from audio_score_tool.managed_tool_resolver import registered_managed_tool
from audio_score_tool.transcription_engine import MT3InferEngine
from scripts.run_tier2_model_smoke import verify_model_outputs

_VALID_MODELS = ("mr_mt3", "yourmt3")
_WEIGHTS = {".pt", ".pth", ".ckpt", ".bin", ".safetensors", ".h5", ".msgpack"}
_MAX_MEMBERS = 4090
_MAX_TOTAL_BYTES = 3 * 1024**3


class ManagedRealCheckpointError(ValueError):
    """The real checkpoint could not be verified or exercised safely."""


def _sha256(file: Path) -> str:
    digest = hashlib.sha256()
    with file.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_files(directory: Path, model: str) -> list[tuple[Path, str]]:
    """Get every source file while refusing symlinks, special files, and escapes."""
    if model not in _VALID_MODELS or not directory.is_dir() or directory.is_symlink():
        raise ManagedRealCheckpointError("A real known-model checkpoint directory is required")
    selected = directory / model
    if selected.is_symlink() or not selected.is_dir():
        raise ManagedRealCheckpointError("The selected model has not been downloaded")
    files: list[tuple[Path, str]] = []
    total = 0
    discovered_weight = False
    for parent, dirs, names in os.walk(selected, followlinks=False):
        base = Path(parent)
        if base.is_symlink():
            raise ManagedRealCheckpointError("Checkpoint directory contains a symlink")
        for name in dirs:
            subdir = base / name
            if subdir.is_symlink() or not subdir.is_dir():
                raise ManagedRealCheckpointError("Checkpoint contains a linked directory")
        for name in names:
            source = base / name
            if source.is_symlink() or not source.is_file():
                raise ManagedRealCheckpointError("Checkpoint contains a link or special file")
            relative = source.relative_to(directory).as_posix()
            if any(part in {"", ".", ".."} for part in relative.split("/")):
                raise ManagedRealCheckpointError("Invalid checkpoint member path")
            total += source.stat().st_size
            if total > _MAX_TOTAL_BYTES or len(files) >= _MAX_MEMBERS - 1:
                raise ManagedRealCheckpointError("Checkpoint exceeds managed ZIP limits")
            if source.suffix.lower() in _WEIGHTS and source.stat().st_size > 0:
                discovered_weight = True
            files.append((source, f"checkpoints/{relative}"))
    if not files or not discovered_weight:
        raise ManagedRealCheckpointError("No nonempty real model weight was found")
    return sorted(files, key=lambda item: item[1])


def _qa_entrypoint() -> Path:
    found = shutil.which("mt3-infer")
    if not found:
        raise ManagedRealCheckpointError("Pinned mt3-infer CLI is missing on the QA runner")
    tool = Path(found).resolve()
    if not tool.is_file() or tool.stat().st_size < 10:
        raise ManagedRealCheckpointError("Host QA launcher is missing or incomplete")
    # This is a runner-owned script, not a frozen runtime. Only exact bytes get
    # copied and installed; production releases must separately freeze Python.
    return tool


def _write_zip(
    archive: Path, launcher: Path, files: list[tuple[Path, str]],
) -> dict[str, str]:
    file_hashes: dict[str, str] = {}
    with zipfile.ZipFile(archive, "w", allowZip64=True) as writer:
        manifest = [("bin/mt3-infer", launcher), *[(relative, source) for source, relative in files]]
        for relative, source in manifest:
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (
                stat.S_IFREG | (0o755 if relative == "bin/mt3-infer" else 0o644)
            ) << 16
            # Uncompressed archive avoids very high ratios and extra memory
            # during a large checkpoint install; ZIP64 supports multi-GB files.
            info.compress_type = zipfile.ZIP_STORED
            digest = hashlib.sha256()
            with source.open("rb") as input_file, writer.open(info, "w", force_zip64=True) as output:
                while chunk := input_file.read(1024 * 1024):
                    digest.update(chunk)
                    output.write(chunk)
            if digest.hexdigest() != _sha256(source):
                raise ManagedRealCheckpointError(f"{relative}: source changed during QA packaging")
            file_hashes[relative] = digest.hexdigest()
    return file_hashes


def run_real_managed_mt3(
    *, model: str,
    audio: Path,
    checkpoint_directory: Path,
    destination: Path,
) -> dict:
    """Verify actual pretrained model files through install + packaged inference."""
    if not audio.is_file() or audio.stat().st_size <= 44:
        raise ManagedRealCheckpointError("Original audio fixture must be available")
    if destination.exists() or destination.is_symlink() or not destination.parent.is_dir():
        raise ManagedRealCheckpointError("QA evidence must be a new path")
    sources = _source_files(checkpoint_directory, model)
    with tempfile.TemporaryDirectory(prefix="ast-real-managed-mt3-qa-") as temp:
        private = Path(temp).resolve()
        zip_path = private / "real-checkpoint-qa-only.zip"
        file_hashes = _write_zip(zip_path, _qa_entrypoint(), sources)
        archive_sha = _sha256(zip_path)
        artifact = ComponentArtifact(
            component="transcription_engine",
            version=f"mt3-0.2.0-{model}-qa-only",
            url="https://example.invalid/not-a-redistribution-asset.zip",
            sha256=archive_sha,
            archive="zip",
            tools={"mt3-infer": "bin/mt3-infer"},
            license="unapproved-real-checkpoint-review",
            provenance="real downloaded runner checkpoint; no redistribution",
        )
        root = private / "components"
        install = install_component_artifact(artifact, root=root, local_archive=zip_path)
        if install.get("integrity") != "verified" or install.get("ready") is not True:
            raise ManagedRealCheckpointError("Product installer rejected genuine checkpoint bytes")
        expected_files = {"bin/mt3-infer", *(path for _, path in sources)}
        if install.get("payload_file_count") != len(expected_files):
            raise ManagedRealCheckpointError("Installed payload inventory is missing resources")
        binary = install["tools"]["mt3-infer"]
        inferred = private / "inference"
        # Do not leave a valid ambient checkpoint path or network-dependent
        # defaults that could accidentally substitute for managed model bytes.
        with patch.dict(os.environ, {
            "AST_PACKAGED": "1",
            "AST_COMPONENT_DIR": str(root),
            "MT3_CHECKPOINT_DIR": str(private / "untrusted-ambient"),
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_DATASETS_OFFLINE": "1",
            "PATH": "",
        }):
            if registered_managed_tool(
                "mt3-infer", component="transcription_engine"
            ) != Path(binary):
                raise ManagedRealCheckpointError("Packaged tool resolver selected a different owner")
            engine = MT3InferEngine(Settings(
                mt3_model=model,
                usage_mode="commercial",
                transcription_engine="mt3_infer",
            ))
            if not engine.ready():
                raise ManagedRealCheckpointError("Packaged inference marked genuine checkpoint missing")
            result = engine.transcribe(audio.resolve(), inferred, device="cpu")
            notes = verify_model_outputs(result.midi_path, result.musicxml_path)
            status = component_status("transcription_engine", root=root)
            if status.get("integrity") != "verified" or not status.get("ready"):
                raise ManagedRealCheckpointError("Real inference modified the immutable managed payload")
        return {
            "schema": 1,
            "target": "linux-x86_64",
            "model": model,
            "checkpoint_files": len(sources),
            "checkpoint_sha256": {
                relative: file_hashes[relative]
                for _source, relative in sources
            },
            "managed_archive_sha256": archive_sha,
            "managed_archive_bytes": zip_path.stat().st_size,
            "all_payload_sha256_verified": True,
            "managed_product_install_verified": True,
            "actual_pretrained_weights_executed": True,
            "packaged_checkpoint_root_verified": True,
            "ambient_download_fallback_disabled": True,
            "real_cpu_inference_notes": notes,
            "output_midi_sha256": _sha256(result.midi_path),
            "output_musicxml_sha256": _sha256(result.musicxml_path),
            "qa_launcher_requires_host_python": True,
            "clean_windows_macos_verified": False,
            "model_redistribution_rights_verified": False,
            "third_party_artifacts_published": False,
            "redistribution_status": "pending",
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="QA only: install actual MT3 checkpoint in a private managed ZIP and infer.")
    parser.add_argument("--model", choices=_VALID_MODELS, required=True)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--checkpoint-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run_real_managed_mt3(
            model=args.model,
            audio=args.audio,
            checkpoint_directory=args.checkpoint_dir,
            destination=args.output,
        )
        with args.output.open("x", encoding="utf-8") as output:
            json.dump(result, output, indent=2, sort_keys=True)
            output.write("\n")
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(2, f"Real managed MT3 checkpoint QA failed: {exc}\n")
    print(json.dumps({
        "model": result["model"],
        "real_cpu_inference_notes": result["real_cpu_inference_notes"],
        "redistribution_status": "pending",
        "qa_launcher_requires_host_python": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

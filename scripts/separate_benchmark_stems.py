"""Run pinned Demucs in a private workspace for paired AMT experiments.

This invokes the real 4.0.1 CLI entry point in this process, after seeding all
three RNGs. It does not select score parts, alter instrument programs, upload
media, or change torch's checkpoint-loading policy. Only JSON evidence is
printed by the CLI; keep the output workspace outside the Git repository.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import random
import sys
import time
import wave
from contextlib import redirect_stdout
from fractions import Fraction
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

DEMUCS_VERSION = "4.0.1"
SOURCE_REVISION = "ef66d254cd6d558e207eeff2c4b8d053db2e77dd"
STEMS = {
    "htdemucs": ("drums", "bass", "other", "vocals"),
    "htdemucs_6s": ("drums", "bass", "other", "vocals", "guitar", "piano"),
}
CHECKPOINTS = {
    "htdemucs": ("955717e8", "955717e8-8726e21a.th", "8726e21a"),
    "htdemucs_6s": ("5c90dfd2", "5c90dfd2-34c22ccb.th", "34c22ccb"),
}
_ROOT = Path(__file__).resolve().parents[1]
_CHECKPOINT_URL = "https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/"
_FILENAME = "{track}/{stem}.{ext}"
_TRUTHY = {"1", "y", "yes", "true"}


class SeparationError(ValueError):
    """Separation or its source-bound evidence cannot be verified."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _regular(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise SeparationError(f"Expected a regular, unlinked file: {path.name}")


def _wave_info(path: Path) -> dict:
    """Inspect real PCM frames, rejecting truncated headers/data and empty WAVs."""
    _regular(path)
    try:
        with wave.open(str(path), "rb") as audio:
            frames, rate = audio.getnframes(), audio.getframerate()
            channels, width = audio.getnchannels(), audio.getsampwidth()
            if frames <= 0 or rate <= 0 or channels <= 0 or not 1 <= width <= 4:
                raise SeparationError(f"Empty or invalid PCM audio: {path.name}")
            expected_bytes = frames * channels * width
            actual_bytes = 0
            while chunk := audio.readframes(65536):
                actual_bytes += len(chunk)
            if actual_bytes != expected_bytes:
                raise SeparationError(f"Truncated PCM audio: {path.name}")
    except (EOFError, OSError, wave.Error) as exc:
        raise SeparationError(f"Benchmark input/output must be readable PCM WAV: {path.name}") from exc
    return {
        "sha256": _sha256(path), "bytes": path.stat().st_size,
        "frames": frames, "sample_rate": rate, "channels": channels,
        "sample_width_bytes": width, "duration_seconds": frames / rate,
    }


def _new_private_root(path: Path) -> Path:
    expanded = path.expanduser().absolute()
    if expanded.exists() or expanded.is_symlink():
        raise SeparationError("Separation output already exists; refusing stale output reuse")
    resolved = expanded.resolve()
    if expanded.is_relative_to(_ROOT) or resolved.is_relative_to(_ROOT):
        raise SeparationError("Raw separated audio must remain outside the Git repository")
    if any(parent.is_symlink() for parent in expanded.parents):
        raise SeparationError("Separation output cannot be under a linked directory")
    return resolved


def _load_runtime():
    # No heavy imports, network calls or model loading during module import.
    try:
        installed = version("demucs")
    except PackageNotFoundError as exc:
        raise SeparationError("Install demucs==4.0.1 in the private research environment") from exc
    if installed != DEMUCS_VERSION:
        raise SeparationError(f"Expected demucs=={DEMUCS_VERSION}, found {installed}")
    import numpy
    import torch
    from demucs import separate

    return separate, numpy, torch


def _package_model(separate, model: str) -> dict:
    signature, filename, _prefix = CHECKPOINTS[model]
    remote = Path(separate.__file__).resolve().parent / "remote"
    yaml = remote / f"{model}.yaml"
    manifest = remote / "files.txt"
    for path in (yaml, manifest):
        _regular(path)
        if not 0 < path.stat().st_size <= 1024 * 1024:
            raise SeparationError("Demucs package model manifest is empty or unexpectedly large")
    yaml_text = yaml.read_text(encoding="utf-8")
    if yaml_text.strip() != f"models: ['{signature}']":
        raise SeparationError("Demucs model YAML differs from the reviewed single-model bag")
    current_root = ""
    matches = []
    for raw in manifest.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("root:"):
            current_root = line.split(":", 1)[1].strip()
        elif line == filename:
            matches.append(current_root)
    if matches != ["hybrid_transformer/"]:
        raise SeparationError("Demucs package does not declare the reviewed checkpoint URL")
    return {
        "signature": signature, "yaml_text": yaml_text, "yaml_sha256": _sha256(yaml),
        "manifest_sha256": _sha256(manifest), "reference_source_revision": SOURCE_REVISION,
    }


def _checkpoint_root(torch) -> Path:
    # Never scan arbitrary caches or claim every cached model was used.
    torch_home = os.getenv("TORCH_HOME")
    if torch_home is None:
        cache = Path(os.getenv("XDG_CACHE_HOME", "~/.cache")).expanduser()
        torch_home = str(cache / "torch")
    expected = Path(torch_home).expanduser() / "hub" / "checkpoints"
    actual = Path(torch.hub.get_dir()).expanduser() / "checkpoints"
    if actual.resolve() != expected.resolve():
        raise SeparationError("Custom torch.hub directory is outside TORCH_HOME/hub/checkpoints")
    if actual.is_symlink() or any(parent.is_symlink() for parent in actual.parents):
        raise SeparationError("Checkpoint cache cannot contain linked directories")
    if actual.exists() and not actual.is_dir():
        raise SeparationError("Checkpoint cache is not a directory")
    return actual.resolve()


def _checkpoint(root: Path, model: str, *, required: bool) -> dict | None:
    _signature, filename, prefix = CHECKPOINTS[model]
    path = root / filename
    if not path.exists() and not path.is_symlink() and not required:
        return None
    _regular(path)
    if path.stat().st_size <= 0:
        raise SeparationError("Selected Demucs checkpoint is empty")
    digest = _sha256(path)
    if not digest.startswith(prefix):
        raise SeparationError("Selected Demucs checkpoint SHA-256 differs from official prefix")
    return {
        "filename": filename, "sha256": digest, "bytes": path.stat().st_size,
        "official_sha256_prefix": prefix, "prefix_verified": True,
        "official_full_sha256_available": False,
        "source_url": _CHECKPOINT_URL + filename,
        "inventory_scope": "selected_model_signature_only",
    }


def _validate_stems(audio: Path, root: Path, model: str, source: dict):
    expected = {name: root / model / audio.stem / f"{name}.wav" for name in STEMS[model]}
    files = list(root.rglob("*"))
    if any(path.is_symlink() for path in files):
        raise SeparationError("Separated output contains a symlink")
    actual_wavs = {path for path in files if path.suffix.lower() == ".wav"}
    if actual_wavs != set(expected.values()):
        raise SeparationError("Missing, duplicate or unexpected stems/output basename")
    evidence = {}
    sizes = set()
    identities = set()
    for name, path in expected.items():
        info = _wave_info(path)
        if (info["sample_rate"], info["channels"], info["sample_width_bytes"]) != (44100, 2, 2):
            raise SeparationError(f"{name} is not Demucs stereo 44.1 kHz PCM16 output")
        error = Fraction(info["frames"]) - Fraction(
            source["frames"] * info["sample_rate"], source["sample_rate"],
        )
        if abs(error) > 1:
            raise SeparationError(f"{name} duration differs from the source by more than one sample")
        sizes.add(info["frames"])
        stat = path.stat()
        identity = (stat.st_dev, stat.st_ino)
        if identity in identities:
            raise SeparationError("Two stem names refer to the same file")
        identities.add(identity)
        evidence[name] = {
            **info, "relative_path": path.relative_to(root).as_posix(),
            "duration_error_output_samples": float(error),
        }
    if len(sizes) != 1:
        raise SeparationError("Separated stems have different frame counts")
    return expected, evidence


def run_separation(
    audio_path: Path,
    output_root: Path,
    *,
    model: str = "htdemucs_6s",
    device: str = "cpu",
    seed: int = 0,
) -> tuple[dict[str, Path], dict]:
    """Run one fresh full 4/6-stem separation and return checked paths/evidence.

    The source must be PCM WAV. Resampling may change duration by at most one
    44.1 kHz output sample; every output must have the same frame count. Silent
    but nonempty stems remain present. A fixed seed is not a promise of bitwise
    equality across PyTorch versions, devices or nondeterministic kernels.
    """
    if model not in STEMS:
        raise SeparationError("Only htdemucs and htdemucs_6s are supported")
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise SeparationError("seed must be an integer in [0, 2**32)")
    if not isinstance(device, str) or not device.strip():
        raise SeparationError("A nonempty Demucs device is required")
    audio = audio_path.expanduser().absolute()
    source = _wave_info(audio)
    audio = audio.resolve()
    root = _new_private_root(output_root)
    force_weights = os.getenv("TORCH_FORCE_WEIGHTS_ONLY_LOAD", "")
    if force_weights.lower() in _TRUTHY:
        raise SeparationError("TORCH_FORCE_WEIGHTS_ONLY_LOAD conflicts with official Demucs checkpoints")
    separate, numpy, torch = _load_runtime()
    package_model = _package_model(separate, model)
    checkpoint_root = _checkpoint_root(torch)
    before = _checkpoint(checkpoint_root, model, required=False)
    args = [
        "-n", model, "-d", device, "--shifts", "1", "--clip-mode", "rescale",
        "--filename", _FILENAME, "-o", str(root), str(audio),
    ]
    parsed = separate.get_parser().parse_args(args)
    options = {
        "shifts": parsed.shifts, "clip_mode": parsed.clip_mode, "filename": parsed.filename,
        "split": parsed.split, "overlap": parsed.overlap, "segment": parsed.segment,
        "jobs": parsed.jobs, "sample_format": "PCM_S", "bits_per_sample": 16,
        "two_stems": parsed.stem,
    }
    random.seed(seed)
    numpy.random.seed(seed)
    torch.manual_seed(seed)
    cuda_seeded = bool(torch.cuda.is_available())
    if cuda_seeded:
        torch.cuda.manual_seed_all(seed)
    root.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    try:
        with redirect_stdout(sys.stderr):
            separate.main(args)
    except SystemExit as exc:
        raise SeparationError(f"Demucs CLI exited before verification ({exc.code})") from exc
    elapsed = time.perf_counter() - started
    if _sha256(audio) != source["sha256"]:
        raise SeparationError("Source audio changed while Demucs was running")
    stems, evidence = _validate_stems(audio, root, model, source)
    checkpoint = _checkpoint(checkpoint_root, model, required=True)
    if before is not None and checkpoint["sha256"] != before["sha256"]:
        raise SeparationError("Selected checkpoint changed while Demucs was running")
    checkpoint["cached_before_run"] = before is not None
    try:
        torchaudio_version = version("torchaudio")
    except PackageNotFoundError:
        torchaudio_version = None
    runtime = {
        "python": platform.python_version(), "numpy": numpy.__version__,
        "torch": torch.__version__, "torchaudio": torchaudio_version,
    }
    identity = {
        "model": model, "demucs_version": DEMUCS_VERSION, "device": device,
        "seed": seed, "options": options, "checkpoint_sha256": checkpoint["sha256"],
        "model_yaml_sha256": package_model["yaml_sha256"], "runtime": runtime,
    }
    return stems, {
        "schema_version": 1, "purpose": "private-demucs-separation-ablation",
        "demucs_version": DEMUCS_VERSION, "model": model, "device": device, "seed": seed,
        "options": options, "elapsed_seconds": round(elapsed, 6),
        "elapsed_scope": "demucs_cli_including_model_load",
        "runtime": runtime, "identity": identity,
        "rng_seeded": ["python_random", "numpy", "torch"], "cuda_rng_seeded": cuda_seeded,
        "bitwise_determinism_claimed": False, "input": source, "stems": evidence,
        "duration_tolerance_output_samples": 1,
        "checkpoint": checkpoint, "package_model": package_model,
        "torch_load_environment": {
            "force_weights_only": force_weights or None,
            "force_no_weights_only": os.getenv("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD") or None,
            "modified_by_runner": False,
        },
        "source_media_published": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path)
    parser.add_argument("output_root", type=Path)
    parser.add_argument("--model", choices=tuple(STEMS), default="htdemucs_6s")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    try:
        _stems, evidence = run_separation(
            args.audio, args.output_root, model=args.model, device=args.device, seed=args.seed,
        )
    except (OSError, RuntimeError, SeparationError) as exc:
        parser.exit(2, f"Demucs research separation failed: {exc}\n")
    print(json.dumps(evidence, sort_keys=True, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

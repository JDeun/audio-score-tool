"""Capture native Windows/macOS FFmpeg build evidence without publishing binaries.

A source checkout is pinned to an exact official FFmpeg commit; ffmpeg and
ffprobe are executed as absolute paths with PATH empty. The report captures
actual stdout + per-executable SHA-256 and proves a synthetic PCM/WAV flow.
This does NOT prove a reproducible build, source signatures, legal compliance,
or real YouTube integration.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from scripts.assemble_youtube_runtime_candidate import _ensure_binary_architecture
from scripts.verify_ffmpeg_build_provenance import _configuration, review_ffmpeg_build, write_report

DEFAULT_PIN = (
    Path(__file__).resolve().parents[1]
    / "release/review/ffmpeg-native-source-pin-2026-11-07.json"
)
_TARGETS = {"windows-x86_64", "macos-aarch64"}
_MAX_STDOUT = 256 * 1024


class FFmpegNativeReviewError(ValueError):
    """A review-only native build did not meet its pinned contract."""


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _platform_ok(target: str) -> bool:
    machine = platform.machine().lower()
    return (
        (target == "windows-x86_64" and platform.system() == "Windows"
         and machine in {"amd64", "x86_64"})
        or (target == "macos-aarch64" and platform.system() == "Darwin"
            and machine in {"arm64", "aarch64"})
    )


def _run(
    argv: list[str], *,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: int = 30,
    label: str,
) -> str:
    try:
        result = subprocess.run(
            argv,
            cwd=str(cwd),
            env=env,
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FFmpegNativeReviewError(f"{label}: native process could not complete.") from exc
    if result.returncode != 0:
        raise FFmpegNativeReviewError(f"{label}: native process failed (exit {result.returncode}).")
    if len(result.stdout.encode("utf-8")) > _MAX_STDOUT:
        raise FFmpegNativeReviewError(f"{label}: unexpected unbounded stdout.")
    return result.stdout


def _pin(pin_file: Path, target: str) -> dict:
    if target not in _TARGETS or not _platform_ok(target):
        raise FFmpegNativeReviewError("FFmpeg build review must run on the exact target OS/CPU.")
    if pin_file.is_symlink() or not pin_file.is_file():
        raise FFmpegNativeReviewError("Pinned review source manifest is missing or unsafe.")
    try:
        pin = json.loads(pin_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise FFmpegNativeReviewError("Pinned review source manifest is not valid JSON.") from exc
    if (
        not isinstance(pin, dict)
        or pin.get("schema") != 1
        or pin.get("component") != "youtube_runtime.ffmpeg"
        or pin.get("repository") != "FFmpeg/FFmpeg"
        or pin.get("target") is not None
        or target not in pin.get("targets", [])
        or pin.get("redistribution_status") != "pending"
        or pin.get("legal_review_status") != "pending"
        or pin.get("source_signature_verified") is not False
        or pin.get("reproducible_rebuild_verified") is not False
        or pin.get("catalog_published") is not False
        or pin.get("notices_and_source_delivery_approved") is not False
    ):
        raise FFmpegNativeReviewError("FFmpeg build must use an unapproved pinned official source review.")
    commit = pin.get("source_commit")
    tag = pin.get("tag")
    flags = pin.get("configure_flags")
    if (
        not isinstance(commit, str)
        or not re.fullmatch(r"[a-f0-9]{40}", commit)
        or not isinstance(tag, str)
        or not re.fullmatch(r"n\d+\.\d+\.\d+", tag)
        or pin.get("version") != tag
        or pin.get("source_url") != f"https://github.com/FFmpeg/FFmpeg/commit/{commit}"
        or not isinstance(flags, list)
        or not flags
        or any(not isinstance(flag, str) or not flag.startswith("--") for flag in flags)
        or len(flags) != len(set(flags))
        or not {"--disable-autodetect", "--disable-gpl", "--disable-nonfree",
                "--disable-shared", "--enable-static", "--enable-ffmpeg",
                "--enable-ffprobe"} <= set(flags)
        or pin.get("external_libraries") != {}
        or pin.get("license_family_review") != "LGPL-2.1-or-later"
    ):
        raise FFmpegNativeReviewError("FFmpeg official source revision/flags/license review contract is invalid.")
    per_target = pin.get("target_configure_flags")
    if not isinstance(per_target, dict) or set(per_target) != _TARGETS:
        raise FFmpegNativeReviewError("Missing explicit per-platform FFmpeg runtime linkage contract.")
    for os_target, extra in per_target.items():
        if (
            not isinstance(extra, list)
            or any(not isinstance(flag, str) or not flag.startswith("--") for flag in extra)
            or len(extra) != len(set(extra))
            or set(extra) & set(flags)
        ):
            raise FFmpegNativeReviewError("Invalid per-platform FFmpeg linker flags.")
        if os_target == "windows-x86_64" and extra != ["--extra-ldflags=-static"]:
            raise FFmpegNativeReviewError("Windows FFmpeg must statically link MinGW runtime dependencies.")
        if os_target == "macos-aarch64" and extra:
            raise FFmpegNativeReviewError("macOS must not claim unsupported static system linkage.")
    return pin


def verify_native_build(
    *,
    source: Path,
    target: str,
    destination: Path,
    pin_file: Path = DEFAULT_PIN,
) -> dict:
    pin = _pin(pin_file, target)
    expected_flags = [*pin["configure_flags"], *pin["target_configure_flags"][target]]
    if source.is_symlink() or not source.is_dir():
        raise FFmpegNativeReviewError("FFmpeg source checkout is missing or symlinked.")
    src = source.resolve()
    if not destination.parent.is_dir() or destination.exists() or destination.is_symlink():
        raise FFmpegNativeReviewError("Evidence output directory must be new with an existing parent.")
    head = _run(["git", "-C", str(src), "rev-parse", "HEAD"], cwd=src, label="git-source")
    if head.strip() != pin["source_commit"]:
        raise FFmpegNativeReviewError("FFmpeg checkout does not match the pinned official commit.")

    suffix = ".exe" if target.startswith("windows-") else ""
    binaries: dict[str, Path] = {}
    hashes: dict[str, str] = {}
    for name in ("ffmpeg", "ffprobe"):
        binary = src / (name + suffix)
        if binary.is_symlink() or not binary.is_file() or binary.resolve().parent != src:
            raise FFmpegNativeReviewError(f"{name}: compiled native binary is missing or unsafe.")
        try:
            _ensure_binary_architecture(binary, target, name)
        except ValueError as exc:
            raise FFmpegNativeReviewError(str(exc)) from exc
        binaries[name] = binary
        hashes[name] = _sha(binary)

    env = os.environ.copy()
    env["PATH"] = ""
    env["PYTHONNOUSERSITE"] = "1"
    stage: Path | None = None
    try:
        stage = Path(tempfile.mkdtemp(prefix=".ffmpeg-review-", dir=destination.parent))
        versions: dict[str, str] = {}
        compilers: set[str] = set()
        for name, binary in binaries.items():
            output = _run(
                [str(binary), "-version"],
                cwd=src, env=env, timeout=20, label=f"{name}-version",
            )
            if not output.startswith(f"{name} version {pin['version']} "):
                raise FFmpegNativeReviewError(f"{name}: native version differs from official release pin.")
            compiler = [
                line.strip().removeprefix("built with ").strip()
                for line in output.splitlines() if line.startswith("built with ")
            ]
            if len(compiler) != 1 or not compiler[0]:
                raise FFmpegNativeReviewError(f"{name}: actual compiler identity is missing.")
            compilers.add(compiler[0])
            report = stage / f"{name}-version.txt"
            report.write_text(output, encoding="utf-8")
            actual_flags = _configuration(report, name, pin["version"])
            if set(actual_flags) != set(expected_flags):
                raise FFmpegNativeReviewError(f"{name}: actual configure flags differ from pinned review build.")
            if _sha(binary) != hashes[name]:
                raise FFmpegNativeReviewError(f"{name}: binary changed during native version probe.")
            versions[name] = output
        if len(compilers) != 1:
            raise FFmpegNativeReviewError("FFmpeg/ffprobe reported different compiler toolchains.")

        with tempfile.TemporaryDirectory(prefix="ast-ffmpeg-synth-") as temp:
            wave = Path(temp) / "original-generated.wav"
            _run(
                [
                    str(binaries["ffmpeg"]), "-hide_banner", "-loglevel", "error",
                    "-nostdin", "-f", "lavfi",
                    "-i", "sine=frequency=440:sample_rate=44100:duration=0.25",
                    "-ac", "1", "-ar", "44100", "-c:a", "pcm_s16le",
                    "-f", "wav", "-y", str(wave),
                ],
                cwd=src, env=env, timeout=45, label="synthetic-PCM-generation",
            )
            if not wave.is_file() or wave.stat().st_size < 2048:
                raise FFmpegNativeReviewError("Synthetic PCM WAV output is missing or empty.")
            probe = _run(
                [
                    str(binaries["ffprobe"]), "-v", "error", "-select_streams", "a:0",
                    "-show_entries", "stream=codec_name,sample_rate",
                    "-of", "json", str(wave),
                ],
                cwd=src, env=env, timeout=20, label="synthetic-PCM-probe",
            )
            try:
                stream_data = json.loads(probe)
                streams = stream_data["streams"]
            except (ValueError, KeyError, TypeError) as exc:
                raise FFmpegNativeReviewError("ffprobe returned invalid synthetic audio metadata.") from exc
            if not (
                isinstance(streams, list)
                and len(streams) == 1
                and streams[0].get("codec_name") == "pcm_s16le"
                and str(streams[0].get("sample_rate")) == "44100"
            ):
                raise FFmpegNativeReviewError("Synthetic audio PCM codec/rate is inconsistent.")
            wave_digest = _sha(wave)

        for name, binary in binaries.items():
            if _sha(binary) != hashes[name]:
                raise FFmpegNativeReviewError(f"{name}: binary changed after audio round-trip.")

        build_record = stage / "build-record.txt"
        toolchain = next(iter(compilers))
        build_record.write_text(
            f"source_commit={pin['source_commit']}\n"
            f"source_tag={pin['tag']}\n"
            f"target={target}\n"
            f"toolchain={toolchain}\n"
            f"flags={' '.join(expected_flags)}\n"
            f"ffmpeg_sha256={hashes['ffmpeg']}\n"
            f"ffprobe_sha256={hashes['ffprobe']}\n"
            "review_status=pending\n",
            encoding="utf-8",
        )
        manifest = {
            "schema": 1, "target": target, "version": pin["version"],
            "source_revision": pin["source_commit"], "source_url": pin["source_url"],
            "toolchain": toolchain,
            "license_notice": str(src / "LICENSE.md"),
            "build_record": str(build_record),
            "configure_flags": expected_flags,
            "external_libraries": {},
            "tools": {
                name: {
                    "file": str(binary), "sha256": hashes[name],
                    "version_report": str(stage / f"{name}-version.txt"),
                    "license": pin["license_family_review"],
                }
                for name, binary in binaries.items()
            },
        }
        offline = review_ffmpeg_build(manifest)
        if offline["inferred_license"] != "LGPL-2.1-or-later":
            raise FFmpegNativeReviewError("Unexpected native FFmpeg license family.")
        attestation = stage / "FFMPEG-BUILD-REVIEW.pending.json"
        write_report(attestation, offline)
        receipt = {
            "schema": 1, "component": "youtube_runtime.ffmpeg",
            "target": target,
            "source_commit": pin["source_commit"], "source_tag": pin["tag"],
            "source_url": pin["source_url"],
            "source_pin_sha256": _sha(pin_file),
            "compiler": toolchain,
            "configure_flags": expected_flags,
            "tools": {
                name: {
                    "binary_sha256": hashes[name],
                    "version_report_sha256": _sha(stage / f"{name}-version.txt"),
                    "native_version": pin["version"],
                    "native_executed": True,
                }
                for name in binaries
            },
            "synthetic_pcm_wav_produced": True,
            "synthetic_pcm_wav_sha256": wave_digest,
            "synthetic_audio_codec": "pcm_s16le",
            "synthetic_audio_sample_rate": 44100,
            "offline_attestation_sha256": _sha(attestation),
            "live_cli_versions_captured": True,
            "binary_execution_verified": True,
            "reproducible_rebuild_verified": False,
            "system_linkage_independently_inspected": False,
            "source_signature_verified": False,
            "legal_review_status": "pending",
            "redistribution_status": "pending",
            "catalog_published": False,
            "approval_required": True,
        }
        (stage / "NATIVE-FFMPEG-EVIDENCE.pending.json").write_text(
            json.dumps(receipt, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        stage.rename(destination)
        stage = None
        return receipt
    finally:
        if stage is not None and stage.exists():
            shutil.rmtree(stage, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capture FFmpeg native build and synthetic PCM proof (review only)."
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", choices=sorted(_TARGETS), required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--pin", type=Path, default=DEFAULT_PIN)
    args = parser.parse_args()
    try:
        report = verify_native_build(
            source=args.source, target=args.target,
            destination=args.output_dir, pin_file=args.pin,
        )
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Native FFmpeg build review rejected: {exc}\n")
    print(json.dumps({
        "target": report["target"],
        "source_commit": report["source_commit"],
        "native_audio_verified": report["synthetic_pcm_wav_produced"],
        "binary_execution_verified": report["binary_execution_verified"],
        "redistribution_status": report["redistribution_status"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

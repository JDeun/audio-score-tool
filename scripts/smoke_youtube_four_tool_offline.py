"""Exercise a four-tool YouTube *candidate* against a loopback-owned sine wave.

This is not an actual YouTube download or a redistribution approval. Only the
official pinned yt-dlp+Deno bytes and the previously native-built SHA-verified
FFmpeg/ffprobe files may enter an isolated bin directory. PATH is empty; the
source is a local 127.0.0.1 HTTP fixture created and deleted in the same run.
Only a pending JSON receipt leaves this process, never an executable or audio.
"""
from __future__ import annotations

import argparse
import hashlib
import http.server
import json
import math
import os
import platform
import shutil
import struct
import subprocess
import tempfile
import threading
import wave
from pathlib import Path
from typing import Any

from scripts.assemble_youtube_runtime_candidate import _ensure_binary_architecture
from scripts.verify_ffmpeg_native_build import DEFAULT_PIN as FFMPEG_PIN
from scripts.verify_youtube_native_cli import PINS as YOUTUBE_PINS

_TOOLS = ("yt-dlp", "deno", "ffmpeg", "ffprobe")
_MAX_TOOL_STDOUT = 128 * 1024


class OfflineFourToolError(ValueError):
    """Four-tool local receipt, runtime, or media handoff failed."""


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, label: str) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise OfflineFourToolError(f"{label}: missing, unsafe, or oversized evidence.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise OfflineFourToolError(f"{label}: evidence cannot be decoded.") from exc
    if not isinstance(data, dict):
        raise OfflineFourToolError(f"{label}: evidence must be an object.")
    return data


def _native_target(target: str) -> bool:
    system = platform.system().lower()
    machine = platform.machine().lower()
    return (
        (target == "windows-x86_64" and system == "windows" and machine in {"amd64", "x86_64"})
        or (target == "macos-aarch64" and system == "darwin" and machine in {"arm64", "aarch64"})
    )


def _validate_sources(
    target: str,
    youtube_dir: Path,
    ffmpeg_dir: Path,
    ffmpeg_receipt: Path,
    youtube_pins: Path,
    ffmpeg_pin: Path,
) -> dict[str, Any]:
    if not _native_target(target):
        raise OfflineFourToolError("The isolated four-tool smoke must run on the native OS/architecture.")
    if any(root.is_symlink() or not root.is_dir() for root in (youtube_dir, ffmpeg_dir)):
        raise OfflineFourToolError("Input binary directories must be regular non-symlink directories.")
    official = _read_json(youtube_dir / "SOURCE-EVIDENCE.pending.json", "official source")
    downloaded = _read_json(youtube_dir / "DOWNLOAD-EVIDENCE.pending.json", "download receipt")
    ffmpeg = _read_json(ffmpeg_receipt, "native FFmpeg")
    yt_pin = _read_json(youtube_pins, "official source pins")
    ff_pin = _read_json(ffmpeg_pin, "FFmpeg source pin")
    if (
        official.get("schema") != 1
        or official.get("component") != "youtube_runtime"
        or official.get("target") != target
        or official.get("local_bytes_verified") is not True
        or official.get("redistribution_status") != "pending"
        or official.get("upstream_signature_verified") is not False
        or downloaded.get("schema") != 1
        or downloaded.get("target") != target
        or downloaded.get("approval_status") != "pending"
        or downloaded.get("official_asset_bytes_sha256_verified") is not True
        or downloaded.get("native_binary_startup_verified") is not True
        or downloaded.get("redistribution_approved") is not False
        or downloaded.get("catalog_modified") is not False
        or ffmpeg.get("schema") != 1
        or ffmpeg.get("component") != "youtube_runtime.ffmpeg"
        or ffmpeg.get("target") != target
        or ffmpeg.get("binary_execution_verified") is not True
        or ffmpeg.get("synthetic_pcm_wav_produced") is not True
        or ffmpeg.get("redistribution_status") != "pending"
        or ffmpeg.get("approval_required") is not True
        or ffmpeg.get("catalog_published") is not False
        or ff_pin.get("schema") != 1
        or ff_pin.get("redistribution_status") != "pending"
        or ff_pin.get("source_commit") != ffmpeg.get("source_commit")
        or ff_pin.get("catalog_published") is not False
        or yt_pin.get("approval_status") != "pending"
        or not isinstance(yt_pin.get("targets"), dict)
        or target not in yt_pin["targets"]
        or _digest(ffmpeg_pin) != ffmpeg.get("source_pin_sha256")
    ):
        raise OfflineFourToolError("Unapproved official and native proof receipts are missing or inconsistent.")
    official_records = official.get("inputs")
    source_records = downloaded.get("sources")
    ffmpeg_tools = ffmpeg.get("tools")
    pinned = yt_pin["targets"][target]
    if any(
        not isinstance(entry, dict)
        for entry in (official_records, source_records, ffmpeg_tools, pinned)
    ) or set(official_records) != {"yt-dlp", "deno"} or set(source_records) != {"yt-dlp", "deno"} or set(ffmpeg_tools) != {"ffmpeg", "ffprobe"}:
        raise OfflineFourToolError("Four-tool source evidence is incomplete.")
    expected: dict[str, str] = {}
    for name in ("yt-dlp", "deno"):
        selected = official_records[name]
        downloaded_tool = source_records[name]
        fixed = pinned[name]
        if not isinstance(selected, dict) or not isinstance(downloaded_tool, dict) or not isinstance(fixed, dict):
            raise OfflineFourToolError(f"{name}: official provenance entry is invalid.")
        if any(selected.get(left) != fixed.get(right) for left, right in (
            ("repository", "repository"), ("tag", "tag"), ("asset", "asset"),
            ("upstream_url", "url"), ("source_sha256", "sha256"),
            ("source_bytes", "bytes"), ("license_review", "license_review"),
        )):
            raise OfflineFourToolError(f"{name}: official source evidence differs from the committed pin.")
        if (
            downloaded_tool.get("pinned_asset_sha256") != fixed.get("sha256")
            or downloaded_tool.get("extracted_tool_sha256") != selected.get("tool_sha256")
            or downloaded_tool.get("official_tag") != fixed.get("tag")
        ):
            raise OfflineFourToolError(f"{name}: download receipt differs from official source.")
        expected[name] = str(selected["tool_sha256"])
    for name in ("ffmpeg", "ffprobe"):
        entry = ffmpeg_tools[name]
        if not isinstance(entry, dict) or entry.get("native_executed") is not True:
            raise OfflineFourToolError(f"{name}: native build proof is incomplete.")
        expected[name] = str(entry.get("binary_sha256") or "")
    suffix = ".exe" if target == "windows-x86_64" else ""
    selected_files = {
        "yt-dlp": youtube_dir / ("yt-dlp" + suffix),
        "deno": youtube_dir / ("deno" + suffix),
        "ffmpeg": ffmpeg_dir / ("ffmpeg" + suffix),
        "ffprobe": ffmpeg_dir / ("ffprobe" + suffix),
    }
    for name, path in selected_files.items():
        if path.is_symlink() or not path.is_file() or path.resolve().parent != path.parent.resolve():
            raise OfflineFourToolError(f"{name}: selected binary path is unsafe.")
        if len(expected[name]) != 64 or _digest(path) != expected[name]:
            raise OfflineFourToolError(f"{name}: selected binary SHA differs from verified source.")
        try:
            _ensure_binary_architecture(path, target, name)
        except ValueError as exc:
            raise OfflineFourToolError(str(exc)) from exc
    return {
        "files": selected_files,
        "digests": expected,
        "official_source_evidence_sha256": _digest(youtube_dir / "SOURCE-EVIDENCE.pending.json"),
        "download_evidence_sha256": _digest(youtube_dir / "DOWNLOAD-EVIDENCE.pending.json"),
        "ffmpeg_native_evidence_sha256": _digest(ffmpeg_receipt),
        "official_source_pin_sha256": _digest(youtube_pins),
        "ffmpeg_source_pin_sha256": _digest(ffmpeg_pin),
    }


def _run_binary(executable: Path, args: list[str], *, cwd: Path, env: dict, label: str, timeout: int = 45) -> str:
    if not executable.is_absolute() or executable.is_symlink() or not executable.is_file():
        raise OfflineFourToolError(f"{label}: binary must be an absolute regular executable.")
    if env.get("PATH") != "":
        raise OfflineFourToolError(f"{label}: PATH fallback is forbidden.")
    try:
        completed = subprocess.run(
            [str(executable), *args],
            shell=False, env=env, cwd=str(cwd),
            timeout=timeout, capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OfflineFourToolError(f"{label}: isolated native CLI did not complete.") from exc
    if completed.returncode != 0:
        detail = completed.stderr[:800].replace("\n", " ").replace("\r", " ")
        raise OfflineFourToolError(f"{label}: CLI failed (exit {completed.returncode}): {detail}")
    if len(completed.stdout.encode("utf-8")) > _MAX_TOOL_STDOUT:
        raise OfflineFourToolError(f"{label}: excessive command output.")
    return completed.stdout


def _synthetic_wav(destination: Path) -> None:
    count = 22_050  # exactly 0.5 seconds of user-owned 440Hz test tone
    frames = b"".join(
        struct.pack("<h", round(7000 * math.sin(2 * math.pi * 440 * i / 44100)))
        for i in range(count)
    )
    with wave.open(str(destination), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(44100)
        handle.writeframes(frames)


def _serve_owned_wav(wav: Path) -> tuple[http.server.ThreadingHTTPServer, threading.Thread]:
    payload = wav.read_bytes()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_HEAD(self):
            self._respond(False)

        def do_GET(self):
            self._respond(True)

        def _respond(self, include_body: bool):
            if self.path != "/original-sine.wav" or self.headers.get("Host", "").split(":")[0] != "127.0.0.1":
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if include_body:
                self.wfile.write(payload)

        def log_message(self, _format, *_args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    task = threading.Thread(target=server.serve_forever, daemon=True)
    task.start()
    return server, task


def verify_offline_four_tool(
    *,
    target: str,
    youtube_dir: Path,
    ffmpeg_dir: Path,
    ffmpeg_receipt: Path,
    output_receipt: Path,
    youtube_pins: Path = YOUTUBE_PINS,
    ffmpeg_pin: Path = FFMPEG_PIN,
) -> dict:
    if not output_receipt.parent.is_dir() or output_receipt.exists() or output_receipt.is_symlink():
        raise OfflineFourToolError("Four-tool pending evidence must be a new file in an existing directory.")
    source = _validate_sources(
        target, youtube_dir, ffmpeg_dir, ffmpeg_receipt, youtube_pins, ffmpeg_pin,
    )
    with tempfile.TemporaryDirectory(prefix="ast-four-tool-offline-") as temp:
        root = Path(temp).resolve()
        bin_dir = root / "bin"
        bin_dir.mkdir()
        copied: dict[str, Path] = {}
        for name in _TOOLS:
            original = source["files"][name]
            target_binary = bin_dir / original.name
            shutil.copy2(original, target_binary)
            if _digest(target_binary) != source["digests"][name]:
                raise OfflineFourToolError(f"{name}: staged binary changed while copying.")
            copied[name] = target_binary

        env = os.environ.copy()
        env.update({
            "PATH": "", "PYTHONNOUSERSITE": "1",
            "HOME": str(root), "XDG_CONFIG_HOME": str(root),
            "APPDATA": str(root),
            "HTTP_PROXY": "", "HTTPS_PROXY": "", "ALL_PROXY": "",
            "NO_PROXY": "127.0.0.1,localhost",
        })
        assert all(p.parent == bin_dir for p in copied.values())
        for name, args, version in (
            ("yt-dlp", ["--ignore-config", "--no-remote-components", "--version"], "2026.10.26"),
            ("deno", ["--version"], "2.9.8"),
        ):
            stdout = _run_binary(copied[name], args, cwd=root, env=env, label=name, timeout=25)
            first = stdout.strip().splitlines()
            actual = first[0].strip() if name == "yt-dlp" and first else (
                first[0].split()[1] if first and len(first[0].split()) >= 2
                and first[0].split()[0].lower() == "deno" else ""
            )
            if actual != version:
                raise OfflineFourToolError(f"{name}: isolated CLI version differs from official source.")

        input_wav = root / "original-sine.wav"
        _synthetic_wav(input_wav)
        http, task = _serve_owned_wav(input_wav)
        try:
            result_dir = root / "exports"
            result_dir.mkdir()
            url = f"http://127.0.0.1:{http.server_address[1]}/original-sine.wav"
            _run_binary(
                copied["yt-dlp"],
                [
                    "--ignore-config", "--no-remote-components",
                    "--no-cache-dir", "--no-playlist", "--force-generic-extractor",
                    "--no-progress", "--js-runtimes", f"deno:{copied['deno']}",
                    "--ffmpeg-location", str(bin_dir),
                    "--extract-audio", "--audio-format", "flac",
                    "--output", str(result_dir / "extracted.%(ext)s"), url,
                ],
                cwd=root, env=env, label="yt-dlp-local-ffmpeg-handoff", timeout=80,
            )
        finally:
            http.shutdown()
            http.server_close()
            task.join(timeout=5)
        results = list(result_dir.glob("*.flac"))
        if len(results) != 1 or results[0].stat().st_size < 1024:
            raise OfflineFourToolError("yt-dlp did not use FFmpeg to produce one FLAC output.")
        if results[0].read_bytes()[:4] != b"fLaC":
            raise OfflineFourToolError("Audio conversion output is not FLAC.")
        stdout = _run_binary(
            copied["ffprobe"],
            [
                "-v", "error", "-select_streams", "a:0",
                "-show_entries", "stream=codec_name,sample_rate",
                "-of", "json", str(results[0]),
            ],
            cwd=root, env=env, label="ffprobe-converted-audio", timeout=20,
        )
        try:
            data = json.loads(stdout)
            streams = data["streams"]
        except (ValueError, KeyError, TypeError) as exc:
            raise OfflineFourToolError("ffprobe did not return valid converted audio metadata.") from exc
        if (
            not isinstance(streams, list) or len(streams) != 1
            or streams[0].get("codec_name") != "flac"
            or str(streams[0].get("sample_rate")) != "44100"
        ):
            raise OfflineFourToolError("Converted FLAC codec/sample-rate mismatch.")
        for name, binary in copied.items():
            if _digest(binary) != source["digests"][name]:
                raise OfflineFourToolError(f"{name}: staged executable changed during handoff.")
        evidence = {
            "schema": 1, "component": "youtube_runtime",
            "target": target,
            "official_source_evidence_sha256": source["official_source_evidence_sha256"],
            "download_evidence_sha256": source["download_evidence_sha256"],
            "ffmpeg_native_evidence_sha256": source["ffmpeg_native_evidence_sha256"],
            "official_source_pin_sha256": source["official_source_pin_sha256"],
            "ffmpeg_source_pin_sha256": source["ffmpeg_source_pin_sha256"],
            "tool_sha256": dict(source["digests"]),
            "isolated_four_tool_bin_verified": True,
            "system_path_fallback": False,
            "synthetic_local_http_only": True,
            "yt_dlp_ffmpeg_flac_handoff_verified": True,
            "ffprobe_converted_audio_verified": True,
            "converted_flac_sha256": _digest(results[0]),
            "converted_flac_bytes": results[0].stat().st_size,
            "deno_native_startup_verified": True,
            "deno_youtube_js_challenge_verified": False,
            "real_youtube_download_verified": False,
            "binary_artifacts_published": False,
            "redistribution_status": "pending",
            "legal_review_status": "pending",
            "approval_required": True,
        }
    with output_receipt.open("x", encoding="utf-8") as output:
        json.dump(evidence, output, ensure_ascii=False, sort_keys=True, indent=2)
        output.write("\n")
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description="Owned local WAV → yt-dlp → FFmpeg → FLAC smoke (unapproved).")
    parser.add_argument("--target", choices=("windows-x86_64", "macos-aarch64"), required=True)
    parser.add_argument("--youtube-dir", type=Path, required=True)
    parser.add_argument("--ffmpeg-dir", type=Path, required=True)
    parser.add_argument("--ffmpeg-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = verify_offline_four_tool(
            target=args.target, youtube_dir=args.youtube_dir,
            ffmpeg_dir=args.ffmpeg_dir, ffmpeg_receipt=args.ffmpeg_receipt,
            output_receipt=args.output,
        )
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Four-tool offline YouTube smoke rejected: {exc}\n")
    print(json.dumps({
        "target": report["target"],
        "local_ffmpeg_handoff_verified": report["yt_dlp_ffmpeg_flac_handoff_verified"],
        "all_binary_publication": False,
        "redistribution_status": report["redistribution_status"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

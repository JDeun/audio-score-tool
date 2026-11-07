"""Fetch only pinned official yt-dlp/Deno assets for local, unapproved release QA.

Never fetch an arbitrary URL, publish binaries, edit the managed catalog, or
grant redistribution approval. Native execution is a separate explicit opt-in.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import zipfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import BinaryIO, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts.assemble_youtube_runtime_candidate import _ensure_binary_architecture  # noqa: E402
from scripts.verify_youtube_official_sources import (  # noqa: E402
    DEFAULT_PINS,
    TARGETS,
    extract_reviewed_sources,
)

ASSETS = {
    "windows-x86_64": {
        "yt-dlp": ("yt-dlp/yt-dlp", "yt-dlp.exe", "yt-dlp.exe"),
        "deno": ("denoland/deno", "deno-x86_64-pc-windows-msvc.zip", "deno.exe"),
    },
    "macos-aarch64": {
        "yt-dlp": ("yt-dlp/yt-dlp", "yt-dlp_macos", "yt-dlp"),
        "deno": ("denoland/deno", "deno-aarch64-apple-darwin.zip", "deno"),
    },
}
_SHA = re.compile(r"^[a-f0-9]{64}$")
_TAG = re.compile(r"^v?[0-9][A-Za-z0-9._-]{0,63}$")
_MAX_ASSET_BYTES = {"yt-dlp": 128 * 1024 * 1024, "deno": 256 * 1024 * 1024}
_DOWNLOAD_HOSTS = frozenset({
    "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com",
})


def _trusted_redirect_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Official asset redirect has an invalid port.") from exc
    if (
        parsed.scheme != "https" or parsed.hostname not in _DOWNLOAD_HOSTS
        or port not in {None, 443} or parsed.username or parsed.password
        or parsed.fragment
    ):
        raise ValueError("Official release asset redirect left trusted HTTPS hosts.")


class _PinnedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Refuse untrusted redirects BEFORE a network request to that host.
        _trusted_redirect_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open_official_asset(url: str) -> BinaryIO:
    _trusted_redirect_url(url)
    opener = urllib.request.build_opener(_PinnedRedirect())
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "AudioScoreTool-pinned-source-qa/1"},
        method="GET",
    )
    return opener.open(request, timeout=90)


def _pinned_assets(pin_file: Path, target: str) -> dict[str, dict]:
    if target not in TARGETS:
        raise ValueError("Unsupported official source target.")
    document = json.loads(pin_file.read_text(encoding="utf-8"))
    if (
        not isinstance(document, dict)
        or document.get("schema") != 1
        or document.get("approval_status") != "pending"
        or document.get("publication_catalog_modified") is not False
        or set(document.get("targets", {}).get(target, {})) != {"yt-dlp", "deno"}
    ):
        raise ValueError("Expected a pending, unchanged official-source pin set.")
    records = document["targets"][target]
    for tool, (repository, asset, extracted) in ASSETS[target].items():
        entry = records[tool]
        if not isinstance(entry, dict):
            raise ValueError(f"{tool}: pin record must be an object.")
        tag = entry.get("tag")
        if (
            not isinstance(tag, str) or not _TAG.fullmatch(tag)
            or entry.get("repository") != repository
            or entry.get("asset") != asset
            or entry.get("extracted_tool") != extracted
            or entry.get("url") != (
                f"https://github.com/{repository}/releases/download/{tag}/{asset}"
            )
        ):
            raise ValueError(f"{tool}: not the exact official tagged release URL/asset.")
        size, digest = entry.get("bytes"), entry.get("sha256")
        if (
            type(size) is not int or size < 1 or size > _MAX_ASSET_BYTES[tool]
            or not isinstance(digest, str) or _SHA.fullmatch(digest) is None
        ):
            raise ValueError(f"{tool}: unsafe or incomplete pinned byte size/SHA-256.")
    return records


def _download_checked(
    url: str,
    destination: Path,
    *,
    size: int,
    sha256: str,
    open_asset: Callable[[str], BinaryIO] = _open_official_asset,
) -> None:
    digest = hashlib.sha256()
    received = 0
    try:
        with open_asset(url) as source, destination.open("xb") as output:
            result_url = source.geturl() if hasattr(source, "geturl") else url
            _trusted_redirect_url(str(result_url))
            while chunk := source.read(min(1024 * 1024, size - received + 1)):
                received += len(chunk)
                if received > size:
                    raise ValueError("Official source exceeds pinned byte size.")
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if received != size:
            raise ValueError("Official source byte size differs from pinned release.")
        if digest.hexdigest() != sha256:
            raise ValueError("Official source SHA-256 differs from pinned release.")
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def _host_target() -> str:
    machine = platform.machine().lower()
    if sys.platform == "win32" and machine in {"amd64", "x86_64"}:
        return "windows-x86_64"
    if sys.platform == "darwin" and machine in {"arm64", "aarch64"}:
        return "macos-aarch64"
    raise ValueError("Native review requires Windows x86_64 or Apple Silicon macOS.")


def _probe_native_tools(
    target: str, path: Path, pins: dict[str, dict],
    *,
    run: Callable | None = None,
) -> dict:
    if target != _host_target():
        raise ValueError("Refusing to execute an executable on a different target architecture.")
    run = run or subprocess.run
    suffix = ".exe" if target == "windows-x86_64" else ""
    expected = {
        "yt-dlp": pins["yt-dlp"]["tag"],
        "deno": pins["deno"]["tag"].removeprefix("v"),
    }
    outputs = {}
    # Never use user-installed yt-dlp config or an ambient JS runtime.
    env = os.environ.copy()
    env.update({
        "PATH": "",
        "HOME": str(path),
        "XDG_CONFIG_HOME": str(path),
        "APPDATA": str(path),
        "PYTHONNOUSERSITE": "1",
    })
    for tool in ("yt-dlp", "deno"):
        executable = path / f"{tool}{suffix}"
        args = (
            ["--ignore-config", "--no-remote-components", "--version"]
            if tool == "yt-dlp" else ["--version"]
        )
        try:
            process = run(
                [str(executable.resolve()), *args], capture_output=True,
                text=True, timeout=25, env=env, cwd=path, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError(f"{tool}: native --version execution failed.") from exc
        if process.returncode != 0:
            raise ValueError(f"{tool}: native --version exited unsuccessfully.")
        first = process.stdout.strip().splitlines()
        parts = first[0].split() if first else []
        version = parts[0] if tool == "yt-dlp" and parts else (
            parts[1] if len(parts) >= 2 and parts[0].lower() == "deno" else ""
        )
        if version != expected[tool]:
            raise ValueError(f"{tool}: executable version differs from pinned release.")
        outputs[tool] = {"version": version, "sha256": (
            pins["yt-dlp"]["sha256"] if tool == "yt-dlp"
            else json.loads((path / "SOURCE-EVIDENCE.pending.json").read_text(
                encoding="utf-8"
            ))["inputs"]["deno"]["tool_sha256"]
        )}
    return outputs


def fetch_reviewed_sources(
    *,
    target: str,
    pin_file: Path,
    output_dir: Path,
    native_probe: bool = False,
    open_asset: Callable[[str], BinaryIO] = _open_official_asset,
) -> dict:
    pins = _pinned_assets(pin_file, target)
    if not output_dir.parent.is_dir() or output_dir.exists() or output_dir.is_symlink():
        raise FileExistsError("Reviewed source output must have an existing parent and be new.")
    with tempfile.TemporaryDirectory(prefix=".official-source-fetch-", dir=output_dir.parent) as temp:
        staging = Path(temp)
        yt = staging / pins["yt-dlp"]["asset"]
        deno = staging / pins["deno"]["asset"]
        for tool, source in (("yt-dlp", yt), ("deno", deno)):
            item = pins[tool]
            _download_checked(
                item["url"], source, size=item["bytes"], sha256=item["sha256"],
                open_asset=open_asset,
            )

        verified = staging / "verified"
        evidence = extract_reviewed_sources(
            pin_file=pin_file, target=target, yt_dlp_asset=yt,
            deno_zip=deno, output_directory=verified,
        )
        for tool in ("yt-dlp", "deno"):
            file = verified / ASSETS[target][tool][2]
            _ensure_binary_architecture(file, target, tool)

        probes = _probe_native_tools(target, verified, pins) if native_probe else None
        result = {
            "schema": 1,
            "target": target,
            "approval_status": "pending",
            "component": "youtube_runtime",
            "sources": {
                name: {
                    "official_tag": pins[name]["tag"],
                    "official_asset": pins[name]["asset"],
                    "official_release_url": pins[name]["url"],
                    "pinned_asset_sha256": pins[name]["sha256"],
                    "pinned_asset_bytes": pins[name]["bytes"],
                    "extracted_tool_sha256": evidence["inputs"][name]["tool_sha256"],
                }
                for name in ("yt-dlp", "deno")
            },
            "official_asset_bytes_sha256_verified": True,
            "native_binary_startup_verified": probes is not None,
            "native_versions": probes,
            "upstream_signature_verified": False,
            "redistribution_approved": False,
            "catalog_modified": False,
            "remote_bundle_published": False,
            "ffmpeg_ffprobe_verified": False,
            "clean_machine_ingestion_verified": False,
        }
        receipt = verified / "DOWNLOAD-EVIDENCE.pending.json"
        receipt.write_text(
            json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        # No unverified/partial destination is visible before the final move.
        verified.replace(output_dir)
        return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download hash-pinned official yt-dlp/Deno sources for review only."
    )
    parser.add_argument("--pins", type=Path, default=DEFAULT_PINS)
    parser.add_argument("--target", choices=TARGETS, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--execute-native", action="store_true",
                        help="On the matching OS only: offline --version startup probes.")
    args = parser.parse_args()
    try:
        report = fetch_reviewed_sources(
            target=args.target, pin_file=args.pins,
            output_dir=args.output_dir, native_probe=args.execute_native,
        )
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError,
            urllib.error.URLError, zipfile.BadZipFile) as exc:
        parser.exit(2, f"Official source retrieval rejected: {exc}\n")
    print(
        f"Verified pinned official bytes for {report['target']}; "
        f"native startup={report['native_binary_startup_verified']}; "
        "redistribution approval and FFmpeg/ffprobe remain pending."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Offline evidence check for two independently pinned official YouTube tools.

Reads an explicit review-only, commit-tracked release asset manifest and
verifies local release assets by exact byte size and SHA-256. Deno's
single-executable ZIP is extracted with strict path/size checks. This tool
does NOT download releases, verify GPG signatures or approve redistribution.
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
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PINS = ROOT / "release/review/youtube-official-source-pins-2026-11-06.json"
TARGETS = ("windows-x86_64", "macos-aarch64")
_MAX_UNPACKED_TOOL = 512 * 1024 * 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_file(path: Path) -> None:
    if not path.is_file() or path.is_symlink():
        raise ValueError("Source release artifact must be a regular non-symlink file.")


def _verified_release_asset(path: Path, item: dict[str, Any], label: str) -> str:
    _source_file(path)
    if (
        not isinstance(item, dict)
        or not isinstance(item.get("bytes"), int)
        or item["bytes"] <= 0
        or not isinstance(item.get("sha256"), str)
        or len(item["sha256"]) != 64
        or any(ch not in "0123456789abcdef" for ch in item["sha256"])
    ):
        raise ValueError(f"{label}: missing pinned source size/SHA-256.")
    actual_size = path.stat().st_size
    if actual_size != item["bytes"]:
        raise ValueError(f"{label}: release asset byte size mismatch.")
    actual_sha = _sha256(path)
    if actual_sha != item["sha256"]:
        raise ValueError(f"{label}: official release SHA-256 mismatch.")
    return actual_sha


def _extract_deno(archive_path: Path, target: Path, expected_name: str) -> str:
    with zipfile.ZipFile(archive_path, "r") as archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        if len(infos) != 1:
            raise ValueError("Official Deno asset must contain exactly one executable.")
        info = infos[0]
        if (
            info.filename != expected_name
            or info.flag_bits & 1
            or stat.S_ISLNK(info.external_attr >> 16)
            or info.file_size <= 0
            or info.file_size > _MAX_UNPACKED_TOOL
            or (info.compress_size and info.file_size / info.compress_size > 500)
        ):
            raise ValueError("Deno archive contains an unsafe or unexpected member.")
        with archive.open(info, "r") as source, target.open("xb") as output:
            digest = hashlib.sha256()
            total = 0
            while chunk := source.read(1024 * 1024):
                total += len(chunk)
                if total > info.file_size or total > _MAX_UNPACKED_TOOL:
                    raise ValueError("Deno decompression exceeded declared bounds.")
                digest.update(chunk)
                output.write(chunk)
            if total != info.file_size:
                raise ValueError("Deno ZIP member is incomplete.")
    return digest.hexdigest()


def extract_reviewed_sources(
    *,
    pin_file: Path,
    target: str,
    yt_dlp_asset: Path,
    deno_zip: Path,
    output_directory: Path,
) -> dict[str, Any]:
    if target not in TARGETS:
        raise ValueError("Unsupported release review target.")
    pin = json.loads(pin_file.read_text(encoding="utf-8"))
    if (
        not isinstance(pin, dict)
        or pin.get("schema") != 1
        or pin.get("approval_status") != "pending"
        or set(pin.get("targets", {}).get(target, {})) != {"yt-dlp", "deno"}
    ):
        raise ValueError("Expected a review-only yt-dlp/Deno pin set.")
    record = pin["targets"][target]
    yt = record["yt-dlp"]
    deno = record["deno"]
    for name, item in (("yt-dlp", yt), ("deno", deno)):
        if not isinstance(item, dict):
            raise ValueError(f"{name}: release metadata is invalid.")
        tag = item.get("tag")
        if (
            not isinstance(tag, str)
            or not tag.strip()
            or "latest" in tag.lower()
            or item.get("asset") not in item.get("url", "")
            or not str(item.get("url", "")).startswith("https://github.com/")
        ):
            raise ValueError(f"{name}: release must be an explicit upstream tag and asset.")
    if yt_dlp_asset == deno_zip:
        raise ValueError("yt-dlp and Deno sources must be distinct release artifacts.")

    _verified_release_asset(yt_dlp_asset, yt, "yt-dlp")
    _verified_release_asset(deno_zip, deno, "deno")
    yt_name = yt["extracted_tool"]
    deno_name = deno["extracted_tool"]
    if (
        (yt_name, deno_name) != (
            ("yt-dlp.exe", "deno.exe") if target == "windows-x86_64" else ("yt-dlp", "deno")
        )
    ):
        raise ValueError("Pinned tool names do not match the OS-specific contract.")
    if not output_directory.parent.is_dir() or output_directory.exists():
        raise FileExistsError("Destination must have an existing parent and must not be overwritten.")

    stage: Path | None = None
    try:
        stage = Path(
            tempfile.mkdtemp(prefix=".youtube-sources-", dir=output_directory.parent)
        )
        yt_path = stage / yt_name
        deno_path = stage / deno_name
        shutil.copyfile(yt_dlp_asset, yt_path)
        if _sha256(yt_path) != yt["sha256"]:
            raise ValueError("yt-dlp source changed while copying.")
        deno_hash = _extract_deno(deno_zip, deno_path, deno_name)
        if os.name != "nt":
            yt_path.chmod(0o755)
            deno_path.chmod(0o755)
        evidence = {
            "schema": 1,
            "component": "youtube_runtime",
            "target": target,
            "redistribution_status": "pending",
            "inputs": {
                "yt-dlp": {
                    "repository": yt["repository"],
                    "tag": yt["tag"],
                    "asset": yt["asset"],
                    "upstream_url": yt["url"],
                    "source_sha256": yt["sha256"],
                    "source_bytes": yt["bytes"],
                    "tool_sha256": yt["sha256"],
                    "license_review": yt["license_review"],
                },
                "deno": {
                    "repository": deno["repository"],
                    "tag": deno["tag"],
                    "asset": deno["asset"],
                    "upstream_url": deno["url"],
                    "source_sha256": deno["sha256"],
                    "source_bytes": deno["bytes"],
                    "tool_sha256": deno_hash,
                    "license_review": deno["license_review"],
                },
            },
            "unresolved": ["ffmpeg", "ffprobe", "third-party notices", "redistribution review"],
            "local_bytes_verified": True,
            "upstream_signature_verified": False,
            "binaries_executed": False,
            "remote_archive_published": False,
            "approval_required": True,
        }
        (stage / "SOURCE-EVIDENCE.pending.json").write_text(
            json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        # Rename only a complete staged directory. The release catalog is
        # untouched; output files are just checked local candidate sources.
        stage.rename(output_directory)
        stage = None
        return evidence
    finally:
        if stage is not None and stage.exists():
            shutil.rmtree(stage, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify locally downloaded official yt-dlp and Deno assets."
    )
    parser.add_argument("--pins", type=Path, default=DEFAULT_PINS)
    parser.add_argument("--target", required=True, choices=TARGETS)
    parser.add_argument("--yt-dlp-asset", type=Path, required=True)
    parser.add_argument("--deno-zip", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = extract_reviewed_sources(
            pin_file=args.pins,
            target=args.target,
            yt_dlp_asset=args.yt_dlp_asset,
            deno_zip=args.deno_zip,
            output_directory=args.output_dir,
        )
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        parser.exit(2, f"Official YouTube source verification rejected: {exc}\n")
    print(
        f"Verified {result['target']} official source asset bytes; "
        "third-party license and full bundle approval remain pending."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

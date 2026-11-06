"""Collect pinned official yt-dlp/Deno release hashes without downloading executables.

The resulting evidence is never a redistribution approval or managed catalog.
It records GitHub release-API digests and, by default, independently parses
the upstream checksum text assets for matching file hashes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

_ROOT = Path(__file__).resolve().parents[1]
_BUNDLED_CATALOG = _ROOT / "src/audio_score_tool/managed-component-catalog.json"
_SOURCE_REPOS = {
    "yt-dlp": ("yt-dlp", "yt-dlp"),
    "deno": ("denoland", "deno"),
}
_PINNED_TAGS = {"yt-dlp": "2026.10.26", "deno": "v2.9.8"}
_TARGETS = {
    "windows-x86_64": {
        "yt-dlp": "yt-dlp.exe",
        "deno": "deno-x86_64-pc-windows-msvc.zip",
    },
    "macos-aarch64": {
        "yt-dlp": "yt-dlp_macos",
        "deno": "deno-aarch64-apple-darwin.zip",
    },
}
_SHA = re.compile(r"^[a-f0-9]{64}$")
_TAG = re.compile(r"^v?[0-9][A-Za-z0-9._-]{0,63}$")
_CHECKSUM_LINE = re.compile(r"^([a-fA-F0-9]{64})\s+\*?(.+?)\s*$")
_MAX_JSON_BYTES = 4 * 1024 * 1024
_MAX_CHECKSUM_BYTES = 128 * 1024


class ReleaseEvidenceError(ValueError):
    """An upstream release cannot be pinned with trustworthy-enough metadata."""


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_bounded(response: Any, limit: int) -> bytes:
    data = response.read(limit + 1)
    if len(data) > limit:
        raise ReleaseEvidenceError("Upstream response exceeds the allowed evidence size.")
    return data


def _release_url(source: str, tag: str) -> str:
    if source not in _SOURCE_REPOS or not _TAG.fullmatch(tag):
        raise ReleaseEvidenceError("Unsupported source or unsafe release tag.")
    owner, repo = _SOURCE_REPOS[source]
    return f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{tag}"


def _fetch_json(url: str) -> dict[str, Any]:
    if not url.startswith("https://api.github.com/repos/"):
        raise ReleaseEvidenceError("Only the expected official GitHub API is allowed.")
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "AudioScoreTool-release-evidence/1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            final = urllib.parse.urlsplit(response.geturl())
            if final.scheme != "https" or final.hostname != "api.github.com":
                raise ReleaseEvidenceError("Unexpected upstream API redirect.")
            data = json.loads(_read_bounded(response, _MAX_JSON_BYTES))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise ReleaseEvidenceError("Official release API is unavailable or malformed.") from exc
    if not isinstance(data, dict):
        raise ReleaseEvidenceError("Upstream release metadata is not an object.")
    return data


def _official_asset_url(source: str, tag: str, name: str) -> str:
    owner, repo = _SOURCE_REPOS[source]
    return f"https://github.com/{owner}/{repo}/releases/download/{tag}/{name}"


def _fetch_checksum(url: str) -> bytes:
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ReleaseEvidenceError("Only pinned, credential-free GitHub release URLs are accepted.")
    request = urllib.request.Request(
        url, headers={"User-Agent": "AudioScoreTool-release-evidence/1"}
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            final = urllib.parse.urlsplit(response.geturl())
            if (
                final.scheme != "https"
                or final.hostname not in {
                    "github.com",
                    "release-assets.githubusercontent.com",
                    "objects.githubusercontent.com",
                }
            ):
                raise ReleaseEvidenceError("Upstream checksum redirect left GitHub-owned hosts.")
            return _read_bounded(response, _MAX_CHECKSUM_BYTES)
    except (OSError, urllib.error.URLError) as exc:
        raise ReleaseEvidenceError("Official checksum asset could not be retrieved.") from exc


def _digest(asset: dict[str, Any]) -> str:
    raw = asset.get("digest")
    if not isinstance(raw, str) or not raw.startswith("sha256:"):
        raise ReleaseEvidenceError("Official release asset is missing a SHA-256 digest.")
    digest = raw.partition(":")[2].lower()
    if not _SHA.fullmatch(digest):
        raise ReleaseEvidenceError("Official release asset has an invalid SHA-256 digest.")
    return digest


def _asset(release: dict[str, Any], source: str, tag: str, name: str) -> dict[str, Any]:
    if release.get("tag_name") != tag or release.get("draft") or release.get("prerelease"):
        raise ReleaseEvidenceError("Release tag differs or release is a draft/prerelease.")
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise ReleaseEvidenceError("Release assets are missing.")
    found = [item for item in assets if isinstance(item, dict) and item.get("name") == name]
    if len(found) != 1:
        raise ReleaseEvidenceError(f"{source} {tag} has no unique asset named {name}.")
    asset = found[0]
    expected_url = _official_asset_url(source, tag, name)
    if asset.get("browser_download_url") != expected_url:
        raise ReleaseEvidenceError(f"{name}: unexpected release download URL.")
    if not isinstance(asset.get("size"), int) or asset["size"] <= 0:
        raise ReleaseEvidenceError(f"{name}: missing positive asset size.")
    return asset


def _checksum_asset_name(source: str, filename: str) -> str:
    if source == "yt-dlp":
        return "SHA2-256SUMS"
    return filename + ".sha256sum"


def _checksum_digest(text: bytes, filename: str) -> str:
    try:
        lines = text.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ReleaseEvidenceError("Checksum asset is not UTF-8 text.") from exc
    digests = []
    for line in lines:
        match = _CHECKSUM_LINE.fullmatch(line.strip())
        if match and match.group(2).lstrip("./") == filename:
            digests.append(match.group(1).lower())
    if len(digests) != 1:
        raise ReleaseEvidenceError(f"Checksum file has no unique hash for {filename}.")
    return digests[0]


def collect_upstream_evidence(
    *,
    target: str,
    tags: dict[str, str] | None = None,
    release_fetch: Callable[[str], dict[str, Any]] = _fetch_json,
    checksum_fetch: Callable[[str], bytes] = _fetch_checksum,
    verify_checksum_assets: bool = True,
) -> dict[str, Any]:
    if target not in _TARGETS:
        raise ReleaseEvidenceError("Unsupported Windows/macOS release target.")
    selected = dict(tags or _PINNED_TAGS)
    if set(selected) != set(_SOURCE_REPOS):
        raise ReleaseEvidenceError("Exactly yt-dlp and Deno release tags must be pinned.")

    evidence: dict[str, Any] = {}
    for source, filename in _TARGETS[target].items():
        tag = selected[source]
        api_url = _release_url(source, tag)
        release = release_fetch(api_url)
        binary = _asset(release, source, tag, filename)
        binary_digest = _digest(binary)
        checksum_name = _checksum_asset_name(source, filename)
        checksum = _asset(release, source, tag, checksum_name)
        checksum_digest = _digest(checksum)
        checksum_url = _official_asset_url(source, tag, checksum_name)

        verified_checksum = False
        if verify_checksum_assets:
            contents = checksum_fetch(checksum_url)
            if _sha256(contents) != checksum_digest:
                raise ReleaseEvidenceError(f"{source}: checksum document digest differs from the API.")
            upstream_hash = _checksum_digest(contents, filename)
            if upstream_hash != binary_digest:
                raise ReleaseEvidenceError(f"{source}: checksum document and API disagree for {filename}.")
            verified_checksum = True

        evidence[source] = {
            "tag": tag,
            "asset_name": filename,
            "asset_url": _official_asset_url(source, tag, filename),
            "asset_id": binary.get("id"),
            "asset_size": binary["size"],
            "asset_sha256": binary_digest,
            "release_api_url": api_url,
            "checksum_name": checksum_name,
            "checksum_url": checksum_url,
            "checksum_asset_sha256": checksum_digest,
            "checksum_file_verified": verified_checksum,
        }

    return {
        "schema": 1,
        "purpose": "upstream-binary-identity-evidence",
        "component": "youtube_runtime",
        "target": target,
        "sources": evidence,
        "redistribution_status": "pending",
        "license_review_status": "pending",
        "local_binary_downloaded": False,
        "binary_bytes_sha256_verified": False,
        "binary_format_verified": False,
        "ffmpeg_build_verified": False,
        "clean_machine_verified": False,
        "approval_required": True,
    }


def write_evidence(output: Path, report: dict[str, Any]) -> None:
    if output.resolve() == _BUNDLED_CATALOG.resolve():
        raise ReleaseEvidenceError("Cannot overwrite the bundled managed catalog.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False, sort_keys=True)
        handle.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pin official yt-dlp/Deno upstream release digest metadata."
    )
    parser.add_argument("--target", required=True, choices=tuple(_TARGETS))
    parser.add_argument("--yt-dlp-tag", default=_PINNED_TAGS["yt-dlp"])
    parser.add_argument("--deno-tag", default=_PINNED_TAGS["deno"])
    parser.add_argument(
        "--metadata-only", action="store_true",
        help="Do not retrieve upstream checksum documents (marks them unverified).",
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        evidence = collect_upstream_evidence(
            target=args.target,
            tags={"yt-dlp": args.yt_dlp_tag, "deno": args.deno_tag},
            verify_checksum_assets=not args.metadata_only,
        )
        write_evidence(args.output, evidence)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Upstream evidence collection rejected: {exc}\n")
    print(f"Recorded pinned source identities for {args.target}: {args.output}")
    print("No binaries were downloaded, approved, or published.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

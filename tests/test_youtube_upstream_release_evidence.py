from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import unquote

import pytest

from scripts import collect_youtube_upstream_release_evidence as release


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _release(source: str, tag: str, *, bad_asset: str | None = None) -> dict:
    filenames = {
        "yt-dlp": ["yt-dlp.exe", "yt-dlp_macos", "SHA2-256SUMS"],
        "deno": [
            "deno-x86_64-pc-windows-msvc.zip",
            "deno-x86_64-pc-windows-msvc.zip.sha256sum",
            "deno-aarch64-apple-darwin.zip",
            "deno-aarch64-apple-darwin.zip.sha256sum",
        ],
    }[source]
    checksum_text = {}
    if source == "yt-dlp":
        checksum_text["SHA2-256SUMS"] = (
            f"{_sha(b'yt-win')}  yt-dlp.exe\n"
            f"{_sha(b'yt-mac')}  yt-dlp_macos\n"
        ).encode()
        data = {
            "yt-dlp.exe": b"yt-win", "yt-dlp_macos": b"yt-mac",
        }
    else:
        data = {
            "deno-x86_64-pc-windows-msvc.zip": b"deno-win",
            "deno-aarch64-apple-darwin.zip": b"deno-mac",
        }
        for name, value in list(data.items()):
            checksum_text[name + ".sha256sum"] = (
                f"{_sha(value)} *{name}\n"
            ).encode()
    data.update(checksum_text)

    assets = []
    for i, filename in enumerate(filenames):
        if filename not in data:
            continue
        owner, repository = release._SOURCE_REPOS[source]
        assets.append({
            "id": i + 101,
            "name": filename,
            "size": len(data[filename]),
            "digest": f"sha256:{_sha(data[filename])}",
            "browser_download_url": (
                f"https://github.com/{owner}/{repository}/releases/download/{tag}/{filename}"
            ),
        })
    for asset in assets:
        if asset["name"] == bad_asset:
            asset["digest"] = "sha256:" + "0" * 64
    return {"tag_name": tag, "draft": False, "prerelease": False, "assets": assets}


def _fixtures():
    releases = {
        release._release_url("yt-dlp", "2026.10.26"): _release("yt-dlp", "2026.10.26"),
        release._release_url("deno", "v2.9.8"): _release("deno", "v2.9.8"),
    }
    checksum = {
        "https://github.com/yt-dlp/yt-dlp/releases/download/2026.10.26/SHA2-256SUMS": (
            f"{_sha(b'yt-win')}  yt-dlp.exe\n{_sha(b'yt-mac')}  yt-dlp_macos\n"
        ).encode(),
    }
    for basename, content in (
        ("deno-x86_64-pc-windows-msvc.zip", b"deno-win"),
        ("deno-aarch64-apple-darwin.zip", b"deno-mac"),
    ):
        checksum[
            f"https://github.com/denoland/deno/releases/download/v2.9.8/{basename}.sha256sum"
        ] = f"{_sha(content)} *{basename}\n".encode()
    return releases, checksum


@pytest.mark.parametrize(
    ("target", "expected_ytdlp", "expected_deno"),
    [
        (
            "windows-x86_64", "yt-dlp.exe",
            "deno-x86_64-pc-windows-msvc.zip",
        ),
        (
            "macos-aarch64", "yt-dlp_macos",
            "deno-aarch64-apple-darwin.zip",
        ),
    ],
)
def test_pinned_release_api_and_checksum_documents_agree(
    target: str, expected_ytdlp: str, expected_deno: str,
):
    releases, checksums = _fixtures()
    seen: list[str] = []

    def fetch(url: str) -> bytes:
        seen.append(url)
        return checksums[url]

    report = release.collect_upstream_evidence(
        target=target,
        release_fetch=releases.__getitem__,
        checksum_fetch=fetch,
    )
    assert report["target"] == target
    assert report["sources"]["yt-dlp"]["asset_name"] == expected_ytdlp
    assert report["sources"]["deno"]["asset_name"] == expected_deno
    assert all(item["checksum_file_verified"] for item in report["sources"].values())
    assert len(seen) == 2
    assert all(url.startswith("https://github.com/") for url in seen)
    assert report["redistribution_status"] == "pending"
    assert report["license_review_status"] == "pending"
    assert report["local_binary_downloaded"] is False
    assert report["binary_bytes_sha256_verified"] is False
    assert report["ffmpeg_build_verified"] is False
    assert report["clean_machine_verified"] is False


def test_checksum_asset_document_hash_tampering_fails_closed():
    releases, checksums = _fixtures()
    checksum_url = next(k for k in checksums if k.endswith("/SHA2-256SUMS"))
    checksums[checksum_url] += b"# tampered\n"
    with pytest.raises(release.ReleaseEvidenceError, match="document digest differs"):
        release.collect_upstream_evidence(
            target="windows-x86_64",
            release_fetch=releases.__getitem__,
            checksum_fetch=checksums.__getitem__,
        )


def test_binary_checksum_vs_api_mismatch_fails_closed():
    releases, checksums = _fixtures()
    upstream = releases[release._release_url("yt-dlp", "2026.10.26")]
    asset = next(x for x in upstream["assets"] if x["name"] == "yt-dlp.exe")
    asset["digest"] = "sha256:" + "f" * 64
    with pytest.raises(release.ReleaseEvidenceError, match="API disagree"):
        release.collect_upstream_evidence(
            target="windows-x86_64",
            release_fetch=releases.__getitem__,
            checksum_fetch=checksums.__getitem__,
        )


def test_metadata_only_can_be_collected_but_is_explicitly_unverified():
    releases, _checksums = _fixtures()
    report = release.collect_upstream_evidence(
        target="macos-aarch64",
        release_fetch=releases.__getitem__,
        checksum_fetch=lambda _: (_ for _ in ()).throw(
            AssertionError("metadata-only must never read checksums")
        ),
        verify_checksum_assets=False,
    )
    assert all(not x["checksum_file_verified"] for x in report["sources"].values())


@pytest.mark.parametrize("invalid", ["../../etc", "latest", "v/2.9.8", "", "main"])
def test_unsafe_or_mutable_tags_are_rejected(invalid: str):
    if invalid == "main":
        # Formally safe syntax; the exact tag still must match the upstream metadata.
        assert release._TAG.fullmatch(invalid) is None
    else:
        assert release._TAG.fullmatch(invalid) is None


def test_release_tag_mismatch_is_not_accepted():
    releases, checksums = _fixtures()
    releases[release._release_url("deno", "v2.9.8")]["tag_name"] = "v2.9.7"
    with pytest.raises(release.ReleaseEvidenceError, match="tag differs"):
        release.collect_upstream_evidence(
            target="windows-x86_64",
            release_fetch=releases.__getitem__,
            checksum_fetch=checksums.__getitem__,
        )


@pytest.mark.parametrize(
    "source,field,value,expected",
    [
        ("yt-dlp", "draft", True, "draft/prerelease"),
        ("deno", "prerelease", True, "draft/prerelease"),
    ],
)
def test_draft_and_prerelease_are_rejected(source, field, value, expected):
    releases, checksums = _fixtures()
    releases[release._release_url(source, release._PINNED_TAGS[source])][field] = value
    with pytest.raises(release.ReleaseEvidenceError, match=expected):
        release.collect_upstream_evidence(
            target="windows-x86_64",
            release_fetch=releases.__getitem__,
            checksum_fetch=checksums.__getitem__,
        )


def test_wrong_official_download_url_is_rejected():
    releases, checksums = _fixtures()
    upstream = releases[release._release_url("deno", "v2.9.8")]
    asset = next(x for x in upstream["assets"] if x["name"].endswith("windows-msvc.zip"))
    asset["browser_download_url"] = "https://attacker.invalid/deno.zip"
    with pytest.raises(release.ReleaseEvidenceError, match="unexpected release download URL"):
        release.collect_upstream_evidence(
            target="windows-x86_64",
            release_fetch=releases.__getitem__,
            checksum_fetch=checksums.__getitem__,
        )


def test_duplicate_asset_names_are_rejected():
    releases, checksums = _fixtures()
    upstream = releases[release._release_url("deno", "v2.9.8")]
    upstream["assets"].append(dict(upstream["assets"][0]))
    with pytest.raises(release.ReleaseEvidenceError, match="unique asset"):
        release.collect_upstream_evidence(
            target="windows-x86_64",
            release_fetch=releases.__getitem__,
            checksum_fetch=checksums.__getitem__,
        )


def test_checksum_parser_requires_one_exact_named_asset_and_supports_gnu_style():
    digest = _sha(b"example")
    assert release._checksum_digest(f"{digest} *sample.zip\n".encode(), "sample.zip") == digest
    assert release._checksum_digest(f"{digest}  sample.zip\n".encode(), "sample.zip") == digest
    with pytest.raises(release.ReleaseEvidenceError, match="no unique"):
        release._checksum_digest(f"{digest}  sample.zip\n{digest} *sample.zip\n".encode(), "sample.zip")
    with pytest.raises(release.ReleaseEvidenceError, match="no unique"):
        release._checksum_digest(f"{digest}  another.zip\n".encode(), "sample.zip")


def test_bounded_network_reader_rejects_oversized_payload():
    class Response:
        def read(self, limit: int):
            return b"0" * limit
    with pytest.raises(release.ReleaseEvidenceError, match="exceeds"):
        release._read_bounded(Response(), 1024)


def test_exclusive_evidence_file_never_replaces_bundled_catalog(tmp_path: Path):
    releases, checksums = _fixtures()
    report = release.collect_upstream_evidence(
        target="windows-x86_64",
        release_fetch=releases.__getitem__,
        checksum_fetch=checksums.__getitem__,
    )
    output = tmp_path / "official-metadata.pending.json"
    release.write_evidence(output, report)
    assert json.loads(output.read_text()) == report
    with pytest.raises(FileExistsError):
        release.write_evidence(output, report)
    with pytest.raises(release.ReleaseEvidenceError, match="bundled managed catalog"):
        release.write_evidence(release._BUNDLED_CATALOG, report)


def test_tag_and_target_allowlist_never_accept_arbitrary_repos():
    with pytest.raises(release.ReleaseEvidenceError, match="Unsupported"):
        release._release_url("other", "v2.9.8")
    with pytest.raises(release.ReleaseEvidenceError, match="Unsupported"):
        release.collect_upstream_evidence(target="linux-x86_64", release_fetch=lambda _: {})

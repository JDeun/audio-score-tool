"""Hash-pinned source retrieval: no unreviewed binary bytes or approved catalog."""
from __future__ import annotations

import hashlib
import io
import json
import urllib.request
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import fetch_youtube_official_assets as fetcher


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _machine(tool: str, target: str) -> bytes:
    # Architecture-correct miniature fixture; never executed as a real binary.
    if target == "windows-x86_64":
        head = bytearray(70)
        head[:2] = b"MZ"
        head[60:64] = (64).to_bytes(4, "little")
        head[64:70] = b"PE\x00\x00\x64\x86"
        return bytes(head) + tool.encode()
    return b"\xcf\xfa\xed\xfe" + (0x0100000C).to_bytes(4, "little") + tool.encode()


def _setup(tmp_path: Path, target: str = "windows-x86_64"):
    asset = fetcher.ASSETS[target]
    yt_bytes = _machine("yt-dlp", target)
    deno_bytes = _machine("deno", target)
    deno_stream = io.BytesIO()
    with zipfile.ZipFile(deno_stream, "w") as zipped:
        zipped.writestr(asset["deno"][2], deno_bytes)
    deno_zip = deno_stream.getvalue()
    sources = {"yt-dlp": yt_bytes, "deno": deno_zip}
    records = {}
    responses = {}
    for tool, (repository, filename, extracted_tool) in asset.items():
        tag = "2026.10.26" if tool == "yt-dlp" else "v2.9.8"
        url = f"https://github.com/{repository}/releases/download/{tag}/{filename}"
        records[tool] = {
            "repository": repository,
            "tag": tag,
            "asset": filename,
            "extracted_tool": extracted_tool,
            "url": url,
            "sha256": _sha(sources[tool]),
            "bytes": len(sources[tool]),
            "license_review": "Pending reviewer approval",
        }
        responses[url] = sources[tool]
    manifest = {
        "schema": 1,
        "approval_status": "pending",
        "publication_catalog_modified": False,
        "targets": {target: records},
    }
    pin = tmp_path / "pins.json"
    pin.write_text(json.dumps(manifest), encoding="utf-8")

    def opener(url: str):
        result = io.BytesIO(responses[url])
        result.geturl = lambda: url
        return result

    return pin, responses, records, opener


@pytest.mark.parametrize("target", ["windows-x86_64", "macos-aarch64"])
def test_retrieved_official_bytes_are_verified_and_unapproved(
    tmp_path: Path, target: str,
):
    pins, responses, records, opener = _setup(tmp_path, target)
    output = tmp_path / "official"
    receipt = fetcher.fetch_reviewed_sources(
        target=target, pin_file=pins, output_dir=output, open_asset=opener,
    )
    assert output.is_dir()
    assert receipt["official_asset_bytes_sha256_verified"] is True
    assert receipt["native_binary_startup_verified"] is False
    assert receipt["redistribution_approved"] is False
    assert receipt["ffmpeg_ffprobe_verified"] is False
    assert receipt["remote_bundle_published"] is False
    assert receipt["catalog_modified"] is False
    assert receipt["clean_machine_ingestion_verified"] is False
    assert json.loads((output / "DOWNLOAD-EVIDENCE.pending.json").read_text()) == receipt
    assert (output / "SOURCE-EVIDENCE.pending.json").is_file()
    assert (output / fetcher.ASSETS[target]["yt-dlp"][2]).read_bytes() == (
        responses[records["yt-dlp"]["url"]]
    )
    assert _sha((output / fetcher.ASSETS[target]["deno"][2]).read_bytes()) == (
        receipt["sources"]["deno"]["extracted_tool_sha256"]
    )
    with pytest.raises(FileExistsError):
        fetcher.fetch_reviewed_sources(
            target=target, pin_file=pins, output_dir=output, open_asset=opener,
        )


@pytest.mark.parametrize(
    "corruption",
    ["wrong-sha", "wrong-size", "oversized-transfer", "short-transfer"],
)
def test_bad_remote_bytes_never_publish_output_directory(tmp_path: Path, corruption: str):
    pins, responses, records, opener = _setup(tmp_path)
    item = records["yt-dlp"]
    if corruption == "wrong-sha":
        responses[item["url"]] = b"x" * item["bytes"]
    elif corruption == "wrong-size":
        item["bytes"] += 1
    elif corruption == "oversized-transfer":
        responses[item["url"]] += b"extra"
    else:
        responses[item["url"]] = responses[item["url"]][:-1]
    pins.write_text(json.dumps({
        "schema": 1, "approval_status": "pending",
        "publication_catalog_modified": False,
        "targets": {"windows-x86_64": records},
    }))
    destination = tmp_path / "unverified"
    with pytest.raises(ValueError, match="byte size|SHA-256|exceeds"):
        fetcher.fetch_reviewed_sources(
            target="windows-x86_64", pin_file=pins,
            output_dir=destination, open_asset=opener,
        )
    assert not destination.exists()
    assert not list(tmp_path.glob(".official-source-fetch-*"))


@pytest.mark.parametrize("bad_url", [
    "http://github.com/yt-dlp/yt-dlp/releases/download/2026.10.26/yt-dlp.exe",
    "https://evil.invalid/yt-dlp.exe",
    "https://github.com.evil.invalid/asset",
    "https://user:token@github.com/yt-dlp/yt-dlp",
    "https://github.com:444/yt-dlp",
    "https://github.com/asset#fragment",
])
def test_untrusted_or_unpinned_asset_url_is_rejected_before_fetch(
    tmp_path: Path, bad_url: str,
):
    pins, _responses, records, _opener = _setup(tmp_path)
    records["yt-dlp"]["url"] = bad_url
    manifest = json.loads(pins.read_text())
    manifest["targets"]["windows-x86_64"] = records
    pins.write_text(json.dumps(manifest))
    calls = []
    with pytest.raises(ValueError, match="official tagged release"):
        fetcher.fetch_reviewed_sources(
            target="windows-x86_64", pin_file=pins, output_dir=tmp_path / "bad",
            open_asset=lambda url: calls.append(url),
        )
    assert not calls
    assert not (tmp_path / "bad").exists()


@pytest.mark.parametrize("url", [
    "http://release-assets.githubusercontent.com/signed",
    "https://attacker.github.com/release",
    "https://release-assets.githubusercontent.com.evil.invalid/release",
    "https://127.0.0.1/private",
    "https://objects.githubusercontent.com:444/file",
    "https://user:secret@release-assets.githubusercontent.com/file",
])
def test_redirect_denies_nonofficial_destination_before_request(url: str):
    request = urllib.request.Request("https://github.com/yt-dlp/yt-dlp/releases/download/v1/tool")
    with pytest.raises(ValueError, match="trusted HTTPS hosts"):
        fetcher._PinnedRedirect().redirect_request(
            request, None, 302, "Found", {}, url,
        )


def test_post_redirect_final_url_checked_before_read_and_partial_deleted(tmp_path: Path):
    _, _, records, _ = _setup(tmp_path)
    item = records["yt-dlp"]
    destination = tmp_path / "unchecked.exe"

    class FakeResponse(io.BytesIO):
        def __init__(self):
            super().__init__(b"must-not-read")

        def geturl(self):
            return "https://evil.invalid/binary"

        def read(self, *_args):
            pytest.fail("Do not read data from untrusted redirect targets.")

    with pytest.raises(ValueError, match="trusted HTTPS hosts"):
        fetcher._download_checked(
            item["url"], destination, size=item["bytes"], sha256=item["sha256"],
            open_asset=lambda _url: FakeResponse(),
        )
    assert not destination.exists()


def test_missing_expected_approved_pin_fields_fail_closed(tmp_path: Path):
    pins, _responses, _records, _opener = _setup(tmp_path)
    document = json.loads(pins.read_text())
    document["publication_catalog_modified"] = True
    pins.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="pending, unchanged"):
        fetcher._pinned_assets(pins, "windows-x86_64")


def test_native_cli_probes_version_from_matching_pinned_executables_only(
    tmp_path: Path, monkeypatch,
):
    pins, _responses, records, opener = _setup(tmp_path)
    output = tmp_path / "review"
    monkeypatch.setattr(fetcher, "_host_target", lambda: "windows-x86_64")
    called = []

    def fake_run(cmd, **kwargs):
        called.append((cmd, kwargs))
        assert Path(cmd[0]).is_absolute()
        assert kwargs["env"]["PATH"] == ""
        assert kwargs["cwd"] == output
        if Path(cmd[0]).name == "yt-dlp.exe":
            assert cmd[1:] == ["--ignore-config", "--no-remote-components", "--version"]
            return SimpleNamespace(returncode=0, stdout="2026.10.26\n")
        assert Path(cmd[0]).name == "deno.exe"
        assert cmd[1:] == ["--version"]
        return SimpleNamespace(returncode=0, stdout="deno 2.9.8\nv8 14.4")

    monkeypatch.setattr(fetcher.subprocess, "run", fake_run)
    result = fetcher.fetch_reviewed_sources(
        target="windows-x86_64", pin_file=pins,
        output_dir=output, open_asset=opener, native_probe=True,
    )
    # The probe runs before the atomic move, inside the verified staging dir.
    assert len(called) == 2
    assert result["native_binary_startup_verified"] is True
    assert result["native_versions"]["yt-dlp"]["version"] == records["yt-dlp"]["tag"]
    assert result["native_versions"]["deno"]["version"] == "2.9.8"
    assert result["redistribution_approved"] is False


def test_native_probe_wrong_version_refuses_output_and_approval(tmp_path: Path, monkeypatch):
    pins, _, _, opener = _setup(tmp_path)
    monkeypatch.setattr(fetcher, "_host_target", lambda: "windows-x86_64")
    monkeypatch.setattr(
        fetcher.subprocess, "run",
        lambda _command, **_kwargs: SimpleNamespace(
            returncode=0, stdout="0.0.0\n",
        ),
    )
    with pytest.raises(ValueError, match="version differs"):
        fetcher.fetch_reviewed_sources(
            target="windows-x86_64", pin_file=pins, output_dir=tmp_path / "failed",
            open_asset=opener, native_probe=True,
        )
    assert not (tmp_path / "failed").exists()


def test_native_probe_refuses_wrong_host_even_with_hash_pinned_inputs(tmp_path: Path):
    pins, _, _, opener = _setup(tmp_path, "macos-aarch64")
    with pytest.raises(ValueError, match="different target architecture"):
        fetcher.fetch_reviewed_sources(
            target="macos-aarch64", pin_file=pins, output_dir=tmp_path / "rejected",
            open_asset=opener, native_probe=True,
        )
    assert not (tmp_path / "rejected").exists()

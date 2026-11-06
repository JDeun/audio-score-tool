"""The real packaged YouTube startup smoke binds executable bytes to manifest versions."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import smoke_packaged_sidecar as smoke

NAMES = ("yt-dlp", "deno", "ffmpeg", "ffprobe")
VERSIONS = {
    "yt-dlp": "2026.10.26",
    "deno": "2.9.8",
    "ffmpeg": "7.1",
    "ffprobe": "7.1",
}


@pytest.fixture
def release(tmp_path: Path, monkeypatch):
    root = tmp_path / "managed"
    bundle = root / "installed" / "youtube_runtime" / "candidate"
    bin_dir = bundle / "bin"
    bin_dir.mkdir(parents=True)
    tools = {}
    records = {}
    for name in NAMES:
        binary = bin_dir / f"{name}.exe"
        data = f"synthetic-{name}".encode()
        binary.write_bytes(data)
        tools[name] = str(binary)
        records[name] = {
            "relative_path": f"bin/{name}.exe",
            "sha256": hashlib.sha256(data).hexdigest(),
            "version": VERSIONS[name],
        }
    payload = {
        "schema": 1,
        "target": "windows-x86_64",
        "version": "youtube-ci-fixture",
        "tools": {**records, "ffmpeg-build": {"attestation_sha256": "a" * 64}},
        "redistribution_status": "pending",
    }
    (bundle / "BUNDLE-INVENTORY.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    monkeypatch.setattr(smoke, "platform_key", lambda: "windows-x86_64")
    return root, bundle, tools, payload


def test_inventory_hashes_and_running_versions_are_bound_to_installed_files(
    release, monkeypatch,
):
    root, _bundle, tools, _payload = release
    versions = smoke._youtube_inventory(tools, root)
    assert versions == VERSIONS

    outputs = {
        "yt-dlp": "2026.10.26\n",
        "deno": "deno 2.9.8\nv8 14.4",
        "ffmpeg": "ffmpeg version 7.1 Copyright FFmpeg",
        "ffprobe": "ffprobe version 7.1 Copyright FFmpeg",
    }
    observed = []

    def execute(command, args, **kwargs):
        name = Path(command).name.removesuffix(".exe")
        observed.append((name, args, kwargs))
        return type("Result", (), {"stdout": outputs[name]})()

    monkeypatch.setattr(smoke, "run_command", execute)
    smoke._verify_youtube_cli_tools(tools, root)
    assert [item[0] for item in observed] == list(NAMES)
    assert all(item[2]["env"]["PATH"] == "" for item in observed)
    assert all(item[2]["timeout_seconds"] == 20 for item in observed)


def test_wrong_binary_version_fails_even_if_hashes_match_release_inventory(
    release, monkeypatch,
):
    root, _bundle, tools, _payload = release
    monkeypatch.setattr(
        smoke, "run_command",
        lambda command, _args, **_kwargs: type(
            "Result", (), {"stdout": (
                "deno 2.9.7" if Path(command).name.startswith("deno")
                else "2026.10.26"
            )}
        )(),
    )
    with pytest.raises(RuntimeError, match="deno: packaged CLI version does not match"):
        smoke._verify_youtube_cli_tools(tools, root)


def test_tampered_binary_is_rejected_before_any_program_execution(
    release, monkeypatch,
):
    root, _bundle, tools, _payload = release
    Path(tools["ffprobe"]).write_bytes(b"modified after managed install")
    monkeypatch.setattr(
        smoke, "run_command",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Tampered executable must never run")
        ),
    )
    with pytest.raises(RuntimeError, match="ffprobe: bundle inventory digest mismatch"):
        smoke._verify_youtube_cli_tools(tools, root)


def test_wrong_inventory_platform_rejected_before_execution(release, monkeypatch):
    root, bundle, tools, payload = release
    payload["target"] = "macos-aarch64"
    (bundle / "BUNDLE-INVENTORY.json").write_text(json.dumps(payload))
    monkeypatch.setattr(
        smoke, "run_command",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Wrong platform must never execute")
        ),
    )
    with pytest.raises(RuntimeError, match="schema/platform mismatch"):
        smoke._verify_youtube_cli_tools(tools, root)


def test_missing_inventory_or_entry_fails_closed(release):
    root, bundle, tools, payload = release
    inventory = bundle / "BUNDLE-INVENTORY.json"
    inventory.unlink()
    with pytest.raises(RuntimeError, match="inventory is missing"):
        smoke._youtube_inventory(tools, root)

    payload["tools"].pop("deno")
    inventory.write_text(json.dumps(payload))
    with pytest.raises(RuntimeError, match="deno: missing bundle inventory entry"):
        smoke._youtube_inventory(tools, root)


def test_wrong_inventory_relative_path_cannot_alias_another_managed_tool(release):
    root, bundle, tools, payload = release
    payload["tools"]["deno"]["relative_path"] = "bin/yt-dlp.exe"
    (bundle / "BUNDLE-INVENTORY.json").write_text(json.dumps(payload))
    with pytest.raises(RuntimeError, match="deno: inventory tool path mismatch"):
        smoke._youtube_inventory(tools, root)


def test_two_component_roots_cannot_be_silently_mixed(release, tmp_path: Path):
    root, _bundle, tools, _payload = release
    foreign = root / "installed" / "other-component" / "bin"
    foreign.mkdir(parents=True)
    other = foreign / "ffprobe.exe"
    other.write_bytes(b"synthetic-ffprobe")
    tools["ffprobe"] = str(other)
    with pytest.raises(RuntimeError, match="different directories"):
        smoke._youtube_inventory(tools, root)


def test_inventory_symlink_cannot_be_trusted(release, tmp_path: Path):
    root, bundle, tools, _payload = release
    inventory = bundle / "BUNDLE-INVENTORY.json"
    outside = tmp_path / "outside-inventory.json"
    outside.write_bytes(inventory.read_bytes())
    inventory.unlink()
    inventory.symlink_to(outside)
    with pytest.raises(RuntimeError, match="inventory is missing or symlinked"):
        smoke._youtube_inventory(tools, root)

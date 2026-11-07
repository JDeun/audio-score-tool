"""Native CLI acceptance is a real subprocess contract, using owned fake executables here.

The GitHub Actions review-only job separately runs it with SHA-pinned official
Windows/macOS release assets. Unit tests must not run untrusted binaries.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import verify_youtube_native_cli as native


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _fixture(tmp_path: Path, monkeypatch, target: str = "windows-x86_64") -> tuple[Path, dict]:
    suffix = ".exe" if target.startswith("windows-") else ""
    root = tmp_path / "verified"
    root.mkdir()
    records = {}
    pins = {}
    for name, repo, tag, asset in (
        ("yt-dlp", "yt-dlp/yt-dlp", "2026.10.26", "yt-dlp.exe" if suffix else "yt-dlp_macos"),
        (
            "deno", "denoland/deno", "v2.9.8",
            "deno-x86_64-pc-windows-msvc.zip" if suffix else "deno-aarch64-apple-darwin.zip",
        ),
    ):
        contents = f"owned-test-{name}".encode()
        (root / (name + suffix)).write_bytes(contents)
        pinned = {
            "repository": repo, "tag": tag, "asset": asset,
            "url": f"https://github.com/{repo}/releases/download/{tag}/{asset}",
            "sha256": _sha(b"original-archive-" + contents),
            "bytes": len(b"original-archive-" + contents),
            "extracted_tool": name + suffix,
            "license_review": f"{name} pending third party review",
        }
        pins[name] = pinned
        records[name] = {
            "repository": pinned["repository"], "tag": tag,
            "asset": asset, "upstream_url": pinned["url"],
            "source_sha256": pinned["sha256"],
            "source_bytes": pinned["bytes"],
            "tool_sha256": _sha(contents),
            "license_review": pinned["license_review"],
        }
    review_pin = tmp_path / "official-fixture-pins.json"
    review_pin.write_text(
        json.dumps({
            "schema": 1, "approval_status": "pending",
            "targets": {target: pins},
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(native, "PINS", review_pin)
    report = {
        "schema": 1, "component": "youtube_runtime",
        "target": target, "local_bytes_verified": True,
        "upstream_signature_verified": False,
        "binaries_executed": False,
        "redistribution_status": "pending",
        "approval_required": True,
        "inputs": records,
    }
    (root / "SOURCE-EVIDENCE.pending.json").write_text(json.dumps(report), encoding="utf-8")
    machine = "AMD64" if target.startswith("windows-") else "arm64"
    system = "Windows" if target.startswith("windows-") else "Darwin"
    monkeypatch.setattr(native.platform, "system", lambda: system)
    monkeypatch.setattr(native.platform, "machine", lambda: machine)
    return root, report


@pytest.mark.parametrize("target", ["windows-x86_64", "macos-aarch64"])
def test_native_versions_use_only_verified_absolute_executables_and_empty_path(
    tmp_path: Path, monkeypatch, target: str,
):
    root, source = _fixture(tmp_path, monkeypatch, target)
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        assert Path(argv[0]).is_absolute()
        assert Path(argv[0]).parent == root
        assert argv[1] == "--version"
        assert kwargs["shell"] is False
        assert kwargs["env"]["PATH"] == ""
        assert kwargs["timeout"] <= 30
        assert kwargs["cwd"] == str(root)
        text = "2026.10.26\n" if "yt-dlp" in Path(argv[0]).name else "deno 2.9.8 (release)\n"
        return SimpleNamespace(stdout=text, returncode=0)

    monkeypatch.setattr(native.subprocess, "run", fake_run)
    report = native.verify_native_startup(root, target)
    assert [Path(call[0][0]).stem for call in calls] == ["yt-dlp", "deno"]
    assert report["target"] == target
    assert report["native_cli_startup_verified"] is True
    assert report["source_asset_bytes_verified"] is True
    assert report["upstream_signature_verified"] is False
    assert report["redistribution_status"] == "pending"
    assert report["ffmpeg_native_verified"] is False
    assert report["clean_machine_installer_verified"] is False
    assert report["official_source_evidence_sha256"] == _sha(
        (root / "SOURCE-EVIDENCE.pending.json").read_bytes()
    )
    assert json.loads((root / "NATIVE-CLI-EVIDENCE.pending.json").read_text()) == report
    assert set(source["inputs"]) == set(report["tools"])


@pytest.mark.parametrize(
    ("output", "exit_code", "message"),
    [
        ("2026.08.19\n", 0, "version differs"),
        ("", 0, "failed native"),
        ("2026.10.26\n", 2, "failed native"),
    ],
)
def test_ytdlp_wrong_version_and_startup_failure_do_not_write_receipt(
    tmp_path: Path, monkeypatch, output, exit_code, message,
):
    root, _ = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        native.subprocess, "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=output, returncode=exit_code),
    )
    with pytest.raises((ValueError, RuntimeError), match=message):
        native.verify_native_startup(root, "windows-x86_64")
    assert not (root / "NATIVE-CLI-EVIDENCE.pending.json").exists()


@pytest.mark.parametrize(
    "exception", [OSError("missing executable"), subprocess.TimeoutExpired("deno", 30)],
)
def test_executable_error_or_timeout_does_not_fabricate_ready(tmp_path: Path, monkeypatch, exception):
    root, _ = _fixture(tmp_path, monkeypatch)

    def failed_run(*_args, **_kwargs):
        raise exception

    monkeypatch.setattr(native.subprocess, "run", failed_run)
    with pytest.raises(RuntimeError, match="failed to start"):
        native.verify_native_startup(root, "windows-x86_64")
    assert not (root / "NATIVE-CLI-EVIDENCE.pending.json").exists()


def test_wrong_runner_os_architecture_never_executes_any_binary(tmp_path: Path, monkeypatch):
    root, _ = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(native.platform, "machine", lambda: "aarch64")
    monkeypatch.setattr(
        native.subprocess, "run",
        lambda *_a, **_k: pytest.fail("Wrong runner must never execute a binary"),
    )
    with pytest.raises(ValueError, match="exact target OS/CPU"):
        native.verify_native_startup(root, "windows-x86_64")


def test_tool_sha_mismatch_fails_before_version_probe(tmp_path: Path, monkeypatch):
    root, _ = _fixture(tmp_path, monkeypatch)
    (root / "deno.exe").write_bytes(b"tampered")
    monkeypatch.setattr(
        native.subprocess, "run",
        lambda *_a, **_k: SimpleNamespace(stdout="2026.10.26", returncode=0),
    )
    with pytest.raises(ValueError, match="SHA-256"):
        native.verify_native_startup(root, "windows-x86_64")
    assert not (root / "NATIVE-CLI-EVIDENCE.pending.json").exists()


def test_pin_drift_is_rejected_before_running_unverified_binary(tmp_path: Path, monkeypatch):
    root, source = _fixture(tmp_path, monkeypatch)
    source["inputs"]["deno"]["source_sha256"] = "0" * 64
    (root / "SOURCE-EVIDENCE.pending.json").write_text(json.dumps(source), encoding="utf-8")
    monkeypatch.setattr(
        native.subprocess, "run",
        lambda *_a, **_k: pytest.fail("Forged source receipt must not execute"),
    )
    with pytest.raises(ValueError, match="differs from committed pins"):
        native.verify_native_startup(root, "windows-x86_64")


def test_symlinked_executable_is_rejected(tmp_path: Path, monkeypatch):
    root, _ = _fixture(tmp_path, monkeypatch)
    (root / "deno.exe").unlink()
    foreign = tmp_path / "outside"
    foreign.write_bytes(b"not a reviewed executable")
    try:
        (root / "deno.exe").symlink_to(foreign)
    except OSError:
        pytest.skip("Symlinks unavailable on runner")
    monkeypatch.setattr(
        native.subprocess, "run",
        lambda *_a, **_k: SimpleNamespace(stdout="2026.10.26", returncode=0),
    )
    with pytest.raises(ValueError, match="missing or unsafe"):
        native.verify_native_startup(root, "windows-x86_64")
    assert foreign.read_bytes() == b"not a reviewed executable"


def test_source_receipt_claiming_redistribution_approval_is_rejected(
    tmp_path: Path, monkeypatch,
):
    root, source = _fixture(tmp_path, monkeypatch)
    source["redistribution_status"] = "approved"
    (root / "SOURCE-EVIDENCE.pending.json").write_text(json.dumps(source), encoding="utf-8")
    with pytest.raises(ValueError, match="unapproved official source report"):
        native.verify_native_startup(root, "windows-x86_64")


def test_existing_native_receipt_is_not_overwritten(tmp_path: Path, monkeypatch):
    root, _ = _fixture(tmp_path, monkeypatch)
    dest = root / "NATIVE-CLI-EVIDENCE.pending.json"
    dest.write_text("existing user evidence", encoding="utf-8")
    with pytest.raises(FileExistsError, match="Refusing"):
        native.verify_native_startup(root, "windows-x86_64")
    assert dest.read_text(encoding="utf-8") == "existing user evidence"

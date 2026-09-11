from __future__ import annotations

import hashlib
import json
from pathlib import Path

from audio_score_tool.managed_publication_readiness import publication_readiness


def _tools_for(component: str) -> dict[str, str]:
    if component == "transcription_engine":
        return {"mt3-infer": "bin/mt3-infer"}
    if component == "youtube_runtime":
        return {
            "yt-dlp": "bin/yt-dlp",
            "deno": "bin/deno",
            "ffmpeg": "bin/ffmpeg",
            "ffprobe": "bin/ffprobe",
        }
    if component == "audiveris":
        return {"audiveris": "bin/audiveris"}
    return {"tool": "bin/tool"}


def _artifact(target: str, component: str, digest: str) -> dict:
    return {
        "url": f"https://example.invalid/{component}/{target}.zip",
        "sha256": digest,
        "archive": "zip",
        "tools": _tools_for(component),
    }


def test_bundled_catalog_is_not_yet_publication_ready():
    report = publication_readiness()
    assert report["ready"] is False
    assert report["checks"]
    assert all(check["reason"] == "artifact-not-published" for check in report["checks"])


def test_pinned_cross_platform_catalog_is_publication_ready(tmp_path: Path, monkeypatch):
    digest = hashlib.sha256(b"fixture").hexdigest()
    targets = ("windows-x86_64", "macos-aarch64")
    licenses = {
        "transcription_engine": "Apache-2.0",
        "youtube_runtime": "MIT/LGPL-2.1-or-later",
        "audiveris": "AGPL-3.0-or-later",
    }
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": 1,
                "components": {
                    name: {
                        "version": "1.0.0",
                        "license": license_name,
                        "provenance": "pinned upstream build",
                        "upstream_revision": "upstream-commit-or-release",
                        "redistribution_status": "approved",
                        "artifacts": {
                            target: _artifact(target, name, digest) for target in targets
                        },
                    }
                    for name, license_name in licenses.items()
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("AST_PACKAGED", raising=False)
    monkeypatch.setenv("AST_COMPONENT_CATALOG", str(catalog))

    report = publication_readiness()
    assert report["ready"] is True
    assert report["required_tools"]["youtube_runtime"] == [
        "deno",
        "ffmpeg",
        "ffprobe",
        "yt-dlp",
    ]
    assert {check["component"] for check in report["checks"]} == set(licenses)
    assert all(check["ready"] for check in report["checks"])


def test_youtube_runtime_requires_managed_deno_and_media_tools(tmp_path: Path, monkeypatch):
    digest = hashlib.sha256(b"fixture").hexdigest()
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": 1,
                "components": {
                    "youtube_runtime": {
                        "version": "1.0.0",
                        "license": "MIT/LGPL-2.1-or-later",
                        "provenance": "pinned upstream build",
                        "upstream_revision": "upstream-commit-or-release",
                        "redistribution_status": "approved",
                        "artifacts": {
                            "windows-x86_64": {
                                "url": "https://example.invalid/youtube.zip",
                                "sha256": digest,
                                "archive": "zip",
                                "tools": {"yt-dlp": "bin/yt-dlp", "ffmpeg": "bin/ffmpeg"},
                            }
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("AST_PACKAGED", raising=False)
    monkeypatch.setenv("AST_COMPONENT_CATALOG", str(catalog))

    report = publication_readiness(
        components=("youtube_runtime",), targets=("windows-x86_64",)
    )
    assert report["ready"] is False
    assert report["checks"][0]["reason"] == "required-tools-missing:deno,ffprobe"


def test_redistribution_must_be_explicitly_approved(tmp_path: Path, monkeypatch):
    digest = hashlib.sha256(b"fixture").hexdigest()
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": 1,
                "components": {
                    "fixture": {
                        "version": "1.0.0",
                        "license": "MIT",
                        "provenance": "upstream",
                        "upstream_revision": "abc123",
                        "redistribution_status": "pending",
                        "artifacts": {
                            "windows-x86_64": {
                                "url": "https://example.invalid/windows.zip",
                                "sha256": digest,
                                "archive": "zip",
                                "tools": {"tool": "bin/tool"},
                            }
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("AST_PACKAGED", raising=False)
    monkeypatch.setenv("AST_COMPONENT_CATALOG", str(catalog))

    report = publication_readiness(components=("fixture",), targets=("windows-x86_64",))
    assert report["ready"] is False
    assert report["checks"][0]["reason"] == "redistribution-not-approved"


def test_missing_platform_keeps_release_not_ready(tmp_path: Path, monkeypatch):
    digest = hashlib.sha256(b"fixture").hexdigest()
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": 1,
                "components": {
                    "transcription_engine": {
                        "version": "1.0.0",
                        "license": "Apache-2.0",
                        "provenance": "pinned upstream revision",
                        "upstream_revision": "abc123",
                        "redistribution_status": "approved",
                        "artifacts": {
                            "windows-x86_64": _artifact(
                                "windows-x86_64", "transcription_engine", digest
                            )
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("AST_PACKAGED", raising=False)
    monkeypatch.setenv("AST_COMPONENT_CATALOG", str(catalog))

    report = publication_readiness(components=("transcription_engine",))
    assert report["ready"] is False
    missing = [check for check in report["checks"] if not check["ready"]]
    assert missing == [
        {
            "component": "transcription_engine",
            "target": "macos-aarch64",
            "ready": False,
            "reason": "artifact-not-published",
        }
    ]

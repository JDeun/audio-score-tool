from __future__ import annotations

import hashlib
import json
from pathlib import Path

from audio_score_tool.managed_publication_readiness import publication_readiness


def test_bundled_catalog_is_not_yet_publication_ready():
    report = publication_readiness()
    assert report["ready"] is False
    assert report["checks"]
    assert all(check["reason"] == "artifact-not-published" for check in report["checks"])


def test_pinned_cross_platform_catalog_is_publication_ready(tmp_path: Path, monkeypatch):
    digest = hashlib.sha256(b"fixture").hexdigest()
    artifacts = {
        target: {
            "url": f"https://example.invalid/{target}.zip",
            "sha256": digest,
            "archive": "zip",
            "tools": {"tool": "bin/tool"},
        }
        for target in ("windows-x86_64", "macos-aarch64")
    }
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
                        "artifacts": artifacts,
                    },
                    "youtube_runtime": {
                        "version": "1.0.0",
                        "license": "MIT/LGPL-2.1-or-later",
                        "provenance": "pinned upstream builds",
                        "artifacts": artifacts,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("AST_PACKAGED", raising=False)
    monkeypatch.setenv("AST_COMPONENT_CATALOG", str(catalog))

    report = publication_readiness()
    assert report["ready"] is True
    assert all(check["ready"] for check in report["checks"])


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

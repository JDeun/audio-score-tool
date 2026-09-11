from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from audio_score_tool.managed_component_catalog import artifact_for, catalog_summary, load_catalog
from audio_score_tool.managed_components import ComponentIntegrityError, ComponentUnavailable


def test_bundled_catalog_declares_all_managed_product_components():
    catalog = load_catalog()
    assert catalog["schema"] == 1
    assert {
        "transcription_engine",
        "youtube_runtime",
        "audiveris",
        "whisperx",
        "audio_validation",
    } <= set(catalog["components"])


def test_dev_catalog_override_accepts_pinned_platform_artifact(tmp_path: Path, monkeypatch):
    payload = b"fixture"
    digest = hashlib.sha256(payload).hexdigest()
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": 1,
                "components": {
                    "fixture": {
                        "version": "1.2.3",
                        "license": "MIT",
                        "provenance": "fixture",
                        "artifacts": {
                            "linux-x86_64": {
                                "url": "https://example.invalid/fixture.zip",
                                "sha256": digest,
                                "archive": "zip",
                                "tools": {"fixture-tool": "bin/tool"},
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

    artifact = artifact_for("fixture", target="linux-x86_64")
    assert artifact.component == "fixture"
    assert artifact.version == "1.2.3"
    assert artifact.sha256 == digest
    assert artifact.license == "MIT"


def test_published_artifact_requires_license_and_provenance(tmp_path: Path, monkeypatch):
    digest = hashlib.sha256(b"fixture").hexdigest()
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": 1,
                "components": {
                    "fixture": {
                        "version": "1.2.3",
                        "artifacts": {
                            "linux-x86_64": {
                                "url": "https://example.invalid/fixture.zip",
                                "sha256": digest,
                                "archive": "zip",
                                "tools": {"fixture-tool": "bin/tool"},
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

    with pytest.raises(ComponentUnavailable, match="license is required"):
        artifact_for("fixture", target="linux-x86_64")


def test_catalog_rejects_path_shaped_component_name(tmp_path: Path, monkeypatch):
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps({"schema": 1, "components": {"../escape": {"version": "1", "artifacts": {}}}}),
        encoding="utf-8",
    )
    monkeypatch.delenv("AST_PACKAGED", raising=False)
    monkeypatch.setenv("AST_COMPONENT_CATALOG", str(catalog))
    with pytest.raises(ComponentIntegrityError):
        load_catalog()


def test_catalog_rejects_path_shaped_version(tmp_path: Path, monkeypatch):
    digest = hashlib.sha256(b"fixture").hexdigest()
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": 1,
                "components": {
                    "fixture": {
                        "version": "../../escape",
                        "license": "MIT",
                        "provenance": "fixture",
                        "artifacts": {
                            "linux-x86_64": {
                                "url": "https://example.invalid/fixture.zip",
                                "sha256": digest,
                                "archive": "zip",
                                "tools": {"fixture-tool": "bin/tool"},
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
    with pytest.raises(ComponentIntegrityError):
        artifact_for("fixture", target="linux-x86_64")


def test_packaged_mode_ignores_external_catalog_override(tmp_path: Path, monkeypatch):
    malicious = tmp_path / "catalog.json"
    malicious.write_text(
        json.dumps({"schema": 1, "components": {"attacker": {"artifacts": {}}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("AST_PACKAGED", "1")
    monkeypatch.setenv("AST_COMPONENT_CATALOG", str(malicious))

    assert catalog_summary("attacker")["published"] is False
    with pytest.raises(ComponentUnavailable):
        artifact_for("attacker")

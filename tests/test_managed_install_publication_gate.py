"""The UI install button and direct install API share release approval rules.

No network requests or real third-party artifacts are needed for these tests.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from audio_score_tool import setup_center_api as setup
from audio_score_tool.api import app
from audio_score_tool.managed_component_catalog import catalog_summary, platform_key
from audio_score_tool.managed_publication_readiness import check_publication


def _approved_entry(component: str) -> dict:
    tools = {
        "transcription_engine": {"mt3-infer": "bin/mt3-infer"},
        "youtube_runtime": {
            "yt-dlp": "bin/yt-dlp",
            "deno": "bin/deno",
            "ffmpeg": "bin/ffmpeg",
            "ffprobe": "bin/ffprobe",
        },
        "audiveris": {"audiveris": "bin/audiveris"},
    }
    return {
        "version": "1.0.0",
        "license": "fixture-only-no-redistribution",
        "provenance": "synthetic CI fixture (not a third-party release)",
        "upstream_revision": "fixture-revision",
        "redistribution_status": "approved",
        "artifacts": {
            platform_key(): {
                "url": "https://example.invalid/ci-only-artifact.zip",
                "sha256": hashlib.sha256(b"synthetic archive").hexdigest(),
                "archive": "zip",
                "tools": tools[component],
            }
        },
    }


def _write_catalog(tmp_path: Path, monkeypatch, component: str, entry: dict) -> None:
    catalog = tmp_path / "ci-catalog.json"
    catalog.write_text(
        json.dumps({"schema": 1, "components": {component: entry}}),
        encoding="utf-8",
    )
    monkeypatch.delenv("AST_PACKAGED", raising=False)
    monkeypatch.setenv("AST_COMPONENT_CATALOG", str(catalog))


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda entry: entry.update(redistribution_status="pending"), "redistribution-not-approved"),
        (lambda entry: entry.pop("upstream_revision"), "upstream-revision-missing"),
        (lambda entry: entry.pop("license"), "license-missing"),
        (lambda entry: entry.pop("provenance"), "provenance-missing"),
        (lambda entry: entry["artifacts"].update({platform_key(): {}}), "incomplete"),
        (
            lambda entry: entry["artifacts"][platform_key()]["tools"].pop("ffprobe"),
            "required-tools-missing:ffprobe",
        ),
    ],
)
def test_incomplete_or_unapproved_youtube_runtime_is_not_installable(
    tmp_path: Path, monkeypatch, mutation, reason: str,
):
    component = "youtube_runtime"
    entry = _approved_entry(component)
    mutation(entry)
    _write_catalog(tmp_path, monkeypatch, component, entry)

    check = check_publication(component, platform_key())
    assert check.ready is False
    assert reason in str(check.reason)

    summary = catalog_summary(component)
    assert summary["published"] is False
    assert reason in str(summary["publication_reason"])

    def must_not_install(_artifact):
        raise AssertionError("Unapproved catalog must never reach downloader/installer")

    monkeypatch.setattr(setup, "install_component_artifact", must_not_install)
    response = TestClient(app).post("/api/setup/install", json={"component": component})
    assert response.status_code == 409
    assert reason in response.json()["detail"]


def test_empty_bundled_catalog_does_not_advertise_unavailable_installer(monkeypatch):
    monkeypatch.delenv("AST_PACKAGED", raising=False)
    monkeypatch.delenv("AST_COMPONENT_CATALOG", raising=False)

    summary = catalog_summary("transcription_engine")
    assert summary["published"] is False
    assert summary["publication_reason"] == "artifact-not-published"
    response = TestClient(app).post(
        "/api/setup/install", json={"component": "transcription_engine"}
    )
    assert response.status_code == 409
    assert "artifact-not-published" in response.json()["detail"]


@pytest.mark.parametrize("component", ["transcription_engine", "youtube_runtime", "audiveris"])
def test_approved_complete_metadata_with_review_stub_calls_pinned_artifact_only(
    tmp_path: Path, monkeypatch, component: str,
):
    # The separate release-signoff enforcement is exercised end-to-end in
    # test_managed_release_approval.py. This test isolates install URL pinning.
    monkeypatch.setattr(
        "audio_score_tool.managed_publication_readiness.check_release_approval",
        lambda *_args: None,
    )
    _write_catalog(tmp_path, monkeypatch, component, _approved_entry(component))
    assert check_publication(component, platform_key()).ready is True
    summary = catalog_summary(component)
    assert summary["published"] is True
    assert summary["publication_reason"] is None

    captured = []

    def record_install(artifact):
        captured.append(artifact)
        return {"component": artifact.component, "ready": True}

    monkeypatch.setattr(setup, "install_component_artifact", record_install)
    monkeypatch.setattr(setup, "setup_center_status", lambda: {"core_ready": False})
    response = TestClient(app).post("/api/setup/install", json={"component": component})
    assert response.status_code == 200, response.text
    assert response.json()["installed"]["component"] == component
    assert len(captured) == 1
    assert captured[0].component == component
    assert captured[0].url == "https://example.invalid/ci-only-artifact.zip"


def test_untrusted_request_cannot_supply_manifest_url_or_bypass_catalog(
    tmp_path: Path, monkeypatch,
):
    component = "transcription_engine"
    pending = _approved_entry(component)
    pending["redistribution_status"] = "pending"
    _write_catalog(tmp_path, monkeypatch, component, pending)
    monkeypatch.setattr(
        setup,
        "install_component_artifact",
        lambda _item: (_ for _ in ()).throw(AssertionError("unauthorized install")),
    )
    response = TestClient(app).post(
        "/api/setup/install",
        json={
            "component": component,
            "url": "https://attacker.invalid/unsanctioned.zip",
            "sha256": "0" * 64,
            "redistribution_status": "approved",
        },
    )
    assert response.status_code == 409
    assert "redistribution-not-approved" in response.json()["detail"]

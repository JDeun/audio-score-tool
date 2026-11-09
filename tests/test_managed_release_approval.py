"""Independent release evidence must bind bytes, platform and legal sign-off.

All approved fixtures here are synthetic. This suite cannot approve or
redistribute third-party runtime/model files.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from audio_score_tool import managed_publication_readiness as readiness
from audio_score_tool import setup_center_api as setup
from audio_score_tool.api import app
from audio_score_tool.managed_component_catalog import catalog_summary, platform_key
from audio_score_tool.managed_release_approvals import (
    catalog_fingerprint,
    check_release_approval,
    load_release_approvals,
    release_approvals_path,
)


def _test_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, component="youtube_runtime"):
    target = platform_key()
    tools = {
        "transcription_engine": {"mt3-infer": "bin/mt3-infer"},
        "audiveris": {"audiveris": "bin/audiveris"},
        "youtube_runtime": {
            "yt-dlp": "bin/yt-dlp",
            "deno": "bin/deno",
            "ffmpeg": "bin/ffmpeg",
            "ffprobe": "bin/ffprobe",
        },
    }[component]
    archive_sha256 = hashlib.sha256(b"synthetic original archive").hexdigest()
    entry = {
        "version": "1.0.0-ci",
        "license": "synthetic-fixture-only",
        "provenance": "synthetic original CI test record",
        "upstream_revision": "review-rev-only",
        "redistribution_status": "approved",
        "artifacts": {
            target: {
                "url": "https://example.invalid/synthetic/ci-artifact.zip",
                "sha256": archive_sha256,
                "archive": "zip",
                "tools": tools,
                "max_download_bytes": 2048,
            },
        },
    }
    if component == "transcription_engine":
        digest = hashlib.sha256(b"synthetic model checkpoint").hexdigest()
        entry["artifacts"][target]["model_identity"] = {
            "model_key": "mr_mt3",
            "checkpoint_path": "checkpoints/mr_mt3/mt3.pth",
            "checkpoint_sha256": digest,
            "model_revision": "sha256:" + digest,
            "runtime_revision": entry["upstream_revision"],
        }
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"schema": 1, "components": {component: entry}}))
    approvals = tmp_path / "approvals.json"
    approvals.write_text(json.dumps({"schema": 1, "approvals": {}}))
    monkeypatch.setenv("AST_PACKAGED", "0")
    monkeypatch.setenv("AST_COMPONENT_CATALOG", str(catalog))
    monkeypatch.setenv("AST_COMPONENT_APPROVALS", str(approvals))
    payload = readiness._artifact_payload(component, target)
    assert payload is not None
    return component, target, entry, payload, catalog, approvals


def _valid_record(component: str, target: str, payload: dict) -> dict:
    published_url = payload["url"]
    tools = {
        name: hashlib.sha256(f"fixture-{name}".encode()).hexdigest()
        for name in payload["tools"]
    }
    record = {
        "catalog_sha256": catalog_fingerprint(payload),
        "remote_evidence": {
            "schema_version": "1",
            "component": component,
            "target": target,
            "version": payload["version"],
            "upstream_revision": payload["upstream_revision"],
            "published_url_sha256": hashlib.sha256(published_url.encode()).hexdigest(),
            "published_archive_sha256": payload["sha256"],
            "published_archive_bytes": 192,
            "published_tool_sha256": tools,
            "candidate_sha256": hashlib.sha256(b"synthetic local receipt").hexdigest(),
            "remote_artifact_verified": True,
            "archive_checked_and_installed_locally": True,
            "redistribution_status": "pending",
            "approval_required": True,
            "license_independently_approved": False,
            "clean_machine_verified": False,
        },
        "license_review": {
            "decision": "approved",
            "reviewer": "synthetic-fixture-reviewer",
            "reviewed_at_utc": "2026-11-08T00:00:00+00:00",
            "license_reference_url": "https://example.invalid/license/fixture",
            "notice_url": "https://example.invalid/notices/fixture",
            "notice_sha256": hashlib.sha256(b"synthetic notice").hexdigest(),
            "source_offer_url": "https://example.invalid/source/fixture",
        },
    }
    if "model_identity" in payload:
        record["remote_evidence"]["published_model_identity"] = {
            **payload["model_identity"], "checkpoint_verified": True,
        }
    return record


def _write_approval(path: Path, component: str, target: str, record: dict) -> None:
    path.write_text(
        json.dumps({"schema": 1, "approvals": {component: {target: record}}}),
        encoding="utf-8",
    )


def test_catalog_approved_string_without_separate_receipt_never_installs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    component, target, _entry, _payload, _catalog, _approvals = _test_catalog(
        tmp_path, monkeypatch,
    )
    check = readiness.check_publication(component, target)
    assert check.ready is False and check.reason == "approval-receipt-missing"
    summary = catalog_summary(component)
    assert summary["published"] is False
    assert summary["publication_reason"] == "approval-receipt-missing"
    assert summary["version"] == "1.0.0-ci"

    monkeypatch.setattr(
        setup, "install_component_artifact",
        lambda *_: (_ for _ in ()).throw(AssertionError("must not download")),
    )
    response = TestClient(app).post(
        "/api/setup/install", json={"component": component},
    )
    assert response.status_code == 409
    assert "approval-receipt-missing" in response.json()["detail"]


@pytest.mark.parametrize("component", [
    "transcription_engine", "youtube_runtime", "audiveris",
])
def test_exact_record_enables_only_pinned_target_and_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, component: str,
):
    name, target, _entry, payload, _catalog, approvals = _test_catalog(
        tmp_path, monkeypatch, component,
    )
    _write_approval(approvals, name, target, _valid_record(name, target, payload))
    assert check_release_approval(name, target, payload) is None
    assert readiness.check_publication(name, target).ready is True
    assert catalog_summary(name)["published"] is True

    hits = []

    def fake_install(artifact):
        hits.append(artifact)
        return {"ready": True, "integrity": "verified"}

    monkeypatch.setattr(setup, "install_component_artifact", fake_install)
    monkeypatch.setattr(setup, "setup_center_status", lambda: {"core_ready": False})
    response = TestClient(app).post("/api/setup/install", json={"component": name})
    assert response.status_code == 200
    assert len(hits) == 1
    assert hits[0].url == payload["url"]
    assert hits[0].sha256 == payload["sha256"]


@pytest.mark.parametrize(("change", "expected"), [
    (lambda r: r.update(catalog_sha256="0" * 64), "approval-catalog-drift"),
    (lambda r: r.pop("remote_evidence"), "remote-evidence-missing"),
    (
        lambda r: r["remote_evidence"].update(published_archive_sha256="0" * 64),
        "remote-evidence-mismatch",
    ),
    (
        lambda r: r["remote_evidence"].update(published_url_sha256="0" * 64),
        "remote-evidence-mismatch",
    ),
    (
        lambda r: r["remote_evidence"].update(version="wrong-runtime"),
        "remote-evidence-mismatch",
    ),
    (
        lambda r: r["remote_evidence"].update(target="macos-fake"),
        "remote-evidence-mismatch",
    ),
    (
        lambda r: r["remote_evidence"]["published_tool_sha256"].pop("deno"),
        "remote-evidence-mismatch",
    ),
    (
        lambda r: r["remote_evidence"].update(license_independently_approved=True),
        "remote-evidence-mismatch",
    ),
    (
        lambda r: r["remote_evidence"].update(redistribution_status="approved"),
        "remote-evidence-mismatch",
    ),
    (
        lambda r: r["remote_evidence"].update(published_archive_bytes=99999),
        "remote-evidence-mismatch",
    ),
    (
        lambda r: r["remote_evidence"].update(candidate_sha256="pending"),
        "remote-evidence-mismatch",
    ),
    (lambda r: r.pop("license_review"), "license-review-missing"),
    (
        lambda r: r["license_review"].update(decision="pending"),
        "license-review-incomplete",
    ),
    (
        lambda r: r["license_review"].update(notice_sha256="invalid"),
        "license-review-incomplete",
    ),
    (
        lambda r: r["license_review"].update(source_offer_url="http://127.0.0.1/source"),
        "license-review-incomplete",
    ),
])
def test_incomplete_or_modified_approval_never_unlocks_setup_center(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change, expected,
):
    name, target, _entry, payload, _catalog, approvals = _test_catalog(
        tmp_path, monkeypatch,
    )
    record = _valid_record(name, target, payload)
    change(record)
    _write_approval(approvals, name, target, record)
    check = readiness.check_publication(name, target)
    assert check.ready is False and check.reason == expected
    assert catalog_summary(name)["publication_reason"] == expected


@pytest.mark.parametrize("change", [
    lambda e: e["artifacts"][platform_key()].update(
        sha256="f" * 64,
    ),
    lambda e: e["artifacts"][platform_key()].update(
        url="https://example.invalid/other-bytes.zip",
    ),
    lambda e: e["artifacts"][platform_key()].update(
        tools={"yt-dlp": "bin/yt-dlp", "deno": "bin/deno", "ffmpeg": "bin/ffmpeg",
               "ffprobe": "other/ffprobe"},
    ),
    lambda e: e.update(version="1.0.1-ci"),
    lambda e: e.update(license="GPL-3.0"),
    lambda e: e.update(upstream_revision="different-revision"),
])
def test_any_approved_catalog_field_drift_refuses_installer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change,
):
    name, target, entry, payload, catalog, approvals = _test_catalog(
        tmp_path, monkeypatch,
    )
    _write_approval(approvals, name, target, _valid_record(name, target, payload))
    change(entry)
    catalog.write_text(json.dumps({"schema": 1, "components": {name: entry}}))
    assert readiness.check_publication(name, target).reason == "approval-catalog-drift"


def test_unexpected_target_or_cross_component_receipt_cannot_authorize(
    tmp_path: Path, monkeypatch,
):
    name, target, _entry, payload, _catalog, approvals = _test_catalog(
        tmp_path, monkeypatch,
    )
    record = _valid_record(name, target, payload)
    _write_approval(approvals, "audiveris", target, record)
    assert readiness.check_publication(name, target).reason == "approval-receipt-missing"
    _write_approval(approvals, name, "windows-fake", record)
    assert readiness.check_publication(name, target).reason == "approval-receipt-missing"


def test_catalog_artifact_cannot_spoof_component_identity(
    tmp_path: Path, monkeypatch,
):
    name, target, entry, _payload, catalog, _approvals = _test_catalog(tmp_path, monkeypatch)
    entry["artifacts"][target]["component"] = "audiveris"
    catalog.write_text(json.dumps({"schema": 1, "components": {name: entry}}))
    assert readiness.check_publication(name, target).reason == "artifact-component-mismatch"


def test_packaged_mode_cannot_override_bundled_approval_receipt(
    tmp_path: Path, monkeypatch,
):
    name, target, _entry, payload, _catalog, approvals = _test_catalog(
        tmp_path, monkeypatch,
    )
    _write_approval(approvals, name, target, _valid_record(name, target, payload))
    monkeypatch.setenv("AST_PACKAGED", "1")
    assert release_approvals_path().name == "managed-release-approvals.json"
    assert load_release_approvals()["approvals"] == {}
    assert check_release_approval(name, target, payload) == "approval-receipt-missing"


@pytest.mark.parametrize("contents", [
    "{ invalid JSON",
    json.dumps({"schema": 1, "approvals": []}),
    json.dumps({"schema": 2, "approvals": {}}),
])
def test_bad_approval_file_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, contents: str,
):
    name, target, _entry, payload, _catalog, approvals = _test_catalog(
        tmp_path, monkeypatch,
    )
    approvals.write_text(contents)
    assert check_release_approval(name, target, payload).startswith("approval-record-")


def test_sidecar_bundles_both_catalog_and_approval_files():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "scripts/build_sidecar.py").read_text()
    assert "managed-component-catalog.json" in source
    assert "managed-release-approvals.json" in source
    assert 'f"{release_approvals}{os.pathsep}audio_score_tool"' in source


def test_stable_amt_model_requires_remote_checkpoint_byte_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    # Synthetic, with an explicitly supplied Windows target on a Linux CI host.
    name, _target, _entry, payload, _catalog, approvals = _test_catalog(
        tmp_path, monkeypatch, "transcription_engine",
    )
    target = "windows-x86_64"
    digest = hashlib.sha256(b"owned-synthetic-model").hexdigest()
    identity = {
        "model_key": "mr_mt3",
        "model_revision": "sha256:" + digest,
        "runtime_revision": payload["upstream_revision"],
        "checkpoint_path": "checkpoints/mr_mt3/mt3.pth",
        "checkpoint_sha256": digest,
    }
    payload["model_identity"] = identity
    approved = _valid_record(name, target, payload)
    approved["remote_evidence"]["published_model_identity"] = {
        **identity, "checkpoint_verified": True,
    }
    _write_approval(approvals, name, target, approved)
    assert check_release_approval(name, target, payload) is None

    approved["remote_evidence"]["published_model_identity"]["checkpoint_sha256"] = "f" * 64
    _write_approval(approvals, name, target, approved)
    assert check_release_approval(name, target, payload) == "model-evidence-mismatch"

    del approved["remote_evidence"]["published_model_identity"]
    _write_approval(approvals, name, target, approved)
    assert check_release_approval(name, target, payload) == "model-evidence-mismatch"

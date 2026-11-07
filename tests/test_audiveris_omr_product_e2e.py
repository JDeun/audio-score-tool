"""Review-only synthetic score + provenance contracts. No third-party binary is tested here."""
from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import smoke_audiveris_omr_product_e2e as e2e
from scripts.verify_audiveris_official_installer import AudiverisReviewError


def _fixture(tmp_path: Path, monkeypatch, target: str = "windows-x86_64"):
    monkeypatch.setattr(e2e, "_platform_matches", lambda chosen: chosen == target)
    archive = tmp_path / "owned-local-only.zip"
    archive.write_bytes(b"review-only fake ZIP original source bytes")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    receipt = {
        "schema": 1,
        "component": "audiveris",
        "target": target,
        "version": "5.11.0-review-1",
        "source_commit": "9e1e55cd2746037d059345881c53e6a6754bffbd",
        "redistribution_status": "pending",
        "legal_review_status": "pending",
        "archive_sha256": digest,
        "source_asset_sha256": "1" * 64,
        "source_receipt_sha256": "2" * 64,
        "native_receipt_sha256": "3" * 64,
        "review_pin_sha256": "4" * 64,
        "launcher_sha256": "5" * 64,
        "java_sha256": "6" * 64,
        "archive_members_sha256": "7" * 64,
        "tool_path": (
            "Audiveris/Audiveris.exe" if target == "windows-x86_64"
            else "Audiveris.app/Contents/MacOS/Audiveris"
        ),
        "embedded_jre_path": (
            "Audiveris/runtime/bin/java.exe" if target == "windows-x86_64"
            else "Audiveris.app/Contents/runtime/Contents/Home/bin/java"
        ),
        "local_managed_zip_install_verified": True,
        "relocated_audiveris_version_verified": True,
        "relocated_embedded_jre_version_verified": True,
        "full_omr_to_musicxml_verified": False,
        "verified_launcher_uses_embedded_java": False,
        "remote_artifact_published": False,
        "clean_machine_verified": False,
        "approval_required": True,
    }
    pending = tmp_path / "owned-local-only.zip.pending.json"
    pending.write_text(json.dumps(receipt), encoding="utf-8")
    return archive, pending, receipt


@pytest.mark.parametrize("target", ["windows-x86_64", "macos-aarch64"])
def test_pending_portable_archive_bound_to_local_byte_sha_and_not_approved(
    tmp_path: Path, monkeypatch, target: str,
):
    archive, pending, report = _fixture(tmp_path, monkeypatch, target)
    checked = e2e._archive_contract(archive=archive, pending=pending, target=target)
    assert checked == report
    assert checked["redistribution_status"] == "pending"
    assert checked["full_omr_to_musicxml_verified"] is False
    assert checked["remote_artifact_published"] is False
    assert checked["clean_machine_verified"] is False


def test_tampered_local_archive_is_refused_before_omr(tmp_path: Path, monkeypatch):
    archive, pending, _receipt = _fixture(tmp_path, monkeypatch)
    archive.write_bytes(archive.read_bytes() + b"tampered")
    with pytest.raises(AudiverisReviewError, match="SHA-pinned"):
        e2e._archive_contract(archive=archive, pending=pending, target="windows-x86_64")


@pytest.mark.parametrize("change", [
    {"redistribution_status": "approved"},
    {"legal_review_status": "approved"},
    {"remote_artifact_published": True},
    {"full_omr_to_musicxml_verified": True},
    {"source_commit": "0" * 40},
    {"relocated_embedded_jre_version_verified": False},
    {"approval_required": False},
])
def test_receipt_cannot_claim_publication_or_unverified_outcomes(
    tmp_path: Path, monkeypatch, change: dict,
):
    archive, pending, receipt = _fixture(tmp_path, monkeypatch)
    receipt.update(change)
    pending.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(AudiverisReviewError, match="incomplete"):
        e2e._archive_contract(archive=archive, pending=pending, target="windows-x86_64")


@pytest.mark.parametrize("field,value", [
    ("tool_path", "../../outside/Audiveris.exe"),
    ("tool_path", "/bin/true"),
    ("embedded_jre_path", r"A:\outside\java.exe"),
    ("embedded_jre_path", "Audiveris/../bin/java.exe"),
    ("launcher_sha256", "bad-digest"),
    ("native_receipt_sha256", ""),
])
def test_unsafe_executable_mapping_and_missing_sha_rejected(
    tmp_path: Path, monkeypatch, field: str, value: str,
):
    archive, pending, receipt = _fixture(tmp_path, monkeypatch)
    receipt[field] = value
    pending.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(AudiverisReviewError, match="unsafe|valid"):
        e2e._archive_contract(archive=archive, pending=pending, target="windows-x86_64")


def test_wrong_native_host_is_refused_before_external_execution(tmp_path: Path, monkeypatch):
    archive, pending, _ = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(e2e, "_platform_matches", lambda _target: False)
    with pytest.raises(AudiverisReviewError, match="exact native OS"):
        e2e._archive_contract(archive=archive, pending=pending, target="windows-x86_64")


def test_original_musicxml_is_engraving_ready_and_has_no_external_repertoire(tmp_path: Path):
    destination = tmp_path / "owned.musicxml"
    created = e2e.make_owned_musicxml(destination)
    assert created["synthetic_measures"] == 12
    assert created["synthetic_pitched_notes"] == 48
    assert created["synthetic_score_sha256"] == hashlib.sha256(destination.read_bytes()).hexdigest()
    root = ET.fromstring(destination.read_bytes())
    measures = root.findall("part/measure")
    assert len(measures) == 12
    assert all(len(measure.findall("note")) == 4 for measure in measures)
    assert sum(node.get("new-system") == "yes" for node in root.findall(".//print")) == 2
    assert len(root.findall(".//lyrics")) == 0
    assert e2e._assert_score_with_notes(destination.read_text()) == (1, 48)
    with pytest.raises(FileExistsError):
        e2e.make_owned_musicxml(destination)


@pytest.mark.parametrize("xml", [
    "<html><body>fake</body></html>",
    '<!DOCTYPE score-partwise [<!ENTITY x "boom">]><score-partwise/>',
    "<score-partwise><part/><part-list/></score-partwise>",
    "<not-valid-xml>",
])
def test_false_or_unsafe_omr_xml_never_counts_as_recognized_notes(xml: str):
    with pytest.raises(AudiverisReviewError):
        e2e._assert_score_with_notes(xml)


def _mock_reply(**result):
    return SimpleNamespace(status_code=200, text="", json=lambda: result)


def test_done_job_status_must_be_real_terminal_success(monkeypatch):
    class Client:
        def get(self, _path):
            return _mock_reply(status="done", job_id="owned-id", kind="omr")
    assert e2e._bounded_job(Client(), "owned-id", timeout_seconds=5)["status"] == "done"


@pytest.mark.parametrize("state", ["failed", "cancelled", "interrupted"])
def test_audiveris_job_failure_is_rejected_not_mocked_success(state: str):
    class Client:
        def get(self, _path):
            return _mock_reply(status=state, error="real managed Audiveris failed")
    with pytest.raises(AudiverisReviewError, match=f"job {state}"):
        e2e._bounded_job(Client(), "owned-id", timeout_seconds=3)


def test_omr_processing_timeout_cancels_job(monkeypatch):
    class Client:
        cancelled = False
        def get(self, _path):
            return _mock_reply(status="running")
        def post(self, _path):
            self.cancelled = True
    client = Client()
    points = iter([0.0, 0.1, 2.0])
    monkeypatch.setattr(e2e.time, "monotonic", lambda: next(points))
    monkeypatch.setattr(e2e.time, "sleep", lambda _time: None)
    with pytest.raises(AudiverisReviewError, match="bounded native timeout"):
        e2e._bounded_job(client, "owned-id", timeout_seconds=1)
    assert client.cancelled is True


def test_job_timeout_is_never_unbounded():
    with pytest.raises(AudiverisReviewError, match="bounded"):
        e2e._bounded_job(None, "id", timeout_seconds=0)
    with pytest.raises(AudiverisReviewError, match="bounded"):
        e2e._bounded_job(None, "id", timeout_seconds=481)


def test_workflow_requires_real_product_api_smoke_on_both_native_hosts():
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github/workflows/audiveris-official-installer-review.yml"
    ).read_text(encoding="utf-8")
    assert "windows-2025" in workflow and "macos-15" in workflow
    assert "scripts.smoke_audiveris_omr_product_e2e" in workflow
    assert "AUDIVERIS-LOCAL-REVIEW-ONLY.zip.pending.json" in workflow
    assert "OMR-PRODUCT-E2E.pending.json" in workflow
    assert "--job-timeout 420" in workflow
    assert "uv run --frozen --extra dev" in workflow
    artifact_paths = workflow.split("Upload unapproved JSON proof only")[1].split(
        "if-no-files-found:"
    )[0]
    assert "OMR-PRODUCT-E2E.pending.json" in artifact_paths
    assert "/AUDIVERIS-LOCAL-REVIEW-ONLY.zip\n" not in artifact_paths
    assert "/raw/" not in artifact_paths

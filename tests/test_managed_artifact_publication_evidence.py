"""Local-only publication-proof tests: no real external archives or music downloaded."""
from __future__ import annotations

import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

from audio_score_tool.managed_components import ComponentIntegrityError
from scripts import prepare_managed_artifact_candidate as candidate
from scripts import verify_managed_artifact_publication as publication


class _PublishedResponse(io.BytesIO):
    def __init__(self, data: bytes, *, url: str = "https://example.invalid/approved-review.zip"):
        super().__init__(data)
        self._url = url

    def geturl(self) -> str:
        return self._url


def _fixture(tmp_path: Path) -> tuple[dict, Path]:
    archive = tmp_path / "owned-fixture.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/mt3-infer", b"owned synthetic CLI fixture")
    report = candidate.draft_candidate(
        archive_path=archive,
        component="transcription_engine",
        version="1.0.0-ci",
        target="linux-x86_64",
        url="https://example.invalid/approved-review.zip",
        archive_format="zip",
        tools={"mt3-infer": "bin/mt3-infer"},
        license_name="Synthetic-fixture-only",
        provenance="original local, not a public third-party artifact",
        upstream_revision="synthetic-fixture-revision",
        max_download_bytes=4096,
        max_uncompressed_bytes=4096,
    )
    return report, archive


def _fake_transport(
    monkeypatch: pytest.MonkeyPatch, data: bytes, *, url: str | None = None,
) -> list[str]:
    from audio_score_tool import managed_components

    received = []

    def urlopen(request, **_kwargs):
        received.append(request.full_url)
        return _PublishedResponse(data, url=url or request.full_url)

    monkeypatch.setattr(managed_components, "_open_trusted_download", urlopen)
    return received


def test_remote_verified_bytes_reinstall_and_match_all_local_tool_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    report, local = _fixture(tmp_path)
    seen = _fake_transport(monkeypatch, local.read_bytes())
    verified = publication.verify_published_candidate(report, local_archive=local)
    assert seen == ["https://example.invalid/approved-review.zip"]
    assert verified["remote_artifact_verified"] is True
    assert verified["published_archive_sha256"] == hashlib.sha256(local.read_bytes()).hexdigest()
    assert verified["published_archive_bytes"] == local.stat().st_size
    assert verified["published_tool_sha256"] == report["local_validation"]["tool_sha256"]
    assert verified["local_archive_rechecked"] is True
    assert verified["redistribution_status"] == "pending"
    assert verified["license_independently_approved"] is False
    assert verified["clean_machine_verified"] is False
    assert verified["tools_executed"] is False
    assert verified["approval_required"] is True
    assert "approved-review.zip" not in json.dumps(verified)
    assert not list(tmp_path.glob("ast-published-artifact-proof-*"))


def test_default_cli_dry_run_does_not_fetch_or_create_remote_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys,
):
    report, _archive = _fixture(tmp_path)
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(json.dumps(report), encoding="utf-8")
    destination = tmp_path / "no-proof.json"
    monkeypatch.setattr(
        publication,
        "_download",
        lambda *_args: (_ for _ in ()).throw(AssertionError("dry-run tried network")),
    )
    monkeypatch.setattr(
        sys, "argv",
        ["verify_managed_artifact_publication.py", str(candidate_path),
         "--output", str(destination)],
    )
    assert publication.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["remote_artifact_verified"] is False
    assert not destination.exists()


def test_explicit_fetch_cli_writes_pending_proof_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys,
):
    report, archive = _fixture(tmp_path)
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(json.dumps(report), encoding="utf-8")
    evidence_path = tmp_path / "remote.pending.json"
    seen = _fake_transport(monkeypatch, archive.read_bytes())
    monkeypatch.setattr(
        sys, "argv",
        ["verify_managed_artifact_publication.py", str(candidate_path),
         "--fetch", "--local-archive", str(archive), "--output", str(evidence_path)],
    )
    assert publication.main() == 0
    assert len(seen) == 1
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert payload["remote_artifact_verified"] is True
    assert payload["approval_required"] is True
    assert payload["redistribution_status"] == "pending"
    assert publication._BUNDLED_CATALOG.is_file()
    assert "remote_artifact_verified" in capsys.readouterr().out


def test_wrong_remote_bytes_rejected_before_archive_extraction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    report, archive = _fixture(tmp_path)
    wrong = b"x" * archive.stat().st_size
    _fake_transport(monkeypatch, wrong)
    with pytest.raises(ComponentIntegrityError, match="Published HTTPS artifact SHA-256 mismatch"):
        publication.verify_published_candidate(report)
    assert not list(tmp_path.glob("ast-published-artifact-proof-*"))


def test_same_archive_pin_but_changed_tool_bytes_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    report, _archive = _fixture(tmp_path)
    malicious = tmp_path / "repacked.zip"
    with zipfile.ZipFile(malicious, "w") as bundle:
        bundle.writestr("bin/mt3-infer", b"other executable content")
    # An attacker may alter a manifest alongside an archive; the original
    # reviewed per-tool fingerprint must still prevent silent replacement.
    new_sha = hashlib.sha256(malicious.read_bytes()).hexdigest()
    report["candidate"]["artifacts"]["linux-x86_64"]["sha256"] = new_sha
    report["local_validation"]["sha256"] = new_sha
    _fake_transport(monkeypatch, malicious.read_bytes())
    with pytest.raises(ComponentIntegrityError, match="Published tool bytes differ"):
        publication.verify_published_candidate(report)


def test_corrupted_local_archive_refused_even_if_remote_claims_same_pin(tmp_path: Path):
    report, archive = _fixture(tmp_path)
    archive.write_bytes(b"altered-after-local-review")
    with pytest.raises(ComponentIntegrityError, match="Local archive differs"):
        publication.verify_published_candidate(report, local_archive=archive)


@pytest.mark.parametrize("mutation", [
    lambda report: report["candidate"].update(redistribution_status="approved"),
    lambda report: report.update(approval_required=False),
    lambda report: report["candidate"]["artifacts"].update({"windows-x86_64": {}}),
    lambda report: report["local_validation"].update(archive_checked_locally=False),
    lambda report: report["local_validation"].update(sha256="0" * 64),
    lambda report: report["candidate"]["artifacts"]["linux-x86_64"]["tools"].clear(),
    lambda report: report["candidate"].update(license="runtime-specific"),
])
def test_invalid_candidate_never_reaches_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation,
):
    report, _archive = _fixture(tmp_path)
    mutation(report)
    monkeypatch.setattr(
        publication,
        "_download",
        lambda *_args: (_ for _ in ()).throw(AssertionError("untrusted candidate fetched")),
    )
    with pytest.raises((ValueError, ComponentIntegrityError)):
        publication.verify_published_candidate(report)


def test_stricter_remote_budget_applies_to_streamed_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    report, archive = _fixture(tmp_path)
    report["candidate"]["artifacts"]["linux-x86_64"]["max_download_bytes"] = 16
    _fake_transport(monkeypatch, archive.read_bytes())
    with pytest.raises(ComponentIntegrityError, match="exceeds its size limit"):
        publication.verify_published_candidate(report)


def test_published_evidence_never_overwrites_existing_file_or_catalog(tmp_path: Path):
    report, archive = _fixture(tmp_path)
    destination = tmp_path / "existing.json"
    destination.write_text("intact", encoding="utf-8")
    with pytest.raises(FileExistsError):
        publication.write_evidence(report, destination)
    assert destination.read_text(encoding="utf-8") == "intact"
    with pytest.raises(ValueError, match="managed catalog"):
        publication.write_evidence(report, publication._BUNDLED_CATALOG)


def test_invalid_output_path_fails_before_fetch_or_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    report, _archive = _fixture(tmp_path)
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(
        publication,
        "_download",
        lambda *_args: (_ for _ in ()).throw(AssertionError("bad path fetched")),
    )
    monkeypatch.setattr(sys, "argv", [
        "verify_managed_artifact_publication.py", str(candidate_path),
        "--fetch", "--output", str(publication._BUNDLED_CATALOG),
    ])
    with pytest.raises(SystemExit) as exc:
        publication.main()
    assert exc.value.code == 2

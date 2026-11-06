from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

import pytest

from audio_score_tool.managed_components import ComponentIntegrityError
from scripts import prepare_managed_artifact_candidate as candidate


def _archive(tmp_path: Path, *, member: str = "bin/mt3-infer") -> Path:
    archive = tmp_path / "candidate.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as writer:
        writer.writestr(member, b"synthetic tool fixture only")
    return archive


def _draft(
    archive: Path,
    *,
    component: str = "transcription_engine",
    tools: dict[str, str] | None = None,
    **kwargs,
) -> dict:
    params = {
        "archive_path": archive,
        "component": component,
        "target": "linux-x86_64",
        "version": "0.8-fixture-1",
        "url": "https://example.invalid/candidate/fixture.zip",
        "archive_format": "zip",
        "tools": tools or {"mt3-infer": "bin/mt3-infer"},
        "license_name": "Synthetic-fixture-test-only",
        "provenance": "deterministic local CI fixture",
        "upstream_revision": "synthetic-revision-123",
    }
    params.update(kwargs)
    return candidate.draft_candidate(**params)


def test_verified_local_archive_produces_only_pending_candidate(tmp_path: Path):
    archive = _archive(tmp_path)
    report = _draft(archive)
    assert report["component"] == "transcription_engine"
    assert report["target"] == "linux-x86_64"
    assert report["candidate"]["redistribution_status"] == "pending"
    assert report["approval_required"] is True
    assert report["candidate"]["artifacts"]["linux-x86_64"]["sha256"] == hashlib.sha256(
        archive.read_bytes()
    ).hexdigest()
    assert report["local_validation"]["integrity"] == "verified"
    assert report["local_validation"]["archive_checked_locally"] is True
    assert report["local_validation"]["remote_artifact_verified"] is False
    assert report["local_validation"]["tools_executed"] is False
    assert report["local_validation"]["clean_machine_verified"] is False
    assert report["local_validation"]["tool_sha256"]["mt3-infer"] == hashlib.sha256(
        b"synthetic tool fixture only"
    ).hexdigest()


def test_candidate_does_not_modify_bundled_catalog(tmp_path: Path):
    original = candidate.BUNDLED_CATALOG.read_bytes()
    report = _draft(_archive(tmp_path))
    output = tmp_path / "candidate.json"
    candidate.write_report(report, output)
    loaded = json.loads(output.read_text(encoding="utf-8"))
    assert loaded["candidate"]["redistribution_status"] == "pending"
    assert candidate.BUNDLED_CATALOG.read_bytes() == original

    with pytest.raises(ValueError, match="bundled"):
        candidate.write_report(report, candidate.BUNDLED_CATALOG)
    with pytest.raises(FileExistsError):
        candidate.write_report(report, output)


def test_missing_required_youtube_stack_is_rejected_before_drafting(tmp_path: Path):
    with pytest.raises(ValueError, match="deno,ffprobe"):
        _draft(
            _archive(tmp_path),
            component="youtube_runtime",
            tools={"yt-dlp": "bin/mt3-infer", "ffmpeg": "bin/mt3-infer"},
        )


def test_unsafe_archive_member_is_rejected_without_installing(tmp_path: Path):
    with pytest.raises(ComponentIntegrityError, match="unsafe path"):
        _draft(_archive(tmp_path, member="../outside"))


def test_missing_tool_mapping_is_rejected(tmp_path: Path):
    with pytest.raises(ComponentIntegrityError, match="missing"):
        _draft(
            _archive(tmp_path),
            tools={"mt3-infer": "bin/no-such-file"},
        )


@pytest.mark.parametrize("name,kwargs", [
    ("license", {"license_name": "runtime-specific"}),
    ("provenance", {"provenance": "TBD"}),
    ("upstream_revision", {"upstream_revision": ""}),
    ("target", {"target": "windows-../../etc"}),
    ("component", {"component": "../transcription_engine"}),
    ("url", {"url": "http://example.invalid/unpinned.zip"}),
])
def test_candidate_rejects_missing_evidence_or_unsafe_metadata(
    tmp_path: Path, name: str, kwargs: dict,
):
    with pytest.raises((ValueError, ComponentIntegrityError), match="."):
        _draft(_archive(tmp_path), **kwargs)


def test_corrupt_local_archive_is_rejected(tmp_path: Path):
    invalid = tmp_path / "invalid.zip"
    invalid.write_bytes(b"this is not a ZIP archive")
    with pytest.raises(ComponentIntegrityError, match="malformed or unreadable"):
        _draft(invalid)


def test_candidate_cli_rehearsal_does_not_approve_redistribution(
    tmp_path: Path, monkeypatch, capsys,
):
    archive = _archive(tmp_path)
    output = tmp_path / "draft.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prepare_managed_artifact_candidate.py",
            "--component", "transcription_engine",
            "--target", "linux-x86_64",
            "--version", "0.8-fixture-1",
            "--archive", str(archive),
            "--archive-format", "zip",
            "--url", "https://example.invalid/candidate/fixture.zip",
            "--tool", "mt3-infer=bin/mt3-infer",
            "--license", "Synthetic-fixture-test-only",
            "--provenance", "local CI fixture",
            "--upstream-revision", "synthetic-revision",
            "--output", str(output),
        ],
    )
    assert candidate.main() == 0
    assert "pending redistribution approval" in capsys.readouterr().out
    assert json.loads(output.read_text(encoding="utf-8"))["candidate"][
        "redistribution_status"
    ] == "pending"

"""Offline adversarial tests for research claim provenance and impact reviews."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from scripts import plan_knowledge_update as review
from scripts.audit_knowledge_evidence import audit


def _setup(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path
    raw = root / "docs/knowledge/raw"
    wiki = root / "docs/knowledge/wiki"
    research = root / "docs/research"
    raw.mkdir(parents=True)
    wiki.mkdir(parents=True)
    research.mkdir(parents=True)
    record = raw / "sample-model.md"
    record.write_text(
        "# Source: Sample model\n\n"
        "Accessed: 2026-10-01\n"
        "URL: https://example.org/releases/sample\n"
        "Revision/hash: abcdef123\n"
        "Rights/license: research only\n"
        "Issue: #48\n"
        "Evidence: external-reported\n",
        encoding="utf-8",
    )
    registry = wiki / "source-register.md"
    registry.write_text(
        "# Evidence register\n\n"
        "Status: reviewed; Last reviewed: 2026-10-23\n\n"
        "| Claim | Evidence status | Source record | Validation gap |\n"
        "| --- | --- | --- | --- |\n"
        "| A public model is described, no local result is claimed | external-reported | "
        "[sample](../raw/sample-model.md) | Need licensed real benchmark |\n",
        encoding="utf-8",
    )
    (wiki / "index.md").write_text(
        "# Research index\n\nStatus: reviewed; Last reviewed: 2026-10-23\n"
        "[Register](source-register.md)\n", encoding="utf-8",
    )
    (research / "model-study.md").write_text(
        "# Model study\n\nReview sample model and issue #48\n", encoding="utf-8",
    )
    return root, record, registry


def _codes(tmp_path: Path) -> set[str]:
    return {item.code for item in audit(tmp_path, as_of=date(2026, 11, 5))}


def test_offline_audit_accepts_sourced_claim_and_pinned_revision(tmp_path: Path):
    _setup(tmp_path)
    assert audit(tmp_path, as_of=date(2026, 11, 5)) == []


def test_missing_source_link_is_both_orphan_and_unregistered(tmp_path: Path):
    _, _, registry = _setup(tmp_path)
    registry.write_text(
        registry.read_text(encoding="utf-8").replace(
            "[sample](../raw/sample-model.md)", "[deleted](../raw/missing.md)"
        ),
        encoding="utf-8",
    )
    assert {"orphan-raw-record", "claim-source-not-raw", "unregistered-source"} <= _codes(tmp_path)


def test_missing_claim_evidence_is_blocking(tmp_path: Path):
    _, _, registry = _setup(tmp_path)
    registry.write_text(
        registry.read_text(encoding="utf-8").replace(
            "| external-reported | [sample]", "| hypothesis | [sample]"
        ),
        encoding="utf-8",
    )
    assert "claim-evidence-conflict" in _codes(tmp_path)
    registry.write_text(
        registry.read_text(encoding="utf-8").replace(
            "| hypothesis | [sample]", "| unknown | [sample]"
        ),
        encoding="utf-8",
    )
    assert "claim-evidence-missing" in _codes(tmp_path)


def test_invalid_raw_metadata_and_reproduction_claim_fail_closed(tmp_path: Path):
    _, record, _ = _setup(tmp_path)
    source = record.read_text(encoding="utf-8")
    source = source.replace("Accessed: 2026-10-01", "Accessed: 2026-12-01")
    source = source.replace("Issue: #48", "Issue: unrelated")
    source = source.replace("Evidence: external-reported", "Evidence: reproduced")
    record.write_text(source, encoding="utf-8")
    codes = _codes(tmp_path)
    assert {"future-accessed-date", "missing-issue-link", "missing-reproduction-run"} <= codes


def test_stale_review_emits_warning_without_inventing_new_date(tmp_path: Path):
    _, _, registry = _setup(tmp_path)
    content = registry.read_text(encoding="utf-8")
    registry.write_text(
        content.replace("Last reviewed: 2026-10-23", "Last reviewed: 2026-01-01"),
        encoding="utf-8",
    )
    findings = audit(tmp_path, as_of=date(2026, 11, 5), max_review_age_days=90)
    assert [(x.severity, x.code) for x in findings] == [("warning", "stale-review")]
    assert "2026-01-01" in registry.read_text(encoding="utf-8")


def test_future_review_date_is_error_not_stale_warning(tmp_path: Path):
    _, _, registry = _setup(tmp_path)
    registry.write_text(
        registry.read_text(encoding="utf-8").replace(
            "Last reviewed: 2026-10-23", "Last reviewed: 2026-12-01"
        ),
        encoding="utf-8",
    )
    assert "future-review-date" in _codes(tmp_path)


def test_impact_plan_is_review_only_and_lists_links_and_candidate_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    root, record, _ = _setup(tmp_path)
    monkeypatch.setattr(review, "ROOT", root)
    monkeypatch.setattr(review, "RAW", root / "docs/knowledge/raw")
    before = record.read_bytes()
    result = review.impact(record)
    assert result["automatic_changes"] is False
    assert result["requires_claim_registration"] is False
    assert "docs/knowledge/wiki/source-register.md" in result["referencing_wiki_pages"]
    assert "docs/research/model-study.md" in result["candidate_review_pages"]
    assert "Review plan for docs/knowledge/raw/sample-model.md" in review.plan(record)
    assert record.read_bytes() == before


def test_unregistered_new_source_appears_in_impact_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    root, source, _ = _setup(tmp_path)
    monkeypatch.setattr(review, "ROOT", root)
    monkeypatch.setattr(review, "RAW", root / "docs/knowledge/raw")
    new_record = source.parent / "sample-model-revision-2.md"
    new_record.write_text(
        source.read_text(encoding="utf-8").replace(
            "Revision/hash: abcdef123", "Revision/hash: revision-two"
        ),
        encoding="utf-8",
    )
    result = review.impact(new_record)
    assert result["requires_claim_registration"] is True
    assert "docs/knowledge/raw/sample-model.md" in result["related_raw_records"]
    assert result["automatic_changes"] is False
    with pytest.raises(ValueError, match="existing raw record"):
        review.impact(root / "outside.md")

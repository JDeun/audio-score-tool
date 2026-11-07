"""Source schema v2 regression: scope/comparability and append-only governance."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from scripts import ingest_knowledge_source as ingest
from scripts.audit_knowledge_evidence import audit


def _repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    root = tmp_path
    raw = root / "docs/knowledge/raw"
    wiki = root / "docs/knowledge/wiki"
    raw.mkdir(parents=True)
    wiki.mkdir(parents=True)
    monkeypatch.setattr(ingest, "RAW", raw)
    (wiki / "source-register.md").write_text(
        "# Evidence register\n\nStatus: reviewed; Last reviewed: 2026-10-23\n\n"
        "| Claim | Evidence status | Source record | Validation gap |\n"
        "| --- | --- | --- | --- |\n"
        "| External public source is catalogued only | external-reported | "
        "[sample](../raw/source-v2.md) | Independent source revision not verified |\n",
        encoding="utf-8",
    )
    (wiki / "index.md").write_text(
        "# Wiki index\n\nStatus: reviewed; Last reviewed: 2026-10-23\n"
        "[Register](source-register.md)\n", encoding="utf-8",
    )
    return root, raw


def test_new_source_requires_scope_and_benchmark_comparability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    root, _ = _repo(tmp_path, monkeypatch)
    record = ingest.register(
        "source-v2", "https://example.org/paper", "abcd123",
        "not-licensed-for-redistribution", "#44",
        scope="AMT-public-paper-metadata", comparability="not-comparable",
    )
    content = record.read_text(encoding="utf-8")
    assert "Record schema: 2" in content
    assert "Scope: AMT-public-paper-metadata" in content
    assert "Benchmark comparability: not-comparable" in content
    assert "Evidence: external-reported" in content
    # Registration uses today's UTC date; an earlier hardcoded audit date
    # started producing false failures the following calendar day.
    accessed = next(line.split(": ", 1)[1] for line in content.splitlines()
                    if line.startswith("Accessed: "))
    assert not [x for x in audit(root, as_of=date.fromisoformat(accessed))
                if x.severity == "error"]
    before = record.read_bytes()
    with pytest.raises(FileExistsError):
        ingest.register(
            "source-v2", "https://example.org/new", "abcd123",
            "unverified", "#44",
        )
    assert record.read_bytes() == before


def test_missing_v2_scope_is_blocked_in_auditor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    root, _ = _repo(tmp_path, monkeypatch)
    record = ingest.register(
        "source-v2", "https://example.org/source", "abc123", "unverified", "#44",
    )
    content = record.read_text(encoding="utf-8")
    record.write_text(content.replace("Scope: metadata-only\n", ""), encoding="utf-8")
    findings = audit(root, as_of=date(2026, 11, 6))
    assert "missing-v2-provenance" in [x.code for x in findings]


@pytest.mark.parametrize(("issue", "url", "scope", "comparability"), [
    ("unlinked", "https://example.org", "ok", "unknown"),
    ("#44", "http://example.org", "ok", "unknown"),
    ("#44", "https://user:password@example.org", "ok", "unknown"),
    ("#44", "https://example.org", "injected\nEvidence: reproduced", "unknown"),
    ("#44", "https://example.org", "ok", "same-corpus-verified"),
])
def test_unsafe_or_unverified_registration_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    issue: str, url: str, scope: str, comparability: str,
):
    _repo(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        ingest.register(
            "source-v2", url, "abc123", "unverified", issue,
            scope=scope, comparability=comparability,
        )


def test_reproduced_requires_verifiable_run_reference_syntax(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    _repo(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="Run URL"):
        ingest.register(
            "source-v2", "https://example.org", "abc123", "unverified", "#44",
            evidence="reproduced",
        )
    with pytest.raises(ValueError, match="Run URL"):
        ingest.register(
            "source-v2", "https://example.org", "abc123", "unverified", "#44",
            evidence="reproduced", run="locally-successful",
        )


def test_legacy_v1_records_are_not_modified_by_new_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    root, raw = _repo(tmp_path, monkeypatch)
    old = raw / "source-v2.md"
    old.write_text(
        "# Source: source-v2\n\nAccessed: 2026-10-23\n"
        "URL: https://example.org\nRevision/hash: unknown\n"
        "Rights/license: unverified\nIssue: #44\n"
        "Evidence: external-reported\n", encoding="utf-8",
    )
    previous = old.read_bytes()
    findings = audit(root, as_of=date(2026, 11, 6))
    assert not [x for x in findings if x.severity == "error"]
    assert old.read_bytes() == previous

"""Regression tests for offline knowledge wiki tooling."""

from pathlib import Path

import pytest

from scripts.check_knowledge_wiki import validate
from scripts.ingest_knowledge_source import register
from scripts.plan_knowledge_update import plan
from scripts.query_knowledge import search


def test_wiki_structure() -> None:
    assert validate() == []


def test_local_query() -> None:
    assert any("SheetSage2" in excerpt for _, _, excerpt in search("SheetSage2"))


def test_ingest_append_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.ingest_knowledge_source as ingest

    monkeypatch.setattr(ingest, "RAW", tmp_path)
    path = register("test-source", "https://example.org/source", "abc", "unverified", "#44")
    assert "Revision/hash: abc" in path.read_text(encoding="utf-8")
    with pytest.raises(FileExistsError):
        register("test-source", "https://example.org/source", "abc", "unverified", "#44")


def test_plan_rejects_outside_raw(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        plan(tmp_path / "missing.md")

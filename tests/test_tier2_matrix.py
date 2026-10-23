from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.run_tier2_matrix import plan


def test_committed_matrix_has_unique_valid_stages() -> None:
    matrix = json.loads(Path("benchmarks/tier2/experiment-matrix.json").read_text(encoding="utf-8"))
    stages = plan(matrix, include_blocked=True)
    assert len(stages) >= 7
    assert any(s["kind"] == "hybrid" for s in stages)
    assert any(s["enabled"] for s in stages)
    assert all(s.get("blocked_reason") for s in stages if not s.get("enabled"))


def test_non_amt_stage_cannot_run_without_adapter() -> None:
    with pytest.raises(ValueError, match="adapter"):
        plan({"schema_version": 1, "stages": [{"id": "hybrid", "kind": "hybrid", "enabled": True}]})


def test_duplicate_or_unsafe_stage_rejected() -> None:
    with pytest.raises(ValueError, match="unsafe"):
        plan({"schema_version": 1, "stages": [{"id": "../escape", "kind": "amt", "enabled": False}]})
    with pytest.raises(ValueError, match="duplicate"):
        plan({"schema_version": 1, "stages": [{"id": "a", "kind": "amt"}, {"id": "a", "kind": "amt"}]})



def test_dry_run_writes_explicit_blocked_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    from scripts import run_tier2_matrix

    monkeypatch.setattr(sys, "argv", [
        "run_tier2_matrix.py",
        "--dry-run",
        "--output-root",
        str(tmp_path),
    ])
    assert run_tier2_matrix.main() == 0
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["completed"] == 0
    assert summary["blocked"] >= 1
    assert any(item["id"] == "yourmt3" and item["status"] == "planned" for item in summary["results"])


def test_dry_run_strict_mode_rejects_blocked_combinations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    from scripts import run_tier2_matrix

    monkeypatch.setattr(sys, "argv", [
        "run_tier2_matrix.py", "--dry-run", "--fail-on-blocked",
        "--output-root", str(tmp_path),
    ])
    assert run_tier2_matrix.main() == 1

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

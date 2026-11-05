"""Regression tests for PR/CI history with no network or model execution."""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.audit_research_history import HISTORY, validate_history


def _history() -> dict:
    return json.loads(HISTORY.read_text(encoding="utf-8"))


def test_committed_historical_history_passes_shape_audit():
    result = validate_history(_history())
    assert result["verified_shape_and_links"] == 8
    assert result["real_audio_quality_validated"] is False
    assert result["commercial_release_approved"] is False
    assert result["remote_github_state_rechecked"] is False


def test_duplicate_pr_or_run_is_rejected():
    for field in ("pr_number", "ci_run_id"):
        payload = _history()
        payload["entries"][1][field] = payload["entries"][0][field]
        with pytest.raises(ValueError, match="duplicate"):
            validate_history(payload)


@pytest.mark.parametrize(("field", "wrong"), [
    ("merge_sha", "z" * 40),
    ("ci_head_sha", "a" * 32),
    ("pr_url", "https://other.org/forged"),
    ("ci_url", "https://evil.invalid/actions/runs/1"),
    ("evidence_level", "model-performance-approved"),
    ("ci_conclusion", "skipped"),
    ("musical_quality_validated", True),
    ("commercial_release_approved", True),
])
def test_forged_history_metadata_fails_closed(field: str, wrong: object):
    payload = _history()
    payload["entries"][0][field] = wrong
    with pytest.raises(ValueError):
        validate_history(payload)


def test_future_merge_timestamp_is_never_accepted():
    payload = _history()
    payload["entries"][0]["merged_at_utc"] = "2099-01-01T00:00:00Z"
    with pytest.raises(ValueError, match="future"):
        validate_history(payload, now=datetime(2026, 11, 6, tzinfo=timezone.utc))


def test_missing_review_gaps_and_unsorted_prs_fail_closed():
    payload = _history()
    payload["entries"][0]["remaining_validation"] = ""
    with pytest.raises(ValueError, match="validation gaps"):
        validate_history(payload)
    payload = _history()
    payload["entries"][0], payload["entries"][1] = payload["entries"][1], payload["entries"][0]
    with pytest.raises(ValueError, match="ordered"):
        validate_history(payload)


def test_offline_audit_does_not_modify_tracked_history():
    before = Path(HISTORY).read_bytes()
    payload = copy.deepcopy(_history())
    assert validate_history(payload)["verified_shape_and_links"] == 8
    assert Path(HISTORY).read_bytes() == before

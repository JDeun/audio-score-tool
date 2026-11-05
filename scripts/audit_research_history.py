"""Validate an offline, deliberately limited historical PR/CI evidence register.

This checks JSON shape and internal consistency only. It cannot independently
query GitHub, authenticate historical logs, establish real-audio accuracy, or
approve licenses. Source PR/CI links are immutable review starting points.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HISTORY = ROOT / "docs/research/IMPLEMENTATION_EVIDENCE_2026.json"
HASH = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY = "JDeun/audio-score-tool"
LEVEL = "implementation-ci-only"


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("merged_at_utc requires UTC ISO 8601 with Z")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid merged_at_utc") from exc
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("merged_at_utc must be UTC")
    return parsed


def validate_history(payload: dict, *, now: datetime | None = None) -> dict:
    """No network. Return explicit evidence limitations instead of verdicts."""
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("history requires schema_version=1")
    if (payload.get("repository") != REPOSITORY
            or payload.get("purpose") != "historical-code-implementation-evidence"):
        raise ValueError("unexpected repository or research evidence purpose")
    reviewed = payload.get("review_date_kst")
    try:
        if not isinstance(reviewed, str):
            raise ValueError("review_date_kst must be a valid date")
        date.fromisoformat(reviewed)
    except ValueError as exc:
        raise ValueError("invalid review_date_kst") from exc
    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ValueError("historical source entries must be a nonempty array")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("validation clock must be timezone aware")

    prs: set[int] = set()
    runs: set[int] = set()
    for index, item in enumerate(entries):
        if not isinstance(item, dict):
            raise ValueError(f"history entry {index} must be an object")
        number, run = item.get("pr_number"), item.get("ci_run_id")
        if (isinstance(number, bool) or not isinstance(number, int) or number <= 0
                or number in prs):
            raise ValueError("invalid or duplicate PR number")
        if (isinstance(run, bool) or not isinstance(run, int) or run <= 0
                or run in runs):
            raise ValueError("invalid or duplicate Actions run ID")
        prs.add(number)
        runs.add(run)
        for field in ("merge_sha", "ci_head_sha"):
            if not isinstance(item.get(field), str) or not HASH.fullmatch(item[field]):
                raise ValueError(f"invalid {field} in PR #{number}")
        merged = _timestamp(item.get("merged_at_utc"))
        if merged > now:
            raise ValueError(f"PR #{number} has a future merge timestamp")
        if item.get("pr_url") != f"https://github.com/{REPOSITORY}/pull/{number}":
            raise ValueError(f"PR #{number} has a noncanonical source URL")
        if item.get("ci_url") != f"https://github.com/{REPOSITORY}/actions/runs/{run}":
            raise ValueError(f"PR #{number} has a noncanonical run URL")
        if item.get("ci_workflow") != "CI" or item.get("ci_conclusion") != "success":
            raise ValueError("only independently observed successful CI runs may be listed")
        if item.get("evidence_level") != LEVEL:
            raise ValueError("implementation evidence cannot be promoted to accuracy evidence")
        if item.get("musical_quality_validated") is not False:
            raise ValueError("historical CI cannot assert musical quality acceptance")
        if item.get("commercial_release_approved") is not False:
            raise ValueError("historical CI cannot assert commercial release approval")
        if (not isinstance(item.get("title"), str) or not item["title"].strip()
                or not isinstance(item.get("remaining_validation"), str)
                or len(item["remaining_validation"].strip()) < 12):
            raise ValueError("every historical entry must state title and validation gaps")
    ordered = [entry["pr_number"] for entry in entries]
    if ordered != sorted(ordered):
        raise ValueError("entries must be ordered by PR number")
    return {
        "schema_version": 1,
        "verified_shape_and_links": len(entries),
        "remote_github_state_rechecked": False,
        "real_audio_quality_validated": False,
        "commercial_release_approved": False,
        "note": "Source URLs and hashes were checked at authoring; this offline audit only validates the committed ledger shape.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check pinned PR/CI history consistency offline")
    parser.add_argument("--history", type=Path, default=HISTORY)
    args = parser.parse_args()
    payload = json.loads(args.history.read_text(encoding="utf-8"))
    print(json.dumps(validate_history(payload), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

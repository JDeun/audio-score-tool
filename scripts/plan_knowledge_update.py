"""Print a review-only update checklist for a registered source record."""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "docs/knowledge/raw"


def plan(path: Path) -> str:
    resolved = path.resolve()
    if not resolved.is_relative_to(RAW) or not resolved.is_file():
        raise ValueError("source must be an existing raw record")
    record = resolved.read_text(encoding="utf-8")
    return (
        f"Review plan for {resolved.relative_to(ROOT)}\n"
        "- Verify URL, revision, rights, issue and evidence status\n"
        "- Compare with existing wiki claims and canonical research\n"
        "- Update relevant wiki page, index and append-only log via PR\n"
        "- Flag contradictions; do not auto-change accepted ADRs or model defaults\n"
        f"\nSource excerpt:\n{record[:600]}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    print(plan(args.source))

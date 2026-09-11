from __future__ import annotations

import argparse
import json
from pathlib import Path

from audio_score_tool.tier2_compare import compare_tier2_reports, write_comparison


def main() -> int:
    parser = argparse.ArgumentParser(description="Rank Tier 2 engine reports for baseline review.")
    parser.add_argument("reports", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, default=Path("tier2-comparison.json"))
    args = parser.parse_args()

    payload = compare_tier2_reports(args.reports)
    write_comparison(args.output, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["recommended_engine"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

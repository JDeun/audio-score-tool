"""Verify a Tier 2 run's recorded stage, corpus and artifact checksums.

Examples:
  uv run --frozen python scripts/validate_tier2_experiment.py \
      --predictions-root /secure/tier2/yourmt3 \
      --manifest /secure/tier2/manifest.json

  uv run --frozen python scripts/validate_tier2_experiment.py \
      --predictions-root /secure/tier2/yourmt3+sheetsage2 \
      --manifest /secure/tier2/manifest.json \
      --events-root /secure/tier2/sheetsage2
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from audio_score_tool.tier2_experiment_record import validate_tier2_experiment_record


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a recorded Tier 2 experiment")
    parser.add_argument("--predictions-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--events-root", type=Path)
    args = parser.parse_args()
    report = validate_tier2_experiment_record(
        args.predictions_root,
        manifest_path=args.manifest,
        events_root=args.events_root,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

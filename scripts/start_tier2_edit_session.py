from __future__ import annotations

import argparse
import json
from pathlib import Path

from audio_score_tool.benchmark_edit_telemetry import start_edit_session


def main() -> int:
    parser = argparse.ArgumentParser(description="Start an opt-in Tier 2 human-edit telemetry session.")
    parser.add_argument("case_id")
    parser.add_argument("--song-id")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    payload = start_edit_session(args.output, case_id=args.case_id, song_id=args.song_id)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print()
    print(f"Launch AudioScoreTool with AST_TIER2_TELEMETRY_FILE={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

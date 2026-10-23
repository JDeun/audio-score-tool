from __future__ import annotations

import argparse
import json
from pathlib import Path

from audio_score_tool.sheetsage_hybrid import (
    merge_sheetsage_musicxml,
    run_sheetsage_adapter,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="SheetSage2 lead-sheet analysis and AMT hybrid export")
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--amt-musicxml", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--adapter-command", help="Reviewed external SheetSage2 executable")
    parser.add_argument("--reuse-events", action="store_true")
    parser.add_argument("--bpm", type=float, default=120.0)
    args = parser.parse_args()
    if not args.reuse_events:
        run_sheetsage_adapter(args.audio, args.events, command=args.adapter_command)
    report = merge_sheetsage_musicxml(
        args.amt_musicxml, args.events, args.output, bpm=args.bpm,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

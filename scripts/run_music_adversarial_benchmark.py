from __future__ import annotations

import argparse
import json
from pathlib import Path

from audio_score_tool.music_adversarial_benchmark import (
    run_music_adversarial_benchmark,
    write_music_adversarial_report,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run AudioScoreTool's deterministic music adversarial benchmark.")
    parser.add_argument("--output", type=Path, help="Optional JSON report output path.")
    parser.add_argument("--json", action="store_true", help="Print the complete JSON report.")
    args = parser.parse_args()

    report = run_music_adversarial_benchmark()
    payload = report.as_dict()
    if args.output:
        write_music_adversarial_report(args.output, report)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("Music Adversarial Benchmark")
        print(f"overall={report.overall_score:.4f} passed={report.passed}")
        for category, score in report.category_scores.items():
            print(f"  {category}: {score:.4f} (min {report.thresholds[category]:.2f})")
        for case in report.cases:
            marker = "PASS" if case.passed else "FAIL"
            print(f"  [{marker}] {case.name}: {case.score:.4f}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

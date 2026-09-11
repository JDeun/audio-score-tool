from __future__ import annotations

import argparse
import json
from pathlib import Path

from audio_score_tool.tier2_benchmark import (
    Tier2EngineIdentity,
    run_tier2_benchmark,
    write_tier2_report,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate a private Tier 2 real-music corpus.")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--predictions-root", type=Path, required=True)
    parser.add_argument("--engine-id", required=True)
    parser.add_argument("--model-revision", required=True)
    parser.add_argument("--runtime-revision", required=True)
    parser.add_argument("--artifact-sha256", required=True)
    parser.add_argument("--output", type=Path, default=Path("tier2-report.json"))
    args = parser.parse_args()

    report = run_tier2_benchmark(
        args.manifest,
        corpus_root=args.corpus_root,
        predictions_root=args.predictions_root,
        engine=Tier2EngineIdentity(
            id=args.engine_id,
            model_revision=args.model_revision,
            runtime_revision=args.runtime_revision,
            artifact_sha256=args.artifact_sha256,
        ),
    )
    write_tier2_report(args.output, report)
    print(json.dumps(report.summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

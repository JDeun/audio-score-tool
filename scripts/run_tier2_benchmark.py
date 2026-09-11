from __future__ import annotations

import argparse
import json
from pathlib import Path

from audio_score_tool.tier2_benchmark import load_manifest, run_tier2_benchmark, write_tier2_report
from audio_score_tool.tier2_prediction import load_tier2_prediction_provenance


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate a private Tier 2 real-music corpus.")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--predictions-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("tier2-report.json"))
    args = parser.parse_args()

    corpus_version, cases = load_manifest(args.manifest)
    provenance_corpus, engine, case_ids, _ = load_tier2_prediction_provenance(args.predictions_root)
    expected_case_ids = tuple(case.id for case in cases)
    if provenance_corpus != corpus_version:
        raise ValueError(
            f"prediction provenance corpus mismatch: {provenance_corpus} != {corpus_version}"
        )
    if case_ids != expected_case_ids:
        raise ValueError("prediction provenance case_ids do not match the benchmark manifest")

    report = run_tier2_benchmark(
        args.manifest,
        corpus_root=args.corpus_root,
        predictions_root=args.predictions_root,
        engine=engine,
    )
    write_tier2_report(args.output, report)
    print(json.dumps(report.summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

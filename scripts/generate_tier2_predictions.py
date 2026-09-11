from __future__ import annotations

import argparse
import json
from pathlib import Path

from audio_score_tool.tier2_prediction import generate_tier2_predictions


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Tier 2 AMT predictions.")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--predictions-root", type=Path, required=True)
    parser.add_argument("--engine", required=True, choices=["mt3_infer", "yourmt3", "muscriptor", "native"])
    parser.add_argument("--model")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    generated = generate_tier2_predictions(
        args.manifest,
        corpus_root=args.corpus_root,
        predictions_root=args.predictions_root,
        engine_id=args.engine,
        model=args.model,
        device=args.device,
    )
    payload = {"generated": generated, "case_count": len(generated)}
    encoded = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

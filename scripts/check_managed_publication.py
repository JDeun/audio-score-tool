from __future__ import annotations

import argparse
import json
from pathlib import Path

from audio_score_tool.managed_publication_readiness import (
    CORE_COMPONENTS,
    OPTIONAL_COMPONENTS,
    STABLE_TARGETS,
    publication_readiness,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check managed-component publication readiness.")
    parser.add_argument(
        "--include-optional",
        action="store_true",
        help="Require optional OMR/WhisperX/audio-validation components too.",
    )
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="Exit non-zero unless every requested component/target is publication-ready.",
    )
    parser.add_argument("--output", help="Optional JSON report path.")
    args = parser.parse_args()

    components = CORE_COMPONENTS + OPTIONAL_COMPONENTS if args.include_optional else CORE_COMPONENTS
    report = publication_readiness(components=components, targets=STABLE_TARGETS)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
    print(rendered)
    if args.require_ready and not report["ready"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
from pathlib import Path

from audio_score_tool.v1_release_readiness import assert_v1_release_ready
from scripts.verify_release_versions import verify_versions

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify AudioScoreTool v1 release readiness.")
    parser.add_argument("--tag", help="Release tag, for example v1.0.0-rc.1")
    args = parser.parse_args()

    version = verify_versions(tag=args.tag) if args.tag else verify_versions()
    report = assert_v1_release_ready(repository_root=ROOT)
    payload = {"version": version, **report}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

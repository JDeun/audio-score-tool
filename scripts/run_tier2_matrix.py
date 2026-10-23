from __future__ import annotations

import argparse
import hashlib
import json
import time
import os
import subprocess
import sys
from pathlib import Path


def plan(matrix: dict, *, include_blocked: bool = False) -> list[dict]:
    stages = matrix.get("stages")
    if matrix.get("schema_version") != 1 or not isinstance(stages, list) or not stages:
        raise ValueError("invalid experiment matrix")
    ids: set[str] = set()
    for stage in stages:
        if not isinstance(stage, dict) or not isinstance(stage.get("id"), str):
            raise ValueError("invalid stage")
        if stage["id"] in ids or "/" in stage["id"] or ".." in stage["id"]:
            raise ValueError("duplicate or unsafe stage ID")
        ids.add(stage["id"])
        if stage.get("kind") not in ("amt", "analysis", "hybrid"):
            raise ValueError("invalid stage kind")
        if stage.get("enabled") and stage.get("kind") != "amt":
            raise ValueError("non-AMT stage needs a real adapter before enabling")
        if stage.get("enabled") and (not stage.get("engine") or not stage.get("model")):
            raise ValueError("enabled AMT stage needs engine and model")
    return stages if include_blocked else [s for s in stages if s.get("enabled")]


def main() -> int:
    parser = argparse.ArgumentParser(description="Sequential Tier 2 model experiment runner")
    parser.add_argument("--matrix", type=Path, default=Path("benchmarks/tier2/experiment-matrix.json"))
    parser.add_argument("--manifest", type=Path, default=Path("benchmarks/tier2/manifest.json"))
    parser.add_argument("--corpus-root", type=Path)
    parser.add_argument("--output-root", type=Path, default=Path("tier2-results"))
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--fail-on-blocked", action="store_true",
        help="Require every listed combination to be executable",
    )
    args = parser.parse_args()

    stages = plan(json.loads(args.matrix.read_text(encoding="utf-8")), include_blocked=True)
    if not args.dry_run:
        if not args.manifest.is_file() or not args.corpus_root or not args.corpus_root.is_dir():
            parser.error("real manifest and accessible --corpus-root are required (no synthetic results)")
    args.output_root.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    if not args.dry_run:
        from audio_score_tool.tier2_benchmark import load_manifest, resolve_locator
        _, cases = load_manifest(args.manifest)
        for case in cases:
            if (
                case.audio_locator is None
                or not resolve_locator(case.audio_locator, corpus_root=args.corpus_root).is_file()
            ):
                parser.error(f"missing real audio for case {case.id}")
    reports: list[Path] = []
    for stage in stages:
        item = {"id": stage["id"], "kind": stage["kind"]}
        if not stage.get("enabled"):
            item.update(status="blocked", reason=stage.get("blocked_reason", "not implemented"))
        elif args.dry_run:
            item["status"] = "planned"
        else:
            prefix = "TIER2_" + stage["id"].upper().replace("-", "_").replace("+", "_")
            revision = os.environ.get(prefix + "_MODEL_REVISION")
            runtime = os.environ.get(prefix + "_RUNTIME_REVISION")
            checksum = os.environ.get(prefix + "_ARTIFACT_SHA256")
            if (
                not revision or not runtime or not checksum or len(checksum) != 64
                or any(c not in "0123456789abcdefABCDEF" for c in checksum)
            ):
                item.update(
                    status="blocked",
                    reason=f"missing pinned {prefix}_MODEL_REVISION/RUNTIME_REVISION/ARTIFACT_SHA256",
                )
            else:
                prediction_root = args.output_root / stage["id"]
                report = args.output_root / (stage["id"] + "-report.json")
                generate = [sys.executable, "scripts/generate_tier2_predictions.py", str(args.manifest),
                    "--corpus-root", str(args.corpus_root), "--predictions-root", str(prediction_root),
                    "--engine", stage["engine"], "--model", stage["model"], "--model-revision", revision,
                    "--runtime-revision", runtime, "--artifact-sha256", checksum, "--device", args.device]
                evaluate = [sys.executable, "scripts/run_tier2_benchmark.py", str(args.manifest),
                    "--corpus-root", str(args.corpus_root), "--predictions-root", str(prediction_root),
                    "--output", str(report)]
                started = time.monotonic()
                try:
                    subprocess.run(generate, check=True)
                    subprocess.run(evaluate, check=True)
                except subprocess.CalledProcessError as exc:
                    item.update(status="failed", reason=f"command exited {exc.returncode}")
                else:
                    item.update(
                        status="completed", report=str(report),
                        report_sha256=hashlib.sha256(report.read_bytes()).hexdigest(),
                    )
                    reports.append(report)
                finally:
                    item["elapsed_seconds"] = round(time.monotonic() - started, 3)
        results.append(item)
        print(json.dumps(item, ensure_ascii=False), flush=True)

    if len(reports) >= 2:
        try:
            subprocess.run(
                [sys.executable, "scripts/compare_tier2_reports.py", *map(str, reports),
                 "--output", str(args.output_root / "comparison.json")], check=True,
            )
        except subprocess.CalledProcessError:
            results.append({"id": "comparison", "status": "failed"})
    summary = {
        "schema_version": 1, "results": results, "completed": len(reports),
        "blocked": sum(r["status"] == "blocked" for r in results),
    }
    (args.output_root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "
", encoding="utf-8",
    )
    has_failure = any(r["status"] == "failed" for r in results)
    has_blocked = any(r["status"] == "blocked" for r in results)
    return 1 if has_failure or (args.fail_on_blocked and has_blocked) else 0


if __name__ == "__main__":
    raise SystemExit(main())

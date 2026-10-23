from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
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
        if stage.get("enabled") and stage.get("kind") == "analysis":
            raise ValueError("analysis stage requires a separately reviewed inference runner")
        if stage.get("enabled") and stage.get("kind") == "hybrid":
            if not stage.get("base_stage"):
                raise ValueError("hybrid stage needs base_stage")
        if stage.get("enabled") and stage.get("kind") == "amt" and (not stage.get("engine") or not stage.get("model")):
            raise ValueError("enabled AMT stage needs engine and model")
    positions = {stage["id"]: index for index, stage in enumerate(stages)}
    for index, stage in enumerate(stages):
        if stage["kind"] == "hybrid":
            base = stage.get("base_stage")
            if base not in positions or positions[base] >= index:
                raise ValueError("hybrid base_stage must refer to an earlier stage")
            if stages[positions[base]]["kind"] != "amt":
                raise ValueError("hybrid base_stage must refer to an AMT stage")
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
    completed_stages: set[str] = set()
    for stage in stages:
        item = {"id": stage["id"], "kind": stage["kind"]}
        if not stage.get("enabled"):
            item.update(status="blocked", reason=stage.get("blocked_reason", "not implemented"))
        elif args.dry_run:
            item["status"] = "planned"
        elif stage["kind"] == "hybrid" and stage["base_stage"] not in completed_stages:
            item.update(status="blocked", reason="base stage not completed: " + stage["base_stage"])
        elif stage["kind"] == "hybrid":
            from audio_score_tool.sheetsage_hybrid import (
                merge_sheetsage_musicxml,
                run_sheetsage_adapter,
            )

            base = args.output_root / stage["base_stage"]
            prediction_root = args.output_root / stage["id"]
            report = args.output_root / (stage["id"] + "-report.json")
            started = time.monotonic()
            try:
                prediction_root.mkdir(parents=True, exist_ok=True)
                for case in cases:
                    midi = base / f"{case.id}.mid"
                    musicxml = base / f"{case.id}.musicxml"
                    events = args.output_root / "sheetsage2" / f"{case.id}.json"
                    if not (midi.is_file() and musicxml.is_file()):
                        raise FileNotFoundError(f"missing AMT artifact: {case.id}")
                    if not events.is_file():
                        if not os.environ.get("AST_SHEETSAGE2_ADAPTER"):
                            raise FileNotFoundError(f"missing SheetSage2 events: {case.id}")
                        audio = resolve_locator(case.audio_locator, corpus_root=args.corpus_root)
                        run_sheetsage_adapter(audio, events)
                    shutil.copy2(midi, prediction_root / midi.name)
                    merge_sheetsage_musicxml(
                        musicxml, events, prediction_root / musicxml.name,
                        bpm=float(stage.get("bpm", 120)),
                    )
                subprocess.run(
                    [sys.executable, "scripts/run_tier2_benchmark.py", str(args.manifest),
                     "--corpus-root", str(args.corpus_root),
                     "--predictions-root", str(prediction_root), "--output", str(report)],
                    check=True,
                )
            except (OSError, ValueError, subprocess.CalledProcessError) as exc:
                item.update(status="failed", reason=str(exc))
            else:
                item.update(
                    status="completed", report=str(report),
                    report_sha256=hashlib.sha256(report.read_bytes()).hexdigest(),
                )
                reports.append(report)
                completed_stages.add(stage['id'])
            finally:
                item["elapsed_seconds"] = round(time.monotonic() - started, 3)
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
                    completed_stages.add(stage['id'])
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
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    has_failure = any(r["status"] == "failed" for r in results)
    has_blocked = any(r["status"] == "blocked" for r in results)
    return 1 if has_failure or (args.fail_on_blocked and has_blocked) else 0


if __name__ == "__main__":
    raise SystemExit(main())

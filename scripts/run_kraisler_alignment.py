"""Run fixed-six source correspondence before reading previous gate outcomes.

This standard-library diagnostic acquires metadata only. Completion means six
diagnostics and conditional ledgers were processed; it does not imply that a
clock or score/performance correspondence was admitted.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import json
import os
import platform
import subprocess
import time
import traceback
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Callable

from scripts import kraisler_alignment_source as source

ROOT = Path(__file__).resolve().parents[1]
PLANNED_IDS = ("02", "19", "08", "12", "05", "06")
PREVIOUS_RECEIPT = ROOT / "docs/research/receipts/kraisler-gate-43184102838.zip"
PREVIOUS_ZIP_SHA256 = "ba88b9bda70d4a560a3d05c85ea5301d2e8ff98ea81746d676a1c6695898e10e"
PREVIOUS_REPORT_SHA256 = "e79ff94736b471da64638a93456ef4f1510750c843960ae924fc1f488ad2f754"
MAX_COMPONENT_BYTES = 1_000_000
MAX_REPORT_BYTES = 8_000_000
NEW_SOURCE_PATHS = (
    "scripts/run_kraisler_alignment.py",
    "scripts/kraisler_alignment_source.py",
    "scripts/kraisler_alignment_manifest.json",
    "scripts/kraisler_score.py",
    "scripts/kraisler_match.py",
    "scripts/kraisler_correspondence.py",
    "tests/test_run_kraisler_alignment.py",
    "tests/test_kraisler_alignment_source.py",
    "tests/test_kraisler_score.py",
    "tests/test_kraisler_match.py",
    "tests/test_kraisler_correspondence.py",
    "scripts/research_test_manifest.json",
    "docs/research/KRAISLER_ALIGNMENT_PROTOCOL_2026-11-12.md",
    ".github/workflows/cpu-kraisler-alignment.yml",
)
FROZEN_SOURCE_SHA256 = {
    **source.FROZEN_SOURCE_SHA256,
    "scripts/audio_gate_attribution.py": "99b3c494b59fbb0725cc9dd4cd25665a777c93d1516ba6e5a13eb238ddf65cea",
    "scripts/audio_gate_rest.py": "05f239835c2bee14e40cb059b68bad35c7c5a79f247c3d616677c501161fff73",
    "scripts/run_cpu_vocadito_candidates.py": "0265be97c1f891816da30e75fa145a58a1972636a5729fcb1ccc761665c52465",
    "scripts/run_offset_tail_probe.py": "44730f903b4e8eddc1755ff0ae89793052c43abc129f15028b91b0d16562939e",
    "scripts/vocadito_reference.py": "2ee6f18518e0f4887b9f0c163fff6cfcb964a05d21da1eddd6fcf8e031259194",
    "scripts/vocal_recovery.py": "9cbc4c1e635b78263c46473d357fa928350fabdf3efcab79ec44a42e00fa246b",
    "scripts/offset_tail_evidence.py": "5adb61edca4b68deac9a0f9f6f619009d8295f006a5913b9f14c6a30f6ce0b4c",
    "src/audio_score_tool/metrics.py": "476fdb3dcebf8660a83b258263a2719193590eee5135d40f79b87ceab313df4f",
    "scripts/run_kraisler_gate.py": "57b23a975bb8f4a64858c8f034c8a66c50def91053a72004717b815114fe700a",
    "scripts/kraisler_gate_eval.py": "ea664ad392d61a12a52b98dcb3987d4bad62ad8d2dbd2aa34301b669434695bf",
    "docs/research/KRAISLER_GATE_PROTOCOL_2026-11-12.md":
        "bfbe4bce2335f1b942f7f55a9c855c8f87657ba4ec8efa5f4ac040981b0e0c1d",
    ".github/workflows/cpu-kraisler-gate.yml":
        "15a408d208567cb4c9ff272460ab2dfc0d937730741e61b8efb061ec12cec705",
}
ACQUISITION_FIELDS = (
    "status", "dataset", "record_id", "manifest_sha256", "frozen_source_sha256",
    "central_directory_sha256", "metadata_region_sha256", "network_bytes",
    "http_range_requests", "cache_hits", "metadata_region_cache_hit",
    "verified_member_count", "full_archive_downloaded", "full_archive_md5_verified",
    "media_acquired",
)


@dataclass(frozen=True)
class Dependencies:
    acquire_sources: Callable
    load_gate_manifest: Callable
    parse_score: Callable
    parse_piano_match: Callable
    analyze_correspondence: Callable
    read_previous_receipt: Callable
    attribute_previous_case: Callable
    summarize_cases: Callable


def _dependencies():
    from scripts.kraisler_correspondence import (
        analyze_correspondence,
        attribute_previous_case,
        read_previous_receipt,
        summarize_cases,
    )
    from scripts.kraisler_match import parse_piano_match
    from scripts.kraisler_score import parse_score

    return Dependencies(source.acquire_alignment_sources, source.frozen.load_manifest,
                        parse_score, parse_piano_match, analyze_correspondence,
                        read_previous_receipt, attribute_previous_case, summarize_cases)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def save(path, report):
    raw = _encoded(report)
    if len(raw) > MAX_REPORT_BYTES:
        raise ValueError("public report exceeds bounded metadata budget")
    source.frozen._write_atomic(path, raw)


def _safe_path(path):
    path = Path(path).absolute()
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("private work/report/cache paths must not contain symlinks")
    return path.resolve()


def _prepare_paths(work, output, source_cache):
    work, output = _safe_path(work), _safe_path(output)
    if (work.exists() or output.exists() or work.is_relative_to(ROOT)
            or output.is_relative_to(ROOT) or output.is_relative_to(work)
            or work.is_relative_to(output)):
        raise ValueError("fresh separate work/report paths outside repository required")
    cache = _safe_path(source_cache) if source_cache is not None else None
    if cache is not None and (not cache.is_dir() or cache.is_relative_to(ROOT)
                              or cache.is_relative_to(work) or work.is_relative_to(cache)
                              or output.is_relative_to(cache) or cache.is_relative_to(output)):
        raise ValueError("existing separate source cache outside repository required")
    work.mkdir(parents=True, mode=0o700)
    return work, output, cache


def validate_frozen_sources():
    for relative, expected in FROZEN_SOURCE_SHA256.items():
        path = ROOT / relative
        if path.is_symlink() or not path.is_file() or digest(path.read_bytes()) != expected:
            raise ValueError("inherited source digest changed: " + relative)


def collect_provenance():
    validate_frozen_sources()
    hashes = {}
    for relative in NEW_SOURCE_PATHS:
        path = ROOT / relative
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1_000_000:
            raise ValueError("missing or invalid predeclared source: " + relative)
        hashes[relative] = digest(path.read_bytes())
    revisions = subprocess.run(
        ["git", "rev-parse", "HEAD", "HEAD^{tree}"], cwd=ROOT, text=True,
        capture_output=True, check=True, timeout=10,
    ).stdout.splitlines()
    if len(revisions) != 2:
        raise ValueError("checkout identity unavailable")
    expected_checkout = os.getenv("GITHUB_SHA")
    if expected_checkout and expected_checkout != revisions[0]:
        raise ValueError("actual checkout differs from GITHUB_SHA")
    dirty = bool(subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, text=True,
        capture_output=True, check=True, timeout=10,
    ).stdout)
    contract_tools = {}
    for name in ("pytest", "ruff"):
        try:
            contract_tools[name] = version(name)
        except PackageNotFoundError:
            contract_tools[name] = None
    return {
        "source_sha256": hashes,
        "source_head": os.getenv("EXPERIMENT_HEAD", "local-uncommitted" if dirty else revisions[0]),
        "source_revision": expected_checkout or revisions[0],
        "checkout_revision": revisions[0], "checkout_tree": revisions[1],
        "workspace_dirty": dirty,
        "runtime": {"implementation": platform.python_implementation(),
                    "python": platform.python_version(), "standard_library_only": True,
                    "contract_tools": contract_tools},
    }


def _public_component(value, private_roots):
    """Reject private paths/opaque arrays and bound each published component."""
    raw = _encoded(value)
    if len(raw) > MAX_COMPONENT_BYTES:
        raise ValueError("public component exceeds bounded metadata budget")
    forbidden = {"raw_notes", "raw_beats", "raw_score", "raw_match", "raw_xml",
                 "raw_members", "audio_samples", "event_arrays", "score_events",
                 "performance_events"}

    def check(item):
        if isinstance(item, dict):
            for key, child in item.items():
                if key.endswith(("_path", "_paths")) or key in forbidden:
                    raise ValueError("private source field in public metadata")
                check(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                check(child)
        elif isinstance(item, str) and any(str(root) in item for root in private_roots):
            raise ValueError("private filesystem path in public metadata")

    check(value)
    return digest(raw)


def _failure(target, status, stage, work, exc):
    target.update(status=status, error_type=type(exc).__name__[:100], failure_stage=stage,
                  reason="The declared stage failed; details are retained in the private execution log.")
    try:
        with (work / "failure.log").open("a", encoding="utf-8") as stream:
            stream.write(stage + "\n" + traceback.format_exc(limit=12)[-12_000:] + "\n")
    except OSError:
        pass


def _finish(output, report, started, status):
    report["status"] = status
    report["elapsed_seconds"] = time.monotonic() - started
    save(output, report)
    return 0 if status == "complete" else 1


def run(work, output, *, source_cache=None, deps=None):
    work, output, cache = _prepare_paths(work, output, source_cache)
    started = time.monotonic()
    private_roots = (ROOT, work, output) + ((cache,) if cache is not None else ())
    report = {
        "schema_version": 1, "status": "running", "cases": [], "summary": None,
        "planned_ids": list(PLANNED_IDS), "planned_analyses": len(PLANNED_IDS),
        "completed_analyses": 0, "completed_attributions": 0,
        "source_head": os.getenv("EXPERIMENT_HEAD", "local"),
        "source_revision": os.getenv("GITHUB_SHA", "local"),
        "source_sha256": {}, "frozen_source_sha256": dict(FROZEN_SOURCE_SHA256),
        "runtime": {}, "previous_receipt_loaded": False,
        "analysis_phase_completed_before_prior_receipt": False,
        "workflow_run_id": os.getenv("GITHUB_RUN_ID"),
        "workflow_run_attempt": os.getenv("GITHUB_RUN_ATTEMPT"),
        "policy": {
            "analysis_type": "reference-assisted source correspondence",
            "cohort": "same six previously observed recordings; exploratory diagnostic",
            "primary_window_ms": 100, "sensitivity_windows_ms": [50, 200],
            "audio_loaded": False, "neural_inference": False, "training": False,
            "fitted_time_shift": False, "tempo_scaling": False, "threshold_tuning": False,
            "written_rest_accuracy_measured": False, "class_f1_measured": False,
            "source_media_or_event_arrays_published": False,
            "completion_definition": "six diagnostics and conditional ledgers processed; admission may fail",
        },
    }
    save(output, report)
    stage = "provenance"
    try:
        report.update(collect_provenance())
        save(output, report)
        deps = deps if deps is not None else _dependencies()
        stage = "source_acquisition"
        with (work / "preparation.log").open("w") as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            previous_manifest = deps.load_gate_manifest()
            sources = deps.acquire_sources(cache if cache is not None else work / "sources")
        if (tuple(item["id"] for item in sources["cases"]) != PLANNED_IDS
                or tuple(item["id"] for item in previous_manifest["sources"]) != PLANNED_IDS):
            raise ValueError("source cohort differs from the six predeclared IDs")
        if (sources["status"] != "verified" or sources["verified_member_count"] != 30
                or sources["media_acquired"] is not False
                or not 0 <= sources["network_bytes"] <= source.MAX_NETWORK_BYTES
                or not 0 <= sources["http_range_requests"] <= source.MAX_HTTP_REQUESTS):
            raise ValueError("source acquisition exceeded the metadata-only contract")
        report["source_acquisition"] = {key: sources[key] for key in ACQUISITION_FIELDS if key in sources}
        _public_component(report["source_acquisition"], private_roots)
        durations = {item["id"]: item["audio"]["duration_seconds"]
                     for item in previous_manifest["sources"]}
        report["preparation_seconds"] = time.monotonic() - started
        save(output, report)
    except Exception as exc:
        _failure(report, "preparation_failed", stage, work, exc)
        return _finish(output, report, started, "preparation_failed")

    analysis_tick = time.monotonic()
    for item in sources["cases"]:
        tick = time.monotonic()
        row = {"id": item["id"], "status": "started", "analysis": None, "attribution": None}
        try:
            raw = {}
            if set(item["member_sha256"]) != set(source.ROLES):
                raise ValueError("source member coverage changed")
            for role, (_, _, path_key) in source.ROLES.items():
                path = Path(item[path_key])
                if path.is_symlink() or path.stat().st_size > source.MAX_MEMBER_BYTES:
                    raise ValueError("source member became invalid after acquisition")
                raw[role] = path.read_bytes()
                if digest(raw[role]) != item["member_sha256"][role]:
                    raise ValueError("source member changed after acquisition")
            with (work / (item["id"] + "-analysis.log")).open("w") as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                score = deps.parse_score(raw["score"])
                piano_score = deps.parse_score(raw["piano_score"])
                match_audit = deps.parse_piano_match(raw["piano_match"], piano_score)
                analysis = deps.analyze_correspondence(
                    score, piano_score, match_audit, raw["beats"], raw["notes"], durations[item["id"]]
                )
            if not isinstance(analysis, dict):
                raise ValueError("analysis must be a public metadata object")
            analysis_hash = _public_component(analysis, private_roots)
            row.update(status="analyzed", analysis=copy.deepcopy(analysis), analysis_sha256=analysis_hash,
                       source_member_sha256=dict(item["member_sha256"]),
                       source_audio_duration_s=durations[item["id"]])
            report["completed_analyses"] += 1
        except Exception as exc:
            _failure(row, "failed", "analysis", work, exc)
        row["analysis_seconds"] = time.monotonic() - tick
        report["cases"].append(row)
        save(output, report)
        print(item["id"], row["status"], flush=True)
    report["analysis_seconds"] = time.monotonic() - analysis_tick
    if report["completed_analyses"] != len(PLANNED_IDS):
        return _finish(output, report, started, "incomplete")
    report["analysis_phase_completed_before_prior_receipt"] = True
    save(output, report)

    try:
        # The first read of prior gate outcomes within this analysis runner.
        with (work / "previous-receipt.log").open("w") as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            previous = deps.read_previous_receipt(PREVIOUS_RECEIPT)
        raw_previous = PREVIOUS_RECEIPT.read_bytes()
        if digest(raw_previous) != PREVIOUS_ZIP_SHA256:
            raise ValueError("previous receipt archive digest mismatch")
        prior_cases = previous["cases"]
        if tuple(item["id"] for item in prior_cases) != PLANNED_IDS:
            raise ValueError("previous receipt cohort changed")
        for prior_case, row in zip(prior_cases, report["cases"], strict=True):
            if any(prior_case["source_member_sha256"][role] != row["source_member_sha256"][role]
                   for role in ("notes", "beats", "score")):
                raise ValueError("previous receipt source identity differs")
        report["previous_receipt_loaded"] = True
        report["previous_receipt"] = {
            "archive_sha256": digest(raw_previous), "report_sha256": PREVIOUS_REPORT_SHA256,
            "source_head": previous["source_head"], "source_revision": previous["source_revision"],
            "status": previous["status"], "case_count": len(prior_cases),
        }
        _public_component(report["previous_receipt"], private_roots)
        save(output, report)
    except Exception as exc:
        _failure(report, "previous_receipt_failed", "previous_receipt", work, exc)
        return _finish(output, report, started, "previous_receipt_failed")

    attribution_tick = time.monotonic()
    for prior_case, row in zip(prior_cases, report["cases"], strict=True):
        try:
            frozen_analysis = copy.deepcopy(row["analysis"])
            with (work / (row["id"] + "-attribution.log")).open("w") as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                attribution = deps.attribute_previous_case(copy.deepcopy(prior_case), frozen_analysis)
            if not isinstance(attribution, dict):
                raise ValueError("conditional attribution must be a public metadata object")
            _public_component(attribution, private_roots)
            if _public_component(frozen_analysis, private_roots) != row["analysis_sha256"]:
                raise ValueError("analysis changed after reading previous outcomes")
            row["attribution"] = attribution
            report["completed_attributions"] += 1
        except Exception as exc:
            _failure(row, "attribution_failed", "attribution", work, exc)
        save(output, report)
    report["attribution_seconds"] = time.monotonic() - attribution_tick
    if report["completed_attributions"] != len(PLANNED_IDS):
        return _finish(output, report, started, "incomplete")
    try:
        summary = deps.summarize_cases(copy.deepcopy(report["cases"]), PLANNED_IDS)
        if summary is not None and not isinstance(summary, dict):
            raise ValueError("aggregate summary must be a public metadata object or unavailable")
        _public_component(summary, private_roots)
        report["summary"] = summary
        status = "complete" if summary is not None else "incomplete"
    except Exception as exc:
        _failure(report, "aggregation_failed", "aggregation", work, exc)
        report["summary"] = None
        status = "aggregation_failed"
    return _finish(output, report, started, status)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-cache", type=Path)
    args = parser.parse_args()
    return run(args.work, args.output, source_cache=args.source_cache)


if __name__ == "__main__":
    raise SystemExit(main())

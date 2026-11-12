"""Run fixed-six local-clock/rhythm diagnostics before historical outcomes.

Synthetic controls are separate authored examples. All six real metadata
analyses are preserved before either historical receipt is read by this runner.
Completion describes diagnostic coverage, not expressive-timing ground truth.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import io
import os
import platform
import subprocess
import time
import zipfile
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Callable

from scripts import kraisler_alignment_source as source
from scripts import run_kraisler_alignment as inherited

ROOT = Path(__file__).resolve().parents[1]
PLANNED_IDS = ("02", "19", "08", "12", "05", "06")
ALIGNMENT_RECEIPT = ROOT / "docs/research/receipts/kraisler-alignment-43201534121.zip"
ALIGNMENT_ZIP_SHA256 = "6f8af87bef6fa8febc977e037130b520d05d0dab8df815e3684ae6239d475005"
GATE_RECEIPT = ROOT / "docs/research/receipts/kraisler-gate-43184102838.zip"
GATE_ZIP_SHA256 = "ba88b9bda70d4a560a3d05c85ea5301d2e8ff98ea81746d676a1c6695898e10e"
MAX_COMPONENT_BYTES = 1_000_000
MAX_REPORT_BYTES = 8_000_000
MAX_RECEIPT_BYTES = 100_000
NEW_SOURCE_PATHS = (
    "scripts/run_kraisler_expressive.py",
    "tests/test_run_kraisler_expressive.py",
    ".github/workflows/cpu-kraisler-expressive.yml",
    "scripts/kraisler_local_clock.py",
    "tests/test_kraisler_local_clock.py",
    "scripts/kraisler_rhythm_ranges.py",
    "tests/test_kraisler_rhythm_ranges.py",
    "scripts/kraisler_expressive.py",
    "tests/test_kraisler_expressive.py",
    "docs/research/KRAISLER_EXPRESSIVE_PROTOCOL_2026-11-12.md",
    "scripts/research_test_manifest.json",
)
# Literal byte pins from committed main 12c9aa5477c63b8a1770a2dcae692dadf930414e.
# No historical outcomes are opened to derive provenance at runtime.
FROZEN_SOURCE_SHA256 = {
    ".github/workflows/cpu-kraisler-alignment.yml": "d94b6841b12507491df7f58c595084d22b238de7a550e70328725b0353ce64f3",
    ".github/workflows/cpu-kraisler-gate.yml": "15a408d208567cb4c9ff272460ab2dfc0d937730741e61b8efb061ec12cec705",
    "docs/research/KRAISLER_ALIGNMENT_PROTOCOL_2026-11-12.md":
        "49d9cc04e08b03afd22201a5a4541336f1fe294d57167ed968476b196d126a28",
    "docs/research/KRAISLER_GATE_PROTOCOL_2026-11-12.md":
        "bfbe4bce2335f1b942f7f55a9c855c8f87657ba4ec8efa5f4ac040981b0e0c1d",
    "scripts/audio_gate_attribution.py": "99b3c494b59fbb0725cc9dd4cd25665a777c93d1516ba6e5a13eb238ddf65cea",
    "scripts/audio_gate_rest.py": "05f239835c2bee14e40cb059b68bad35c7c5a79f247c3d616677c501161fff73",
    "scripts/kraisler_alignment_manifest.json": "ba062dc673f0ebb64c12a95c096144b3efb0975ab7e7be34be645359c3d6503d",
    "scripts/kraisler_alignment_source.py": "25e0ed3327facffdd0f1dcf1a34134176673f9012f2c9f318d2b32ce288642f5",
    "scripts/kraisler_correspondence.py": "c3046d387ba83c7a97c2eb2d16d7f609ecd71c6708ec45d25f5aec9238198efb",
    "scripts/kraisler_gate_eval.py": "ea664ad392d61a12a52b98dcb3987d4bad62ad8d2dbd2aa34301b669434695bf",
    "scripts/kraisler_gate_manifest.json": "a18857a4b7a2025ea327f9a03855ca02dca0964110d973d5224b85dfbb258c60",
    "scripts/kraisler_match.py": "3fbf1c07783bfa9205eb152e553032e5922018c3c1c7d673b524d2a7632a373c",
    "scripts/kraisler_score.py": "515f7f06579e9ee590f4a17147993d496d0b4040e9f60574eb82377c7ac3c431",
    "scripts/kraisler_source.py": "94ba9c30adfd60dfc518a371a53b6fdaa722a44352a019311582b8125423e2bd",
    "scripts/offset_tail_evidence.py": "5adb61edca4b68deac9a0f9f6f619009d8295f006a5913b9f14c6a30f6ce0b4c",
    "scripts/run_cpu_vocadito_candidates.py": "0265be97c1f891816da30e75fa145a58a1972636a5729fcb1ccc761665c52465",
    "scripts/run_kraisler_alignment.py": "fb5a1682ead8d5416143228a9ff845006ccfd1672d700b277f5f41a0eaea4847",
    "scripts/run_kraisler_gate.py": "57b23a975bb8f4a64858c8f034c8a66c50def91053a72004717b815114fe700a",
    "scripts/run_offset_tail_probe.py": "44730f903b4e8eddc1755ff0ae89793052c43abc129f15028b91b0d16562939e",
    "scripts/vocadito_reference.py": "2ee6f18518e0f4887b9f0c163fff6cfcb964a05d21da1eddd6fcf8e031259194",
    "scripts/vocal_recovery.py": "9cbc4c1e635b78263c46473d357fa928350fabdf3efcab79ec44a42e00fa246b",
    "src/audio_score_tool/metrics.py": "476fdb3dcebf8660a83b258263a2719193590eee5135d40f79b87ceab313df4f",
    "tests/test_kraisler_alignment_source.py": "f53aab084da20bb60333e6a7205c74e0476806b9a2309fcc9c299dd76700167f",
    "tests/test_kraisler_correspondence.py": "82f4f6226c2e1e3f9a21a30cfca7a58019f8853666d406fa5316882fa156cf7e",
    "tests/test_kraisler_match.py": "e630f244d1c526325954dba12a467eee6668a52dfa05a789105b57d93114b9ca",
    "tests/test_kraisler_score.py": "e1e8f40144d37936bfe505b866a72326fbfb3709b1adb864482c1afaf31661c4",
    "tests/test_run_kraisler_alignment.py": "3bfa6640ef4be15f4cd62bbc82c7fbe88801f35f26741d016ea46c5c84c00c48",
}


@dataclass(frozen=True)
class Dependencies:
    acquire_sources: Callable
    load_gate_manifest: Callable
    parse_score: Callable
    parse_piano_match: Callable
    synthetic_controls: Callable
    analyze_expressive: Callable
    read_alignment_baseline: Callable
    verify_baseline_case: Callable
    read_previous_receipt: Callable
    attribute_expressive: Callable
    summarize_expressive: Callable


def _dependencies():
    from scripts.kraisler_correspondence import read_previous_receipt
    from scripts.kraisler_expressive import (
        analyze_expressive,
        attribute_expressive,
        read_alignment_baseline,
        summarize_expressive,
        verify_baseline_case,
    )
    from scripts.kraisler_match import parse_piano_match
    from scripts.kraisler_rhythm_ranges import synthetic_controls
    from scripts.kraisler_score import parse_score

    return Dependencies(
        source.acquire_alignment_sources, source.frozen.load_manifest,
        parse_score, parse_piano_match, synthetic_controls, analyze_expressive,
        read_alignment_baseline, verify_baseline_case, read_previous_receipt,
        attribute_expressive, summarize_expressive,
    )


def validate_frozen_sources():
    for relative, expected in FROZEN_SOURCE_SHA256.items():
        path = ROOT / relative
        if (path.is_symlink() or not path.is_file() or path.stat().st_size > 1_000_000
                or inherited.digest(path.read_bytes()) != expected):
            raise ValueError("inherited source digest changed: " + relative)


def collect_provenance():
    validate_frozen_sources()
    hashes = {}
    for relative in NEW_SOURCE_PATHS:
        path = ROOT / relative
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1_000_000:
            raise ValueError("missing or invalid predeclared source: " + relative)
        hashes[relative] = inherited.digest(path.read_bytes())
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
    if len(inherited._encoded(value)) > MAX_COMPONENT_BYTES:
        raise ValueError("public component exceeds bounded metadata budget")
    return inherited._public_component(value, private_roots)


def _check_report_budget(report):
    # Leave room for bounded failure diagnostics and counters if a component fails.
    reserve = min(32_000, MAX_REPORT_BYTES // 10)
    if len(inherited._encoded(report)) > MAX_REPORT_BYTES - reserve:
        raise ValueError("combined public metadata exceeds report budget")


def save(path, report):
    raw = inherited._encoded(report)
    if len(raw) > MAX_REPORT_BYTES:
        raise ValueError("public report exceeds bounded metadata budget")
    source.frozen._write_atomic(path, raw)


def _finish(output, report, started, status):
    report["status"] = status
    report["elapsed_seconds"] = time.monotonic() - started
    save(output, report)
    return 0 if status == "complete" else 1


def _receipt_metadata(path, expected_sha256, report):
    if (path.is_symlink() or not path.is_file()
            or not 0 < path.stat().st_size <= MAX_RECEIPT_BYTES):
        raise ValueError("invalid bounded historical receipt")
    raw = path.read_bytes()
    if inherited.digest(raw) != expected_sha256 or report["status"] != "complete":
        raise ValueError("historical receipt identity or completion mismatch")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if archive.namelist() != ["report.json"]:
            raise ValueError("historical receipt member coverage mismatch")
        member = archive.getinfo("report.json")
        if not 0 < member.file_size <= MAX_REPORT_BYTES:
            raise ValueError("historical report exceeds metadata budget")
        report_hash = inherited.digest(archive.read(member))
    return {"archive_sha256": expected_sha256, "report_sha256": report_hash,
            "source_head": report["source_head"], "source_revision": report["source_revision"],
            "status": report["status"], "case_count": len(report["cases"])}


def run(work, output, *, source_cache=None, deps=None):
    work, output, cache = inherited._prepare_paths(work, output, source_cache)
    started = time.monotonic()
    private_roots = (ROOT, work, output) + ((cache,) if cache is not None else ())
    report = {
        "schema_version": 1, "status": "running", "cases": [], "summary": None,
        "synthetic_controls": None, "planned_ids": list(PLANNED_IDS),
        "planned_analyses": len(PLANNED_IDS), "completed_analyses": 0,
        "completed_baseline_verifications": 0, "completed_attributions": 0,
        "source_head": os.getenv("EXPERIMENT_HEAD", "local"),
        "source_revision": os.getenv("GITHUB_SHA", "local"),
        "source_sha256": {}, "frozen_source_sha256": dict(FROZEN_SOURCE_SHA256),
        "runtime": {}, "alignment_baseline_loaded": False, "gate_receipt_loaded": False,
        "analysis_phase_completed_before_prior_receipts": False,
        "workflow_run_id": os.getenv("GITHUB_RUN_ID"),
        "workflow_run_attempt": os.getenv("GITHUB_RUN_ATTEMPT"),
        "policy": {
            "analysis_type": "reference-assisted local clock and rhythm-range diagnostics",
            "cohort": "same six previously observed recordings; exploratory diagnostic",
            "synthetic_controls_are_separate_authored_examples": True,
            "audio_loaded": False, "neural_inference": False, "training": False,
            "threshold_tuning": False, "original_events_changed": False,
            "acoustic_dynamics_accuracy_measured": False,
            "real_recording_swing_accuracy_measured": False,
            "written_rest_accuracy_measured": False, "class_f1_measured": False,
            "source_media_or_event_arrays_published": False,
            "completion_definition": "six diagnostics, baseline checks and conditional ledgers processed; admission may fail",
        },
    }
    save(output, report)
    stage = "provenance"
    try:
        report.update(collect_provenance())
        save(output, report)
        deps = deps if deps is not None else _dependencies()
        stage = "synthetic_controls"
        with (work / "synthetic-controls.log").open("w") as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            controls = deps.synthetic_controls()
        if not isinstance(controls, dict):
            raise ValueError("synthetic control receipt must be a metadata object")
        _public_component(controls, private_roots)
        _check_report_budget({**report, "synthetic_controls": controls})
        report["synthetic_controls"] = copy.deepcopy(controls)
        save(output, report)
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
        acquisition = {key: sources[key] for key in inherited.ACQUISITION_FIELDS if key in sources}
        _public_component(acquisition, private_roots)
        _check_report_budget({**report, "source_acquisition": acquisition})
        report["source_acquisition"] = acquisition
        durations = {item["id"]: item["audio"]["duration_seconds"]
                     for item in previous_manifest["sources"]}
        report["preparation_seconds"] = time.monotonic() - started
        save(output, report)
    except Exception as exc:
        inherited._failure(report, "preparation_failed", stage, work, exc)
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
                if inherited.digest(raw[role]) != item["member_sha256"][role]:
                    raise ValueError("source member changed after acquisition")
            with (work / (item["id"] + "-analysis.log")).open("w") as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                score = deps.parse_score(raw["score"])
                piano_score = deps.parse_score(raw["piano_score"])
                match_audit = deps.parse_piano_match(raw["piano_match"], piano_score)
                analysis = deps.analyze_expressive(
                    score, piano_score, match_audit, raw["beats"], raw["notes"],
                    durations[item["id"]], raw_score=raw["score"],
                )
            if not isinstance(analysis, dict) or not isinstance(analysis.get("frozen_baseline"), dict):
                raise ValueError("analysis must retain the frozen baseline metadata")
            analysis_hash = _public_component(analysis, private_roots)
            candidate = {**row, "status": "analyzed", "analysis": copy.deepcopy(analysis),
                         "analysis_sha256": analysis_hash,
                         "source_member_sha256": dict(item["member_sha256"]),
                         "source_audio_duration_s": durations[item["id"]]}
            _check_report_budget({**report, "cases": [*report["cases"], candidate]})
            row = candidate
            report["completed_analyses"] += 1
        except Exception as exc:
            inherited._failure(row, "failed", "analysis", work, exc)
        row["analysis_seconds"] = time.monotonic() - tick
        report["cases"].append(row)
        save(output, report)
        print(item["id"], row["status"], flush=True)
    report["analysis_seconds"] = time.monotonic() - analysis_tick
    if report["completed_analyses"] != len(PLANNED_IDS):
        return _finish(output, report, started, "incomplete")
    report["analysis_phase_completed_before_prior_receipts"] = True
    save(output, report)

    stage = "alignment_baseline"
    try:
        # First historical-outcome reads within this analysis runner, after all six analyses.
        with (work / "historical-receipts.log").open("w") as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            alignment = deps.read_alignment_baseline(ALIGNMENT_RECEIPT)
            alignment_identity = _receipt_metadata(ALIGNMENT_RECEIPT, ALIGNMENT_ZIP_SHA256, alignment)
            report["alignment_baseline_loaded"] = True
            stage = "gate_receipt"
            gate = deps.read_previous_receipt(GATE_RECEIPT)
            gate_identity = _receipt_metadata(GATE_RECEIPT, GATE_ZIP_SHA256, gate)
            report["gate_receipt_loaded"] = True
        if (tuple(item["id"] for item in alignment["cases"]) != PLANNED_IDS
                or tuple(item["id"] for item in gate["cases"]) != PLANNED_IDS):
            raise ValueError("historical receipt cohort changed")
        report["historical_receipts"] = {"alignment": alignment_identity, "gate": gate_identity}
        _public_component(report["historical_receipts"], private_roots)
        save(output, report)
        stage = "baseline_verification"
        for old, previous, row in zip(alignment["cases"], gate["cases"], report["cases"], strict=True):
            if (old["source_member_sha256"] != row["source_member_sha256"]
                    or old["source_audio_duration_s"] != row["source_audio_duration_s"]
                    or any(previous["source_member_sha256"][role] != row["source_member_sha256"][role]
                           for role in ("notes", "beats", "score"))):
                raise ValueError("historical source identity differs from current inputs")
            frozen_analysis = copy.deepcopy(row["analysis"])
            with (work / (row["id"] + "-baseline.log")).open("w") as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                deps.verify_baseline_case(copy.deepcopy(old), frozen_analysis)
            if _public_component(frozen_analysis, private_roots) != row["analysis_sha256"]:
                raise ValueError("baseline verification changed frozen analysis")
            report["completed_baseline_verifications"] += 1
        save(output, report)
    except Exception as exc:
        status = "baseline_verification_failed" if stage == "baseline_verification" else "historical_receipt_failed"
        inherited._failure(report, status, stage, work, exc)
        return _finish(output, report, started, status)

    attribution_tick = time.monotonic()
    for index, (previous, row) in enumerate(zip(gate["cases"], report["cases"], strict=True)):
        try:
            frozen_analysis = copy.deepcopy(row["analysis"])
            with (work / (row["id"] + "-attribution.log")).open("w") as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                attribution = deps.attribute_expressive(copy.deepcopy(previous), frozen_analysis)
            if not isinstance(attribution, dict):
                raise ValueError("conditional attribution must be a public metadata object")
            _public_component(attribution, private_roots)
            if _public_component(frozen_analysis, private_roots) != row["analysis_sha256"]:
                raise ValueError("analysis changed after reading historical outcomes")
            candidates = list(report["cases"])
            candidates[index] = {**row, "attribution": attribution}
            _check_report_budget({**report, "cases": candidates})
            row["attribution"] = copy.deepcopy(attribution)
            report["completed_attributions"] += 1
        except Exception as exc:
            inherited._failure(row, "attribution_failed", "attribution", work, exc)
        save(output, report)
    report["attribution_seconds"] = time.monotonic() - attribution_tick
    if report["completed_attributions"] != len(PLANNED_IDS):
        return _finish(output, report, started, "incomplete")
    try:
        summary = deps.summarize_expressive(copy.deepcopy(report["cases"]), PLANNED_IDS)
        if summary is not None and not isinstance(summary, dict):
            raise ValueError("aggregate summary must be a public metadata object or unavailable")
        _public_component(summary, private_roots)
        _check_report_budget({**report, "summary": summary})
        report["summary"] = copy.deepcopy(summary)
        status = "complete" if summary is not None else "incomplete"
    except Exception as exc:
        inherited._failure(report, "aggregation_failed", "aggregation", work, exc)
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

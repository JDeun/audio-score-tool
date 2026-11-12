"""Save every fixed repeat-context prediction before opening evaluation sources.

Four disjoint cohorts share a label-free inference boundary. Original sources,
observations, candidate paths and full predictions stay in a fresh private work
directory. The public report contains bounded receipts and derived diagnostics.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import json
import math
import os
import platform
import subprocess
import tempfile
import time
import traceback
from dataclasses import asdict, dataclass, is_dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
DECLARED_BASE_REVISION = "b7561cc64e2a595ba9d99cbaf1cf2170f00ae2ee"
SCOPES = ("reused_authored", "factorial_authored", "reused_real", "additional_real")
SYNTHETIC_SCOPES, REAL_SCOPES = SCOPES[:2], SCOPES[2:]
EXPECTED_SCOPE_COUNTS = dict(zip(SCOPES, (484, 1028, 4, 4), strict=True))
DECLARED_PLANS = {
    "reused_authored": [f"syn{i:03d}" for i in range(1, 485)],
    "factorial_authored": [f"fac{i:04d}" for i in range(1, 1029)],
    "reused_real": [f"nasap{i:03d}" for i in range(1, 5)],
    "additional_real": [f"nasap{i:03d}" for i in range(5, 9)],
}
NATIVE_REAL_SCOPES = {"reused_real": "real_same_score",
                      "additional_real": "real_additional_same_score"}
ARMS = ("straight_narrow", "global_phase", "local_switch005", "repeat_soft0025",
        "repeat_soft010", "repeat_hard")
EVENT_FIELDS = {"event_id", "pitch", "onset_q", "velocity"}
MAX_REPORT_BYTES = 32_000_000
MAX_METADATA_COMPONENT_BYTES = 1_000_000
MAX_EVALUATION_BYTES = 30_000_000
MAX_PREDICTION_BYTES = 4_000_000
MAX_ALL_PREDICTION_BYTES = 512_000_000
MAX_EVENTS_PER_CASE = 10_000
MAX_SOURCE_NETWORK_BYTES = 4_602_128
MAX_SOURCE_HTTP_REQUESTS = 50
EXPECTED_UNIQUE_SOURCE_MEMBERS = 49
EXPECTED_UNIQUE_SOURCE_BYTES = 3_985_273
SOURCE_BUDGETS = {
    "reused_real": {"member_count": 25, "total_bytes": 2_241_212,
                    "input_member_count": 8, "input_bytes": 48_459},
    "additional_real": {"member_count": 25, "total_bytes": 2_360_916,
                        "input_member_count": 8, "input_bytes": 69_674},
}
NEW_SOURCE_PATHS = (
    "scripts/repeat_context_phase.py",
    "scripts/nasap_repeat_context_source.py",
    "scripts/repeat_context_study.py",
    "scripts/run_repeat_context.py",
    "scripts/nasap_repeat_context_manifest.json",
    "tests/test_repeat_context_phase.py",
    "tests/test_nasap_repeat_context_source.py",
    "tests/test_repeat_context_study.py",
    "tests/test_run_repeat_context.py",
    ".github/workflows/cpu-repeat-context.yml",
    "docs/research/REPEAT_CONTEXT_PROTOCOL_2026-11-13.md",
    "scripts/research_test_manifest.json",
)
# Literal pins from the committed baseline, never derived from outcome receipts.
# The old inventory is historical metadata because the current inventory gains tests.
HISTORICAL_INVENTORY_SHA256 = "18fe7728c15a8bdb06da0ea32bce99f6b708f24514c80859e2a0bbc858f04a36"
FROZEN_SOURCE_SHA256 = {
    "scripts/same_score_phase.py": "109985eeb81f8119c202927b1c6f9e7e285cec83c38f549908e36a15c3c69aa3",
    "scripts/nasap_same_score_source.py": "a1a60da73da4f25dad5ddd3b1576a2dbee42a5d750e7b212eea4b318042c1f0a",
    "scripts/same_score_expression_study.py": "3520016223c1655f5d5856631d831e714c7757c0b98642e48adf0c1cee8285c5",
    "scripts/run_same_score_expression.py": "de53182ca4072d8193bac834f802445b434675af079d44a16dde0fd9cf59d28c",
    "scripts/nasap_same_score_manifest.json": "27c576542fef26dbca605db4a9f938cc00451702b2c7f441aa84013fe3496239",
    "tests/test_same_score_phase.py": "db0c2cf6ad780ce2f6977fbe9eb87c34579e72f69ee2f90672aeadf643ee7389",
    "tests/test_nasap_same_score_source.py": "521a1fe7c8d4f2f0457d21363f42bf4afc2bb84dcfbab64b91c2bd649c4de7ce",
    "tests/test_same_score_expression_study.py": "b924c45badffab8569cbe7fd7c018709d67c40ec81698c569aab2aa8f4a404a2",
    "tests/test_run_same_score_expression.py": "44317b858fa537ed887a6c335ab5b6456feee3e08e87fd3ddece255f0ddfe6ef",
    ".github/workflows/cpu-same-score-expression.yml": "71d67983fd0526ad9be1df980ab99cde53322582ee28f9cf7e88d1f5e76930c3",
    "docs/research/SAME_SCORE_EXPRESSION_PROTOCOL_2026-11-12.md": "d94b5f4a238f8534f20d9b998fffd97ec125ea84b1afce4d204c2fc9b6049472",
    "scripts/performed_rhythm_invariance.py": "7f42567f97a5b5b51053bcd9e9a5a9859701190971d33df4c308af5f0f11ab22",
    "scripts/rhythm_invariance_study.py": "adcf66f68514c844f33e9f3b77cfd1a658d7a965bd4226fa6cc0a9532d503e45",
    "scripts/nasap_joint_rhythm.py": "e2f136d486c0ef14206469db1a4b1c7a5dfc5dfcd55de3c3a80df2f6f5263681",
    "scripts/nasap_duration_probe.py": "881a0a7544745d5fe50317ca81bca8ea05adce510bbfb2facc46405c65ffa973",
    "scripts/nasap_keyoff_paired.py": "97368c713177ac5537a6c22f57689d375260674a36efe5b92cbfbd64131a641a",
    "scripts/audit_nasap_duration_source.py": "c63c44b2a6c5a391d972b22417cba21830b71c0bed2dd6996b38f9f93044244c",
    "docs/research/receipts/same-score-expression-43247249315.zip": "38107d18e89058ef4e870214e0ba5af0bb7b97eb92d1b7ef056e9096c30c7f17",
}
MEASURED_SOURCE_PATHS = NEW_SOURCE_PATHS + tuple(FROZEN_SOURCE_SHA256)


@dataclass(frozen=True)
class SyntheticAdapter:
    plan: Callable
    prepare: Callable
    load_evaluation: Callable


@dataclass(frozen=True)
class SourceAdapter:
    load_manifest: Callable
    prepare_inputs: Callable
    load_evaluation: Callable


@dataclass(frozen=True)
class Dependencies:
    synthetic: dict[str, SyntheticAdapter]
    sources: dict[str, SourceAdapter]
    infer_repeated_performance: Callable
    evaluate_study: Callable


def _dependencies():
    from scripts import nasap_repeat_context_source as additional
    from scripts import nasap_same_score_source as reused
    from scripts import repeat_context_study as study
    from scripts.repeat_context_phase import infer_repeated_performance

    return Dependencies(
        {"reused_authored": SyntheticAdapter(study.reused_plan, study.prepare_reused_inputs,
                                             study.load_reused_evaluation),
         "factorial_authored": SyntheticAdapter(study.factorial_plan, study.prepare_factorial_inputs,
                                                study.load_factorial_evaluation)},
        {"reused_real": SourceAdapter(reused.load_manifest, reused.prepare_inputs, reused.load_evaluation),
         "additional_real": SourceAdapter(additional.load_manifest, additional.prepare_inputs,
                                          additional.load_evaluation)},
        infer_repeated_performance, study.evaluate_study,
    )


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _atomic_write(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _safe_path(path):
    path = Path(path).absolute()
    if any(component.is_symlink() for component in (path, *path.parents)):
        raise ValueError("work and report paths must not contain symlinks")
    return path.resolve()


def _prepare_paths(work, output):
    work, output = _safe_path(work), _safe_path(output)
    if (work.exists() or output.exists() or work.is_relative_to(ROOT)
            or output.is_relative_to(ROOT) or output.is_relative_to(work)
            or work.is_relative_to(output)):
        raise ValueError("fresh separate private work and public report paths outside repository required")
    work.mkdir(parents=True, mode=0o700)
    return work, output


def collect_provenance():
    if os.getenv("HF_TOKEN") or os.getenv("HUGGING_FACE_HUB_TOKEN"):
        raise ValueError("external model credentials are not permitted")
    if version("mido") != "1.3.3":
        raise ValueError("the pinned mido 1.3.3 source parser is required")
    if len(set(MEASURED_SOURCE_PATHS)) != len(MEASURED_SOURCE_PATHS):
        raise ValueError("duplicate measured source")
    hashes = {}
    for relative in MEASURED_SOURCE_PATHS:
        path = ROOT / relative
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1_000_000:
            raise ValueError("missing or oversized declared source: " + relative)
        hashes[relative] = digest(path.read_bytes())
        if relative in FROZEN_SOURCE_SHA256 and hashes[relative] != FROZEN_SOURCE_SHA256[relative]:
            raise ValueError("inherited scientific source differs from its immutable pin: " + relative)
    revisions = subprocess.run(
        ["git", "rev-parse", "HEAD", "HEAD^{tree}"], cwd=ROOT, text=True,
        capture_output=True, check=True, timeout=10,
    ).stdout.splitlines()
    if len(revisions) != 2:
        raise ValueError("checkout identity unavailable")
    expected = os.getenv("GITHUB_SHA")
    if expected and expected != revisions[0]:
        raise ValueError("actual checkout differs from GITHUB_SHA")
    commit = subprocess.run(
        ["git", "cat-file", "-p", "HEAD"], cwd=ROOT, text=True,
        capture_output=True, check=True, timeout=10,
    ).stdout.split("\n\n", 1)[0]
    parents = [line.split()[1] for line in commit.splitlines() if line.startswith("parent ")]
    dirty = bool(subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, text=True,
        capture_output=True, check=True, timeout=10,
    ).stdout)
    if expected and dirty:
        raise ValueError("the Actions study must use an unchanged committed checkout")
    packages = {}
    for name in ("mido", "pytest", "ruff"):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = None
    return {
        "declared_base_revision": DECLARED_BASE_REVISION,
        "source_head": os.getenv("EXPERIMENT_HEAD", "local-uncommitted" if dirty else revisions[0]),
        "source_revision": expected or revisions[0], "checkout_revision": revisions[0],
        "checkout_tree": revisions[1], "checkout_parents": parents,
        "workspace_dirty": dirty, "source_sha256": hashes,
        "frozen_source_sha256": dict(FROZEN_SOURCE_SHA256),
        "historical_inventory": {"revision": DECLARED_BASE_REVISION,
                                 "sha256": HISTORICAL_INVENTORY_SHA256,
                                 "current_inventory_measured_separately": True},
        "runtime": {"implementation": platform.python_implementation(),
                    "python": platform.python_version(), "packages": packages,
                    "analysis_standard_library_only": True, "model_inferences": 0},
    }


def _public_component(value, private_roots, limit=MAX_METADATA_COMPONENT_BYTES):
    raw = encoded(value)
    if len(raw) > limit:
        raise ValueError("public metadata component exceeds its declared size bound")
    forbidden = {"events", "raw_events", "event_arrays", "raw_midi", "raw_bytes", "assignments",
                 "private_predictions", "prediction_events", "audio_samples", "waveform",
                 "score_events", "score_rows", "alignment_rows", "full_candidate_assignments",
                 "full_selected_assignments", "diagnostic_assignments", "path_sets"}

    def visit(item):
        if isinstance(item, dict):
            for key, child in item.items():
                if isinstance(key, str) and (key in forbidden or key.endswith(("_path", "_paths"))):
                    raise ValueError("private source or prediction field in public metadata")
                if key in ("target_notes", "input_links") and isinstance(child, (dict, list, tuple)):
                    raise ValueError("private evaluation records in public metadata")
                visit(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                visit(child)
        elif isinstance(item, str) and any(str(root) in item for root in private_roots):
            raise ValueError("private filesystem location in public metadata")

    visit(value)
    return digest(raw)


def _check_report_budget(report):
    # Reserve bounded failures for all 1,520 rows before attaching a component.
    reserve = min(2_000_000, MAX_REPORT_BYTES // 10)
    if len(encoded(report)) > MAX_REPORT_BYTES - reserve:
        raise ValueError("combined public metadata exceeds the report budget")


def save(output, report):
    raw = encoded(report)
    if len(raw) > MAX_REPORT_BYTES:
        raise ValueError("public report exceeds the declared size bound")
    _atomic_write(output, raw)


def _failure(target, status, stage, work, exc):
    target.update(status=status, failure_stage=stage, error_type=type(exc).__name__[:100],
                  reason="The declared stage failed; details remain in the private execution log.")
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


def _plan(deps):
    if set(deps.synthetic) != set(SYNTHETIC_SCOPES) or set(deps.sources) != set(REAL_SCOPES):
        raise ValueError("the four predeclared cohort adapters are required")
    plan = {scope: list(deps.synthetic[scope].plan()) for scope in SYNTHETIC_SCOPES}
    manifests = {scope: deps.sources[scope].load_manifest() for scope in REAL_SCOPES}
    plan.update({scope: [row["id"] for row in manifests[scope]["cases"]] for scope in REAL_SCOPES})
    ids = [tid for scope in SCOPES for tid in plan[scope]]
    if (plan != DECLARED_PLANS
            or any(len(plan[scope]) != EXPECTED_SCOPE_COUNTS[scope] for scope in SCOPES)
            or any(not isinstance(tid, str) or not 0 < len(tid) <= 200 for tid in ids)
            or len(set(ids)) != len(ids)):
        raise ValueError("predeclared ordered cohort population changed")
    return plan, manifests, _source_inventory(manifests)


def _source_inventory(manifests):
    unique, source_entries, source_bytes = {}, 0, 0
    for scope in REAL_SCOPES:
        manifest = manifests[scope]
        members, budget = manifest["members"], manifest["budget"]
        expected_inputs = {row[key] for row in manifest["cases"] for key in ("midi", "performance_annotations")}
        observed = {"member_count": len(members), "total_bytes": sum(m["bytes"] for m in members.values()),
                    "input_member_count": len(expected_inputs),
                    "input_bytes": sum(members[path]["bytes"] for path in expected_inputs)}
        if observed != SOURCE_BUDGETS[scope] or any(budget[key] != value for key, value in observed.items()):
            raise ValueError("source manifest differs from its predeclared acquisition budget")
        source_entries += len(members)
        source_bytes += observed["total_bytes"]
        for path, member in members.items():
            identity = (manifest["source_base"], path)
            if identity in unique and unique[identity] != member:
                raise ValueError("shared source member identities disagree between adapters")
            unique[identity] = member
    unique_bytes = sum(member["bytes"] for member in unique.values())
    if (source_entries != MAX_SOURCE_HTTP_REQUESTS or source_bytes != MAX_SOURCE_NETWORK_BYTES
            or len(unique) != EXPECTED_UNIQUE_SOURCE_MEMBERS or unique_bytes != EXPECTED_UNIQUE_SOURCE_BYTES):
        raise ValueError("combined actual-cache and unique-source budgets disagree")
    return {"independent_source_caches": True, "source_member_entries": source_entries,
            "planned_cold_http_requests": source_entries, "planned_cold_network_bytes": source_bytes,
            "unique_source_members": len(unique), "unique_source_bytes": unique_bytes,
            "shared_member_count": source_entries - len(unique)}


def _observation_payload(case):
    events, length = case["events"], case["length_q"]
    if (not isinstance(events, tuple) or not 0 < len(events) <= MAX_EVENTS_PER_CASE
            or not isinstance(length, (int, float)) or isinstance(length, bool)
            or not math.isfinite(length) or length <= 0):
        raise ValueError("bounded event tuple and positive quarter-note length required")
    rows = []
    for event in events:
        if not is_dataclass(event) or not event.__dataclass_params__.frozen:
            raise ValueError("inference requires an immutable declared event dataclass")
        row = asdict(event)
        if set(row) != EVENT_FIELDS:
            raise ValueError("labels or unapproved context entered an inference event")
        rows.append(row)
    return {"events": rows, "length_q": length}


def _validate_prepared(cases, planned, scope):
    allowed = {"id", "scope", "events", "length_q", "receipt"}
    if (not isinstance(cases, list)
            or any(not isinstance(case, dict) or set(case) not in (allowed, allowed | {"status"})
                   for case in cases)
            or [case["id"] for case in cases] != planned
            or any(case["scope"] != scope or not isinstance(case["receipt"], dict)
                   or case["receipt"].get("status") not in {"complete", "failed"}
                   or ("status" in case and case["status"] != case["receipt"]["status"])
                   for case in cases)):
        raise ValueError("prepared cases must preserve the ordered cohort without evaluation fields")


def _validate_source_receipt(receipt, manifest, cases, stage, previous=None, *, require_full_coverage=True):
    members, budget = manifest["members"], manifest["budget"]
    expected_inputs = {row[key] for row in manifest["cases"] for key in ("midi", "performance_annotations")}
    expected = expected_inputs if stage == "inputs" else set(members)
    complete = sum(case["receipt"]["status"] == "complete" for case in cases)
    if (receipt["stage"] != stage or receipt["planned_recordings"] != len(cases)
            or receipt["complete_recordings"] != complete or receipt["failed_recordings"] != len(cases) - complete
            or receipt["full_source_member_count"] != len(members)
            or receipt["full_source_bytes"] != budget["total_bytes"]
            or receipt["verified_member_count"] != len(receipt["members"])
            or not set(receipt["members"]) <= expected):
        raise ValueError("source scope, stage coverage or fixed budget changed")
    for path in receipt["members"]:
        if any(receipt["members"][path][key] != members[path][key] for key in ("bytes", "sha256")):
            raise ValueError("source receipt identity differs from fixed manifest")
    for key in ("http_requests", "downloaded_bytes", "cache_hits"):
        if type(receipt[key]) is not int or receipt[key] < 0:
            raise ValueError("invalid source acquisition counter")
    prior = {} if previous is None else previous
    if (receipt["http_requests"] > len(expected)
            or receipt["downloaded_bytes"] > sum(members[path]["bytes"] for path in expected)
            or receipt["http_requests"] + prior.get("http_requests", 0) > budget["member_count"]
            or receipt["downloaded_bytes"] + prior.get("downloaded_bytes", 0) > budget["total_bytes"]):
        raise ValueError("combined source network budget exceeded")
    if require_full_coverage and set(receipt["members"]) != expected:
        raise ValueError("the declared source stage does not have complete verified coverage")


def _attach_acquisition(report, scope, stage, receipt, private_roots):
    _public_component(receipt, private_roots)
    acquisition = copy.deepcopy(report["source_acquisition"])
    acquisition[scope][stage] = copy.deepcopy(receipt)
    stages = [r for source_scope in REAL_SCOPES for r in acquisition[source_scope].values()]
    totals = {key: sum(r[key] for r in stages) for key in ("http_requests", "downloaded_bytes", "cache_hits")}
    if totals["http_requests"] > MAX_SOURCE_HTTP_REQUESTS or totals["downloaded_bytes"] > MAX_SOURCE_NETWORK_BYTES:
        raise ValueError("all-source transfer budget exceeded")
    acquisition["actual_totals"] = totals
    _check_report_budget({**report, "source_acquisition": acquisition})
    report["source_acquisition"] = acquisition


def _assert_frozen(cases, predictions, report, expected_ids=None, native_scope=None):
    rows = {row["id"]: row for row in report["cases"]}
    expected_ids = report["planned_ids"] if expected_ids is None else expected_ids
    if [case["id"] for case in cases] != expected_ids:
        raise ValueError("evaluation changed the frozen observation population or order")
    for case in cases:
        row = rows[case["id"]]
        if (case["scope"] != (native_scope or row["scope"])
                or digest(encoded(_observation_payload(case))) != row["input_file_sha256"]
                or digest(encoded(case["receipt"])) != row["source_receipt_sha256"]):
            raise ValueError("evaluation modified a frozen observation, cohort or source receipt")
    if predictions is not None:
        if set(predictions) != set(expected_ids):
            raise ValueError("evaluation changed the frozen prediction population")
        for tid, prediction in predictions.items():
            if digest(encoded(prediction)) != rows[tid]["prediction_file_sha256"]:
                raise ValueError("evaluation modified a frozen prediction")


def _initial_report():
    plan = copy.deepcopy(DECLARED_PLANS)
    return {
        "schema_version": 1, "status": "running", "planned_ids": [tid for scope in SCOPES for tid in plan[scope]],
        "planned_scopes": plan, "plan_sha256": digest(encoded(plan)),
        "expected_scope_case_counts": dict(EXPECTED_SCOPE_COUNTS),
        "cases": [{"id": tid, "scope": scope, "status": "planned", "receipt": None,
                   "input_file_sha256": None, "prediction_file_sha256": None,
                   "source_receipt_sha256": None, "event_mutation_check_passed": False,
                   "evaluation_status": "pending"} for scope in SCOPES for tid in plan[scope]],
        "planned_inferences": sum(EXPECTED_SCOPE_COUNTS.values()),
        "completed_inferences": 0, "completed_preservation_checks": 0, "private_prediction_bytes": 0,
        "evaluation_started": False, "evaluation_loading_started": False,
        "evaluation_loaded": {scope: False for scope in SCOPES},
        "all_predictions_saved_before_evaluation": False, "evaluation": None, "summary": None,
        "source_acquisition": {scope: {} for scope in REAL_SCOPES},
        "source_head": os.getenv("EXPERIMENT_HEAD", "local"),
        "source_revision": os.getenv("GITHUB_SHA", "local"),
        "declared_base_revision": DECLARED_BASE_REVISION, "source_sha256": {}, "runtime": {},
        "workflow_run_id": os.getenv("GITHUB_RUN_ID"), "workflow_run_attempt": os.getenv("GITHUB_RUN_ATTEMPT"),
        "policy": {
            "inference_inputs": ["event_id", "pitch", "onset_q", "velocity", "length_q"],
            "group_labels_or_score_alignment_passed_to_inference": False,
            "repeat_context_from_observations_only": True, "real_inputs_use_supplied_annotated_clock": True,
            "real_midi_timebase_is_not_score_quarter_clock": True,
            "four_cohort_denominators_are_separate": True, "synthetic_network_access": False,
            "model_inferences": 0, "training": False,
            "preservation_check": "event mutation checks and retained source identity; no MIDI export roundtrip",
            "audio_transcription_or_listening_quality_measured": False,
            "real_evaluation_uses_shared_score_and_publisher_alignment": True,
            "full_durations_rests_and_engraving_validated": False,
            "automatic_product_correction_enabled": False,
            "raw_sources_events_or_full_predictions_published": False,
        },
    }


def _accept_evaluation_population(report, scope, evaluation):
    if (not isinstance(evaluation, dict)
            or set(evaluation) != set(report["planned_scopes"][scope])
            or any(not isinstance(value, dict) or value.get("status") not in {"complete", "failed"}
                   for value in evaluation.values())):
        raise ValueError("evaluation population or admission status changed")
    for row in report["cases"]:
        if row["scope"] == scope:
            row["evaluation_status"] = evaluation[row["id"]]["status"]
    if any(value["status"] != "complete" for value in evaluation.values()):
        raise ValueError("a planned evaluation source was not admitted")


def run(work, output, *, deps=None):
    work, output = _prepare_paths(work, output)
    started = time.monotonic()
    private_roots = (ROOT, work, output)
    report = _initial_report()
    save(output, report)
    stage = "provenance"
    try:
        report.update(collect_provenance())
        save(output, report)
        deps = deps if deps is not None else _dependencies()
        stage = "planning"
        plan, manifests, inventory = _plan(deps)
        report["source_inventory"] = inventory
        _check_report_budget(report)
        save(output, report)
        prepared, source_cases, source_work = [], {}, {}
        with (work / "preparation.log").open("w") as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            for scope in SYNTHETIC_SCOPES:
                stage = scope + "_preparation"
                cases = deps.synthetic[scope].prepare()
                _validate_prepared(cases, plan[scope], scope)
                prepared.extend(cases)
            for scope in REAL_SCOPES:
                stage = scope + "_preparation"
                source_work[scope] = work / (scope + "-sources")
                real = deps.sources[scope].prepare_inputs(source_work[scope])
                _validate_prepared(real["cases"], plan[scope], NATIVE_REAL_SCOPES[scope])
                # Preserve verified partial transfers before the unchanged complete-coverage gate.
                _validate_source_receipt(real["source_receipt"], manifests[scope], real["cases"], "inputs",
                                         require_full_coverage=False)
                _attach_acquisition(report, scope, "inputs", real["source_receipt"], private_roots)
                _validate_source_receipt(real["source_receipt"], manifests[scope], real["cases"], "inputs")
                source_cases[scope] = real["cases"]
                prepared.extend({**case, "scope": scope} for case in real["cases"])
                save(output, report)
        report["preparation_seconds"] = time.monotonic() - started
        save(output, report)
    except Exception as exc:
        _failure(report, "preparation_failed", stage, work, exc)
        return _finish(output, report, started, "preparation_failed")

    predictions = {}
    private_inputs, private_outputs = work / "inputs", work / "predictions"
    inference_tick = time.monotonic()
    for index, case in enumerate(prepared):
        row = report["cases"][index]
        tick, stage = time.monotonic(), "source_receipt"
        try:
            receipt_sha = _public_component(case["receipt"], private_roots)
            candidate = {**row, "receipt": copy.deepcopy(case["receipt"]), "source_receipt_sha256": receipt_sha}
            rows = list(report["cases"])
            rows[index] = candidate
            _check_report_budget({**report, "cases": rows})
            row.update(candidate)
            if case["receipt"]["status"] != "complete":
                row["status"] = "source_failed"
                save(output, report)
                continue
            stage = "input_preservation"
            input_bytes = encoded(_observation_payload(case))
            before = digest(input_bytes)
            if len(input_bytes) > MAX_PREDICTION_BYTES:
                raise ValueError("private observation exceeds its declared size bound")
            filename = digest(case["id"].encode()) + ".json"
            _atomic_write(private_inputs / filename, input_bytes)
            row.update(input_file_sha256=before, input_event_count=len(case["events"]))
            stage = "inference"
            isolated_events = copy.deepcopy(case["events"])
            with (work / "inference.log").open("a") as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                prediction = deps.infer_repeated_performance(isolated_events, case["length_q"])
            if not isinstance(prediction, dict) or set(prediction.get("arms", {})) != set(ARMS):
                raise ValueError("inference did not preserve the six predeclared arms")
            stage = "input_preservation"
            passed_case = {"events": isolated_events, "length_q": case["length_q"]}
            if (digest(encoded(_observation_payload(case))) != before
                    or digest(encoded(_observation_payload(passed_case))) != before):
                raise ValueError("inference modified original performed events")
            raw = encoded(prediction)
            if (len(raw) > MAX_PREDICTION_BYTES
                    or report["private_prediction_bytes"] + len(raw) > MAX_ALL_PREDICTION_BYTES):
                raise ValueError("private prediction exceeds its declared size budget")
            _atomic_write(private_outputs / filename, raw)
            predictions[case["id"]] = copy.deepcopy(prediction)
            row.update(status="inferred", prediction_file_sha256=digest(raw), prediction_bytes=len(raw),
                       event_mutation_check_passed=True, arm_names=list(ARMS))
            report["private_prediction_bytes"] += len(raw)
            report["completed_inferences"] += 1
            report["completed_preservation_checks"] += 1
        except Exception as exc:
            _failure(row, "failed", stage, work, exc)
        row["inference_seconds"] = time.monotonic() - tick
        save(output, report)
        if (index + 1) % 25 == 0 or row["status"] != "inferred" or index + 1 == len(prepared):
            print(index + 1, "/", len(prepared), row["id"], row["status"], flush=True)
    report["inference_seconds"] = time.monotonic() - inference_tick
    if report["completed_inferences"] != report["planned_inferences"]:
        return _finish(output, report, started, "incomplete")
    report["all_predictions_saved_before_evaluation"] = True
    report["prediction_set_sha256"] = digest(encoded([
        {"id": row["id"], "input_file_sha256": row["input_file_sha256"],
         "prediction_file_sha256": row["prediction_file_sha256"]} for row in report["cases"]
    ]))
    save(output, report)

    try:
        # Every cohort prediction is immutable before any evaluation loader runs.
        report["evaluation_loading_started"] = True
        save(output, report)
        evaluation_map = {}
        with (work / "evaluation.log").open("w") as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            for scope in SYNTHETIC_SCOPES:
                stage = scope + "_evaluation_loading"
                labels = deps.synthetic[scope].load_evaluation()
                _accept_evaluation_population(report, scope, labels)
                evaluation_map.update(labels)
                report["evaluation_loaded"][scope] = True
                save(output, report)
            for scope in REAL_SCOPES:
                stage = scope + "_evaluation_loading"
                evaluation_cases = copy.deepcopy(source_cases[scope])
                loaded = deps.sources[scope].load_evaluation(source_work[scope], evaluation_cases)
                _assert_frozen(evaluation_cases, None, report, plan[scope], NATIVE_REAL_SCOPES[scope])
                labels, receipt = loaded["cases"], loaded["source_receipt"]
                if not isinstance(labels, dict) or set(labels) != set(plan[scope]):
                    raise ValueError("real evaluation population changed")
                _validate_source_receipt(receipt, manifests[scope], list(labels.values()), "evaluation",
                                         report["source_acquisition"][scope]["inputs"], require_full_coverage=False)
                _attach_acquisition(report, scope, "evaluation", receipt, private_roots)
                _validate_source_receipt(receipt, manifests[scope], list(labels.values()), "evaluation",
                                         report["source_acquisition"][scope]["inputs"])
                _accept_evaluation_population(report, scope, labels)
                evaluation_map.update(labels)
                report["evaluation_loaded"][scope] = True
                save(output, report)
            _assert_frozen(prepared, predictions, report)
            if set(evaluation_map) != set(report["planned_ids"]):
                raise ValueError("combined evaluation population changed")
            stage = "evaluation"
            report["evaluation_started"] = True
            save(output, report)
            evaluated_cases, evaluated_predictions = copy.deepcopy(prepared), copy.deepcopy(predictions)
            evaluation = deps.evaluate_study(evaluated_cases, evaluated_predictions, copy.deepcopy(evaluation_map))
            _assert_frozen(evaluated_cases, evaluated_predictions, report)
            _assert_frozen(prepared, predictions, report)
        if (not isinstance(evaluation, dict) or not {"cohorts", "limitations"} <= set(evaluation)
                or not isinstance(evaluation["cohorts"], dict) or set(evaluation["cohorts"]) != set(SCOPES)):
            raise ValueError("evaluation must preserve all four cohorts and their limitations")
        _public_component(evaluation, private_roots, MAX_EVALUATION_BYTES)
        summary = {scope: evaluation["cohorts"][scope]["summary"] for scope in SCOPES}
        if not all(isinstance(value, dict) for value in summary.values()):
            raise ValueError("all four complete-cohort summaries are required")
        _public_component(summary, private_roots)
        _check_report_budget({**report, "evaluation": evaluation, "summary": summary})
        report["evaluation"] = copy.deepcopy(evaluation)
        report["evaluation_sha256"] = digest(encoded(evaluation))
        report["summary"] = copy.deepcopy(summary)
        status = "complete"
    except Exception as exc:
        _failure(report, "evaluation_failed", stage, work, exc)
        report["evaluation"] = report["summary"] = None
        status = "evaluation_failed"
    return _finish(output, report, started, status)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    return run(args.work, args.output)


if __name__ == "__main__":
    raise SystemExit(main())

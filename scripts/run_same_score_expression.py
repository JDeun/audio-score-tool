"""Freeze every synthetic and real same-score prediction before loading evaluation.

Only events and the fixed analysis length enter inference. Full predictions and
original source data stay private; the published receipt contains identities,
preservation checks, failures and the separately scoped evaluation metadata.
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
DECLARED_BASE_REVISION = "61b77bec85d60733aac5af751ae272fa33e60daf"
SCOPES = ("synthetic_exact_onsets", "real_same_score")
EXPECTED_SCOPE_COUNTS = {"synthetic_exact_onsets": 484, "real_same_score": 4}
ARMS = ("straight_narrow", "straight_wide", "global_phase", "local_raw",
        "local_switch005", "local_switch010")
EVENT_FIELDS = {"event_id", "pitch", "onset_q", "velocity"}
MAX_REPORT_BYTES = 8_000_000
MAX_METADATA_COMPONENT_BYTES = 1_000_000
MAX_EVALUATION_BYTES = 7_000_000
MAX_PREDICTION_BYTES = 2_000_000
MAX_ALL_PREDICTION_BYTES = 256_000_000
MAX_EVENTS_PER_CASE = 10_000
MAX_SOURCE_NETWORK_BYTES = 2_241_212
MAX_SOURCE_HTTP_REQUESTS = 25
NEW_SOURCE_PATHS = (
    "scripts/same_score_phase.py",
    "scripts/nasap_same_score_source.py",
    "scripts/same_score_expression_study.py",
    "scripts/run_same_score_expression.py",
    "scripts/nasap_same_score_manifest.json",
    "tests/test_same_score_phase.py",
    "tests/test_nasap_same_score_source.py",
    "tests/test_same_score_expression_study.py",
    "tests/test_run_same_score_expression.py",
    ".github/workflows/cpu-same-score-expression.yml",
    "docs/research/SAME_SCORE_EXPRESSION_PROTOCOL_2026-11-12.md",
    "scripts/research_test_manifest.json",
)
# Literal pins from actual main 61b77bec; no prior result receipt is read to derive these.
FROZEN_SOURCE_SHA256 = {
    "scripts/performed_rhythm_invariance.py": "7f42567f97a5b5b51053bcd9e9a5a9859701190971d33df4c308af5f0f11ab22",
    "scripts/rhythm_invariance_study.py": "adcf66f68514c844f33e9f3b77cfd1a658d7a965bd4226fa6cc0a9532d503e45",
    "scripts/nasap_joint_rhythm.py": "e2f136d486c0ef14206469db1a4b1c7a5dfc5dfcd55de3c3a80df2f6f5263681",
    "scripts/nasap_duration_probe.py": "881a0a7544745d5fe50317ca81bca8ea05adce510bbfb2facc46405c65ffa973",
    "scripts/nasap_keyoff_paired.py": "97368c713177ac5537a6c22f57689d375260674a36efe5b92cbfbd64131a641a",
    "scripts/audit_nasap_duration_source.py": "c63c44b2a6c5a391d972b22417cba21830b71c0bed2dd6996b38f9f93044244c",
}
MEASURED_SOURCE_PATHS = NEW_SOURCE_PATHS + tuple(FROZEN_SOURCE_SHA256)


@dataclass(frozen=True)
class Dependencies:
    synthetic_plan: Callable
    load_source_manifest: Callable
    prepare_synthetic_inputs: Callable
    prepare_inputs: Callable
    infer_performance: Callable
    load_synthetic_evaluation: Callable
    load_evaluation: Callable
    evaluate_study: Callable


def _dependencies():
    from scripts.nasap_same_score_source import load_evaluation, load_manifest, prepare_inputs
    from scripts.same_score_expression_study import (
        evaluate_study,
        load_synthetic_evaluation,
        prepare_synthetic_inputs,
        synthetic_plan,
    )
    from scripts.same_score_phase import infer_performance

    return Dependencies(synthetic_plan, load_manifest, prepare_synthetic_inputs, prepare_inputs,
                        infer_performance, load_synthetic_evaluation, load_evaluation, evaluate_study)



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
                 "full_selected_assignments", "diagnostic_assignments"}

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
    # All 488 planned rows already exist; reserve enough for bounded failures on every row.
    reserve = min(512_000, MAX_REPORT_BYTES // 10)
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
    synthetic = list(deps.synthetic_plan())
    manifest = deps.load_source_manifest()
    real = [row["id"] for row in manifest["cases"]]
    scopes = dict(zip(SCOPES, (synthetic, real), strict=True))
    all_ids = synthetic + real
    if (any(len(scopes[scope]) != EXPECTED_SCOPE_COUNTS[scope] for scope in SCOPES)
            or any(not isinstance(tid, str) or not 0 < len(tid) <= 200 for tid in all_ids)
            or len(set(all_ids)) != len(all_ids)):
        raise ValueError("predeclared scope population or case identity changed")
    return scopes, manifest


def _observation_payload(case):
    events, length = case["events"], case["length_q"]
    if (not isinstance(events, tuple) or not 0 < len(events) <= MAX_EVENTS_PER_CASE
            or not isinstance(length, (int, float)) or isinstance(length, bool)
            or not math.isfinite(length) or length <= 0):
        raise ValueError("bounded event tuple and positive quarter-note length required")
    rows = []
    for event in events:
        if not is_dataclass(event):
            raise ValueError("inference requires the declared event dataclass")
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
        raise ValueError("prepared cases must preserve the full ordered scope without evaluation fields")


def _validate_source_receipt(receipt, manifest, cases, stage, previous=None):
    members, budget = manifest["members"], manifest["budget"]
    expected_inputs = {row[key] for row in manifest["cases"] for key in ("midi", "performance_annotations")}
    expected = expected_inputs if stage == "inputs" else set(members)
    complete = sum(case["receipt"]["status"] == "complete" for case in cases)
    if (budget["member_count"] != len(members)
            or budget["total_bytes"] != sum(item["bytes"] for item in members.values())
            or budget["input_member_count"] != len(expected_inputs)
            or budget["input_bytes"] != sum(members[path]["bytes"] for path in expected_inputs)
            or budget["total_bytes"] > MAX_SOURCE_NETWORK_BYTES
            or budget["member_count"] > MAX_SOURCE_HTTP_REQUESTS
            or receipt["stage"] != stage
            or receipt["planned_recordings"] != len(cases)
            or receipt["complete_recordings"] != complete
            or receipt["failed_recordings"] != len(cases) - complete
            or receipt["full_source_member_count"] != len(members)
            or receipt["full_source_bytes"] != budget["total_bytes"]
            or receipt["verified_member_count"] != len(expected)
            or set(receipt["members"]) != expected):
        raise ValueError("source scope, stage coverage or fixed budget changed")
    for path in expected:
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


def _assert_frozen(cases, predictions, report):
    rows = {row["id"]: row for row in report["cases"]}
    expected = report["planned_scopes"][SCOPES[1]] if predictions is None else report["planned_ids"]
    if [case["id"] for case in cases] != expected:
        raise ValueError("evaluation changed the frozen observation population or order")
    for case in cases:
        if digest(encoded(_observation_payload(case))) != rows[case["id"]]["input_file_sha256"]:
            raise ValueError("evaluation modified a frozen inference observation")
    if predictions is not None:
        if set(predictions) != set(rows):
            raise ValueError("evaluation changed the frozen prediction population")
        for tid, prediction in predictions.items():
            if digest(encoded(prediction)) != rows[tid]["prediction_file_sha256"]:
                raise ValueError("evaluation modified a frozen prediction")


def run(work, output, *, deps=None):
    work, output = _prepare_paths(work, output)
    started = time.monotonic()
    private_roots = (ROOT, work, output)
    report = {
        "schema_version": 1, "status": "running", "planned_ids": [], "planned_scopes": {},
        "expected_scope_case_counts": dict(EXPECTED_SCOPE_COUNTS), "cases": [],
        "planned_inferences": sum(EXPECTED_SCOPE_COUNTS.values()),
        "completed_inferences": 0, "completed_preservation_checks": 0,
        "private_prediction_bytes": 0, "evaluation_started": False,
        "all_predictions_saved_before_evaluation": False, "evaluation": None, "summary": None,
        "evaluation_loading_started": False, "synthetic_evaluation_loaded": False,
        "real_evaluation_loaded": False,
        "source_head": os.getenv("EXPERIMENT_HEAD", "local"),
        "source_revision": os.getenv("GITHUB_SHA", "local"),
        "declared_base_revision": DECLARED_BASE_REVISION, "source_sha256": {}, "runtime": {},
        "workflow_run_id": os.getenv("GITHUB_RUN_ID"),
        "workflow_run_attempt": os.getenv("GITHUB_RUN_ATTEMPT"),
        "policy": {
            "inference_inputs": ["event_id", "pitch", "onset_q", "velocity", "length_q"],
            "group_labels_or_score_alignment_passed_to_inference": False,
            "real_inputs_use_supplied_annotated_clock": True,
            "real_midi_timebase_is_not_score_quarter_clock": True,
            "synthetic_and_real_denominators_are_separate": True,
            "synthetic_network_access": False, "model_inferences": 0, "training": False,
            "preservation_check": "event mutation checks and retained source identity; no MIDI export roundtrip",
            "audio_transcription_or_listening_quality_measured": False,
            "real_evaluation_uses_shared_score_and_publisher_alignment": True,
            "full_durations_rests_and_engraving_validated": False,
            "automatic_product_correction_enabled": False,
            "raw_sources_events_or_full_predictions_published": False,
        },
    }
    save(output, report)
    stage = "provenance"
    try:
        report.update(collect_provenance())
        save(output, report)
        deps = deps if deps is not None else _dependencies()
        stage = "planning"
        plan, manifest = _plan(deps)
        report["planned_scopes"] = plan
        report["planned_ids"] = [tid for scope in SCOPES for tid in plan[scope]]
        report["plan_sha256"] = digest(encoded(plan))
        report["cases"] = [{"id": tid, "scope": scope, "status": "planned", "receipt": None,
                            "input_file_sha256": None, "prediction_file_sha256": None,
                            "event_mutation_check_passed": False}
                           for scope in SCOPES for tid in plan[scope]]
        _check_report_budget(report)
        save(output, report)
        stage = "synthetic_preparation"
        with (work / "preparation.log").open("w") as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            synthetic = deps.prepare_synthetic_inputs()
            _validate_prepared(synthetic, plan[SCOPES[0]], SCOPES[0])
            stage = "real_source_preparation"
            real_work = work / "nasap-sources"
            real = deps.prepare_inputs(real_work)
            _validate_prepared(real["cases"], plan[SCOPES[1]], SCOPES[1])
            _validate_source_receipt(real["source_receipt"], manifest, real["cases"], "inputs")
        _public_component(real["source_receipt"], private_roots)
        _check_report_budget({**report, "source_acquisition": {"inputs": real["source_receipt"]}})
        report["source_acquisition"] = {"inputs": copy.deepcopy(real["source_receipt"])}
        prepared = synthetic + real["cases"]
        report["preparation_seconds"] = time.monotonic() - started
        save(output, report)
    except Exception as exc:
        _failure(report, "preparation_failed", stage, work, exc)
        return _finish(output, report, started, "preparation_failed")

    predictions = {}
    private_inputs = work / "inputs"
    private_outputs = work / "predictions"
    inference_tick = time.monotonic()
    for index, case in enumerate(prepared):
        row = report["cases"][index]
        tick = time.monotonic()
        stage = "source_receipt"
        try:
            _public_component(case["receipt"], private_roots)
            candidate = {**row, "receipt": copy.deepcopy(case["receipt"])}
            rows = list(report["cases"])
            rows[index] = candidate
            _check_report_budget({**report, "cases": rows})
            row.update(candidate)
            if case["receipt"]["status"] != "complete":
                row["status"] = "source_failed"
                save(output, report)
                continue
            stage = "input_preservation"
            observations = _observation_payload(case)
            input_bytes = encoded(observations)
            before = digest(input_bytes)
            if len(input_bytes) > MAX_PREDICTION_BYTES:
                raise ValueError("private observation exceeds its declared size bound")
            filename = digest(case["id"].encode()) + ".json"
            _atomic_write(private_inputs / filename, input_bytes)
            row["input_file_sha256"] = before
            row["input_event_count"] = len(case["events"])
            stage = "inference"
            isolated_events = copy.deepcopy(case["events"])
            with (work / "inference.log").open("a") as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                prediction = deps.infer_performance(isolated_events, case["length_q"])
            if not isinstance(prediction, dict) or set(prediction.get("arms", {})) != set(ARMS):
                raise ValueError("inference did not preserve the six declared arms")
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
        # Actual score/alignment semantics first enter this runner after all predictions are saved.
        stage = "synthetic_evaluation_loading"
        report["evaluation_loading_started"] = True
        save(output, report)
        with (work / "evaluation.log").open("w") as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            synthetic_evaluation = deps.load_synthetic_evaluation()
            if not isinstance(synthetic_evaluation, dict) or set(synthetic_evaluation) != set(plan[SCOPES[0]]):
                raise ValueError("synthetic evaluation population changed")
            report["synthetic_evaluation_loaded"] = True
            save(output, report)
            stage = "real_evaluation_loading"
            evaluation_cases = copy.deepcopy(real["cases"])
            real_evaluation = deps.load_evaluation(real_work, evaluation_cases)
            if (not isinstance(real_evaluation, dict) or not isinstance(real_evaluation.get("cases"), dict)
                    or set(real_evaluation["cases"]) != set(plan[SCOPES[1]])):
                raise ValueError("real evaluation population changed")
            _assert_frozen(evaluation_cases, None, report)
            receipt = real_evaluation["source_receipt"]
            _validate_source_receipt(receipt, manifest, real["cases"], "evaluation", real["source_receipt"])
            _public_component(receipt, private_roots)
            acquisition = {**report["source_acquisition"], "evaluation": copy.deepcopy(receipt),
                           "http_requests": receipt["http_requests"] + real["source_receipt"]["http_requests"],
                           "downloaded_bytes": receipt["downloaded_bytes"] + real["source_receipt"]["downloaded_bytes"]}
            _check_report_budget({**report, "source_acquisition": acquisition})
            report["source_acquisition"] = acquisition
            report["real_evaluation_loaded"] = True
            _assert_frozen(prepared, predictions, report)
            evaluation_map = {**synthetic_evaluation, **real_evaluation["cases"]}
            stage = "evaluation"
            report["evaluation_started"] = True
            save(output, report)
            evaluated_cases, evaluated_predictions = copy.deepcopy(prepared), copy.deepcopy(predictions)
            evaluation = deps.evaluate_study(evaluated_cases, evaluated_predictions, copy.deepcopy(evaluation_map))
            _assert_frozen(evaluated_cases, evaluated_predictions, report)
            _assert_frozen(prepared, predictions, report)
        if not isinstance(evaluation, dict) or not {"synthetic", "real", "limitations"} <= set(evaluation):
            raise ValueError("evaluation must preserve both scopes and their limitations")
        _public_component(evaluation, private_roots, MAX_EVALUATION_BYTES)
        summary = {"synthetic": evaluation["synthetic"]["summary"], "real": evaluation["real"]["summary"]}
        if not all(isinstance(value, dict) for value in summary.values()):
            raise ValueError("both complete-scope summaries are required")
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

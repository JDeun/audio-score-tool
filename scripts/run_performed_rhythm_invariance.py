"""Run the frozen synthetic and same-groove studies before exposing evaluation.

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
DECLARED_BASE_REVISION = "3023db6ce3e3544b189716ffc9d0836c569dff2a"
SCOPES = ("synthetic_exact_onsets", "real_same_groove")
EXPECTED_SCOPE_COUNTS = {"synthetic_exact_onsets": 484, "real_same_groove": 40}
ARMS = ("straight_narrow", "straight_wide", "phase_aware")
EVENT_FIELDS = {"event_id", "instrument", "onset_q", "velocity"}
MAX_REPORT_BYTES = 8_000_000
MAX_METADATA_COMPONENT_BYTES = 1_000_000
MAX_EVALUATION_BYTES = 7_000_000
MAX_PREDICTION_BYTES = 2_000_000
MAX_ALL_PREDICTION_BYTES = 256_000_000
MAX_EVENTS_PER_CASE = 10_000
MAX_SOURCE_NETWORK_BYTES = 3_260_318
MEASURED_SOURCE_PATHS = (
    "scripts/performed_rhythm_invariance.py",
    "scripts/gmd_same_groove_source.py",
    "scripts/rhythm_invariance_study.py",
    "scripts/run_performed_rhythm_invariance.py",
    "scripts/gmd_same_groove_manifest.json",
    "tests/test_performed_rhythm_invariance.py",
    "tests/test_gmd_same_groove_source.py",
    "tests/test_rhythm_invariance_study.py",
    "tests/test_run_performed_rhythm_invariance.py",
    ".github/workflows/cpu-performed-rhythm-invariance.yml",
    "docs/research/PERFORMED_RHYTHM_INVARIANCE_PROTOCOL_2026-11-12.md",
    "scripts/research_test_manifest.json",
)


@dataclass(frozen=True)
class Dependencies:
    synthetic_plan: Callable
    load_source_manifest: Callable
    prepare_synthetic: Callable
    prepare_real: Callable
    infer_take: Callable
    evaluate_study: Callable


def _dependencies():
    from scripts.gmd_same_groove_source import load_manifest, prepare_real
    from scripts.performed_rhythm_invariance import infer_take
    from scripts.rhythm_invariance_study import evaluate_study, prepare_synthetic, synthetic_plan

    return Dependencies(synthetic_plan, load_manifest, prepare_synthetic, prepare_real,
                        infer_take, evaluate_study)


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
        "runtime": {"implementation": platform.python_implementation(),
                    "python": platform.python_version(), "packages": packages,
                    "analysis_standard_library_only": True, "model_inferences": 0},
    }


def _public_component(value, private_roots, limit=MAX_METADATA_COMPONENT_BYTES):
    raw = encoded(value)
    if len(raw) > limit:
        raise ValueError("public metadata component exceeds its declared size bound")
    forbidden = {"events", "raw_events", "event_arrays", "raw_midi", "raw_bytes", "assignments",
                 "private_predictions", "prediction_events", "audio_samples", "waveform"}

    def visit(item):
        if isinstance(item, dict):
            for key, child in item.items():
                if isinstance(key, str) and (key in forbidden or key.endswith(("_path", "_paths"))):
                    raise ValueError("private source or prediction field in public metadata")
                visit(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                visit(child)
        elif isinstance(item, str) and any(str(root) in item for root in private_roots):
            raise ValueError("private filesystem location in public metadata")

    visit(value)
    return digest(raw)


def _check_report_budget(report):
    # All 524 planned rows already exist; reserve enough for bounded failures on every row.
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
    return scopes


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
    if (not isinstance(cases, list) or [case["id"] for case in cases] != planned
            or any(case["scope"] != scope or not isinstance(case["receipt"], dict)
                   or case["receipt"].get("status") not in {"complete", "failed"} for case in cases)):
        raise ValueError("prepared source cases do not preserve the full ordered scope")


def _validate_source_receipt(real):
    receipt, cases = real["source_receipt"], real["cases"]
    complete = sum(case["receipt"]["status"] == "complete" for case in cases)
    if (receipt["planned_recordings"] != len(cases)
            or receipt["complete_recordings"] != complete
            or receipt["failed_recordings"] != len(cases) - complete
            or receipt["verified_member_count"] != len(cases) + 1
            or type(receipt["downloaded_bytes"]) is not int
            or not 0 <= receipt["downloaded_bytes"] <= MAX_SOURCE_NETWORK_BYTES
            or type(receipt["http_requests"]) is not int or not 0 <= receipt["http_requests"] <= 1):
        raise ValueError("real source acquisition coverage or bounded network receipt changed")


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
        "source_head": os.getenv("EXPERIMENT_HEAD", "local"),
        "source_revision": os.getenv("GITHUB_SHA", "local"),
        "declared_base_revision": DECLARED_BASE_REVISION, "source_sha256": {}, "runtime": {},
        "workflow_run_id": os.getenv("GITHUB_RUN_ID"),
        "workflow_run_attempt": os.getenv("GITHUB_RUN_ATTEMPT"),
        "policy": {
            "inference_inputs": ["event_id", "instrument", "onset_q", "velocity", "length_q"],
            "group_labels_or_bpm_passed_to_inference": False,
            "synthetic_and_real_denominators_are_separate": True,
            "synthetic_network_access": False, "model_inferences": 0, "training": False,
            "preservation_check": "event mutation checks and retained source identity; no MIDI export roundtrip",
            "audio_transcription_or_listening_quality_measured": False,
            "real_data_has_canonical_notation_ground_truth": False,
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
        plan = _plan(deps)
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
            synthetic = deps.prepare_synthetic()
            _validate_prepared(synthetic, plan[SCOPES[0]], SCOPES[0])
            stage = "real_source_preparation"
            real = deps.prepare_real(work / "gmd-sources")
            _validate_prepared(real["cases"], plan[SCOPES[1]], SCOPES[1])
            _validate_source_receipt(real)
        _public_component(real["source_receipt"], private_roots)
        _check_report_budget({**report, "source_acquisition": real["source_receipt"]})
        report["source_acquisition"] = copy.deepcopy(real["source_receipt"])
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
                prediction = deps.infer_take(isolated_events, case["length_q"])
            if (not isinstance(prediction, dict) or set(prediction.get("arms", {})) != set(ARMS)
                    or not isinstance(prediction.get("fits"), list) or len(prediction["fits"]) != 4):
                raise ValueError("inference did not preserve the declared arms and phase fits")
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
                       event_mutation_check_passed=True, fit_count=4, arm_names=list(ARMS))
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
        # Evaluation-only labels and references are used only after every prediction is saved.
        report["evaluation_started"] = True
        save(output, report)
        with (work / "evaluation.log").open("w") as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            evaluation = deps.evaluate_study(copy.deepcopy(prepared), copy.deepcopy(predictions))
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
        _failure(report, "evaluation_failed", "evaluation", work, exc)
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

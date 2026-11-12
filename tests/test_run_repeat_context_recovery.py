"""Small invented replay files exercise recovery without a cohort or network run."""
from __future__ import annotations

import copy
import json
import zipfile
from dataclasses import dataclass, replace
from typing import Callable

import pytest

from scripts import run_repeat_context as legacy
from scripts import run_repeat_context_recovery as recovery
from scripts.same_score_phase import OnsetEvent


@dataclass(frozen=True)
class FakeLegacyDependencies:
    evaluate_study: Callable


def fixture(tmp_path, *, before=None, after=None, evaluate=None, exit_kind="budget"):
    plan = {scope: [f"toy{i}"] for i, scope in enumerate(legacy.SCOPES)}
    cases, predictions, rows, input_bytes, prediction_bytes = [], {}, [], {}, {}
    for i, (scope, ids) in enumerate(plan.items()):
        tid = ids[0]
        # Numeric native histogram keys deliberately have a different lexical order.
        receipt = {"status": "complete", "velocity_histogram": {2: 1, 10: 1}}
        case = {"id": tid, "scope": scope, "length_q": 4.0, "receipt": receipt,
                "events": (OnsetEvent("e1", 60, 0.0, 2), OnsetEvent("e2", 64, 0.75, 10))}
        prediction = {"fits": [{"phase": [1, 2], "cost": 0.0}],
                      "arms": {arm: {"status": "abstained", "toy": i} for arm in legacy.ARMS}}
        input_raw, prediction_raw = legacy.encoded(legacy._observation_payload(case)), legacy.encoded(prediction)
        input_bytes[tid], prediction_bytes[tid] = input_raw, prediction_raw
        cases.append(case)
        predictions[tid] = prediction
        rows.append({"id": tid, "scope": scope, "status": "inferred", "evaluation_status": "complete",
                     "event_mutation_check_passed": True, "input_event_count": 2,
                     "input_file_sha256": legacy.digest(input_raw), "prediction_file_sha256": legacy.digest(prediction_raw),
                     "prediction_bytes": len(prediction_raw), "receipt": copy.deepcopy(receipt),
                     "source_receipt_sha256": legacy.digest(legacy.encoded(receipt))})
    source = {scope: {stage: {"members": {"toy.mid": {"bytes": 10, "sha256": "a" * 64}}}
                      for stage in ("inputs", "evaluation")} for scope in legacy.REAL_SCOPES}
    original = {
        "schema_version": 1, "status": "evaluation_failed", "failure_stage": "evaluation",
        "error_type": "ValueError", "reason": "Original known budget failure.",
        "planned_scopes": plan, "planned_ids": [row["id"] for row in rows], "cases": rows,
        "expected_scope_case_counts": {scope: 1 for scope in plan},
        "planned_inferences": 4, "completed_inferences": 4, "completed_preservation_checks": 4,
        "all_predictions_saved_before_evaluation": True, "evaluation_started": True,
        "evaluation_loaded": {scope: True for scope in plan}, "evaluation": None, "summary": None,
        "source_head": recovery.ORIGINAL_HEAD, "checkout_revision": recovery.ORIGINAL_CHECKOUT,
        "checkout_tree": recovery.ORIGINAL_TREE, "source_sha256": dict(recovery.CONTRACT.original_source_sha256),
        "workflow_run_id": recovery.ORIGINAL_RUN_ID, "workflow_run_attempt": "1",
        "plan_sha256": legacy.digest(legacy.encoded(plan)),
        "prediction_set_sha256": legacy.digest(legacy.encoded([
            {key: row[key] for key in ("id", "input_file_sha256", "prediction_file_sha256")} for row in rows])),
        "private_prediction_bytes": sum(row["prediction_bytes"] for row in rows),
        "source_acquisition": source, "elapsed_seconds": 1.0,
    }
    archive = tmp_path / "original-failure.zip"
    report_bytes = legacy.encoded(original)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("report.json", report_bytes)
    contract = replace(recovery.CONTRACT, archive=archive, archive_bytes=archive.stat().st_size,
                       archive_sha256=legacy.digest(archive.read_bytes()), report_bytes=len(report_bytes),
                       report_sha256=legacy.digest(report_bytes),
                       planned_scopes=tuple((scope, tuple(ids)) for scope, ids in plan.items()))
    calls = {"legacy": 0, "evaluate": 0}
    value = {"cohorts": {scope: {"summary": {"cases": 1, "correct": 0, "abstained": 1},
                                "case_rows": [{"id": ids[0], "target_notes": 2, "reference_masks": {"status": "AA"}}]}
                        for scope, ids in plan.items()},
             "baseline_parity": {"toy_only": True}, "limitations": ["Invented metadata; no performance claim."]}

    def evaluator(native_cases, native_predictions, labels):
        calls["evaluate"] += 1
        public = json.loads((tmp_path / "public" / "report.json").read_bytes())
        assert public["recovery"]["matched_input_files"] == public["recovery"]["matched_prediction_files"] == 4
        assert labels == {tid: {"secret_truth": "PRIVATE-LABEL"} for tid in predictions}
        assert native_cases[0]["receipt"]["velocity_histogram"] == {2: 1, 10: 1}
        if evaluate is not None:
            return evaluate(native_cases, native_predictions, labels, copy.deepcopy(value))
        return copy.deepcopy(value)

    def executor(work, output, *, deps):
        calls["legacy"] += 1
        work.mkdir()
        for directory, raw_by_id in (("inputs", input_bytes), ("predictions", prediction_bytes)):
            (work / directory).mkdir()
            for tid, raw in raw_by_id.items():
                (work / directory / (legacy.digest(tid.encode()) + ".json")).write_bytes(raw)
        replay = copy.deepcopy(original)
        replay.update(status="running", source_head="recovery-head", workflow_run_id="recovery-run")
        replay["source_sha256"]["scripts/research_test_manifest.json"] = "f" * 64
        for key in ("failure_stage", "error_type", "reason"):
            replay.pop(key)
        native_cases, native_predictions = copy.deepcopy(cases), copy.deepcopy(predictions)
        try:
            if before is not None:
                before(work, replay)
            legacy._atomic_write(output, legacy.encoded(replay))
            result = deps.evaluate_study(native_cases, native_predictions,
                                         {tid: {"secret_truth": "PRIVATE-LABEL"} for tid in predictions})
            if after is not None:
                after(work, replay, result, native_cases, native_predictions)
            if exit_kind == "success":
                replay.update(status="complete", evaluation=result,
                              summary={scope: result["cohorts"][scope]["summary"] for scope in plan})
                legacy._atomic_write(output, legacy.encoded(replay))
                return 0
            if exit_kind == "other_failure":
                raise ValueError("PRIVATE-UNRELATED-FAILURE " + str(work))
            raise ValueError("combined public metadata exceeds the report budget")
        except Exception as exc:
            # Exercise the real frozen writer, including its trailing empty line.
            legacy._failure(replay, "evaluation_failed", "evaluation", work, exc)
            replay["evaluation"] = replay["summary"] = None
            legacy._atomic_write(output, legacy.encoded(replay))
            return 1

    def provenance():
        return {"source_head": "recovery-head", "checkout_revision": "recovery-checkout",
                "source_sha256": {"new-recovery.py": "b" * 64}}

    deps = recovery.Dependencies(executor, lambda: FakeLegacyDependencies(evaluator), provenance)
    return deps, contract, calls, original, value


def execute(tmp_path, deps, contract):
    work, output = tmp_path / "private", tmp_path / "public" / "report.json"
    code = recovery.run(work, output, deps=deps, contract=contract)
    return code, json.loads(output.read_bytes()), work, output


def test_single_original_execution_and_evaluation_publish_only_compact_json_after_exact_file_parity(tmp_path):
    deps, contract, calls, original, value = fixture(tmp_path)
    code, report, work, output = execute(tmp_path, deps, contract)
    assert code == 0 and report["status"] == "complete" and calls == {"legacy": 1, "evaluate": 1}
    assert report["evaluation"] == value
    assert report["evaluation_sha256"] == legacy.digest(legacy.encoded(value))
    assert report["recovery"]["matched_input_files"] == report["recovery"]["matched_prediction_files"] == 4
    assert report["recovery"]["parity_rechecked_after_evaluation"]
    assert report["recovery"]["original_failure"]["status"] == "evaluation_failed"
    assert report["recovery"]["replayed_legacy_failure"]["known_budget_failure_verified"]
    assert report["summary"]["additional_real"]["correct"] == 0
    assert output.read_bytes() == recovery.compact(report)
    assert len(output.read_bytes()) < len(legacy.encoded(report)) and output.read_bytes().count(b"\n") == 1
    assert (work / "legacy-run" / "failure.log").read_text().endswith("\n\n")
    assert recovery.read_original(contract)["status"] == "evaluation_failed"
    assert legacy.digest(contract.archive.read_bytes()) == contract.archive_sha256
    assert report["cases"][0]["source_receipt_sha256"] == original["cases"][0]["source_receipt_sha256"]
    assert str(tmp_path) not in output.read_text() and "PRIVATE-LABEL" not in output.read_text()


@pytest.mark.parametrize("change", ["input_file", "prediction_file", "row_and_file", "source_members", "population"])
def test_any_original_row_current_row_or_actual_file_mismatch_blocks_score_computation(tmp_path, change):
    def before(work, report):
        row = report["cases"][0]
        if change in {"input_file", "prediction_file", "row_and_file"}:
            directory = "inputs" if change == "input_file" else "predictions"
            path = work / directory / (legacy.digest(row["id"].encode()) + ".json")
            path.write_bytes(path.read_bytes() + b" ")
            if change == "row_and_file":
                row["prediction_file_sha256"] = legacy.digest(path.read_bytes())
        elif change == "source_members":
            report["source_acquisition"]["additional_real"]["evaluation"]["members"]["toy.mid"]["sha256"] = "b" * 64
        else:
            report["cases"].reverse()

    deps, contract, calls, _, _ = fixture(tmp_path, before=before)
    code, report, _, _ = execute(tmp_path, deps, contract)
    assert code == 1 and report["status"] == "recovery_failed" and calls["evaluate"] == 0
    assert report["summary"] is report["evaluation"] is None
    assert len(report["cases"]) == 4 and report["failure_stage"] == "original_file_parity"


def test_original_archive_digest_mismatch_blocks_evaluation_after_predictions_are_preserved(tmp_path):
    deps, contract, calls, _, _ = fixture(tmp_path)
    contract.archive.write_bytes(contract.archive.read_bytes() + b"unexpected")
    code, report, work, _ = execute(tmp_path, deps, contract)
    assert code == 1 and calls["evaluate"] == 0 and report["summary"] is None
    assert len(list((work / "legacy-run" / "predictions").glob("*.json"))) == 4


@pytest.mark.parametrize("change", ["prediction_file", "input_file", "native_prediction", "captured_evaluation"])
def test_post_evaluation_tampering_cannot_publish_scores(tmp_path, change):
    def after(work, report, value, cases, predictions):
        if change in {"prediction_file", "input_file"}:
            directory = "predictions" if change == "prediction_file" else "inputs"
            path = work / directory / (legacy.digest(cases[0]["id"].encode()) + ".json")
            path.write_bytes(path.read_bytes() + b" ")
        elif change == "native_prediction":
            predictions[cases[0]["id"]]["fits"][0]["cost"] = 99
        else:
            value["cohorts"]["reused_authored"]["summary"]["correct"] = 1

    deps, contract, calls, _, _ = fixture(tmp_path, after=after)
    code, report, _, _ = execute(tmp_path, deps, contract)
    assert code == 1 and calls == {"legacy": 1, "evaluate": 1}
    assert report["status"] == "recovery_failed" and report["failure_stage"] == "post_evaluation_preservation"
    assert report["summary"] is report["evaluation"] is None


@pytest.mark.parametrize("exit_kind", ["other_failure", "success"])
def test_only_the_known_legacy_budget_failure_is_recoverable(tmp_path, exit_kind):
    deps, contract, calls, _, _ = fixture(tmp_path, exit_kind=exit_kind)
    code, report, _, output = execute(tmp_path, deps, contract)
    assert code == 1 and calls["evaluate"] == 1 and report["status"] == "recovery_failed"
    assert report["failure_stage"] == "expected_legacy_failure" and report["summary"] is report["evaluation"] is None
    assert "PRIVATE-UNRELATED" not in output.read_text() and str(tmp_path) not in output.read_text()


@pytest.mark.parametrize("change", ["raw_records", "raw_mask", "missing_cohort", "native_input", "exception", "nan"])
def test_original_evaluation_privacy_mutation_and_completeness_guards_still_apply(tmp_path, change):
    def evaluate(cases, predictions, labels, value):
        if change == "raw_records":
            value["target_notes"] = [{"pitch": 60, "onset_q": 0.0}]
        elif change == "raw_mask":
            value["path_sets"] = {"mask": "ffff"}
        elif change == "missing_cohort":
            value["cohorts"].pop("additional_real")
        elif change == "native_input":
            object.__setattr__(cases[0]["events"][0], "velocity", 99)
        elif change == "exception":
            raise RuntimeError("PRIVATE-LABEL-FAILURE")
        else:
            value["cohorts"]["additional_real"]["summary"]["cost"] = float("nan")
        return value

    deps, contract, calls, _, _ = fixture(tmp_path, evaluate=evaluate)
    code, report, _, output = execute(tmp_path, deps, contract)
    assert code == 1 and calls["evaluate"] == 1 and report["status"] == "recovery_failed"
    assert report["summary"] is report["evaluation"] is None
    assert '"path_sets"' not in output.read_text() and "PRIVATE-LABEL-FAILURE" not in output.read_text()


def test_standalone_evaluation_budget_is_not_relaxed_by_compact_publication(tmp_path):
    deps, contract, calls, _, _ = fixture(tmp_path)
    contract = replace(contract, evaluation_limit=100)
    code, report, _, _ = execute(tmp_path, deps, contract)
    assert code == 1 and calls["evaluate"] == 1 and report["summary"] is report["evaluation"] is None


def test_compact_report_budget_and_failure_reserve_still_prevent_overwrite(tmp_path):
    output = tmp_path / "report.json"
    output.write_text("existing bounded receipt")
    contract = replace(recovery.CONTRACT, report_limit=100)
    with pytest.raises(ValueError, match="original budget and reserve"):
        recovery._save(output, {"metadata": "x" * 100}, contract, ())
    assert output.read_text() == "existing bounded receipt"


def test_provenance_failure_preserves_every_predeclared_case_without_executing_legacy(tmp_path):
    deps, contract, calls, _, _ = fixture(tmp_path)

    def failed():
        raise ValueError("PRIVATE-SOURCE-FILE " + str(tmp_path))

    code, report, _, output = execute(tmp_path, replace(deps, provenance=failed), contract)
    assert code == 1 and calls == {"legacy": 0, "evaluate": 0}
    assert len(report["cases"]) == 4 and report["summary"] is None
    assert report["failure_stage"] == "recovery_provenance" and "PRIVATE-SOURCE" not in output.read_text()


def test_existing_output_is_preserved_before_any_legacy_invocation(tmp_path):
    deps, contract, calls, _, _ = fixture(tmp_path)
    output = tmp_path / "existing.json"
    output.write_text("keep original evidence")
    with pytest.raises(ValueError):
        recovery.run(tmp_path / "work", output, deps=deps, contract=contract)
    assert calls == {"legacy": 0, "evaluate": 0} and output.read_text() == "keep original evidence"

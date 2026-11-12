"""Small invented cohorts exercise runner isolation, ordering and failure receipts."""
from __future__ import annotations

import copy
import dataclasses
import json
from dataclasses import dataclass

import pytest

from scripts import run_same_score_expression as runner


@dataclass(frozen=True)
class Event:
    event_id: str
    pitch: int
    onset_q: float
    velocity: int


def dependencies(tmp_path, monkeypatch):
    timeline, inference_arguments = [], []
    plans = {runner.SCOPES[0]: ["synthetic-a", "synthetic-b"],
             runner.SCOPES[1]: ["real-a", "real-b"]}
    monkeypatch.setattr(runner, "EXPECTED_SCOPE_COUNTS", {scope: 2 for scope in runner.SCOPES})
    monkeypatch.setattr(runner, "collect_provenance", lambda: {
        "source_sha256": {"invented-contract": "0" * 64},
        "checkout_revision": "actual-checkout", "checkout_tree": "actual-tree",
        "checkout_parents": ["declared-base", "frozen-head"],
        "workspace_dirty": False, "runtime": {"model_inferences": 0},
    })
    members = {tid + suffix: {"bytes": 10, "sha256": "1" * 64}
               for tid in plans[runner.SCOPES[1]] for suffix in (".mid", ".tsv")}
    input_members = copy.deepcopy(members)
    members["evaluation.xml"] = {"bytes": 20, "sha256": "2" * 64}
    manifest_value = {
        "members": members,
        "budget": {"member_count": 5, "total_bytes": 60, "input_member_count": 4,
                   "input_bytes": 40, "maximum_member_bytes": 4_000_000},
        "cases": [{"id": tid, "midi": tid + ".mid", "performance_annotations": tid + ".tsv"}
                  for tid in plans[runner.SCOPES[1]]],
    }

    def cases(scope):
        return [{"id": tid, "scope": scope,
                 "events": (Event("e0", 60, 0.0, 60), Event("e1", 67, 0.6, 110)),
                 "length_q": 4.0,
                 "receipt": {"status": "complete", "source_sha256": "1" * 64,
                             "velocity_histogram": {60: 1, 110: 1}}}
                for tid in plans[scope]]

    def source_receipt(stage):
        return {"stage": stage, "planned_recordings": 2, "complete_recordings": 2,
                "failed_recordings": 0, "full_source_member_count": 5, "full_source_bytes": 60,
                "verified_member_count": 4 if stage == "inputs" else 5,
                "members": copy.deepcopy(input_members if stage == "inputs" else members),
                "downloaded_bytes": 40 if stage == "inputs" else 20,
                "http_requests": 4 if stage == "inputs" else 1,
                "cache_hits": 0 if stage == "inputs" else 4}

    def synthetic_plan():
        timeline.append("plan:synthetic")
        return plans[runner.SCOPES[0]]

    def manifest():
        timeline.append("plan:real")
        return copy.deepcopy(manifest_value)

    def prepare_synthetic_inputs():
        timeline.append("prepare:synthetic")
        return cases(runner.SCOPES[0])

    def prepare_inputs(work):
        timeline.append("prepare:real")
        work.mkdir()
        real_cases = [{**case, "status": "complete"} for case in cases(runner.SCOPES[1])]
        return {"cases": real_cases, "source_receipt": source_receipt("inputs")}

    def infer(events, length_q):
        timeline.append("infer")
        assert isinstance(events, tuple) and length_q == 4.0
        assert all(set(dataclasses.asdict(e)) == runner.EVENT_FIELDS for e in events)
        inference_arguments.append((copy.deepcopy(events), length_q))
        return {"fits": [{"phase": list(phase), "assignments": [{"event_id": "e0", "tick": 0}]}
                         for phase in ((1, 2), (3, 5), (2, 3), (3, 4))],
                "arms": {name: {"status": "ambiguous", "selected": None} for name in runner.ARMS}}

    def assert_predictions_saved():
        saved = json.loads((tmp_path / "public" / "report.json").read_bytes())
        assert saved["all_predictions_saved_before_evaluation"] is True
        assert saved["completed_inferences"] == saved["completed_preservation_checks"] == 4
        assert len(saved["cases"]) == 4
        for row in saved["cases"]:
            name = runner.digest(row["id"].encode()) + ".json"
            for kind, field in (("inputs", "input_file_sha256"), ("predictions", "prediction_file_sha256")):
                raw = (tmp_path / "work" / kind / name).read_bytes()
                assert runner.digest(raw) == row[field]
        return saved

    def labels(scope):
        return {tid: {"score_id": "SECRET-SCORE-" + tid, "target_notes": [{"pitch": 60, "tick": 0}]}
                for tid in plans[scope]}

    def load_synthetic_evaluation():
        timeline.append("load:synthetic")
        saved = assert_predictions_saved()
        assert not saved["evaluation_started"] and not saved["real_evaluation_loaded"]
        return labels(runner.SCOPES[0])

    def load_evaluation(work, real_cases):
        timeline.append("load:real")
        assert work == tmp_path / "work" / "nasap-sources"
        assert [case["id"] for case in real_cases] == plans[runner.SCOPES[1]]
        assert all("evaluation" not in case for case in real_cases)
        saved = assert_predictions_saved()
        assert saved["synthetic_evaluation_loaded"] and not saved["evaluation_started"]
        return {"cases": labels(runner.SCOPES[1]), "source_receipt": source_receipt("evaluation")}

    def evaluate(prepared, predictions, evaluation):
        timeline.append("evaluate")
        assert [case["id"] for case in prepared] == [tid for scope in runner.SCOPES for tid in plans[scope]]
        assert set(predictions) == set(evaluation) == {case["id"] for case in prepared}
        assert all("evaluation" not in case for case in prepared)
        saved = assert_predictions_saved()
        assert saved["synthetic_evaluation_loaded"] and saved["real_evaluation_loaded"]
        assert saved["evaluation_started"]
        for case in prepared:
            name = runner.digest(case["id"].encode()) + ".json"
            raw = (tmp_path / "work" / "predictions" / name).read_bytes()
            assert json.loads(raw) == predictions[case["id"]]
            assert evaluation[case["id"]]["score_id"].startswith("SECRET-SCORE")
        return {"synthetic": {"case_rows": [], "summary": {"cases": 2, "correct": 0, "abstained": 2}},
                "real": {"case_rows": [{"evaluation_receipt": {"target_notes": 2}}],
                         "summary": {"cases": 2, "decided": 0}},
                "limitations": ["invented diagnostic only"]}

    deps = runner.Dependencies(synthetic_plan, manifest, prepare_synthetic_inputs, prepare_inputs,
                               infer, load_synthetic_evaluation, load_evaluation, evaluate)
    return deps, timeline, inference_arguments


def execute(tmp_path, deps):
    work, output = tmp_path / "work", tmp_path / "public" / "report.json"
    code = runner.run(work, output, deps=deps)
    return code, json.loads(output.read_bytes()), work, output


def test_all_private_predictions_precede_evaluation_and_labels_never_enter_inference(tmp_path, monkeypatch):
    deps, timeline, seen = dependencies(tmp_path, monkeypatch)
    code, report, _, output = execute(tmp_path, deps)
    assert code == 0 and report["status"] == "complete"
    assert timeline == ["plan:synthetic", "plan:real", "prepare:synthetic", "prepare:real",
                        "infer", "infer", "infer", "infer", "load:synthetic", "load:real", "evaluate"]
    assert report["completed_inferences"] == report["completed_preservation_checks"] == 4
    assert all(row["event_mutation_check_passed"] for row in report["cases"])
    assert report["summary"]["synthetic"]["correct"] == 0  # Completion is not a quality claim.
    assert report["summary"]["synthetic"]["abstained"] == 2
    assert len(seen) == 4 and all(events[0].velocity == 60 for events, _ in seen)
    assert report["source_acquisition"]["http_requests"] == 5
    assert report["source_acquisition"]["downloaded_bytes"] == 60
    assert "SECRET" not in output.read_text() and "assignments" not in output.read_text()
    assert str(tmp_path) not in output.read_text()
    assert report["cases"][0]["receipt"]["velocity_histogram"] == {"60": 1, "110": 1}


@pytest.mark.parametrize("stage", ["provenance", "synthetic_preparation", "real_source_preparation"])
def test_preparation_exception_keeps_a_redacted_receipt_and_no_evaluation(tmp_path, monkeypatch, stage):
    deps, timeline, _ = dependencies(tmp_path, monkeypatch)

    def fail(*args):
        raise RuntimeError("PRIVATE-MIDI " + str(tmp_path / "original.mid"))

    if stage == "provenance":
        monkeypatch.setattr(runner, "collect_provenance", fail)
    else:
        field = "prepare_synthetic_inputs" if stage == "synthetic_preparation" else "prepare_inputs"
        deps = dataclasses.replace(deps, **{field: fail})
    code, report, work, output = execute(tmp_path, deps)
    assert code == 1 and report["status"] == "preparation_failed"
    assert report["failure_stage"] == stage and report["evaluation"] is report["summary"] is None
    assert "infer" not in timeline and "evaluate" not in timeline
    assert len(report["cases"]) == (0 if stage == "provenance" else 4)
    assert "PRIVATE-MIDI" not in output.read_text() and str(tmp_path) not in output.read_text()
    assert "PRIVATE-MIDI" in (work / "failure.log").read_text()


def test_failed_source_row_remains_in_the_denominator_and_blocks_all_evaluation(tmp_path, monkeypatch):
    deps, timeline, _ = dependencies(tmp_path, monkeypatch)
    original = deps.prepare_inputs

    def fail_one(work):
        result = original(work)
        result["cases"][0]["status"] = "failed"
        result["cases"][0]["receipt"] = {"status": "failed", "failure_code": "unsupported_input"}
        result["cases"][0]["events"] = ()
        result["source_receipt"].update(complete_recordings=1, failed_recordings=1)
        return result

    code, report, _, _ = execute(tmp_path, dataclasses.replace(deps, prepare_inputs=fail_one))
    assert code == 1 and report["status"] == "incomplete" and report["summary"] is None
    assert len(report["cases"]) == 4 and report["completed_inferences"] == 3
    assert report["cases"][2]["status"] == "source_failed" and "evaluate" not in timeline
    assert not report["evaluation_started"] and not report["all_predictions_saved_before_evaluation"]


@pytest.mark.parametrize("change", ["missing_case", "reordered", "network_budget", "wrong_scope"])
def test_source_coverage_and_network_contract_cannot_be_silently_changed(tmp_path, monkeypatch, change):
    deps, timeline, _ = dependencies(tmp_path, monkeypatch)
    original = deps.prepare_inputs

    def changed(work):
        result = original(work)
        if change == "missing_case":
            result["cases"].pop()
        elif change == "reordered":
            result["cases"].reverse()
        elif change == "network_budget":
            result["source_receipt"]["downloaded_bytes"] = runner.MAX_SOURCE_NETWORK_BYTES + 1
        else:
            result["cases"][0]["scope"] = runner.SCOPES[0]
        return result

    code, report, _, _ = execute(tmp_path, dataclasses.replace(deps, prepare_inputs=changed))
    assert code == 1 and report["status"] == "preparation_failed"
    assert len(report["cases"]) == 4 and report["summary"] is None
    assert "infer" not in timeline and "evaluate" not in timeline


def test_single_inference_failure_keeps_all_rows_and_other_predictions(tmp_path, monkeypatch):
    deps, timeline, _ = dependencies(tmp_path, monkeypatch)
    original = deps.infer_performance
    count = 0

    def fail_one(*args):
        nonlocal count
        count += 1
        if count == 2:
            raise ValueError("invented solver failure")
        return original(*args)

    code, report, work, _ = execute(tmp_path, dataclasses.replace(deps, infer_performance=fail_one))
    assert code == 1 and report["status"] == "incomplete" and report["summary"] is None
    assert len(report["cases"]) == 4 and report["completed_inferences"] == 3
    assert report["cases"][1]["status"] == "failed" and "evaluate" not in timeline
    assert len(list((work / "predictions").glob("*.json"))) == 3


def test_velocity_mutation_is_rejected_even_when_the_solver_changes_only_its_copy(tmp_path, monkeypatch):
    deps, timeline, _ = dependencies(tmp_path, monkeypatch)
    original = deps.infer_performance

    def mutate(events, length):
        result = original(events, length)
        object.__setattr__(events[0], "velocity", 1)
        return result

    code, report, work, _ = execute(tmp_path, dataclasses.replace(deps, infer_performance=mutate))
    assert code == 1 and report["completed_inferences"] == report["completed_preservation_checks"] == 0
    assert report["summary"] is None and "evaluate" not in timeline
    assert all(row["failure_stage"] == "input_preservation" for row in report["cases"])
    for path in (work / "inputs").glob("*.json"):
        assert json.loads(path.read_bytes())["events"][0]["velocity"] == 60


def test_evaluation_only_labels_inside_an_event_are_rejected(tmp_path, monkeypatch):
    deps, timeline, _ = dependencies(tmp_path, monkeypatch)
    original = deps.prepare_synthetic_inputs

    @dataclass(frozen=True)
    class LeakyEvent:
        event_id: str
        pitch: int
        onset_q: float
        velocity: int
        groove: str

    def prepare():
        rows = original()
        rows[0]["events"] = (LeakyEvent("e0", 0, 0.0, 60, "SECRET-GROUP"),)
        return rows

    code, report, _, output = execute(tmp_path, dataclasses.replace(deps, prepare_synthetic_inputs=prepare))
    assert code == 1 and report["completed_inferences"] == 3 and report["summary"] is None
    assert "evaluate" not in timeline and "SECRET-GROUP" not in output.read_text()


@pytest.mark.parametrize("bad_prediction", ["missing_arm", "nan", "oversized"])
def test_invalid_or_oversized_prediction_never_reaches_evaluation(tmp_path, monkeypatch, bad_prediction):
    deps, timeline, _ = dependencies(tmp_path, monkeypatch)
    original = deps.infer_performance
    if bad_prediction == "oversized":
        monkeypatch.setattr(runner, "MAX_PREDICTION_BYTES", 1000)

    def corrupt(*args):
        result = original(*args)
        if bad_prediction == "missing_arm":
            result["arms"].pop("global_phase")
        elif bad_prediction == "nan":
            result["fits"][0]["cost"] = float("nan")
        else:
            result["extra"] = "x" * 1500
        return result

    code, report, _, _ = execute(tmp_path, dataclasses.replace(deps, infer_performance=corrupt))
    assert code == 1 and report["status"] == "incomplete" and report["completed_inferences"] == 0
    assert report["evaluation"] is report["summary"] is None and "evaluate" not in timeline


def test_evaluation_exception_preserves_frozen_predictions_and_hides_private_details(tmp_path, monkeypatch):
    deps, _, _ = dependencies(tmp_path, monkeypatch)

    def fail(cases, predictions, evaluation):
        evaluation[cases[0]["id"]]["private_path"] = str(tmp_path / "secret.mid")
        predictions[cases[0]["id"]]["fits"].clear()
        raise RuntimeError("PRIVATE-REFERENCE " + str(tmp_path))

    code, report, work, output = execute(tmp_path, dataclasses.replace(deps, evaluate_study=fail))
    assert code == 1 and report["status"] == "evaluation_failed"
    assert report["completed_inferences"] == 4 and report["summary"] is report["evaluation"] is None
    assert report["all_predictions_saved_before_evaluation"] is True
    assert "PRIVATE-REFERENCE" not in output.read_text() and str(tmp_path) not in output.read_text()
    assert all(len(json.loads(p.read_bytes())["fits"]) == 4 for p in (work / "predictions").glob("*.json"))


@pytest.mark.parametrize("change", ["raw_events", "raw_targets", "missing_scope", "oversized"])
def test_nonpublic_or_incomplete_evaluation_is_rejected(tmp_path, monkeypatch, change):
    deps, _, _ = dependencies(tmp_path, monkeypatch)
    original = deps.evaluate_study
    if change == "oversized":
        monkeypatch.setattr(runner, "MAX_EVALUATION_BYTES", 1000)

    def bad(*args):
        result = original(*args)
        if change == "raw_events":
            result["events"] = [{"velocity": 60}]
        elif change == "raw_targets":
            result["real"]["case_rows"][0]["evaluation_receipt"]["target_notes"] = [{"pitch": 60, "onset_q": 0.0}]
        elif change == "missing_scope":
            result.pop("real")
        else:
            result["large"] = "x" * 1500
        return result

    code, report, _, output = execute(tmp_path, dataclasses.replace(deps, evaluate_study=bad))
    assert code == 1 and report["status"] == "evaluation_failed"
    assert report["completed_inferences"] == 4 and report["summary"] is report["evaluation"] is None
    assert '"events"' not in output.read_text()


def test_combined_report_budget_retains_every_planned_failure_row(tmp_path, monkeypatch):
    deps, timeline, _ = dependencies(tmp_path, monkeypatch)
    original = deps.prepare_synthetic_inputs
    monkeypatch.setattr(runner, "MAX_REPORT_BYTES", 7000)

    def large_receipts():
        rows = original()
        for row in rows:
            row["receipt"]["diagnostic"] = "x" * 4000
        return rows

    code, report, _, output = execute(tmp_path, dataclasses.replace(deps, prepare_synthetic_inputs=large_receipts))
    assert code == 1 and report["summary"] is None and len(report["cases"]) == 4
    assert output.stat().st_size <= runner.MAX_REPORT_BYTES and "evaluate" not in timeline
    assert any(row["status"] == "failed" for row in report["cases"])


@pytest.mark.parametrize("unsafe", ["existing_output", "inside_work", "symlink_work"])
def test_unsafe_paths_fail_before_preparation_and_preserve_existing_data(tmp_path, monkeypatch, unsafe):
    deps, timeline, _ = dependencies(tmp_path, monkeypatch)
    work, output = tmp_path / "work", tmp_path / "report.json"
    if unsafe == "existing_output":
        output.write_text("keep this")
    elif unsafe == "inside_work":
        output = work / "report.json"
    else:
        actual = tmp_path / "existing"
        actual.mkdir()
        work.symlink_to(actual, target_is_directory=True)
    with pytest.raises(ValueError):
        runner.run(work, output, deps=deps)
    assert timeline == []
    if unsafe == "existing_output":
        assert output.read_text() == "keep this"


def test_prepared_cases_cannot_smuggle_reference_fields_before_prediction(tmp_path, monkeypatch):
    deps, timeline, _ = dependencies(tmp_path, monkeypatch)
    original = deps.prepare_inputs

    def leaky(work):
        result = original(work)
        result["cases"][0]["evaluation"] = {"score_id": "PRIVATE-TRUTH"}
        return result

    code, report, _, output = execute(tmp_path, dataclasses.replace(deps, prepare_inputs=leaky))
    assert code == 1 and report["status"] == "preparation_failed"
    assert len(report["cases"]) == 4 and report["summary"] is None
    assert "infer" not in timeline and "load:synthetic" not in timeline
    assert "PRIVATE-TRUTH" not in output.read_text()


@pytest.mark.parametrize("loader", ["load_synthetic_evaluation", "load_evaluation"])
def test_evaluation_loader_failure_keeps_all_predictions_and_null_summary(tmp_path, monkeypatch, loader):
    deps, timeline, _ = dependencies(tmp_path, monkeypatch)

    def fail(*args):
        saved = json.loads((tmp_path / "public" / "report.json").read_bytes())
        assert saved["completed_inferences"] == 4
        assert saved["all_predictions_saved_before_evaluation"]
        assert len(list((tmp_path / "work" / "predictions").glob("*.json"))) == 4
        raise ValueError("PRIVATE-EVALUATION " + str(tmp_path))

    code, report, work, output = execute(tmp_path, dataclasses.replace(deps, **{loader: fail}))
    assert code == 1 and report["status"] == "evaluation_failed"
    assert len(report["cases"]) == report["completed_preservation_checks"] == 4
    assert report["summary"] is report["evaluation"] is None
    assert report["evaluation_loading_started"] and not report["evaluation_started"]
    assert "evaluate" not in timeline and "PRIVATE-EVALUATION" not in output.read_text()
    assert "PRIVATE-EVALUATION" in (work / "failure.log").read_text()


@pytest.mark.parametrize("change", ["missing_evaluation_case", "member_identity", "combined_budget",
                                    "input_mutation", "input_removed"])
def test_real_evaluation_cannot_change_population_source_identity_or_frozen_inputs(
    tmp_path, monkeypatch, change,
):
    deps, timeline, _ = dependencies(tmp_path, monkeypatch)
    original = deps.load_evaluation

    def changed(work, real_cases):
        result = original(work, real_cases)
        if change == "missing_evaluation_case":
            result["cases"].pop("real-a")
        elif change == "member_identity":
            result["source_receipt"]["members"]["evaluation.xml"]["sha256"] = "9" * 64
        elif change == "combined_budget":
            result["source_receipt"]["downloaded_bytes"] = 21  # Input40 + new21 exceeds fixed total60.
        elif change == "input_mutation":
            object.__setattr__(real_cases[0]["events"][0], "onset_q", 0.75)
        else:
            real_cases.pop()
        return result

    code, report, work, _ = execute(tmp_path, dataclasses.replace(deps, load_evaluation=changed))
    assert code == 1 and report["status"] == "evaluation_failed"
    assert report["completed_inferences"] == len(report["cases"]) == 4
    assert report["summary"] is report["evaluation"] is None and "evaluate" not in timeline
    for path in (work / "inputs").glob("*.json"):
        assert json.loads(path.read_bytes())["events"][0]["onset_q"] == 0.0


def test_evaluator_mutation_is_rejected_even_when_it_returns_valid_public_output(tmp_path, monkeypatch):
    deps, _, _ = dependencies(tmp_path, monkeypatch)
    original = deps.evaluate_study

    def changed(cases, predictions, evaluation):
        output = original(cases, predictions, evaluation)
        predictions[cases[0]["id"]]["fits"][0]["phase"] = [3, 4]
        return output

    code, report, work, _ = execute(tmp_path, dataclasses.replace(deps, evaluate_study=changed))
    assert code == 1 and report["status"] == "evaluation_failed"
    assert report["completed_inferences"] == 4 and report["summary"] is None
    for path in (work / "predictions").glob("*.json"):
        assert json.loads(path.read_bytes())["fits"][0]["phase"] == [1, 2]


def test_inherited_source_pin_failure_preserves_preparation_receipt(tmp_path, monkeypatch):
    real_provenance = runner.collect_provenance
    deps, timeline, _ = dependencies(tmp_path, monkeypatch)
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "inherited.py").write_text("changed source")
    monkeypatch.setattr(runner, "ROOT", checkout)
    monkeypatch.setattr(runner, "MEASURED_SOURCE_PATHS", ("inherited.py",))
    monkeypatch.setattr(runner, "FROZEN_SOURCE_SHA256", {"inherited.py": "0" * 64})
    monkeypatch.setattr(runner, "version", lambda name: "1.3.3")
    monkeypatch.setattr(runner, "collect_provenance", real_provenance)
    code, report, _, _ = execute(tmp_path, deps)
    assert code == 1 and report["status"] == "preparation_failed"
    assert report["failure_stage"] == "provenance" and report["cases"] == []
    assert report["summary"] is None and not timeline

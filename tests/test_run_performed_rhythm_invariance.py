"""Small invented cohorts exercise runner isolation, ordering and failure receipts."""
from __future__ import annotations

import copy
import dataclasses
import json
from dataclasses import dataclass

import pytest

from scripts import run_performed_rhythm_invariance as runner


@dataclass(frozen=True)
class Event:
    event_id: str
    instrument: int
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

    def cases(scope):
        return [{"id": tid, "scope": scope,
                 "events": (Event("e0", 0, 0.0, 60), Event("e1", 1, 0.6, 110)),
                 "length_q": 4.0,
                 "evaluation": {"groove": "SECRET-GROUP-" + tid, "drummer": "SECRET-DRUMMER",
                                "truth": [{"instrument": 0, "tick": 0}, {"instrument": 1, "tick": 6}]},
                 "receipt": {"status": "complete", "source_sha256": "1" * 64,
                             "velocity_histogram": {60: 1, 110: 1}}}
                for tid in plans[scope]]

    def synthetic_plan():
        timeline.append("plan:synthetic")
        return plans[runner.SCOPES[0]]

    def manifest():
        timeline.append("plan:real")
        return {"cases": [{"id": tid} for tid in plans[runner.SCOPES[1]]]}

    def prepare_synthetic():
        timeline.append("prepare:synthetic")
        return cases(runner.SCOPES[0])

    def prepare_real(work):
        timeline.append("prepare:real")
        work.mkdir()
        return {"cases": cases(runner.SCOPES[1]), "source_receipt": {
            "planned_recordings": 2, "complete_recordings": 2, "failed_recordings": 0,
            "verified_member_count": 3, "downloaded_bytes": 0, "http_requests": 0,
            "archive_cache_hit": True, "archive_sha256": "2" * 64,
        }}

    def infer(events, length_q):
        timeline.append("infer")
        assert isinstance(events, tuple) and length_q == 4.0
        assert all(set(dataclasses.asdict(e)) == runner.EVENT_FIELDS for e in events)
        inference_arguments.append((copy.deepcopy(events), length_q))
        return {"fits": [{"phase": list(phase), "assignments": [{"event_id": "e0", "tick": 0}]}
                         for phase in ((1, 2), (3, 5), (2, 3), (3, 4))],
                "arms": {name: {"status": "ambiguous", "selected": None} for name in runner.ARMS}}

    def evaluate(prepared, predictions):
        timeline.append("evaluate")
        assert [case["id"] for case in prepared] == [tid for scope in runner.SCOPES for tid in plans[scope]]
        assert set(predictions) == {case["id"] for case in prepared}
        saved = json.loads((tmp_path / "public" / "report.json").read_bytes())
        assert saved["all_predictions_saved_before_evaluation"] is True
        assert saved["completed_inferences"] == saved["completed_preservation_checks"] == 4
        for case, row in zip(prepared, saved["cases"], strict=True):
            name = runner.digest(case["id"].encode()) + ".json"
            raw = (tmp_path / "work" / "predictions" / name).read_bytes()
            assert runner.digest(raw) == row["prediction_file_sha256"]
            assert json.loads(raw) == predictions[case["id"]]
            assert case["evaluation"]["groove"].startswith("SECRET-GROUP")
        return {"synthetic": {"case_rows": [], "summary": {"cases": 2, "correct": 0, "abstained": 2}},
                "real": {"case_rows": [], "summary": {"cases": 2, "decided": 0}},
                "limitations": ["invented diagnostic only"]}

    deps = runner.Dependencies(synthetic_plan, manifest, prepare_synthetic, prepare_real, infer, evaluate)
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
                        "infer", "infer", "infer", "infer", "evaluate"]
    assert report["completed_inferences"] == report["completed_preservation_checks"] == 4
    assert all(row["event_mutation_check_passed"] for row in report["cases"])
    assert report["summary"]["synthetic"]["correct"] == 0  # Completion is not a quality claim.
    assert report["summary"]["synthetic"]["abstained"] == 2
    assert len(seen) == 4 and all(events[0].velocity == 60 for events, _ in seen)
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
        field = "prepare_synthetic" if stage == "synthetic_preparation" else "prepare_real"
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
    original = deps.prepare_real

    def fail_one(work):
        result = original(work)
        result["cases"][0]["receipt"] = {"status": "failed", "failure_code": "unsupported_input"}
        result["cases"][0]["events"] = ()
        result["source_receipt"].update(complete_recordings=1, failed_recordings=1)
        return result

    code, report, _, _ = execute(tmp_path, dataclasses.replace(deps, prepare_real=fail_one))
    assert code == 1 and report["status"] == "incomplete" and report["summary"] is None
    assert len(report["cases"]) == 4 and report["completed_inferences"] == 3
    assert report["cases"][2]["status"] == "source_failed" and "evaluate" not in timeline
    assert not report["evaluation_started"] and not report["all_predictions_saved_before_evaluation"]


@pytest.mark.parametrize("change", ["missing_case", "reordered", "network_budget", "wrong_scope"])
def test_source_coverage_and_network_contract_cannot_be_silently_changed(tmp_path, monkeypatch, change):
    deps, timeline, _ = dependencies(tmp_path, monkeypatch)
    original = deps.prepare_real

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

    code, report, _, _ = execute(tmp_path, dataclasses.replace(deps, prepare_real=changed))
    assert code == 1 and report["status"] == "preparation_failed"
    assert len(report["cases"]) == 4 and report["summary"] is None
    assert "infer" not in timeline and "evaluate" not in timeline


def test_single_inference_failure_keeps_all_rows_and_other_predictions(tmp_path, monkeypatch):
    deps, timeline, _ = dependencies(tmp_path, monkeypatch)
    original = deps.infer_take
    count = 0

    def fail_one(*args):
        nonlocal count
        count += 1
        if count == 2:
            raise ValueError("invented solver failure")
        return original(*args)

    code, report, work, _ = execute(tmp_path, dataclasses.replace(deps, infer_take=fail_one))
    assert code == 1 and report["status"] == "incomplete" and report["summary"] is None
    assert len(report["cases"]) == 4 and report["completed_inferences"] == 3
    assert report["cases"][1]["status"] == "failed" and "evaluate" not in timeline
    assert len(list((work / "predictions").glob("*.json"))) == 3


def test_velocity_mutation_is_rejected_even_when_the_solver_changes_only_its_copy(tmp_path, monkeypatch):
    deps, timeline, _ = dependencies(tmp_path, monkeypatch)
    original = deps.infer_take

    def mutate(events, length):
        result = original(events, length)
        object.__setattr__(events[0], "velocity", 1)
        return result

    code, report, work, _ = execute(tmp_path, dataclasses.replace(deps, infer_take=mutate))
    assert code == 1 and report["completed_inferences"] == report["completed_preservation_checks"] == 0
    assert report["summary"] is None and "evaluate" not in timeline
    assert all(row["failure_stage"] == "input_preservation" for row in report["cases"])
    for path in (work / "inputs").glob("*.json"):
        assert json.loads(path.read_bytes())["events"][0]["velocity"] == 60


def test_evaluation_only_labels_inside_an_event_are_rejected(tmp_path, monkeypatch):
    deps, timeline, _ = dependencies(tmp_path, monkeypatch)
    original = deps.prepare_synthetic

    @dataclass(frozen=True)
    class LeakyEvent:
        event_id: str
        instrument: int
        onset_q: float
        velocity: int
        groove: str

    def prepare():
        rows = original()
        rows[0]["events"] = (LeakyEvent("e0", 0, 0.0, 60, "SECRET-GROUP"),)
        return rows

    code, report, _, output = execute(tmp_path, dataclasses.replace(deps, prepare_synthetic=prepare))
    assert code == 1 and report["completed_inferences"] == 3 and report["summary"] is None
    assert "evaluate" not in timeline and "SECRET-GROUP" not in output.read_text()


@pytest.mark.parametrize("bad_prediction", ["missing_arm", "nan", "oversized"])
def test_invalid_or_oversized_prediction_never_reaches_evaluation(tmp_path, monkeypatch, bad_prediction):
    deps, timeline, _ = dependencies(tmp_path, monkeypatch)
    original = deps.infer_take
    if bad_prediction == "oversized":
        monkeypatch.setattr(runner, "MAX_PREDICTION_BYTES", 1000)

    def corrupt(*args):
        result = original(*args)
        if bad_prediction == "missing_arm":
            result["arms"].pop("phase_aware")
        elif bad_prediction == "nan":
            result["fits"][0]["cost"] = float("nan")
        else:
            result["extra"] = "x" * 1500
        return result

    code, report, _, _ = execute(tmp_path, dataclasses.replace(deps, infer_take=corrupt))
    assert code == 1 and report["status"] == "incomplete" and report["completed_inferences"] == 0
    assert report["evaluation"] is report["summary"] is None and "evaluate" not in timeline


def test_evaluation_exception_preserves_frozen_predictions_and_hides_private_details(tmp_path, monkeypatch):
    deps, _, _ = dependencies(tmp_path, monkeypatch)

    def fail(cases, predictions):
        cases[0]["evaluation"]["private_path"] = str(tmp_path / "secret.mid")
        predictions[cases[0]["id"]]["fits"].clear()
        raise RuntimeError("PRIVATE-REFERENCE " + str(tmp_path))

    code, report, work, output = execute(tmp_path, dataclasses.replace(deps, evaluate_study=fail))
    assert code == 1 and report["status"] == "evaluation_failed"
    assert report["completed_inferences"] == 4 and report["summary"] is report["evaluation"] is None
    assert report["all_predictions_saved_before_evaluation"] is True
    assert "PRIVATE-REFERENCE" not in output.read_text() and str(tmp_path) not in output.read_text()
    assert all(len(json.loads(p.read_bytes())["fits"]) == 4 for p in (work / "predictions").glob("*.json"))


@pytest.mark.parametrize("change", ["raw_events", "missing_scope", "oversized"])
def test_nonpublic_or_incomplete_evaluation_is_rejected(tmp_path, monkeypatch, change):
    deps, _, _ = dependencies(tmp_path, monkeypatch)
    original = deps.evaluate_study
    if change == "oversized":
        monkeypatch.setattr(runner, "MAX_EVALUATION_BYTES", 1000)

    def bad(*args):
        result = original(*args)
        if change == "raw_events":
            result["events"] = [{"velocity": 60}]
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
    original = deps.prepare_synthetic
    monkeypatch.setattr(runner, "MAX_REPORT_BYTES", 7000)

    def large_receipts():
        rows = original()
        for row in rows:
            row["receipt"]["diagnostic"] = "x" * 4000
        return rows

    code, report, _, output = execute(tmp_path, dataclasses.replace(deps, prepare_synthetic=large_receipts))
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

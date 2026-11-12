"""Invented eight-case cohorts test the execution boundary without source or model runs."""
from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
from dataclasses import dataclass

import pytest

from scripts import run_repeat_context as runner
from scripts.same_score_phase import OnsetEvent


def dependencies(tmp_path, monkeypatch):
    plan = {scope: [scope + "-a", scope + "-b"] for scope in runner.SCOPES}
    monkeypatch.setattr(runner, "DECLARED_PLANS", plan)
    monkeypatch.setattr(runner, "EXPECTED_SCOPE_COUNTS", {scope: 2 for scope in runner.SCOPES})
    monkeypatch.setattr(runner, "collect_provenance", lambda: {"source_sha256": {"invented.py": "1" * 64}})
    monkeypatch.setattr(runner, "MAX_SOURCE_HTTP_REQUESTS", 12)
    monkeypatch.setattr(runner, "MAX_SOURCE_NETWORK_BYTES", 120)
    monkeypatch.setattr(runner, "EXPECTED_UNIQUE_SOURCE_MEMBERS", 11)
    monkeypatch.setattr(runner, "EXPECTED_UNIQUE_SOURCE_BYTES", 115)
    budget = {"member_count": 6, "total_bytes": 60, "input_member_count": 4, "input_bytes": 40}
    monkeypatch.setattr(runner, "SOURCE_BUDGETS", {scope: dict(budget) for scope in runner.REAL_SCOPES})
    timeline, seen = [], []
    manifests = {}
    for scope in runner.REAL_SCOPES:
        members = {"metadata.csv": {"bytes": 5, "sha256": "d" * 64},
                   scope + "/score.xml": {"bytes": 15, "sha256": "c" * 64}}
        for i in range(2):
            for suffix in (".mid", ".txt"):
                members[f"{scope}/{i}{suffix}"] = {"bytes": 10, "sha256": "a" * 64}
        manifests[scope] = {
            "source_base": "https://example.invalid/pinned/", "budget": dict(budget), "members": members,
            "cases": [{"id": tid, "midi": f"{scope}/{i}.mid",
                       "performance_annotations": f"{scope}/{i}.txt"} for i, tid in enumerate(plan[scope])],
        }

    def cases(scope):
        native = runner.NATIVE_REAL_SCOPES.get(scope, scope)
        return [{"id": tid, "scope": native, "status": "complete",
                 "events": (OnsetEvent("e000001", 60, 0.0, 60), OnsetEvent("e000002", 64, 0.75, 110)),
                 "length_q": 4.0, "receipt": {"status": "complete", "source_sha256": "1" * 64,
                                              "velocity_histogram": {"60": 1, "110": 1}}}
                for tid in plan[scope]]

    def source_receipt(scope, stage):
        manifest = manifests[scope]
        members = manifest["members"]
        selected = {path: item for path, item in members.items()
                    if stage == "evaluation" or path.endswith((".mid", ".txt"))}
        return {"stage": stage, "planned_recordings": 2, "complete_recordings": 2,
                "failed_recordings": 0, "full_source_member_count": 6, "full_source_bytes": 60,
                "verified_member_count": len(selected), "members": copy.deepcopy(selected),
                "http_requests": 4 if stage == "inputs" else 2,
                "downloaded_bytes": 40 if stage == "inputs" else 20,
                "cache_hits": 0 if stage == "inputs" else 4}

    def assert_predictions_saved():
        report = json.loads((tmp_path / "public" / "report.json").read_bytes())
        assert report["completed_inferences"] == report["completed_preservation_checks"] == 8
        assert report["all_predictions_saved_before_evaluation"] is True
        assert len(list((tmp_path / "work" / "predictions").glob("*.json"))) == 8
        for row in report["cases"]:
            filename = runner.digest(row["id"].encode()) + ".json"
            for kind, field in (("inputs", "input_file_sha256"), ("predictions", "prediction_file_sha256")):
                raw = (tmp_path / "work" / kind / filename).read_bytes()
                assert hashlib.sha256(raw).hexdigest() == row[field]
        return report

    def labels(scope):
        return {tid: {"id": tid, "status": "complete", "score_id": "SECRET-SCORE-" + scope,
                      "target_notes": [{"pitch": 60, "onset_q": 0.0}],
                      "input_links": [{"event_id": "e000001", "score_id": "SECRET-TARGET"}],
                      "receipt": {"status": "complete", "target_notes": 1}}
                for tid in plan[scope]}

    def synthetic_adapter(scope):
        def planned():
            timeline.append("plan:" + scope)
            return list(plan[scope])

        def prepare():
            timeline.append("prepare:" + scope)
            return cases(scope)

        def load():
            timeline.append("load:" + scope)
            saved = assert_predictions_saved()
            assert not saved["evaluation_started"] and saved["evaluation_loading_started"]
            previous = runner.SCOPES[:runner.SCOPES.index(scope)]
            assert all(saved["evaluation_loaded"][name] for name in previous)
            return labels(scope)

        return runner.SyntheticAdapter(planned, prepare, load)

    def source_adapter(scope):
        def manifest():
            timeline.append("plan:" + scope)
            return copy.deepcopy(manifests[scope])

        def prepare(work):
            timeline.append("prepare:" + scope)
            assert work == tmp_path / "work" / (scope + "-sources")
            return {"cases": cases(scope), "source_receipt": source_receipt(scope, "inputs")}

        def load(work, source_cases):
            timeline.append("load:" + scope)
            assert work == tmp_path / "work" / (scope + "-sources")
            assert [case["id"] for case in source_cases] == plan[scope]
            assert all(case["scope"] == runner.NATIVE_REAL_SCOPES[scope] for case in source_cases)
            assert all("evaluation" not in case for case in source_cases)
            saved = assert_predictions_saved()
            assert not saved["evaluation_started"]
            previous = runner.SCOPES[:runner.SCOPES.index(scope)]
            assert all(saved["evaluation_loaded"][name] for name in previous)
            return {"cases": labels(scope), "source_receipt": source_receipt(scope, "evaluation")}

        return runner.SourceAdapter(manifest, prepare, load)

    def infer(events, length_q):
        timeline.append("infer")
        assert type(events) is tuple and length_q == 4.0
        assert all(set(dataclasses.asdict(event)) == runner.EVENT_FIELDS for event in events)
        seen.append((events, length_q))
        return {"fits": [{"phase": [1, 2], "cost": 0.0}],
                "path_sets": {"toy": {"diagnostic_hex": "a", "full_hex": "f"}},
                "arms": {name: {"status": "abstained"} for name in runner.ARMS}}

    def evaluate(prepared, predictions, evaluation):
        timeline.append("evaluate")
        saved = assert_predictions_saved()
        assert saved["evaluation_started"] and all(saved["evaluation_loaded"].values())
        ids = [tid for scope in runner.SCOPES for tid in plan[scope]]
        assert [case["id"] for case in prepared] == ids
        assert set(predictions) == set(evaluation) == set(ids)
        for case in prepared:
            assert "evaluation" not in case and case["id"] in plan[case["scope"]]
            filename = runner.digest(case["id"].encode()) + ".json"
            raw = (tmp_path / "work" / "predictions" / filename).read_bytes()
            assert json.loads(raw) == predictions[case["id"]]
            assert evaluation[case["id"]]["score_id"].startswith("SECRET-SCORE")
        return {"cohorts": {scope: {"summary": {"cases": 2, "correct": 0, "abstained": 2},
                                    "case_rows": [{"target_notes": 2, "input_links": 2}]}
                            for scope in runner.SCOPES}, "limitations": ["invented diagnostic only"]}

    return runner.Dependencies(
        {scope: synthetic_adapter(scope) for scope in runner.SYNTHETIC_SCOPES},
        {scope: source_adapter(scope) for scope in runner.REAL_SCOPES}, infer, evaluate,
    ), timeline, seen


def replace_adapter(deps, kind, scope, field, replacement):
    adapters = dict(getattr(deps, kind))
    adapters[scope] = dataclasses.replace(adapters[scope], **{field: replacement})
    return dataclasses.replace(deps, **{kind: adapters})


def execute(tmp_path, deps):
    work, output = tmp_path / "work", tmp_path / "public" / "report.json"
    code = runner.run(work, output, deps=deps)
    return code, json.loads(output.read_bytes()), work, output


def test_four_evaluation_loaders_wait_for_every_saved_prediction_and_receive_native_source_cases(tmp_path, monkeypatch):
    deps, timeline, seen = dependencies(tmp_path, monkeypatch)
    code, report, _, output = execute(tmp_path, deps)
    assert code == 0 and report["status"] == "complete"
    assert timeline == (["plan:" + s for s in runner.SCOPES]
                        + ["prepare:" + s for s in runner.SCOPES]
                        + ["infer"] * 8 + ["load:" + s for s in runner.SCOPES] + ["evaluate"])
    assert report["completed_inferences"] == report["completed_preservation_checks"] == len(seen) == 8
    assert all(row["event_mutation_check_passed"] and row["evaluation_status"] == "complete"
               for row in report["cases"])
    assert all(summary["correct"] == 0 for summary in report["summary"].values())
    assert report["source_acquisition"]["actual_totals"] == {"http_requests": 12, "downloaded_bytes": 120, "cache_hits": 8}
    assert report["source_inventory"]["unique_source_members"] == 11
    assert report["source_inventory"]["unique_source_bytes"] == 115
    assert report["source_inventory"]["shared_member_count"] == 1
    assert "SECRET" not in output.read_text() and str(tmp_path) not in output.read_text()
    assert '"path_sets"' not in output.read_text() and '"events"' not in output.read_text()


@pytest.mark.parametrize("scope", runner.SCOPES)
def test_preparation_failure_preserves_all_planned_rows_and_never_opens_evaluation(tmp_path, monkeypatch, scope):
    deps, timeline, _ = dependencies(tmp_path, monkeypatch)

    def fail(*args):
        raise RuntimeError("PRIVATE-MIDI " + str(tmp_path / "original.mid"))

    kind, field = ("synthetic", "prepare") if scope in runner.SYNTHETIC_SCOPES else ("sources", "prepare_inputs")
    deps = replace_adapter(deps, kind, scope, field, fail)
    code, report, work, output = execute(tmp_path, deps)
    assert code == 1 and report["status"] == "preparation_failed"
    assert report["failure_stage"] == scope + "_preparation" and len(report["cases"]) == 8
    assert report["summary"] is report["evaluation"] is None
    assert "infer" not in timeline and not any(item.startswith("load:") for item in timeline)
    assert "PRIVATE-MIDI" not in output.read_text() and "PRIVATE-MIDI" in (work / "failure.log").read_text()


@pytest.mark.parametrize("change", ["duplicate_id", "wrong_count", "shared_identity", "budget"])
def test_registry_and_combined_source_identity_are_checked_before_preparation(tmp_path, monkeypatch, change):
    deps, timeline, _ = dependencies(tmp_path, monkeypatch)
    if change in {"duplicate_id", "wrong_count"}:
        def changed_plan():
            ids = list(runner.DECLARED_PLANS["factorial_authored"])
            if change == "duplicate_id":
                ids[0] = runner.DECLARED_PLANS["reused_authored"][0]
            else:
                ids.pop()
            return ids
        deps = replace_adapter(deps, "synthetic", "factorial_authored", "plan", changed_plan)
    else:
        original = deps.sources["additional_real"].load_manifest

        def changed_manifest():
            value = original()
            if change == "shared_identity":
                value["members"]["metadata.csv"]["sha256"] = "f" * 64
            else:
                value["budget"]["total_bytes"] += 1
            return value
        deps = replace_adapter(deps, "sources", "additional_real", "load_manifest", changed_manifest)
    code, report, _, _ = execute(tmp_path, deps)
    assert code == 1 and report["failure_stage"] == "planning" and len(report["cases"]) == 8
    assert report["summary"] is None and not any(item.startswith("prepare:") for item in timeline)


def test_failed_additional_source_remains_in_population_and_blocks_all_four_evaluation_loaders(tmp_path, monkeypatch):
    deps, timeline, _ = dependencies(tmp_path, monkeypatch)
    original = deps.sources["additional_real"].prepare_inputs

    def fail_one(work):
        result = original(work)
        case = result["cases"][-1]
        case.update(status="failed", events=(), receipt={"status": "failed", "failure": "unsupported_input"})
        result["source_receipt"].update(complete_recordings=1, failed_recordings=1)
        return result

    deps = replace_adapter(deps, "sources", "additional_real", "prepare_inputs", fail_one)
    code, report, _, _ = execute(tmp_path, deps)
    assert code == 1 and report["status"] == "incomplete"
    assert len(report["cases"]) == 8 and report["completed_inferences"] == 7
    assert report["cases"][-1]["status"] == "source_failed"
    assert report["summary"] is None and not any(item.startswith("load:") for item in timeline)


@pytest.mark.parametrize("stage", ["inputs", "evaluation"])
def test_unavailable_source_retains_verified_partial_transfers_but_still_fails_full_coverage(tmp_path, monkeypatch, stage):
    deps, timeline, _ = dependencies(tmp_path, monkeypatch)
    field = "prepare_inputs" if stage == "inputs" else "load_evaluation"
    original = getattr(deps.sources["additional_real"], field)

    def unavailable(*args):
        value = original(*args)
        receipt = value["source_receipt"]
        if stage == "inputs":
            missing = "additional_real/1.txt"
            case = value["cases"][-1]
            case.update(status="failed", events=(), receipt={"status": "failed", "failure": "source_unavailable"})
            receipt.update(complete_recordings=1, failed_recordings=1, downloaded_bytes=30)
        else:
            missing = "additional_real/score.xml"
            for case in value["cases"].values():
                case.update(status="failed", receipt={"status": "failed", "failure": "source_unavailable"})
            receipt.update(complete_recordings=0, failed_recordings=2, downloaded_bytes=5)
        receipt["members"].pop(missing)
        receipt["verified_member_count"] -= 1
        return value

    deps = replace_adapter(deps, "sources", "additional_real", field, unavailable)
    code, report, _, output = execute(tmp_path, deps)
    assert code == 1 and len(report["cases"]) == 8
    assert report["summary"] is report["evaluation"] is None and "evaluate" not in timeline
    receipt = report["source_acquisition"]["additional_real"][stage]
    assert receipt["verified_member_count"] == (3 if stage == "inputs" else 5)
    assert receipt["full_source_member_count"] == 6
    missing = "additional_real/1.txt" if stage == "inputs" else "additional_real/score.xml"
    assert missing not in receipt["members"]
    totals = report["source_acquisition"]["actual_totals"]
    assert totals["downloaded_bytes"] == (70 if stage == "inputs" else 105)
    assert totals["http_requests"] == (8 if stage == "inputs" else 12)
    assert report["status"] == ("preparation_failed" if stage == "inputs" else "evaluation_failed")
    assert report["completed_inferences"] == (0 if stage == "inputs" else 8)
    assert str(tmp_path) not in output.read_text()


@pytest.mark.parametrize("mode", ["exception", "private_write"])
def test_last_prediction_failure_retains_earlier_files_and_prevents_any_evaluation(tmp_path, monkeypatch, mode):
    deps, timeline, _ = dependencies(tmp_path, monkeypatch)
    if mode == "exception":
        original = deps.infer_repeated_performance
        calls = 0

        def fail_last(*args):
            nonlocal calls
            calls += 1
            if calls == 8:
                raise ValueError("PRIVATE-INFERENCE")
            return original(*args)
        deps = dataclasses.replace(deps, infer_repeated_performance=fail_last)
    else:
        original = runner._atomic_write
        calls = 0

        def fail_last_write(path, raw):
            nonlocal calls
            if path.parent.name == "predictions":
                calls += 1
                if calls == 8:
                    raise OSError("PRIVATE-PREDICTION " + str(path))
            return original(path, raw)
        monkeypatch.setattr(runner, "_atomic_write", fail_last_write)
    code, report, work, output = execute(tmp_path, deps)
    assert code == 1 and report["status"] == "incomplete"
    assert report["completed_inferences"] == 7 and len(report["cases"]) == 8
    assert report["cases"][-1]["status"] == "failed" and report["summary"] is None
    assert len(list((work / "predictions").glob("*.json"))) == 7
    assert not any(item.startswith("load:") for item in timeline) and "PRIVATE-" not in output.read_text()


def test_mutating_even_the_isolated_event_copy_blocks_evaluation_and_preserves_saved_inputs(tmp_path, monkeypatch):
    deps, timeline, _ = dependencies(tmp_path, monkeypatch)
    original = deps.infer_repeated_performance

    def mutate(events, length):
        result = original(events, length)
        object.__setattr__(events[0], "velocity", 1)
        return result

    code, report, work, _ = execute(tmp_path, dataclasses.replace(deps, infer_repeated_performance=mutate))
    assert code == 1 and report["completed_inferences"] == report["completed_preservation_checks"] == 0
    assert report["summary"] is None and not any(item.startswith("load:") for item in timeline)
    assert all(row["failure_stage"] == "input_preservation" for row in report["cases"])
    assert all(json.loads(path.read_bytes())["events"][0]["velocity"] == 60
               for path in (work / "inputs").glob("*.json"))


@pytest.mark.parametrize("where", ["case", "event"])
def test_reference_context_cannot_enter_prepared_case_or_inference_event(tmp_path, monkeypatch, where):
    deps, timeline, _ = dependencies(tmp_path, monkeypatch)
    original = deps.synthetic["factorial_authored"].prepare

    @dataclass(frozen=True)
    class LeakyEvent:
        event_id: str
        pitch: int
        onset_q: float
        velocity: int
        repeat_truth: str

    def leaked():
        cases = original()
        if where == "case":
            cases[0]["evaluation"] = {"score_id": "SECRET-TRUTH"}
        else:
            cases[0]["events"] = (LeakyEvent("e0", 60, 0.0, 60, "SECRET-TRUTH"),)
        return cases

    deps = replace_adapter(deps, "synthetic", "factorial_authored", "prepare", leaked)
    code, report, _, output = execute(tmp_path, deps)
    assert code == 1 and len(report["cases"]) == 8 and report["summary"] is None
    assert not any(item.startswith("load:") for item in timeline) and "SECRET-TRUTH" not in output.read_text()


@pytest.mark.parametrize("change", ["missing_arm", "nan", "per_file_budget", "total_budget"])
def test_invalid_prediction_or_private_budget_cannot_reach_evaluation(tmp_path, monkeypatch, change):
    deps, timeline, _ = dependencies(tmp_path, monkeypatch)
    original = deps.infer_repeated_performance
    if change == "per_file_budget":
        monkeypatch.setattr(runner, "MAX_PREDICTION_BYTES", 700)
    if change == "total_budget":
        monkeypatch.setattr(runner, "MAX_ALL_PREDICTION_BYTES", 1500)

    def corrupted(*args):
        value = original(*args)
        if change == "missing_arm":
            value["arms"].pop("repeat_soft010")
        elif change == "nan":
            value["fits"][0]["cost"] = float("nan")
        elif change == "per_file_budget":
            value["large"] = "x" * 1000
        return value

    deps = dataclasses.replace(deps, infer_repeated_performance=corrupted)
    code, report, _, _ = execute(tmp_path, deps)
    assert code == 1 and report["status"] == "incomplete" and report["completed_inferences"] < 8
    assert len(report["cases"]) == 8 and report["summary"] is None
    assert not any(item.startswith("load:") for item in timeline)


@pytest.mark.parametrize("scope", runner.SCOPES)
def test_each_evaluation_loader_failure_preserves_all_prediction_files_and_null_summary(tmp_path, monkeypatch, scope):
    deps, timeline, _ = dependencies(tmp_path, monkeypatch)

    def failed(*args):
        assert len(list((tmp_path / "work" / "predictions").glob("*.json"))) == 8
        raise RuntimeError("PRIVATE-EVALUATION " + str(tmp_path))

    kind = "synthetic" if scope in runner.SYNTHETIC_SCOPES else "sources"
    deps = replace_adapter(deps, kind, scope, "load_evaluation", failed)
    code, report, work, output = execute(tmp_path, deps)
    assert code == 1 and report["status"] == "evaluation_failed"
    assert report["failure_stage"] == scope + "_evaluation_loading"
    assert report["completed_inferences"] == len(report["cases"]) == 8
    assert report["all_predictions_saved_before_evaluation"] and not report["evaluation_started"]
    assert report["summary"] is report["evaluation"] is None and "evaluate" not in timeline
    assert "PRIVATE-EVALUATION" not in output.read_text()
    assert "PRIVATE-EVALUATION" in (work / "failure.log").read_text()


@pytest.mark.parametrize("change", ["missing_case", "native_scope", "input_mutation", "receipt_mutation",
                                    "member_identity", "combined_budget", "source_failure"])
def test_additional_evaluation_source_cannot_change_frozen_population_or_transfer_contract(tmp_path, monkeypatch, change):
    deps, timeline, _ = dependencies(tmp_path, monkeypatch)
    original = deps.sources["additional_real"].load_evaluation

    def changed(work, cases):
        value = original(work, cases)
        if change == "missing_case":
            value["cases"].pop(cases[-1]["id"])
        elif change == "native_scope":
            cases[-1]["scope"] = "reused_real"
        elif change == "input_mutation":
            object.__setattr__(cases[-1]["events"][0], "onset_q", 0.5)
        elif change == "receipt_mutation":
            cases[-1]["receipt"]["source_sha256"] = "f" * 64
        elif change == "member_identity":
            value["source_receipt"]["members"]["metadata.csv"]["sha256"] = "f" * 64
        elif change == "combined_budget":
            value["source_receipt"]["downloaded_bytes"] = 21
        else:
            value["cases"][cases[-1]["id"]].update(status="failed", receipt={"status": "failed"})
            value["source_receipt"].update(complete_recordings=1, failed_recordings=1)
        return value

    deps = replace_adapter(deps, "sources", "additional_real", "load_evaluation", changed)
    code, report, work, _ = execute(tmp_path, deps)
    assert code == 1 and report["status"] == "evaluation_failed"
    assert report["completed_inferences"] == len(report["cases"]) == 8
    assert report["summary"] is report["evaluation"] is None and "evaluate" not in timeline
    assert all(json.loads(path.read_bytes())["events"][0]["onset_q"] == 0.0
               for path in (work / "inputs").glob("*.json"))
    if change == "source_failure":
        assert report["cases"][-1]["evaluation_status"] == "failed"


@pytest.mark.parametrize("change", ["prediction", "input", "cohort", "exception"])
def test_evaluator_mutation_or_exception_never_replaces_frozen_outputs_with_a_result(tmp_path, monkeypatch, change):
    deps, _, _ = dependencies(tmp_path, monkeypatch)
    original = deps.evaluate_study

    def altered(cases, predictions, evaluation):
        value = original(cases, predictions, evaluation)
        if change == "prediction":
            predictions[cases[-1]["id"]]["fits"][0]["phase"] = [3, 4]
        elif change == "input":
            object.__setattr__(cases[-1]["events"][0], "velocity", 1)
        elif change == "cohort":
            cases[-1]["scope"] = "reused_real"
        else:
            raise ValueError("PRIVATE-REFERENCE " + str(tmp_path))
        return value

    code, report, work, output = execute(tmp_path, dataclasses.replace(deps, evaluate_study=altered))
    assert code == 1 and report["status"] == "evaluation_failed"
    assert report["completed_inferences"] == 8 and report["evaluation_started"]
    assert report["summary"] is report["evaluation"] is None and "PRIVATE-REFERENCE" not in output.read_text()
    assert all(json.loads(path.read_bytes())["fits"][0]["phase"] == [1, 2]
               for path in (work / "predictions").glob("*.json"))


@pytest.mark.parametrize("change", ["raw_events", "raw_targets", "path_sets", "private_path", "missing_cohort", "oversized"])
def test_public_evaluation_rejects_raw_records_private_paths_and_incomplete_cohorts(tmp_path, monkeypatch, change):
    deps, _, _ = dependencies(tmp_path, monkeypatch)
    original = deps.evaluate_study
    if change == "oversized":
        monkeypatch.setattr(runner, "MAX_EVALUATION_BYTES", 2000)

    def bad(*args):
        value = original(*args)
        if change == "raw_events":
            value["events"] = [{"pitch": 60, "onset_q": 0.0}]
        elif change == "raw_targets":
            value["cohorts"]["additional_real"]["case_rows"][0]["target_notes"] = [{"pitch": 60}]
        elif change == "path_sets":
            value["path_sets"] = {"private": "ffff"}
        elif change == "private_path":
            value["source_path"] = str(tmp_path / "original.mid")
        elif change == "missing_cohort":
            value["cohorts"].pop("additional_real")
        else:
            value["large"] = "x" * 2500
        return value

    code, report, _, output = execute(tmp_path, dataclasses.replace(deps, evaluate_study=bad))
    assert code == 1 and report["status"] == "evaluation_failed" and report["completed_inferences"] == 8
    assert report["summary"] is report["evaluation"] is None
    assert '"events"' not in output.read_text() and '"path_sets"' not in output.read_text()


def test_combined_public_budget_preserves_every_failure_row_without_partial_summary(tmp_path, monkeypatch):
    deps, timeline, _ = dependencies(tmp_path, monkeypatch)
    monkeypatch.setattr(runner, "MAX_REPORT_BYTES", 18_000)
    original = deps.synthetic["factorial_authored"].prepare

    def large_receipts():
        cases = original()
        for case in cases:
            case["receipt"]["diagnostic"] = "x" * 14_000
        return cases

    deps = replace_adapter(deps, "synthetic", "factorial_authored", "prepare", large_receipts)
    code, report, _, output = execute(tmp_path, deps)
    assert code == 1 and report["summary"] is None and len(report["cases"]) == 8
    assert output.stat().st_size <= runner.MAX_REPORT_BYTES
    assert any(row["status"] == "failed" for row in report["cases"])
    assert not any(item.startswith("load:") for item in timeline)


@pytest.mark.parametrize("unsafe", ["existing_output", "inside_work", "symlink_work"])
def test_unsafe_work_and_output_paths_preserve_existing_data_before_any_operation(tmp_path, monkeypatch, unsafe):
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


def test_inherited_pin_failure_still_preserves_the_predeclared_full_population(tmp_path, monkeypatch):
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
    assert code == 1 and report["status"] == "preparation_failed" and report["failure_stage"] == "provenance"
    assert len(report["cases"]) == 8 and report["summary"] is None and timeline == []

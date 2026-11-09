"""Model tournament roster must not compare incompatible roles or approve NC weights."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

from scripts import plan_tier2_candidate_groups as plans
from scripts.run_tier2_matrix import plan as matrix_plan

CATALOG_PATH = Path("benchmarks/tier2/model-candidate-registry.json")
MATRIX_PATH = Path("benchmarks/tier2/experiment-matrix.json")


def _catalog() -> dict:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def test_all_open_issues_candidate_roles_and_unapproved_state_are_explicit():
    registry = plans.validate_registry(_catalog())
    assert registry["commercial_baseline_approved"] is False
    assert registry["same_corpus_multi_model_benchmark_complete"] is False
    by_id = {model["id"]: model for model in registry["candidates"]}
    assert len(by_id) == 14
    assert {"mr-mt3", "yourmt3-yptf-moe", "mt3-pytorch", "miros"}.issubset(by_id)
    assert {"muscriptor-small", "muscriptor-medium", "muscriptor-large"}.issubset(by_id)
    assert by_id["audio-score-native"]["kind"] == "training_scaffold"
    assert by_id["mt3-pytorch"]["license_gate"] == "no_upstream_license"
    assert "full_instrument_amt" not in by_id["sheetsage2"]["roles"]
    assert by_id["sheetsage2"]["vocal_evaluation"]["recordings"] == 40
    assert by_id["sheetsage2"]["vocal_evaluation"]["publishing_quality_approved"] is False
    assert "full_instrument_amt" not in by_id["chordify-manual"]["roles"]
    assert by_id["chordify-manual"]["kind"] == "external_service"


def test_personal_amt_roster_comprises_all_direct_comparable_candidates_only():
    plan = plans.plan_candidate_group(
        _catalog(), role="full_instrument_amt", usage_mode="personal",
    )
    assert plan["candidate_count"] == 7
    assert plan["quality_winner"] is None
    assert plan["commercial_baseline_approved"] is False
    assert plan["models_discarded_without_evidence"] is False
    assert {m["id"] for m in plan["candidates"]} == {
        "mr-mt3", "yourmt3-yptf-moe", "mt3-pytorch",
        "muscriptor-small", "muscriptor-medium", "muscriptor-large", "miros",
    }
    mr = next(c for c in plan["candidates"] if c["id"] == "mr-mt3")
    assert mr["status"] == "needs_shared_heldout_corpus_and_production_review"
    small = next(c for c in plan["candidates"] if c["id"] == "muscriptor-small")
    assert small["status"] == "needs_verified_checkpoint_and_execution_adapter"


def test_commercial_amt_disqualifies_noncommercial_weights_and_unknown_rights():
    result = plans.plan_candidate_group(
        _catalog(), role="full_instrument_amt", usage_mode="commercial",
    )
    statuses = {candidate["id"]: candidate["status"] for candidate in result["candidates"]}
    for name in ("muscriptor-small", "muscriptor-medium", "muscriptor-large", "miros", "mt3-pytorch"):
        assert statuses[name] == "blocked_rights_or_service_terms"
    assert statuses["mr-mt3"] == "needs_shared_heldout_corpus_and_production_review"
    assert statuses["yourmt3-yptf-moe"] == "needs_shared_heldout_corpus_and_production_review"
    assert result["quality_winner"] is None
    assert result["license_approval_inferred_from_score"] is False


def test_chord_and_beat_comparisons_never_include_full_amt_or_pretend_chordify_is_truth():
    chord = plans.plan_candidate_group(
        _catalog(), role="chord_estimation", usage_mode="personal",
    )
    beat = plans.plan_candidate_group(
        _catalog(), role="beat_downbeat", usage_mode="commercial",
    )
    assert chord["candidate_count"] == 5
    assert beat["candidate_count"] == 4
    assert "mr-mt3" not in {c["id"] for c in chord["candidates"]}
    assert "beat-this" in {c["id"] for c in beat["candidates"]}
    competitor = next(c for c in chord["candidates"] if c["id"] == "chordify-manual")
    assert competitor["status"] == "manual_comparison_only"
    competitor = next(c for c in beat["candidates"] if c["id"] == "chordify-manual")
    assert competitor["status"] == "blocked_rights_or_service_terms"
    assert "no automatic" not in chord["shared_experiment_contract"].lower()


@pytest.mark.parametrize("mutation,expected", [
    (lambda p: p.update(commercial_baseline_approved=True), "approval"),
    (lambda p: p["candidates"].append(copy.deepcopy(p["candidates"][0])), "classified"),
    (
        lambda p: p["comparison_groups"][0]["candidate_ids"].append("sheetsage2"),
        "different task roles",
    ),
    (
        lambda p: p["comparison_groups"][0]["candidate_ids"].append("audio-score-native"),
        "training scaffold",
    ),
    (
        lambda p: p["candidates"][0].update(license_gate="approved_for_commercial"),
        "classified",
    ),
    (
        lambda p: p["candidates"][0].update(roles=["full_instrument_amt", "full_instrument_amt"]),
        "classified",
    ),
])
def test_unreviewed_or_cross_role_claims_fail_closed(mutation, expected):
    data = copy.deepcopy(_catalog())
    mutation(data)
    with pytest.raises(plans.CandidatePlanError, match=expected):
        plans.validate_registry(data)


def test_historical_sheetsage2_ids_explicitly_name_actual_old_sheetsage_adapter():
    matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
    stages = matrix_plan(matrix, include_blocked=True)
    by_id = {stage["id"]: stage for stage in stages}
    for name in ("sheetsage2", "yourmt3+sheetsage2", "mr-mt3+sheetsage2",
                 "muscriptor+sheetsage2"):
        assert by_id[name]["model_actual"] == "SheetSage legacy via sheetsage-infer"
        assert by_id[name]["model_is_new_sheetsage2"] is False
    for name in ("muscriptor-small", "muscriptor-medium", "mt3-pytorch", "miros", "sheetsage2-native"):
        assert by_id[name]["enabled"] is False
        assert by_id[name]["blocked_reason"]
    assert by_id["mr-mt3"]["enabled"] is True
    assert by_id["yourmt3"]["enabled"] is True


def test_cli_writes_only_planning_metadata_and_refuses_overwrite(tmp_path, monkeypatch, capsys):
    target = tmp_path / "candidate-plan.json"
    monkeypatch.setattr(sys, "argv", [
        "plan_tier2_candidate_groups.py",
        "--registry", str(CATALOG_PATH),
        "--role", "full_instrument_amt",
        "--usage-mode", "commercial",
        "--output", str(target),
    ])
    assert plans.main() == 0
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["quality_winner"] is None
    assert "commercial_baseline_approved" in capsys.readouterr().out
    with pytest.raises(SystemExit) as failure:
        plans.main()
    assert failure.value.code == 2

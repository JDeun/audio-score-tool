"""Plan *comparable* model trials without running or blessing unreviewed weights.

Candidate selection is not a license opinion: missing checkpoint provenance,
noncommercial rights, absent official annotation and non-equivalent task roles
are always visible. Same-run batching is appropriate; simultaneous models
on one contested GPU are not a scientifically fair latency comparison.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

_ALLOWED_ROLES = {"full_instrument_amt", "chord_estimation", "beat_downbeat", "lead_sheet"}
_KINDS = {"model", "external_service", "training_scaffold"}
_GATES = {
    "redistribution_review", "noncommercial_weights", "no_upstream_license",
    "unknown", "unreviewed", "service_terms", "own_training_required",
}
_STATUSES = {
    "real_author_train_measured", "synthetic_smoke_only", "not_product_wired",
    "auth_runtime_not_verified", "unintegrated_research", "no_pretrained_weights",
    "research_adapter_available", "new_adapter_not_integrated", "not_integrated",
    "new_research_candidate", "manual_reference_export_only",
}
_UNSAFE_FOR_COMMERCIAL = {
    "noncommercial_weights", "no_upstream_license", "unknown",
    "unreviewed", "service_terms", "own_training_required",
}


class CandidatePlanError(ValueError):
    """The role taxonomy or model selection request contradicts reviewed facts."""


def validate_registry(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise CandidatePlanError("Expected version 1 candidate registry")
    if (
        data.get("automated_model_selection_approved") is not False
        or data.get("commercial_baseline_approved") is not False
        or data.get("same_corpus_multi_model_benchmark_complete") is not False
    ):
        raise CandidatePlanError("Research registry cannot claim model selection or release approval")
    candidates = data.get("candidates")
    groups = data.get("comparison_groups")
    if not isinstance(candidates, list) or not candidates or not isinstance(groups, list):
        raise CandidatePlanError("Candidates and comparison groups are required")
    by_id = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise CandidatePlanError("Candidate entry is not an object")
        identity = candidate.get("id")
        roles = candidate.get("roles")
        if (
            not isinstance(identity, str) or not identity
            or identity in by_id
            or candidate.get("kind") not in _KINDS
            or candidate.get("license_gate") not in _GATES
            or candidate.get("implementation") not in _STATUSES
            or not isinstance(roles, list) or not roles
            or not set(roles).issubset(_ALLOWED_ROLES)
            or len(set(roles)) != len(roles)
            or not isinstance(candidate.get("issues"), list)
            or not all(type(issue) is int and issue > 0 for issue in candidate["issues"])
            or not isinstance(candidate.get("source"), str)
            or not candidate["source"].startswith("https://")
        ):
            raise CandidatePlanError("Unreviewed, duplicate or incorrectly classified model entry")
        by_id[identity] = candidate
    seen = set()
    for group in groups:
        if not isinstance(group, dict):
            raise CandidatePlanError("Malformed comparison group")
        role = group.get("id")
        ids = group.get("candidate_ids")
        metrics = group.get("primary_quality")
        if (
            role not in _ALLOWED_ROLES or role in seen
            or not isinstance(ids, list) or len(ids) < 2
            or len(ids) != len(set(ids))
            or not isinstance(metrics, list) or not metrics
            or not isinstance(group.get("constraints"), str)
        ):
            raise CandidatePlanError("Invalid group role, candidate count or metrics")
        seen.add(role)
        for identity in ids:
            if identity not in by_id or role not in by_id[identity]["roles"]:
                raise CandidatePlanError("Never compare different task roles in one score table")
            if by_id[identity]["kind"] == "training_scaffold":
                raise CandidatePlanError("A training scaffold without weights is not a trial model")
    if seen != _ALLOWED_ROLES:
        raise CandidatePlanError("Role roster does not cover all independent comparison tasks")
    return data


def plan_candidate_group(
    registry: dict[str, Any], *, role: str, usage_mode: str,
) -> dict[str, Any]:
    validate_registry(registry)
    if role not in _ALLOWED_ROLES or usage_mode not in {"personal", "commercial"}:
        raise CandidatePlanError("Unsupported task role or usage mode")
    group = next(g for g in registry["comparison_groups"] if g["id"] == role)
    by_id = {candidate["id"]: candidate for candidate in registry["candidates"]}
    planned = []
    for identity in group["candidate_ids"]:
        item = by_id[identity]
        gate = item["license_gate"]
        implementation = item["implementation"]
        if usage_mode == "commercial" and gate in _UNSAFE_FOR_COMMERCIAL:
            status = "blocked_rights_or_service_terms"
        elif item["kind"] == "external_service":
            status = "manual_comparison_only"
        elif implementation == "real_author_train_measured":
            status = "needs_shared_heldout_corpus_and_production_review"
        elif implementation == "research_adapter_available":
            status = "adapter_available_requires_model_checkpoint_and_same_corpus"
        else:
            status = "needs_verified_checkpoint_and_execution_adapter"
        planned.append({
            "id": identity, "name": item["name"],
            "kind": item["kind"], "status": status,
            "license_gate": gate,
            "implementation_evidence": implementation,
            "issues": item["issues"],
        })
    return {
        "schema_version": 1,
        "purpose": "same-role-candidate-experiment-planning",
        "role": role,
        "usage_mode": usage_mode,
        "reference_metrics": group["primary_quality"],
        "shared_experiment_contract": group["constraints"],
        "candidate_count": len(planned),
        "candidates": planned,
        "execution_policy": (
            "Dispatch candidates as independent jobs on equivalent dedicated hardware; "
            "if sharing one GPU, serialize inference to avoid memory/latency contention. "
            "Use exactly the same recordings, reference labels, split, postprocessing "
            "and evaluation tolerances; record separate candidate checkpoints/runtimes."
        ),
        "quality_winner": None,
        "commercial_baseline_approved": False,
        "license_approval_inferred_from_score": False,
        "models_discarded_without_evidence": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Role-correct Tier 2 candidate inventory")
    parser.add_argument(
        "--registry", type=Path,
        default=Path("benchmarks/tier2/model-candidate-registry.json"),
    )
    parser.add_argument("--role", choices=sorted(_ALLOWED_ROLES), required=True)
    parser.add_argument("--usage-mode", choices=("personal", "commercial"), required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = plan_candidate_group(
            json.loads(args.registry.read_text(encoding="utf-8")),
            role=args.role, usage_mode=args.usage_mode,
        )
        if args.output is not None:
            if args.output.exists() or args.output.is_symlink():
                raise CandidatePlanError("Do not overwrite an existing candidate decision")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
            )
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Candidate group rejected: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

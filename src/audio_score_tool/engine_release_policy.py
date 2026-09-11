from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

EngineMaturity = Literal["personal_stable", "release_candidate", "experimental"]


class EnginePromotionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class EngineReleasePolicy:
    engine_key: str
    maturity: EngineMaturity
    default_eligible: bool
    commercial_eligible: bool
    requires_tier2_approval: bool
    note: str


_POLICIES = {
    "muscriptor": EngineReleasePolicy(
        engine_key="muscriptor",
        maturity="personal_stable",
        default_eligible=True,
        commercial_eligible=False,
        requires_tier2_approval=False,
        note="Public weights are non-commercial; personal/non-commercial only.",
    ),
    "mt3_infer": EngineReleasePolicy(
        engine_key="mt3_infer",
        maturity="release_candidate",
        default_eligible=True,
        commercial_eligible=True,
        requires_tier2_approval=True,
        note="Commercial default requires an exact backend/checkpoint and Tier 2 approval.",
    ),
    "native": EngineReleasePolicy(
        engine_key="native",
        maturity="experimental",
        default_eligible=False,
        commercial_eligible=False,
        requires_tier2_approval=True,
        note="Project-owned R&D path; never auto-promote to the product default.",
    ),
}

_ALIASES = {"yourmt3": "mt3_infer"}


def policy_for_engine(engine_key: str) -> EngineReleasePolicy:
    key = engine_key.strip().lower()
    key = _ALIASES.get(key, key)
    try:
        return _POLICIES[key]
    except KeyError as exc:
        raise EnginePromotionError(f"Unknown transcription engine policy: {engine_key}") from exc


def assert_default_promotion(
    engine_key: str,
    *,
    usage_mode: str,
    tier2_approved: bool,
) -> EngineReleasePolicy:
    policy = policy_for_engine(engine_key)
    if not policy.default_eligible:
        raise EnginePromotionError(
            f"{policy.engine_key} is {policy.maturity} and cannot be promoted to the default."
        )
    if usage_mode.strip().lower() == "commercial" and not policy.commercial_eligible:
        raise EnginePromotionError(f"{policy.engine_key} is not eligible for the commercial default.")
    if policy.requires_tier2_approval and not tier2_approved:
        raise EnginePromotionError(
            f"{policy.engine_key} requires Tier 2 approval before default promotion."
        )
    return policy


def release_policy_summary() -> list[dict[str, object]]:
    return [
        {
            "engine_key": policy.engine_key,
            "maturity": policy.maturity,
            "default_eligible": policy.default_eligible,
            "commercial_eligible": policy.commercial_eligible,
            "requires_tier2_approval": policy.requires_tier2_approval,
            "note": policy.note,
        }
        for policy in _POLICIES.values()
    ]

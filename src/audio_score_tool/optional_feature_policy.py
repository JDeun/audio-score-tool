from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

FeatureMaturity = Literal["experimental", "planned", "research"]


@dataclass(frozen=True, slots=True)
class OptionalFeaturePolicy:
    key: str
    maturity: FeatureMaturity
    enabled_by_default: bool
    core_release_blocker: bool
    canonical_state_write_allowed: bool
    note: str


_POLICIES = (
    OptionalFeaturePolicy(
        key="additional_amt_providers",
        maturity="experimental",
        enabled_by_default=False,
        core_release_blocker=False,
        canonical_state_write_allowed=False,
        note="Providers must enter through the AMT adapter and pass Tier 2 before default promotion.",
    ),
    OptionalFeaturePolicy(
        key="vision_llm_critic",
        maturity="experimental",
        enabled_by_default=False,
        core_release_blocker=False,
        canonical_state_write_allowed=False,
        note="Critics may propose findings but may not silently mutate canonical MusicXML.",
    ),
    OptionalFeaturePolicy(
        key="additional_formats",
        maturity="planned",
        enabled_by_default=False,
        core_release_blocker=False,
        canonical_state_write_allowed=False,
        note="Importers must normalize into canonical MusicXML; exporters are explicit materializations.",
    ),
    OptionalFeaturePolicy(
        key="daw_integration",
        maturity="planned",
        enabled_by_default=False,
        core_release_blocker=False,
        canonical_state_write_allowed=False,
        note="DAW bridges are adapters around explicit import/export and cannot become a second source of truth.",
    ),
    OptionalFeaturePolicy(
        key="collaboration_cloud_sync",
        maturity="planned",
        enabled_by_default=False,
        core_release_blocker=False,
        canonical_state_write_allowed=False,
        note="Cloud sync must preserve local SQLite/MusicXML ownership and use explicit conflict handling.",
    ),
    OptionalFeaturePolicy(
        key="mobile_web_companion",
        maturity="planned",
        enabled_by_default=False,
        core_release_blocker=False,
        canonical_state_write_allowed=False,
        note="Companions remain clients of the canonical desktop/library contract.",
    ),
    OptionalFeaturePolicy(
        key="realtime_transcription",
        maturity="research",
        enabled_by_default=False,
        core_release_blocker=False,
        canonical_state_write_allowed=False,
        note="Streaming transcription is isolated from the deterministic offline publish workflow.",
    ),
)


def optional_feature_summary() -> list[dict[str, object]]:
    return [
        {
            "key": policy.key,
            "maturity": policy.maturity,
            "enabled_by_default": policy.enabled_by_default,
            "core_release_blocker": policy.core_release_blocker,
            "canonical_state_write_allowed": policy.canonical_state_write_allowed,
            "note": policy.note,
        }
        for policy in _POLICIES
    ]


def assert_optional_feature_isolated(key: str) -> OptionalFeaturePolicy:
    normalized = key.strip().lower()
    for policy in _POLICIES:
        if policy.key == normalized:
            if policy.enabled_by_default or policy.core_release_blocker or policy.canonical_state_write_allowed:
                raise RuntimeError(f"Optional feature violates isolation policy: {normalized}")
            return policy
    raise KeyError(f"Unknown optional feature policy: {key}")

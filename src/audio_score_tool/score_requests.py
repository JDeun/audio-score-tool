"""User-selected score output contracts, shared by local and YouTube jobs.

Only advertise modes that have an actual processing path. A score mode is a
request for a *playable draft*, not a guarantee of instrument isolation,
professional notation or copyright clearance.
"""
from __future__ import annotations

SCORE_PARTS: dict[str, tuple[str, ...]] = {
    "full": ("all",),
    "lead_sheet": ("vocal", "chords"),
    "guitar_vocal": ("vocal", "guitar"),
}


def validate_score_mode(value: str | None) -> str:
    if not isinstance(value, str) or value not in SCORE_PARTS:
        raise ValueError("score_mode must be full, lead_sheet or guitar_vocal")
    return value


def requested_parts_for_mode(value: str) -> list[str]:
    return list(SCORE_PARTS[validate_score_mode(value)])


def needs_stem_separation(value: str) -> bool:
    return validate_score_mode(value) != "full"

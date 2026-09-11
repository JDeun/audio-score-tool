from __future__ import annotations

import pytest

from audio_score_tool.engine_release_policy import (
    EnginePromotionError,
    assert_default_promotion,
    policy_for_engine,
)


def test_native_engine_is_experimental_and_not_default_eligible():
    policy = policy_for_engine("native")
    assert policy.maturity == "experimental"
    assert policy.default_eligible is False
    with pytest.raises(EnginePromotionError, match="cannot be promoted"):
        assert_default_promotion("native", usage_mode="personal", tier2_approved=True)


def test_commercial_mt3_default_requires_tier2_approval():
    with pytest.raises(EnginePromotionError, match="requires Tier 2 approval"):
        assert_default_promotion("mt3_infer", usage_mode="commercial", tier2_approved=False)
    policy = assert_default_promotion(
        "mt3_infer", usage_mode="commercial", tier2_approved=True
    )
    assert policy.commercial_eligible is True


def test_muscriptor_cannot_be_commercial_default():
    with pytest.raises(EnginePromotionError, match="not eligible for the commercial default"):
        assert_default_promotion("muscriptor", usage_mode="commercial", tier2_approved=True)


def test_yourmt3_alias_uses_mt3_infer_policy():
    assert policy_for_engine("yourmt3").engine_key == "mt3_infer"

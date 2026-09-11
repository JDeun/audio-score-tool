from __future__ import annotations

import pytest

from audio_score_tool.optional_feature_policy import (
    assert_optional_feature_isolated,
    optional_feature_summary,
)


def test_all_optional_features_are_isolated_from_core_release():
    policies = optional_feature_summary()
    assert policies
    for policy in policies:
        assert policy["enabled_by_default"] is False
        assert policy["core_release_blocker"] is False
        assert policy["canonical_state_write_allowed"] is False
        assert_optional_feature_isolated(str(policy["key"]))


def test_expected_p3_tracks_are_declared():
    keys = {str(policy["key"]) for policy in optional_feature_summary()}
    assert {
        "additional_amt_providers",
        "vision_llm_critic",
        "additional_formats",
        "daw_integration",
        "collaboration_cloud_sync",
        "mobile_web_companion",
        "realtime_transcription",
    } <= keys


def test_unknown_optional_feature_fails_closed():
    with pytest.raises(KeyError, match="Unknown optional feature policy"):
        assert_optional_feature_isolated("future-unreviewed-feature")

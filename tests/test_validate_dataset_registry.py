from __future__ import annotations

import pytest

from scripts.validate_dataset_registry import validate_registry


def sample(license: str = "CC-BY-4.0", audio: bool = True) -> dict:
    return {"schema_version": 1, "datasets": [{
        "id": "example", "task": "multi_instrument_amt",
        "source": "https://example.org/dataset", "audio_included": audio,
        "license": license, "status": "planned",
    }]}


def test_permissive_audio_candidate() -> None:
    assert validate_registry(sample())["audio_candidates"] == ["example"]


def test_noncommercial_rejected_for_commercial_pipeline() -> None:
    assert validate_registry(sample("CC-BY-NC-SA-4.0"), commercial=True)["blocked"]["example"] == "noncommercial_license"


def test_unverified_license_blocked() -> None:
    assert validate_registry(sample("verify_upstream"))["blocked"]["example"] == "license_requires_verification"


def test_annotation_only_not_treated_as_audio() -> None:
    assert validate_registry(sample(audio=False))["blocked"]["example"] == "no_audio_in_dataset"


def test_duplicate_id_rejected() -> None:
    data = sample()
    data["datasets"].append(dict(data["datasets"][0]))
    with pytest.raises(ValueError, match="Duplicate"):
        validate_registry(data)

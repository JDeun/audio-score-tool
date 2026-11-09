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


def test_recommended_real_dataset_registry_preserves_reference_availability():
    import json
    from pathlib import Path

    registry = json.loads(
        (Path(__file__).resolve().parents[1] / "benchmarks/tier2/dataset-registry.json")
        .read_text(encoding="utf-8")
    )
    datasets = {item["id"]: item for item in registry["datasets"]}
    vocal = datasets["vocadito_v3"]
    assert vocal["task"] == "vocal_amt"
    assert vocal["license"] == "CC-BY-4.0"
    assert vocal["training_overlap"] == "unknown"
    assert vocal["archive_md5"] == "dea40fd18f14d899643c4ba221b33a46"
    coco = datasets["cocochorales"]
    assert coco["audio_included"] is True
    assert coco["license"] == "CC-BY-4.0"
    assert coco["reference_format"] == "mix.mid"
    assert coco["audio_format"] == "mix.wav"
    assert coco["status"] == "planned"  # not prematurely approved
    assert coco["subset"] == "official_tiny"
    assert datasets["slakh2100"]["audio_included"] is True
    assert datasets["guitarset"]["audio_included"] is True
    # ASAP annotations/score do not embed the aligned MAESTRO recordings.
    assert datasets["asap"]["audio_included"] is False
    assert datasets["asap"]["license"] == "CC-BY-NC-SA-4.0"
    assert datasets["maestro"]["license"] == "CC-BY-NC-SA-4.0"
    commercial = validate_registry(registry, commercial=True)
    assert commercial["blocked"]["asap"] in {
        "noncommercial_license", "no_audio_in_dataset",
    }
    assert commercial["blocked"]["maestro"] == "noncommercial_license"
    assert "cocochorales" in commercial["audio_candidates"]


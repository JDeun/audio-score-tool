"""Exact-source MR-MT3 / YourMT3 model comparisons; synthetic metadata only."""
from __future__ import annotations

import copy
import json
import sys

import pytest

from scripts import compare_cocochorales_models as comparison


def _fixture(model_key: str) -> dict:
    revision, checksum, runtime = comparison._MODEL_ID[model_key]
    scores = {
        "mr_mt3": (0.65, 0.43, 0.22),
        "yourmt3": (0.74, 0.52, 0.31),
    }[model_key]
    cases = []
    for track in comparison.TRACKS:
        cases.append({
            "ensemble": track.split("_track")[0],
            "track_id": track, "split": "train", "status": "scored",
            "source_proof_sha256": "a" * 64,
            "score_report_sha256": "b" * 64,
            "audio_sha256": "c" * 64,
            "reference_midi_sha256": "d" * 64,
            "reference_note_count": 109,
            "prediction_note_count": 130,
            "inference_seconds": 30.0,
            "musicxml": {"parts": 4, "notes": 150},
            **dict(zip(comparison._METRICS, scores)),
        })
    return {
        "schema_version": 1,
        "purpose": "four-ensemble-author-sample-real-mt3-review",
        "model": model_key,
        "model_revision": revision,
        "runtime_revision": runtime,
        "checkpoint_sha256": checksum,
        "all_samples_in_train_split": True,
        "heldout_generalization_measured": False,
        "human_editing_time_measured": False,
        "commercial_release_quality_approved": False,
        "model_redistribution_approved": False,
        "source_media_published": False,
        "sample_count": 4, "scored_count": 4, "failed_count": 0,
        "cases": cases,
        "macro_metrics_successful_only": dict(zip(comparison._METRICS, scores)),
    }


def test_identical_original_sources_produce_metrics_and_no_commercial_promotion():
    result = comparison.compare_same_source_models(_fixture("mr_mt3"), _fixture("yourmt3"))
    assert result["case_count"] == 4
    assert result["complete_paired_case_count"] == 4
    assert result["all_candidates_completed"] is True
    assert result["research_only_order_if_complete"] == ["yourmt3", "mr_mt3"]
    assert all(
        row["yourmt3_minus_mrmt3"]["instrument_onset_offset_f1"] == pytest.approx(0.09)
        for row in result["tracks"]
    )
    assert result["exactly_same_audio_and_independent_reference_proven"] is True
    assert result["heldout_generalization_measured"] is False
    assert result["commercial_default_selected"] is False
    assert result["model_redistribution_approved"] is False
    assert result["discarded_models"] == []


@pytest.mark.parametrize(("path", "value"), [
    ("audio_sha256", "f" * 64),
    ("reference_midi_sha256", "e" * 64),
    ("source_proof_sha256", "8" * 64),
    ("reference_note_count", 200),
    ("split", "test"),
])
def test_different_audio_references_or_splits_are_never_compared(path, value):
    left, right = _fixture("mr_mt3"), _fixture("yourmt3")
    right["cases"][0][path] = value
    with pytest.raises(comparison.ModelComparisonError):
        comparison.compare_same_source_models(left, right)


@pytest.mark.parametrize(("mutate", "reason"), [
    (lambda x: x.update(checkpoint_sha256="0" * 64), "pinned"),
    (lambda x: x.update(commercial_release_quality_approved=True), "unapproved"),
    (lambda x: x.update(heldout_generalization_measured=True), "unapproved"),
    (lambda x: x["cases"][2].update(note_onset_f1=float("nan")), "inference/metrics"),
    (lambda x: x["cases"][2].update(note_onset_f1=1.5), "inference/metrics"),
    (lambda x: x["cases"][1].update(track_id="random_track145011"), "invalid track"),
    (lambda x: x["cases"].pop(), "incomplete ensemble coverage"),
    (lambda x: x["macro_metrics_successful_only"].update(
        instrument_onset_offset_f1=0.99), "claimed macro"),
])
def test_unverified_model_identity_or_fake_metrics_fail_closed(mutate, reason):
    a, b = _fixture("mr_mt3"), _fixture("yourmt3")
    mutate(b)
    with pytest.raises(comparison.ModelComparisonError, match=reason):
        comparison.compare_same_source_models(a, b)


def test_failed_model_case_is_not_hidden_by_macro_average():
    mr, your = _fixture("mr_mt3"), _fixture("yourmt3")
    case = your["cases"][2]
    case.update(status="failed")
    your["scored_count"] = 3
    your["failed_count"] = 1
    result = comparison.compare_same_source_models(mr, your)
    assert result["complete_paired_case_count"] == 3
    assert result["all_candidates_completed"] is False
    assert result["research_only_order_if_complete"] is None
    assert result["tracks"][2]["yourmt3_minus_mrmt3"] is None


def test_cli_keeps_pending_metrics_private_and_refuses_existing_output(tmp_path, monkeypatch):
    first, second = tmp_path / "mr.json", tmp_path / "your.json"
    first.write_text(json.dumps(_fixture("mr_mt3")), encoding="utf-8")
    second.write_text(json.dumps(_fixture("yourmt3")), encoding="utf-8")
    output = tmp_path / "comparison.pending.json"
    monkeypatch.setattr(sys, "argv", [
        "compare_cocochorales_models.py",
        "--mrmt3", str(first), "--yourmt3", str(second), "--output", str(output),
    ])
    assert comparison.main() == 0
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["commercial_default_selected"] is False
    with pytest.raises(SystemExit) as exc:
        comparison.main()
    assert exc.value.code == 2


def test_same_original_reference_does_not_mean_same_checkpoint():
    first, second = _fixture("mr_mt3"), _fixture("yourmt3")
    assert first["checkpoint_sha256"] != second["checkpoint_sha256"]
    result = comparison.compare_same_source_models(copy.deepcopy(first), copy.deepcopy(second))
    assert result["model_checkpoints"]["mr_mt3"]["checkpoint_sha256"] == first["checkpoint_sha256"]
    assert result["model_checkpoints"]["yourmt3"]["checkpoint_sha256"] == second["checkpoint_sha256"]

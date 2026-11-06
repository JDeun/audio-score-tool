from __future__ import annotations

import pytest

pytest.importorskip("mir_eval")

from scripts.score_casd_chords import score


def test_perfect_chord_predictions_for_two_annotators() -> None:
    reference = {
        "annotators": [
            {"index": 0, "intervals": [
                {"start": 0.0, "end": 2.0, "label": "C:maj"},
                {"start": 2.0, "end": 4.0, "label": "A:min"},
            ]},
            {"index": 1, "intervals": [
                {"start": 0.0, "end": 2.0, "label": "C:maj"},
                {"start": 2.0, "end": 4.0, "label": "A:min"},
            ]},
        ]
    }
    prediction = {"chords": [
        {"time_seconds": 0.0, "label": "C:maj"},
        {"time_seconds": 2.0, "label": "A:min"},
    ]}
    result = score(reference, prediction)
    assert len(result["annotators"]) == 2
    assert result["mean_by_metric"]["root"] == pytest.approx(1.0)
    assert result["mean_by_metric"]["majmin"] == pytest.approx(1.0)


def test_mismatched_root_reduces_score() -> None:
    reference = {"annotators": [{"index": 0, "intervals": [
        {"start": 0.0, "end": 4.0, "label": "C:maj"}
    ]}]}
    prediction = {"chords": [{"time_seconds": 0.0, "label": "D:maj"}]}
    assert score(reference, prediction)["mean_by_metric"]["root"] == pytest.approx(0.0)


@pytest.mark.parametrize("mutation", ["initial-gap", "internal-gap", "overlap", "truncated", "empty"])
def test_reject_incomplete_or_inconsistent_independent_reference(mutation: str) -> None:
    reference = {
        "annotators": [{"index": 0, "intervals": [
            {"start": 0.0, "end": 2.0, "label": "C:maj"},
            {"start": 2.0, "end": 4.0, "label": "A:min"},
        ]}],
        "duration_seconds": 4.0,
    }
    rows = reference["annotators"][0]["intervals"]
    if mutation == "initial-gap":
        rows[0]["start"] = 0.5
    elif mutation == "internal-gap":
        rows[1]["start"] = 2.1
    elif mutation == "overlap":
        rows[1]["start"] = 1.9
    elif mutation == "truncated":
        rows[1]["end"] = 3.9
    else:
        rows.clear()
    with pytest.raises(ValueError, match="cover|empty"):
        score(reference, {"chords": [{"time_seconds": 0, "label": "C:maj"}]})


@pytest.mark.parametrize("timeline", [
    [{"time_seconds": -1.0, "label": "C:maj"}],
    [{"time_seconds": float("nan"), "label": "C:maj"}],
    [{"time_seconds": float("inf"), "label": "C:maj"}],
    [{"time_seconds": 4.0, "label": "C:maj"}],
    [{"time_seconds": True, "label": "C:maj"}],
    [{"time_seconds": 0, "label": ""}],
    [{"time_seconds": 1.0, "label": "C:maj"}, {"time_seconds": 0.0, "label": "G:maj"}],
    [{"time_seconds": 1.0, "label": "C:maj"}, {"time_seconds": 1.0, "label": "G:maj"}],
])
def test_reject_invalid_unsorted_or_nonfinite_prediction_timing(timeline: list) -> None:
    from scripts.score_casd_chords import intervals_from_prediction

    with pytest.raises(ValueError, match="time|ordered|label|nonempty|duration"):
        intervals_from_prediction({"chords": timeline}, 4.0)


def test_multiexpert_reference_requires_same_complete_duration() -> None:
    reference = {"annotators": [
        {"index": 0, "intervals": [{"start": 0, "end": 4, "label": "C:maj"}]},
        {"index": 1, "intervals": [{"start": 0, "end": 3, "label": "C:maj"}]},
    ]}
    with pytest.raises(ValueError, match="cover"):
        score(reference, {"chords": [{"time_seconds": 0, "label": "C:maj"}]})


def test_reject_mismatched_recording_fingerprints_and_duration() -> None:
    reference = {
        "annotators": [{"index": 0, "intervals": [
            {"start": 0, "end": 4, "label": "C:maj"},
        ]}],
        "recording_sha256": "a" * 64,
        "duration_seconds": 4.0,
    }
    candidate = {
        "recording_sha256": "b" * 64,
        "duration_seconds": 4.0,
        "chords": [{"time_seconds": 0, "label": "C:maj"}],
    }
    with pytest.raises(ValueError, match="recording SHA-256"):
        score(reference, candidate)
    candidate["recording_sha256"] = "a" * 64
    candidate["duration_seconds"] = 3.0
    with pytest.raises(ValueError, match="duration"):
        score(reference, candidate)


def test_prediction_can_declare_initial_no_chord_as_n_label() -> None:
    from scripts.score_casd_chords import intervals_from_prediction

    times, labels = intervals_from_prediction({
        "chords": [
            {"time_seconds": 1.0, "label": "C:maj"},
            {"time_seconds": 2.0, "label": "A:min"},
        ],
    }, 4.0)
    assert times.tolist() == [[0.0, 1.0], [1.0, 2.0], [2.0, 4.0]]
    assert labels == ["N", "C:maj", "A:min"]

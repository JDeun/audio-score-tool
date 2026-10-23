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

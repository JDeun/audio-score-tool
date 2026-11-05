from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.import_casd_annotations import extract_casd


def test_imports_all_chord_annotators(tmp_path: Path) -> None:
    path = tmp_path / "sample.jams"
    path.write_text(json.dumps({
        "annotations": [
            {"namespace": "chord", "data": [{"time": 0, "duration": 1.5, "value": "C:maj"}]},
            {"namespace": "chord", "data": [{"time": 0, "duration": 1.5, "value": "C"}]},
            {"namespace": "beat", "data": [{"time": 0, "duration": 0, "value": 1}]},
        ],
    }), encoding="utf-8")
    result = extract_casd(path)
    assert len(result["annotators"]) == 2
    assert result["annotators"][0]["intervals"] == [
        {"start": 0.0, "end": 1.5, "label": "C:maj"}
    ]
    assert result["audio_included"] is False


def test_rejects_invalid_interval(tmp_path: Path) -> None:
    path = tmp_path / "invalid.jams"
    path.write_text(json.dumps({
        "annotations": [{"namespace": "chord", "data": [
            {"time": 0, "duration": -1, "value": "C:maj"}
        ]}],
    }), encoding="utf-8")
    with pytest.raises(ValueError):
        extract_casd(path)

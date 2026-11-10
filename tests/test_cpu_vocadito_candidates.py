"""Local synthetic evaluator tests only; no network, real models, audio or downloads."""
from __future__ import annotations

import hashlib

import numpy as np
import pytest

from scripts.run_cpu_vocadito_candidates import (
    CASE_IDS,
    complete_macro,
    f0_metrics,
    validate_f0,
    verified_asset,
)
from scripts.summarize_cpu_vocadito import summarize


def test_asset_requires_upstream_identity_before_load(tmp_path):
    data = b"synthetic, not model weights"
    path = tmp_path / "test.pth"
    path.write_bytes(data)
    blob = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
    assert verified_asset(path, blob, len(data))["sha256"] == hashlib.sha256(data).hexdigest()
    path.write_bytes(b"X" * len(data))
    with pytest.raises(ValueError, match="Git blob"):
        verified_asset(path, blob, len(data))


@pytest.mark.parametrize("raw", [b"0,440\n0,441\n", b"0,-440\n1,440\n", b"0,440,2\n1,440,2\n"])
def test_invalid_f0_reference_rejected(raw):
    with pytest.raises(ValueError):
        validate_f0(raw)


def test_f0_octave_error_is_not_hidden_by_pitch_class_agreement():
    pytest.importorskip("mir_eval")
    raw = b"0,440\n0.01,440\n0.02,440\n0.03,440\n"
    times = np.arange(4) * 0.01
    exact = f0_metrics(raw, times, np.full(4, 440.0))
    octave = f0_metrics(raw, times, np.full(4, 880.0))
    silent = f0_metrics(raw, times, np.zeros(4))
    assert exact["Raw Pitch Accuracy"] == 1
    assert octave["Raw Pitch Accuracy"] == 0
    assert octave["Raw Chroma Accuracy"] == 1
    assert octave["octave_errors_per_reference_voiced_frame"] == 1
    assert silent["Raw Pitch Accuracy"] == 0
    assert silent["Voicing Recall"] == 0


def _cases():
    return [{"id": case, "status": "scored", "audio_sha256": "audio-" + case,
             "reference_sha256": {"A1": "a1", "A2": "a2"}, "f0_reference_sha256": "f0",
             "annotators": {"A1": {"onset_f1": 0.2, "onset_offset_f1": 0.1},
                            "A2": {"onset_f1": 0.8, "onset_offset_f1": 0.5}}}
            for case in CASE_IDS]


def _report(candidate="mr_mt3"):
    cases = _cases()
    return {"candidate": candidate, "task": "note_amt", "device": "cpu", "cases": cases,
            "macro": complete_macro(cases, "note_amt"), "all_cases_complete": True,
            "archive_sha256": "archive", "source_revision": "commit"}


def test_macro_uses_both_annotators_and_all_forty_recordings():
    cases = _cases()
    assert complete_macro(cases, "note_amt") == {"onset_f1": 0.5, "onset_offset_f1": 0.3}
    assert complete_macro(cases[:-1], "note_amt") is None
    cases[-1]["status"] = "failed"
    assert complete_macro(cases, "note_amt") is None
    assert complete_macro(cases[:1] * 40, "note_amt") is None


def test_summary_rejects_changed_audio_and_false_completion():
    first, second = _report(), _report("yourmt3")
    second["cases"][0]["audio_sha256"] = "different-waveform"
    with pytest.raises(ValueError, match="Different audio"):
        summarize([first, second])
    first["cases"].pop()
    with pytest.raises(ValueError, match="aggregate"):
        summarize([first])


def test_missing_candidates_never_produce_a_complete_comparison():
    result = summarize([_report()])
    assert result["all_candidates_complete"] is False
    assert "basic_pitch" in result["missing_candidates"]
    assert result["f0_tracking"] == []
    assert result["note_amt"][0]["macro"]["onset_f1"] == 0.5

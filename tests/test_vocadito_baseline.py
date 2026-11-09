from pathlib import Path

import numpy as np
import pytest

from audio_score_tool.metrics import MidiNote
from scripts.run_vocadito_baseline import read_notes, run, score_annotations


def test_vocadito_preserves_human_pitch_hz_and_duration():
    intervals, pitches = read_notes(b"0.5,445.25,0.3\n0.1,220,0.2\n")
    np.testing.assert_allclose(intervals, [[0.1, 0.3], [0.5, 0.8]])
    np.testing.assert_allclose(pitches, [220, 445.25])


@pytest.mark.parametrize("raw", [b"", b"0,440", b"0,0,1", b"nan,440,1", b"0,440,-1"])
def test_vocadito_rejects_invalid_reference(raw):
    with pytest.raises(ValueError):
        read_notes(raw)


def test_vocadito_rejects_unverified_archive_before_running_model(tmp_path: Path):
    archive = tmp_path / "wrong.zip"
    archive.write_bytes(b"wrong source")
    with pytest.raises(ValueError, match="checksum"):
        run(archive, tmp_path / "checkpoints", tmp_path / "output", model="mr_mt3")
    assert not (tmp_path / "output").exists()


def test_vocadito_scores_actual_pitch_and_onset_separately_from_offsets():
    pytest.importorskip("mir_eval")
    reference = b"0.5,440,1\n"
    predicted = [MidiNote(69, 0.5, 1.5, 0, 0, False)]
    assert score_annotations(predicted, reference)["onset_offset_f1"] == 1
    shifted = [MidiNote(69, 0.75, 1.75, 0, 0, False)]
    assert score_annotations(shifted, reference)["onset_f1"] == 0
    shortened = [MidiNote(69, 0.5, 0.6, 0, 0, False)]
    assert score_annotations(shortened, reference)["onset_f1"] == 1
    assert score_annotations(shortened, reference)["onset_offset_f1"] == 0
    assert score_annotations([], reference)["onset_f1"] == 0

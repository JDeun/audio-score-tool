from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import numpy as np
import pytest

from scripts.run_cpu_specialists import (
    TUNING,
    beat_references,
    check_url,
    guitar_notes,
    score_midi,
    selected_jams,
    verify_blob,
    zip_bytes,
)


def test_source_digest_rejects_tamper(tmp_path: Path):
    path = tmp_path / "weights"
    path.write_bytes(b"example")
    digest = hashlib.sha1(b"blob 7\0example").hexdigest()
    verify_blob(path, digest, 7)
    path.write_bytes(b"EXAMPLE")
    with pytest.raises(ValueError, match="blob mismatch"):
        verify_blob(path, digest, 7)


@pytest.mark.parametrize("url", ["http://zenodo.org/test", "https://example.com/a",
                                 "https://token@zenodo.org/test", "https://zenodo.org:444/a"])
def test_download_rejects_untrusted_urls(url):
    with pytest.raises(ValueError):
        check_url(url)


def test_predeclared_case_selection_is_independent_of_scores():
    names = [f"annotations/{p}_BN1-129-Eb_{m}.jams"
             for p in ("03", "04", "05") for m in ("comp", "solo")]
    assert selected_jams(list(reversed(names))) == names
    with pytest.raises(ValueError, match="Missing"):
        selected_jams(names[:-1])


def test_zip_member_budget(tmp_path):
    path = tmp_path / "tiny.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("notes.jams", b"12345")
    with zipfile.ZipFile(path) as zf:
        assert zip_bytes(zf, "notes.jams", 5) == b"12345"
        with pytest.raises(ValueError):
            zip_bytes(zf, "notes.jams", 4)


def test_all_six_string_identities_not_annotation_order():
    annotations = [{"namespace": "note_midi", "annotation_metadata": {"data_source": str(i)},
                    "data": [{"time": 1.0 + i, "duration": 0.5, "value": float(p)}]}
                   for i, p in enumerate(TUNING)]
    notes, labels = guitar_notes({"annotations": list(reversed(annotations))})
    assert [p for _, p in notes] == list(TUNING)
    np.testing.assert_array_equal(labels, np.arange(6))
    with pytest.raises(ValueError):
        guitar_notes({"annotations": annotations[:-1]})


def test_reference_beats_keep_absolute_seconds():
    data = [{"time": 2 + i * 0.5, "value": {"position": (i % 4) + 1}} for i in range(12)]
    beats, down = beat_references({"annotations": [{"namespace": "beat_position", "data": data}]})
    np.testing.assert_array_equal(down, [2, 4, 6])
    assert beats[0] == 2 and beats[-1] == 7.5


def test_note_evaluation_does_not_forgive_octave_errors(tmp_path):
    pretty_midi = pytest.importorskip("pretty_midi")
    pytest.importorskip("mir_eval")
    paths = []
    for name, pitch in (("reference", 60), ("same", 60), ("octave", 72)):
        pm = pretty_midi.PrettyMIDI()
        part = pretty_midi.Instrument(0)
        part.notes.append(pretty_midi.Note(80, pitch, 0.5, 1.0))
        pm.instruments.append(part)
        path = tmp_path / (name + ".mid")
        pm.write(str(path))
        paths.append(path)
    assert score_midi(paths[0], paths[1])["onset"]["f1"] == 1.0
    assert score_midi(paths[0], paths[2])["onset"]["f1"] == 0.0

"""Contract checks for real-model CI: never pass empty or corrupt note output."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from music21 import instrument, note, stream

from scripts import run_tier2_model_smoke as smoke


def _score_file(path: Path, fmt: str, *, notes: bool = True) -> Path:
    score = stream.Score()
    piano = stream.Part()
    piano.insert(0, instrument.Piano())
    piano.append(note.Note("C4", quarterLength=1) if notes else note.Rest(quarterLength=1))
    score.insert(0, piano)
    score.write(fmt, fp=str(path))
    return path


def _outputs(root: Path) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    midi = _score_file(root / "score.mid", "midi")
    musicxml = _score_file(root / "score.musicxml", "musicxml")
    return midi, musicxml


def test_model_smoke_requires_notes_in_both_actual_file_formats(tmp_path: Path):
    midi, musicxml = _outputs(tmp_path)
    summary = smoke.verify_model_outputs(midi, musicxml)
    assert summary["midi_notes"] > 0
    assert summary["notes"] > 0
    assert summary["parts"] == 1


@pytest.mark.parametrize(
    ("format_name", "label"),
    [("midi", "MIDI"), ("musicxml", "MusicXML")],
)
def test_parseable_but_empty_note_outputs_must_fail(
    tmp_path: Path, format_name: str, label: str,
):
    midi, musicxml = _outputs(tmp_path)
    selected = midi if format_name == "midi" else musicxml
    _score_file(selected, format_name, notes=False)
    with pytest.raises(RuntimeError, match=f"{label} model output (contains no notes|cannot be parsed)"):
        smoke.verify_model_outputs(midi, musicxml)


@pytest.mark.parametrize(
    ("format_name", "label"),
    [("midi", "MIDI"), ("musicxml", "MusicXML")],
)
def test_missing_or_zero_byte_output_is_not_accepted(tmp_path: Path, format_name: str, label: str):
    midi, musicxml = _outputs(tmp_path)
    selected = midi if format_name == "midi" else musicxml
    selected.write_bytes(b"")
    with pytest.raises(RuntimeError, match=f"{label} model output is missing or empty"):
        smoke.verify_model_outputs(midi, musicxml)


def test_corrupt_model_output_is_not_accepted(tmp_path: Path):
    midi, musicxml = _outputs(tmp_path)
    midi.write_bytes(b"not-a-valid-midi-file")
    with pytest.raises(RuntimeError, match="MIDI model output cannot be parsed"):
        smoke.verify_model_outputs(midi, musicxml)


def test_cli_emits_verified_artifact_hashes_and_runtime_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    audio = tmp_path / "input.wav"
    audio.write_bytes(b"fake audio passed only to the stubbed inference engine")
    output = tmp_path / "output"
    midi, musicxml = _outputs(output)

    class FakeEngine:
        def __init__(self, _settings):
            pass

        def ready(self):
            return True

        def transcribe(self, given_audio, given_output, *, device):
            assert (given_audio, given_output, device) == (audio, output, "cpu")
            return SimpleNamespace(midi_path=midi, musicxml_path=musicxml)

    monkeypatch.setattr(smoke, "MT3InferEngine", FakeEngine)
    monkeypatch.setattr(sys, "argv", [
        "run_tier2_model_smoke.py", str(audio), str(output), "--model", "yourmt3",
    ])
    monkeypatch.setenv("GITHUB_SHA", "1" * 40)
    assert smoke.main() == 0

    result = json.loads((output / "smoke-result.json").read_text(encoding="utf-8"))
    assert result["note_events_detected"] is True
    assert result["notes"] > 0 and result["midi_notes"] > 0
    assert result["source_commit"] == "1" * 40
    assert result["runtime"]["device"] == "cpu"
    assert result["runtime"]["python"]
    assert result["audio_sha256"] == hashlib.sha256(audio.read_bytes()).hexdigest()
    assert result["midi_sha256"] == hashlib.sha256(midi.read_bytes()).hexdigest()
    assert result["musicxml_sha256"] == hashlib.sha256(musicxml.read_bytes()).hexdigest()
    assert result["checkpoint"] == {"revision": None, "sha256": None, "verified": False}


def test_failed_real_model_smoke_does_not_write_success_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    audio = tmp_path / "input.wav"
    audio.write_bytes(b"fixture")
    output = tmp_path / "out"
    midi, musicxml = _outputs(output)
    _score_file(musicxml, "musicxml", notes=False)

    class FakeEngine:
        def __init__(self, _settings):
            pass

        def ready(self):
            return True

        def transcribe(self, _audio, _output, *, device):
            assert device == "cpu"
            return SimpleNamespace(midi_path=midi, musicxml_path=musicxml)

    monkeypatch.setattr(smoke, "MT3InferEngine", FakeEngine)
    monkeypatch.setattr(sys, "argv", [
        "run_tier2_model_smoke.py", str(audio), str(output), "--model", "mr_mt3",
    ])
    with pytest.raises(RuntimeError, match="MusicXML model output contains no notes"):
        smoke.main()
    assert not (output / "smoke-result.json").exists()

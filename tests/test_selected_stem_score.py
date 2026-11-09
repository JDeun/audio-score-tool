"""Real score-mode contracts and isolated-stem assembly tests.

Only original test notes are generated. No public model/audio downloads and
no claims that 6-stem separation is perfect.
"""
from __future__ import annotations

import sys
from pathlib import Path

import mido
import pytest
from music21 import instrument, note, stream

from audio_score_tool import selected_stem_score as stems
from audio_score_tool.auto_chords import ChordInference
from audio_score_tool.config import Settings
from audio_score_tool.score_requests import requested_parts_for_mode, validate_score_mode
from audio_score_tool.transcription_engine import TranscriptionArtifacts


def _fake_model_score(output_dir: Path) -> TranscriptionArtifacts:
    output_dir.mkdir(parents=True, exist_ok=True)
    score = stream.Score()
    part = stream.Part()
    part.partName = "Piano"
    part.insert(0, instrument.Piano())
    measure = stream.Measure(number=1)
    measure.append(note.Note("C4", quarterLength=1.0))
    measure.append(note.Note("E4", quarterLength=1.0))
    part.append(measure)
    score.insert(0, part)
    xml = output_dir / "score.musicxml"
    midi = output_dir / "score.mid"
    score.write("musicxml", fp=str(xml))
    score.write("midi", fp=str(midi))
    return TranscriptionArtifacts(midi, xml)


class FakeEngine:
    def __init__(self):
        self.inputs = []

    def transcribe(self, audio: Path, output_dir: Path, *, device: str, **_kwargs):
        self.inputs.append((audio.name, device))
        return _fake_model_score(output_dir)


def _run(tmp_path: Path, monkeypatch, mode: str, *, no_guitar: bool = False):
    input_path = tmp_path / "source.wav"
    input_path.write_bytes(b"source-only-unsigned-test")
    engine = FakeEngine()

    monkeypatch.setattr(stems, "command_exists", lambda _: True)

    def fake_demucs(_command, args, **kwargs):
        assert args[0] == "-n"
        assert args[-1] == input_path
        stem_root = Path(args[args.index("-o") + 1])
        model = args[1]
        chosen = stem_root / model / "source"
        chosen.mkdir(parents=True)
        for role in ("vocals", "no_vocals", "guitar"):
            if role == "guitar" and no_guitar:
                continue
            (chosen / f"{role}.wav").write_bytes(b"X" * 1024)

    monkeypatch.setattr(stems, "run_command", fake_demucs)
    monkeypatch.setattr(
        stems, "infer_chords",
        lambda _score: [
            ChordInference(
                measure_index=0, measure="1", offset_quarters=0.0,
                symbol="C", confidence=0.93, target_note_id=None,
            )
        ],
    )
    result = stems.transcribe_selected_stems(
        input_path, tmp_path / "output", tmp_path / "stems",
        score_mode=mode,
        settings=Settings(demucs_cmd=sys.executable),
        engine=engine,
        device="cpu", demucs_device="cpu",
    )
    return result, engine


def test_guitar_and_vocal_actually_transcribe_two_distinct_separated_stems(
    tmp_path, monkeypatch,
):
    (artifacts, vocals, warnings), engine = _run(tmp_path, monkeypatch, "guitar_vocal")
    assert engine.inputs == [("vocals.wav", "cpu"), ("guitar.wav", "cpu")]
    assert vocals.name == "vocals.wav"
    assert any("TAB" in warning for warning in warnings)
    from music21 import converter

    score = converter.parse(str(artifacts.musicxml_path))
    assert sorted(part.partName for part in score.parts) == ["Guitar", "Voice"]
    midi = mido.MidiFile(str(artifacts.midi_path))
    assert sum(msg.type == "note_on" and msg.velocity > 0
               for track in midi.tracks for msg in track) >= 2


def test_lead_sheet_transcribes_vocals_and_backing_to_infer_real_chords(
    tmp_path, monkeypatch,
):
    (artifacts, vocals, warnings), engine = _run(tmp_path, monkeypatch, "lead_sheet")
    assert engine.inputs == [("vocals.wav", "cpu"), ("no_vocals.wav", "cpu")]
    assert vocals.name == "vocals.wav"
    assert len(warnings) == 1
    from music21 import converter, harmony

    score = converter.parse(str(artifacts.musicxml_path))
    assert len(score.parts) == 1
    assert score.parts[0].partName == "Voice"
    assert list(score.recurse().getElementsByClass(harmony.ChordSymbol))


@pytest.mark.parametrize("invalid", ["", "full_mix", "piano_only", "guitar"])
def test_unrecognized_or_unimplemented_modes_are_rejected(invalid):
    with pytest.raises(ValueError, match="score_mode"):
        validate_score_mode(invalid)


def test_score_mode_contract_names_correspond_to_actual_output_roles():
    assert requested_parts_for_mode("full") == ["all"]
    assert requested_parts_for_mode("lead_sheet") == ["vocal", "chords"]
    assert requested_parts_for_mode("guitar_vocal") == ["vocal", "guitar"]


def test_missing_guitar_stem_fails_without_publishing_wrong_part(tmp_path, monkeypatch):
    with pytest.raises(stems.SelectedScoreError, match="guitar"):
        _run(tmp_path, monkeypatch, "guitar_vocal", no_guitar=True)
    assert not (tmp_path / "output" / "score.musicxml").exists()


def test_missing_separator_blocks_before_any_model_execution(tmp_path, monkeypatch):
    monkeypatch.setattr(stems, "command_exists", lambda _: False)
    engine = FakeEngine()
    audio = tmp_path / "source.wav"
    audio.write_bytes(b"source")
    with pytest.raises(stems.SelectedScoreError, match="Demucs"):
        stems.transcribe_selected_stems(
            audio, tmp_path / "out", tmp_path / "stems",
            score_mode="guitar_vocal", settings=Settings(demucs_cmd="missing"),
            engine=engine, device="cpu", demucs_device="cpu",
        )
    assert engine.inputs == []


def test_original_source_never_becomes_an_unverified_fallback_stem(tmp_path, monkeypatch):
    monkeypatch.setattr(stems, "command_exists", lambda _: True)
    monkeypatch.setattr(stems, "run_command", lambda *_args, **_kwargs: None)
    audio = tmp_path / "source.wav"
    audio.write_bytes(b"source")
    with pytest.raises(stems.SelectedScoreError, match="vocals"):
        stems.transcribe_selected_stems(
            audio, tmp_path / "out", tmp_path / "stems",
            score_mode="lead_sheet", settings=Settings(demucs_cmd="demucs"),
            engine=FakeEngine(), device="cpu", demucs_device="cpu",
        )
    assert not (tmp_path / "out" / "score.musicxml").exists()

"""Real score-mode contracts and isolated-stem assembly tests.

Only original test notes are generated. No public model/audio downloads and
no claims that 6-stem separation is perfect.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import mido
import pytest
from music21 import instrument, note, stream

from audio_score_tool import selected_stem_score as stems
from audio_score_tool.auto_chords import ChordInference
from audio_score_tool.config import Settings
from audio_score_tool.metrics import midi_notes
from audio_score_tool.mt3_program_midi import midi_from_program_notes
from audio_score_tool.notation_backend import midi_to_musicxml
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
    assert any("tablature" in warning for warning in warnings)
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
    # Harmony labels must not synthesize extra backing notes in the MIDI.
    assert len(midi_notes(artifacts.midi_path)) == 2


@pytest.mark.parametrize("mode", ["lead_sheet", "guitar_vocal"])
def test_selected_modes_preserve_arbitrary_note_timings_and_cross_bar_ties(
    tmp_path, monkeypatch, mode,
):
    def arbitrary_score(output_dir):
        output_dir.mkdir(parents=True)
        program = 40 if output_dir.name == "vocal" else 24
        events = [
            SimpleNamespace(
                pitch=pitch, program=program, velocity=90, is_drum=False,
                start_time=start / 440, end_time=end / 440,
            )
            for pitch, start, end in [(60, 53, 1240), (64, 84, 531), (67, 101, 550)]
        ]
        midi = output_dir / "score.mid"
        xml = output_dir / "score.musicxml"
        midi_from_program_notes(events, ticks_per_quarter=220).save(midi)
        midi_to_musicxml(midi, xml)
        return TranscriptionArtifacts(midi, xml)

    monkeypatch.setattr(sys.modules[__name__], "_fake_model_score", arbitrary_score)
    (artifacts, _, _), _ = _run(tmp_path, monkeypatch, mode)
    original = midi_notes(tmp_path / "output" / "vocal" / "score.mid")
    if mode == "guitar_vocal":
        original += midi_notes(tmp_path / "output" / "guitar" / "score.mid")
    def key(n):
        return n.pitch, n.program, n.onset, n.offset
    actual = sorted(midi_notes(artifacts.midi_path), key=key)
    expected = sorted(original, key=key)
    assert len(actual) == len(expected)
    for left, right in zip(actual, expected):
        assert (left.pitch, left.program, left.is_drum) == (right.pitch, right.program, right.is_drum)
        assert left.onset == pytest.approx(right.onset, abs=0.0001)
        assert left.offset == pytest.approx(right.offset, abs=0.0001)


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


def test_guitar_vocal_independent_tempos_share_elapsed_audio_clock(tmp_path, monkeypatch):
    """One source can change tempo while the other is constant: notes remain synchronized."""
    from music21 import converter

    def different_tempo_score(output_dir):
        output_dir.mkdir(parents=True)
        vocal = output_dir.name == "vocal"
        midi = mido.MidiFile(type=1, ticks_per_beat=480)
        clock = mido.MidiTrack()
        if vocal:
            clock.append(mido.MetaMessage("set_tempo", tempo=1_000_000, time=0))
            clock.append(mido.MetaMessage("set_tempo", tempo=500_000, time=480))
        else:
            clock.append(mido.MetaMessage("set_tempo", tempo=750_000, time=0))
        midi.tracks.append(clock)

        def to_tick(seconds):
            if not vocal:
                return round(seconds * 480 * 1_000_000 / 750_000)
            return round(seconds * 480) if seconds <= 1 else round(480 + (seconds - 1) * 960)

        program = 40 if vocal else 24
        events = [(0, 0, mido.Message("program_change", channel=0, program=program))]
        for index, seconds in enumerate((0.25, 1.25, 2.25)):
            onset, finish = to_tick(seconds), to_tick(seconds + 0.25)
            pitch = (60 if vocal else 55) + index
            events.extend([
                (onset, 1, mido.Message("note_on", channel=0, note=pitch, velocity=83)),
                (finish, 0, mido.Message("note_off", channel=0, note=pitch, velocity=0)),
            ])
        events.sort(key=lambda row: (row[0], row[1]))
        notes = mido.MidiTrack()
        previous = 0
        for tick, _kind, message in events:
            notes.append(message.copy(time=tick - previous))
            previous = tick
        midi.tracks.append(notes)
        source_midi = output_dir / "score.mid"
        source_xml = output_dir / "score.musicxml"
        midi.save(source_midi)
        midi_to_musicxml(source_midi, source_xml)
        return TranscriptionArtifacts(source_midi, source_xml)

    monkeypatch.setattr(sys.modules[__name__], "_fake_model_score", different_tempo_score)
    (artifacts, _, warnings), _engine = _run(tmp_path, monkeypatch, "guitar_vocal")
    assert any("experimental" in warning for warning in warnings)
    expected = midi_notes(tmp_path / "output" / "vocal" / "score.mid") + midi_notes(
        tmp_path / "output" / "guitar" / "score.mid"
    )
    actual = midi_notes(artifacts.midi_path)

    def note_key(n):
        return n.is_drum, n.program, n.pitch, n.onset, n.offset

    assert len(actual) == len(expected) == 6
    for produced, original in zip(sorted(actual, key=note_key), sorted(expected, key=note_key)):
        assert (produced.pitch, produced.program, produced.is_drum) == (
            original.pitch, original.program, original.is_drum,
        )
        assert produced.onset == pytest.approx(original.onset, abs=0.002)
        assert produced.offset == pytest.approx(original.offset, abs=0.002)
    published = converter.parse(str(artifacts.musicxml_path))
    assert [part.partName for part in published.parts] == ["Voice", "Guitar"]

"""Preserve upstream-decoded MR-MT3 instrument identities without reference leakage."""
from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from audio_score_tool import mt3_program_midi as bridge
from audio_score_tool.metrics import evaluate_midi_files, midi_notes


def _note(pitch=60, program=40, onset=0.0, offset=0.5, drum=False, velocity=95):
    return SimpleNamespace(
        pitch=pitch, velocity=velocity, program=program,
        start_time=onset, end_time=offset, is_drum=drum,
    )


def test_programs_survive_pitched_midi_tracks_channels_and_music_metrics(tmp_path: Path):
    sequence = [
        _note(60, 40, 0.0, 0.5),
        _note(64, 41, 0.0, 0.5),
        _note(67, 42, 0.25, 0.75),
        _note(69, 40, 0.5, 1.0),
    ]
    midi = bridge.midi_from_program_notes(sequence, ticks_per_quarter=480)
    assert midi.type == 1
    assert len(midi.tracks) == 3
    assert [
        message.program
        for track in midi.tracks
        for message in track
        if message.type == "program_change"
    ] == [40, 41, 42]
    assert {
        message.channel
        for track in midi.tracks
        for message in track
        if message.type == "program_change"
    } == {0, 1, 2}
    path = tmp_path / "programs.mid"
    midi.save(str(path))
    decoded = midi_notes(path)
    assert len(decoded) == len(sequence)
    assert {(note.pitch, note.program) for note in decoded} == {
        (60, 40), (64, 41), (67, 42), (69, 40),
    }
    assert decoded[2].onset == pytest.approx(0.5) or (
        # Sorted by onset; the later two notes have exact 0.25/0.5 seconds.
        {round(note.onset, 3) for note in decoded} == {0.0, 0.25, 0.5}
    )
    assert sorted(round(n.offset - n.onset, 3) for n in decoded) == [0.5] * 4
    metrics = evaluate_midi_files(path, path)
    assert metrics.instrument_f1 == pytest.approx(1.0)


def test_drum_channel_is_reserved_and_not_given_to_melodic_instruments(tmp_path: Path):
    notes = [_note(36, program=0, drum=True)]
    notes.extend(_note(60 + i, program=i, onset=0.0, offset=0.5) for i in range(12))
    midi = bridge.midi_from_program_notes(notes)
    channels = {
        message.channel
        for track in midi.tracks for message in track
        if message.type == "program_change"
    }
    assert channels == set(range(9)) | {10, 11, 12}
    percussion = [
        msg for tr in midi.tracks for msg in tr
        if msg.type == "note_on" and msg.channel == 9
    ]
    assert len(percussion) == 1
    assert percussion[0].note == 36
    path = tmp_path / "drums.mid"
    midi.save(str(path))
    actual = midi_notes(path)
    assert len(actual) == len(notes)
    assert len([n for n in actual if n.is_drum]) == 1


@pytest.mark.parametrize(("change", "error"), [
    (lambda items: items + [_note(program=128)], "Invalid"),
    (lambda items: items + [_note(program=-1)], "Invalid"),
    (lambda items: items + [_note(onset=-1)], "Invalid"),
    (lambda items: items + [_note(onset=0.8, offset=0.5)], "Invalid"),
    (lambda items: items + [_note(onset=float("nan"))], "Invalid"),
    (lambda items: items + [_note(velocity=128)], "Invalid"),
    (
        lambda items: [_note(program=i) for i in range(16)],
        "more pitched programs than MIDI channels",
    ),
])
def test_bad_model_notes_and_channel_overflow_fail_closed(change, error):
    with pytest.raises(ValueError, match=error):
        bridge.midi_from_program_notes(change([_note()]))


def test_same_tick_note_off_ordered_before_retrigger_and_empty_note_sequence():
    midi = bridge.midi_from_program_notes([
        _note(60, 40, 0.0, 0.25),
        _note(60, 40, 0.25, 0.5),
    ])
    note_types = [
        message.type for track in midi.tracks for message in track
        if message.type in {"note_on", "note_off"}
    ]
    assert note_types == ["note_on", "note_off", "note_on", "note_off"]
    assert bridge.midi_from_program_notes([]).tracks


def test_adapter_patch_reuses_upstream_program_events_without_model_retraining(monkeypatch):
    fake_package = types.ModuleType("mt3_infer")
    fake_package.__path__ = []
    adapters = types.ModuleType("mt3_infer.adapters")
    adapters.__path__ = []
    mr = types.ModuleType("mt3_infer.adapters.mr_mt3")
    vocab = types.ModuleType("mt3_infer.adapters.vocab_utils")
    called = []

    class Adapter:
        codec = object()

        def decode(self, outputs):
            raise AssertionError("Upstream lossy serializer should not be called")

    mr.MRMT3Adapter = Adapter

    def decode_original_tokens(predictions, codec):
        called.append((predictions, codec))
        return SimpleNamespace(
            notes=[_note(60, 40), _note(67, 42)],
            ticks_per_quarter=220,
        ), 0, 0

    vocab.decode_and_combine_predictions = decode_original_tokens
    adapters.vocab_utils = vocab
    for name, module in (
        ("mt3_infer", fake_package),
        ("mt3_infer.adapters", adapters),
        ("mt3_infer.adapters.mr_mt3", mr),
        ("mt3_infer.adapters.vocab_utils", vocab),
    ):
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(bridge, "version", lambda name: "0.2.0")
    bridge.install_mr_mt3_program_preservation()
    bridge.install_mr_mt3_program_preservation()  # idempotent
    adapter = Adapter()
    output = adapter.decode({
        "tokens": np.array([[10, 11, -1, -1]]),
        "frame_times": np.array([[0.0, 0.01, 0.02, 0.03]]),
    })
    assert called[0][0][0]["est_tokens"].tolist() == [10, 11]
    assert called[0][1] is adapter.codec
    assert len(output.tracks) == 2
    assert sorted(message.program for tr in output.tracks for message in tr
                  if message.type == "program_change") == [40, 42]


def test_upstream_version_drift_is_not_silently_patched(monkeypatch):
    monkeypatch.setattr(bridge, "version", lambda _name: "0.3.0")
    with pytest.raises(RuntimeError, match="requires mt3-infer 0.2.0"):
        bridge.install_mr_mt3_program_preservation()


def test_cli_preserves_explicit_mr_mt3_but_does_not_patch_other_models(monkeypatch):
    fake_upstream_cli = types.ModuleType("mt3_infer.cli")
    fake_upstream_cli.main = lambda: 0
    monkeypatch.setitem(sys.modules, "mt3_infer.cli", fake_upstream_cli)
    called = []
    monkeypatch.setattr(
        bridge, "install_mr_mt3_program_preservation",
        lambda: called.append("patch"),
    )
    monkeypatch.setattr(sys, "argv", ["audio-score-mt3", "transcribe", "a.wav", "-m", "mr_mt3"])
    assert bridge.main() == 0
    assert called == ["patch"]
    monkeypatch.setattr(sys, "argv", ["audio-score-mt3", "transcribe", "a.wav", "-m", "yourmt3"])
    assert bridge.main() == 0
    monkeypatch.setattr(sys, "argv", ["audio-score-mt3", "--version"])
    assert bridge.main() == 0
    assert called == ["patch"]


def test_packaged_entrypoint_and_local_settings_use_same_program_preserving_bridge(
    monkeypatch,
):
    from audio_score_tool import config

    commands = {"mt3-infer": "/bin/mt3-infer", "audio-score-mt3": "/bin/audio-score-mt3"}
    monkeypatch.setattr(config, "_find_executable", lambda name: commands.get(name))
    assert config._default_mt3_infer_command() == "/bin/audio-score-mt3"
    del commands["audio-score-mt3"]
    assert config._default_mt3_infer_command() == "/bin/mt3-infer"
    del commands["mt3-infer"]
    # No local wrapper selected when upstream is absent.
    assert config._default_mt3_infer_command() != "/bin/audio-score-mt3"
    frozen = (Path(__file__).resolve().parents[1] / "scripts/mt3_frozen_entry.py"
              ).read_text(encoding="utf-8")
    assert "from audio_score_tool.mt3_program_midi import main" in frozen

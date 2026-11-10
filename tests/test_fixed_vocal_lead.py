"""Fixed recipe orchestration; model processes use owned synthetic fixtures."""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from dataclasses import replace
from pathlib import Path

import mido
import pytest

from audio_score_tool import fixed_vocal_lead as lead
from audio_score_tool.config import Settings
from audio_score_tool.fixed_lead_recipe import (
    DEMUCS_WEIGHT,
    ENGINE,
    YOUR_CHECKPOINT,
    YOUR_SHA256,
    verify_weight,
)
from audio_score_tool.job_transcription_settings import (
    restore_transcription_job_settings,
    transcription_job_selection,
)
from audio_score_tool.metrics import midi_notes
from audio_score_tool.score_requests import needs_stem_separation, validate_engine_score_mode
from audio_score_tool.transcription_engine import FixedVocalLeadEngine, SheetSage2Engine

ABC = 'X:1\nM:3/4\nL:1/4\nV:Vocal clef=treble\nK:C\nV: Vocal\n"C"C D E |]\n'
MAPPING = {"duration": 1.5, "measures": [
    dict(start=0,end=1.5,score_start=0,score_end=.75)]}


def snapshot(tmp_path):
    root = tmp_path / "snapshot"
    for name in ["sheetsage2/model/model.safetensors", "sheetsage2/mert/model.safetensors",
                 Path("checkpoints") / YOUR_CHECKPOINT, Path("demucs") / DEMUCS_WEIGHT]:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"owned fixture, not model weights")
    (root / "demucs/htdemucs.yaml").write_text("models: ['955717e8']\n")
    return root


def test_one_recipe_preserves_provider_outputs_and_uses_selected_vocal(tmp_path, monkeypatch):
    from audio_score_tool.sheetsage2_score import CHECKPOINT_SHA256, MODEL_REVISION

    root = snapshot(tmp_path)
    audio = tmp_path / "source.wav"
    audio.write_bytes(b"owned source waveform")
    settings = Settings(transcription_engine=ENGINE, fixed_lead_snapshot=root,
                        fixed_vocal_cmd="vocal-fixture", demucs_cmd="separator-fixture",
                        sheetsage2_cmd="structure-fixture")
    observed = []
    monkeypatch.setattr(lead, "verify_weight", lambda path, expected: observed.append((path.name, expected)))
    monkeypatch.setattr(lead, "verify_separator", lambda repo: observed.append((repo.name, "pinned separator")))

    def structure(self, source, output, **kwargs):
        assert source == audio
        native = output / "native"
        native.mkdir(parents=True)
        (native / "score.abc").write_text(ABC.replace("C D E", "z3"))
        (native / "playback.json").write_text(json.dumps(MAPPING))
        (native / "notation").mkdir()
        (native / "notation/song_beats.txt").write_text("0 1 3 4\n.5 2 3 4\n1 3 3 4\n1.5 1 3 4\n")
        (output / "analysis.json").write_text(json.dumps({
            "model_revision": MODEL_REVISION, "checkpoint_sha256": CHECKPOINT_SHA256,
            "meter": "3/4", "chords": [{"time_seconds": 0, "label": "C:maj"}]}))
        observed.append("whole-mix structure")

    monkeypatch.setattr(SheetSage2Engine, "analyze", structure)
    monkeypatch.setattr(SheetSage2Engine, "transcribe", lambda *a, **k: pytest.fail("S2 vocal is not the melody provider"))
    monkeypatch.setattr(lead, "prepare_demucs_audio", lambda source, target, **kw: shutil.copy2(source, target) and target)

    def command(command, args, **kwargs):
        if command == "vocal-fixture" and args[0] == "separate":
            assert args[3:] == ["--snapshot", root]
            stems = args[2] / "htdemucs/source"
            stems.mkdir(parents=True)
            (stems / "vocals.wav").write_bytes(b"owned vocal waveform" * 5)
            (args[2] / "runtime.json").write_text('{"model":"htdemucs"}')
            observed.append("separate")
        elif command == "vocal-fixture":
            assert args[0] == "vocal" and args[1].name == "vocals.wav" and args[3:] == ["--snapshot", root]
            midi = mido.MidiFile(ticks_per_beat=480)
            track = mido.MidiTrack()
            midi.tracks.append(track)
            for pitch in [60, 62, 64]:
                track.append(mido.Message("note_on", note=pitch, velocity=80, time=0))
                track.append(mido.Message("note_off", note=pitch, time=480))
            midi.save(args[2])
            args[2].with_suffix(".runtime.json").write_text(json.dumps({"checkpoint_sha256": YOUR_SHA256}))
            observed.append("vocal inference")
        else:
            assert command == "structure-fixture"
            assert args[args.index("--vocal-midi")+1].name == "selected.mid"
            native = args[1].parent / "native"
            native.mkdir()
            (native / "score.abc").write_text(ABC)
            (native / "playback.json").write_text(json.dumps(MAPPING))
            shutil.copytree(args[args.index("--context-dir")+1] / "notation", native / "notation")
            args[1].write_text(json.dumps({"unrepresented_note_indices": [],
                "grid_audio_seconds": [0,.5,1,1.5], "source_note_indices": [0,1,2]}))
            observed.append("vocal notation")

    monkeypatch.setattr(lead, "run_command", command)
    output = tmp_path / "result"
    result = lead.transcribe_fixed_vocal_lead(audio, output, settings=settings)
    assert [x for x in observed if isinstance(x, str)] == [
        "whole-mix structure", "separate", "vocal inference", "vocal notation"]
    assert [(n.pitch, n.onset, n.offset) for n in midi_notes(result.midi_path)] == [
        (60,0,.5),(62,.5,1),(64,1,1.5)]
    assert (output / "structure/native/score.abc").read_text() == ABC.replace("C D E", "z3")
    assert len(midi_notes(output / "vocal/score.mid")) == 3
    receipt = json.loads((output / "recipe.json").read_text())
    assert receipt["status"] == "completed" and receipt["quality_approved"] is False
    assert receipt["notation_fidelity"]["matched_interpretation"] is True
    assert receipt["source_audio_sha256"] == hashlib.sha256(audio.read_bytes()).hexdigest()
    report = json.loads((output / "notation-report.json").read_text())
    assert report["melody_provider"] == "yourmt3" and "model_revision" not in report
    analysis = json.loads((output / "analysis.json").read_text())
    assert analysis["provider"] == ENGINE and analysis["structure_model_revision"] == MODEL_REVISION


def test_changed_checkpoint_is_rejected_before_any_model_runs(tmp_path, monkeypatch):
    root = snapshot(tmp_path)
    settings = Settings(fixed_lead_snapshot=root)
    monkeypatch.setattr(SheetSage2Engine, "analyze", lambda *a, **k: pytest.fail("must not infer"))
    with pytest.raises(ValueError, match="SHA mismatch"):
        lead.transcribe_fixed_vocal_lead(tmp_path / "input.wav", tmp_path / "output", settings=settings)
    assert not (tmp_path / "output").exists()
    path = root / "checkpoints" / YOUR_CHECKPOINT
    assert verify_weight(path, hashlib.sha256(path.read_bytes()).hexdigest())


def test_saved_fixed_selection_cannot_drift_to_global_mt3_model(tmp_path, monkeypatch):
    monkeypatch.setenv("AST_PACKAGED", "0")
    settings = Settings(transcription_engine=ENGINE, mt3_model="mr_mt3")
    job = transcription_job_selection(settings)
    assert job["mt3_model"] is None
    restored = restore_transcription_job_settings(replace(settings, transcription_engine="muscriptor"), job)
    assert restored.transcription_engine == ENGINE
    assert validate_engine_score_mode("lead_sheet", ENGINE) == "lead_sheet"
    assert not needs_stem_separation("lead_sheet", engine=ENGINE)
    with pytest.raises(ValueError, match="lead_sheet only"):
        validate_engine_score_mode("full", ENGINE)
    with pytest.raises(ValueError, match="commercial"):
        transcription_job_selection(replace(settings, usage_mode="commercial"))
    monkeypatch.setenv("AST_PACKAGED", "1")
    with pytest.raises(ValueError, match="packaged"):
        transcription_job_selection(settings)


def test_fixed_readiness_requires_all_components_and_is_never_packaged(tmp_path, monkeypatch):
    monkeypatch.setenv("AST_PACKAGED", "0")
    settings = Settings(fixed_lead_snapshot=snapshot(tmp_path), fixed_vocal_cmd=sys.executable,
                        sheetsage2_cmd=sys.executable, demucs_cmd=sys.executable, ffmpeg_cmd=sys.executable)
    assert FixedVocalLeadEngine(settings).ready()
    assert not FixedVocalLeadEngine(replace(settings, fixed_vocal_cmd="missing-fixed-vocal-runtime")).ready()
    monkeypatch.setenv("AST_PACKAGED", "1")
    assert not FixedVocalLeadEngine(settings).ready()

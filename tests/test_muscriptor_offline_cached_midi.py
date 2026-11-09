"""Offline product wiring: HF-authenticated cache -> MuScriptor MIDI -> embedded MusicXML.

Only synthetic cache contents / MIDI fixtures are used. These tests do not
download gated weights, run a neural model, or approve redistribution.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import mido
import pytest
from music21 import converter, note

from audio_score_tool import model_manager_api, preflight_v2, transcription_engine
from audio_score_tool.config import Settings
from audio_score_tool.muscriptor_cache import cached_muscriptor_checkpoint

_REV = "a" * 40
_CONFIGS = {
    "small": (768, 12, 14, 1393),
    "medium": (1024, 16, 24, 1395),
    "large": (1536, 24, 48, 1395),
}


def _cache(tmp_path: Path, monkeypatch, variant: str = "small") -> tuple[Path, Path]:
    monkeypatch.delenv("AST_PACKAGED", raising=False)
    home = tmp_path / "hf-home"
    monkeypatch.setenv("HF_HOME", str(home))
    repo = home / "hub" / f"models--MuScriptor--muscriptor-{variant}"
    snapshot = repo / "snapshots" / _REV
    snapshot.mkdir(parents=True)
    (repo / "refs").mkdir(parents=True)
    (repo / "refs" / "main").write_text(_REV, encoding="ascii")
    weight = snapshot / "model.safetensors"
    with weight.open("wb") as stream:
        stream.truncate(1024 * 1024 + 1)  # sparse fake, never parsed as model
    dim, heads, layers, card = _CONFIGS[variant]
    (snapshot / "config.json").write_text(json.dumps({
        "model_type": "muscriptor", "variant": variant,
        "dim": dim, "num_heads": heads, "num_layers": layers, "card": card,
    }), encoding="utf-8")
    return snapshot, weight


def _midi_with_notes(path: Path) -> None:
    output = mido.MidiFile(type=1)
    for channel, program, pitch in ((0, 0, 60), (1, 32, 36)):
        track = mido.MidiTrack()
        output.tracks.append(track)
        track.append(mido.Message("program_change", channel=channel, program=program, time=0))
        track.append(mido.Message("note_on", channel=channel, note=pitch, velocity=90, time=0))
        track.append(mido.Message("note_off", channel=channel, note=pitch, velocity=0, time=480))
    output.save(path)


@pytest.mark.parametrize("variant", ["small", "medium", "large"])
def test_complete_hf_snapshot_resolves_exact_user_cached_variant(tmp_path, monkeypatch, variant):
    _snapshot, weight = _cache(tmp_path, monkeypatch, variant)
    assert cached_muscriptor_checkpoint(variant) == weight
    assert cached_muscriptor_checkpoint("not-a-model") is None
    ready, size = model_manager_api._model_cached(f"MuScriptor/muscriptor-{variant}")
    assert ready is True and size > 1024 * 1024


def test_incomplete_or_mismatched_config_never_claims_model_ready(tmp_path, monkeypatch):
    snapshot, _ = _cache(tmp_path, monkeypatch)
    config = snapshot / "config.json"
    config.unlink()
    assert cached_muscriptor_checkpoint("small") is None
    config.write_text('{"dim":1536,"num_heads":24,"num_layers":48,"card":1395}')
    assert cached_muscriptor_checkpoint("small") is None
    ready, _ = model_manager_api._model_cached("MuScriptor/muscriptor-small")
    assert ready is False


def test_stale_or_ambiguous_revision_and_external_weight_symlink_are_rejected(
    tmp_path, monkeypatch,
):
    snapshot, weight = _cache(tmp_path, monkeypatch)
    repo = snapshot.parent.parent
    (repo / "refs" / "main").write_text("b" * 40)
    assert cached_muscriptor_checkpoint("small") is None
    (repo / "refs" / "main").unlink()
    assert cached_muscriptor_checkpoint("small") == weight
    (repo / "snapshots" / ("c" * 40)).mkdir()
    assert cached_muscriptor_checkpoint("small") is None
    (repo / "snapshots" / ("c" * 40)).rmdir()
    external = tmp_path / "external.safetensors"
    external.write_bytes(b"untrusted" * 400000)
    weight.unlink()
    weight.symlink_to(external)
    assert cached_muscriptor_checkpoint("small") is None


def test_snapshot_symlink_to_own_hf_blob_is_supported(tmp_path, monkeypatch):
    snapshot, weight = _cache(tmp_path, monkeypatch)
    repo = snapshot.parent.parent
    blobs = repo / "blobs"
    blobs.mkdir()
    own_blob = blobs / ("b" * 64)
    weight.replace(own_blob)
    weight.symlink_to(own_blob)
    # Return the snapshot path, NOT the resolved blob path. MuScriptor loads
    # the adjacent config.json from weight.parent.
    assert cached_muscriptor_checkpoint("small") == weight


def test_real_midi_output_is_converted_without_musescore_or_network(tmp_path, monkeypatch):
    _snapshot, weight = _cache(tmp_path, monkeypatch)
    monkeypatch.setattr(transcription_engine, "command_exists", lambda _: True)
    monkeypatch.setattr(
        transcription_engine, "backend_status", lambda _: {"music21": True},
    )
    calls = []

    def fake_run(command, args, **kwargs):
        values = [str(item) for item in args]
        calls.append((command, values, kwargs))
        assert values[values.index("--format") + 1] == "midi"
        assert values[values.index("--model") + 1] == str(weight)
        assert "sheets" not in values and "musescore" not in values
        assert kwargs["env"]["HF_HUB_OFFLINE"] == "1"
        assert kwargs["env"]["HF_HOME"] == str(tmp_path / "hf-home")
        assert "HF_TOKEN" not in kwargs["env"]
        _midi_with_notes(Path(values[values.index("--output") + 1]))

    monkeypatch.setattr(transcription_engine, "run_command", fake_run)
    engine = transcription_engine.MuScriptorEngine(Settings(
        usage_mode="personal", muscriptor_cmd=sys.executable, muscriptor_model="small",
    ))
    assert engine.ready() is True
    source = tmp_path / "input.wav"
    source.write_bytes(b"synthetic input")
    artifacts = engine.transcribe(source, tmp_path / "output", device="cpu")
    assert len(calls) == 1
    assert artifacts.midi_path.is_file()
    assert artifacts.musicxml_path.is_file()
    assert artifacts.initial_pdf_path is None
    score = converter.parse(str(artifacts.musicxml_path))
    performed = [event for event in score.recurse().notes if isinstance(event, note.Note)]
    assert len(performed) >= 2


def test_missing_cache_blocks_inference_before_spawning_subprocess(tmp_path, monkeypatch):
    monkeypatch.delenv("AST_PACKAGED", raising=False)
    monkeypatch.setenv("HF_HOME", str(tmp_path / "empty-cache"))
    monkeypatch.setattr(transcription_engine, "command_exists", lambda _: True)
    monkeypatch.setattr(
        transcription_engine, "backend_status", lambda _: {"music21": True},
    )
    monkeypatch.setattr(transcription_engine, "run_command", lambda *_a, **_k: pytest.fail(
        "must never download model implicitly"
    ))
    engine = transcription_engine.MuScriptorEngine(Settings(
        usage_mode="personal", muscriptor_cmd=sys.executable, muscriptor_model="small",
    ))
    assert engine.ready() is False
    with pytest.raises(transcription_engine.TranscriptionEngineUnavailable, match="checkpoint/config"):
        engine.transcribe(tmp_path / "audio.wav", tmp_path / "output", device="cpu")


@pytest.mark.parametrize("kind", ["empty", "malformed", "absent"])
def test_invalid_or_empty_model_midi_never_claims_success(tmp_path, monkeypatch, kind):
    _cache(tmp_path, monkeypatch)
    monkeypatch.setattr(transcription_engine, "command_exists", lambda _: True)
    monkeypatch.setattr(
        transcription_engine, "backend_status", lambda _: {"music21": True},
    )

    def fake_run(_cmd, args, **_kwargs):
        output = Path(args[args.index("--output") + 1])
        if kind == "empty":
            midi = mido.MidiFile()
            midi.tracks.append(mido.MidiTrack())
            midi.save(output)
        elif kind == "malformed":
            output.write_bytes(b"not a MIDI file")
        # absent: CLI returned success but never wrote the promised file

    monkeypatch.setattr(transcription_engine, "run_command", fake_run)
    engine = transcription_engine.MuScriptorEngine(Settings(
        usage_mode="personal", muscriptor_cmd=sys.executable, muscriptor_model="small",
    ))
    with pytest.raises(transcription_engine.TranscriptionEngineError):
        engine.transcribe(tmp_path / "audio.wav", tmp_path / "out", device="cpu")
    assert not (tmp_path / "out" / "score.musicxml").exists()


def test_muscriptor_cached_model_does_not_require_auth_session_for_offline_inference(
    tmp_path, monkeypatch,
):
    _cache(tmp_path, monkeypatch)
    monkeypatch.setattr(preflight_v2, "huggingface_authenticated", lambda: False)
    monkeypatch.setattr(preflight_v2, "command_exists", lambda _: True)
    monkeypatch.setattr(preflight_v2, "audiveris_status", lambda _: {"ready": False})
    monkeypatch.setattr(
        preflight_v2, "backend_status",
        lambda _: {"music21": True, "verovio": True, "fpdf2": True},
    )
    monkeypatch.setattr(
        transcription_engine, "backend_status", lambda _: {"music21": True},
    )
    monkeypatch.setattr(transcription_engine, "command_exists", lambda _: True)
    setting = Settings(
        usage_mode="personal", transcription_engine="muscriptor",
        muscriptor_cmd=sys.executable, muscriptor_model="small",
    )
    report = preflight_v2.preflight(setting)
    assert report["ok"] is True
    assert report["tools"]["transcription_engine"] is True
    assert "huggingface_auth" not in report["missing"]


def test_commercial_muscriptor_never_uses_private_cached_weights(tmp_path, monkeypatch):
    _cache(tmp_path, monkeypatch)
    monkeypatch.setattr(transcription_engine, "command_exists", lambda _: True)
    engine = transcription_engine.MuScriptorEngine(Settings(
        usage_mode="commercial", muscriptor_cmd=sys.executable, muscriptor_model="small",
    ))
    assert engine.ready() is False
    with pytest.raises(transcription_engine.TranscriptionEngineUnavailable, match="commercial"):
        engine.transcribe(tmp_path / "audio.wav", tmp_path / "out", device="cpu")


def test_opt_in_real_model_workflow_exercises_product_engine_without_musescore():
    workflow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/tier2-actual-models.yml"
    ).read_text(encoding="utf-8")
    job = workflow.split("\n  muscriptor:\n", 1)[1]
    assert "MuScriptorEngine" in job
    assert "cached_muscriptor_checkpoint" in job
    assert "HF_TOKEN: ''" in job
    assert "--format sheets" not in job
    assert "muscriptor transcribe" not in job
    assert "verification.pending.json" in job
    assert "path: out/muscriptor/verification.pending.json" in job
    assert "path: out/muscriptor/" not in job.replace(
        "path: out/muscriptor/verification.pending.json", ""
    )

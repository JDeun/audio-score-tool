"""Execute one frozen vocal/structure recipe, preserving each provider's output."""
from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from dataclasses import replace

from .demucs_runtime import prepare_demucs_audio
from .fixed_lead_recipe import (
    DEMUCS_SHA256,
    ENGINE,
    YOUR_CHECKPOINT,
    YOUR_REVISION,
    YOUR_SHA256,
    verify_separator,
    verify_weight,
)
from .lead_notation import verify_notated_midi
from .notation_backend import midi_to_musicxml, musicxml_to_midi
from .runner import run_command
from .selected_stem_score import _main_part, _stem
from .sheetsage2_score import CHECKPOINT_SHA256, MODEL_REVISION, import_native_lead_sheet
from .vocal_evidence import fixed_tiny_pitch_track


def transcribe_fixed_vocal_lead(audio_path, output_dir, *, settings, cancel_event=None):
    from .transcription_engine import SheetSage2Engine, TranscriptionArtifacts

    root = settings.fixed_lead_snapshot
    checkpoint = root / "checkpoints" / YOUR_CHECKPOINT
    verify_weight(checkpoint, YOUR_SHA256)
    verify_separator(root / "demucs")
    with audio_path.open("rb") as handle:
        source_sha = hashlib.file_digest(handle, "sha256").hexdigest()
    output_dir.mkdir(parents=True, exist_ok=True)
    recipe = {"recipe_version": 2, "engine": ENGINE, "source_audio_sha256": source_sha,
              "melody": {"model": "yourmt3", "model_revision": YOUR_REVISION,
                         "checkpoint_sha256": YOUR_SHA256},
              "structure": {"model": "sheetsage2", "model_revision": MODEL_REVISION,
                            "checkpoint_sha256": CHECKPOINT_SHA256},
              "separation": {"model": "htdemucs", "checkpoint_sha256": DEMUCS_SHA256,
                             "shifts": 0, "device": "cpu", "encoding": "float32",
                             "clip_mode": "rescale"},
              "quality_approved": False, "status": "running"}
    receipt = output_dir / "recipe.json"
    receipt.write_text(json.dumps(recipe, indent=2) + "\n")
    run_command(settings.fixed_vocal_cmd, ["pitch-preflight", audio_path, output_dir / "pitch-preflight.npz",
                "--snapshot", root], cancel_event=cancel_event, timeout_seconds=120)
    normalized = prepare_demucs_audio(audio_path, output_dir / "demucs-input.wav",
                                      settings=settings, cancel_event=cancel_event)
    model_audio = audio_path if audio_path.suffix.lower() == ".wav" else normalized
    with model_audio.open("rb") as handle:
        recipe["model_audio_sha256"] = hashlib.file_digest(handle, "sha256").hexdigest()
    recipe["model_audio_normalized"] = model_audio != audio_path
    structure_dir = output_dir / "structure"
    # Whole-mix structure is a separate, immutable observation from vocal inference.
    SheetSage2Engine(replace(settings, sheetsage2_snapshot=root / "sheetsage2")).analyze(
        model_audio, structure_dir, cancel_event=cancel_event)
    stems = output_dir / "stems"
    run_command(settings.fixed_vocal_cmd, ["separate", normalized, stems, "--snapshot", root],
                cancel_event=cancel_event, timeout_seconds=1800)
    recipe["separation"]["runtime"] = json.loads((stems / "runtime.json").read_text())
    vocal_audio = _stem(stems, "vocals")
    raw = output_dir / "vocal"
    raw.mkdir()
    pitch_track, pitch_receipt = fixed_tiny_pitch_track(vocal_audio, raw / "pitch.npz", settings=settings,
                                                       cancel_event=cancel_event)
    recipe["pitch_verifier"] = pitch_receipt
    raw_midi = raw / "score.mid"
    run_command(settings.fixed_vocal_cmd, ["vocal", vocal_audio, raw_midi,
                "--snapshot", root], cancel_event=cancel_event,
                timeout_seconds=1800, env={"PYTHONHASHSEED": "0", "OMP_NUM_THREADS": "2",
                                           "MKL_NUM_THREADS": "2"})
    midi_to_musicxml(raw_midi, raw / "score.musicxml")
    selected_xml = raw / "selected.musicxml"
    selected = _main_part(raw / "score.musicxml", selected_xml, part_name="Voice",
                          vocal_audio=vocal_audio, ffmpeg_cmd=settings.ffmpeg_cmd, pitch_track=pitch_track)
    selected_xml.write_bytes(ET.tostring(selected, encoding="utf-8", xml_declaration=True))
    selected_midi = musicxml_to_midi(selected_xml, raw / "selected.mid")
    run_command(settings.sheetsage2_cmd, [model_audio, output_dir / "interpretation.json",
                "--model-dir", root / "sheetsage2/model", "--vocal-midi", selected_midi,
                "--context-dir", structure_dir / "native"], cancel_event=cancel_event,
                timeout_seconds=1800, env={"AST_USAGE_MODE": "personal", "AST_FIXED_LEAD_V1": "1"})
    xml = output_dir / "score.musicxml"
    report = import_native_lead_sheet(output_dir / "native", xml)
    report["clock_model_revision"] = report.pop("model_revision")
    report["clock_checkpoint_sha256"] = report.pop("checkpoint_sha256")
    report.update(melody_provider="yourmt3", melody_checkpoint_sha256=YOUR_SHA256)
    (output_dir / "notation-report.json").write_text(json.dumps(report, indent=2) + "\n")
    midi = musicxml_to_midi(xml, output_dir / "score.mid")
    interpretation = json.loads((output_dir / "interpretation.json").read_text())
    recipe["notation_fidelity"] = verify_notated_midi(selected_midi, midi, interpretation)
    analysis = json.loads((structure_dir / "analysis.json").read_text())
    analysis["structure_model_revision"] = analysis.pop("model_revision")
    analysis["structure_checkpoint_sha256"] = analysis.pop("checkpoint_sha256")
    analysis.update(provider=ENGINE, model="yourmt3+sheetsage2", melody_checkpoint_sha256=YOUR_SHA256)
    (output_dir / "analysis.json").write_text(json.dumps(analysis, indent=2) + "\n")
    verify_weight(checkpoint, YOUR_SHA256)
    verify_separator(root / "demucs")
    with audio_path.open("rb") as handle:
        if hashlib.file_digest(handle, "sha256").hexdigest() != source_sha:
            raise ValueError("Fixed recipe source audio changed during processing")
    recipe["melody"]["runtime"] = json.loads(raw_midi.with_suffix(".runtime.json").read_text())
    recipe["status"] = "completed"
    receipt.write_text(json.dumps(recipe, indent=2) + "\n")
    normalized.unlink()
    return TranscriptionArtifacts(midi_path=midi, musicxml_path=xml)

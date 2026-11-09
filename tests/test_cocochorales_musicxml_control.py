"""Synthetic-only control tests: reference MIDI→MusicXML→MIDI without a model."""
from __future__ import annotations

import json
from pathlib import Path

import mido
import pytest

from scripts import score_cocochorales_musicxml_control as control


def _source_midi(path: Path) -> Path:
    mid = mido.MidiFile(ticks_per_beat=480)
    for channel, program, pitch in ((0, 40, 60), (1, 41, 64)):
        part = mido.MidiTrack()
        part.extend([
            mido.Message("program_change", channel=channel, program=program, time=0),
            mido.Message("note_on", channel=channel, note=pitch, velocity=70, time=0),
            mido.Message("note_off", channel=channel, note=pitch, velocity=0, time=480),
        ])
        mid.tracks.append(part)
    mid.save(str(path))
    return path


def test_reference_only_roundtrip_has_real_playable_notes_without_checkpoint(tmp_path):
    reference = _source_midi(tmp_path / "reference.mid")
    result = control.reference_roundtrip(
        reference, scratch_root=tmp_path, original_parts=4,
    )
    assert result["conversion_method"] == "ast_tick_preserving_musicxml_voice_aware_midi_v1"
    assert result["source_note_count"] == 2
    assert result["roundtrip_note_count"] >= 1
    for key in control._SCORE_KEYS:
        assert 0 <= result["f1"][key] <= 1
    assert result["reference_musicxml_part_count"] == 4
    assert list(tmp_path.glob(".reference-score-control-*")) == []


def test_reference_only_roundtrip_rejects_missing_and_empty_midi(tmp_path):
    with pytest.raises(ValueError, match="bounded regular"):
        control.reference_roundtrip(
            tmp_path / "missing.mid", scratch_root=tmp_path, original_parts=4,
        )
    empty = tmp_path / "empty.mid"
    empty.write_bytes(b"")
    with pytest.raises(ValueError, match="bounded regular"):
        control.reference_roundtrip(empty, scratch_root=tmp_path, original_parts=4)


def _receipt(track: str, *, f1: float = 0.8) -> dict:
    return {
        "schema_version": 1,
        "purpose": "reference-only-musicxml-conversion-control",
        "dataset_split": "train",
        "track_id": track,
        "source_revision": control.SOURCE_COMMIT,
        "source_proof_sha256": "a" * 64,
        "source_audio_sha256": "b" * 64,
        "reference_midi_sha256": "c" * 64,
        "music21_roundtrip": {
            "f1": {
                "onset_f1": f1,
                "onset_offset_f1": f1,
                "instrument_onset_offset_f1": f1,
            },
        },
        "model_inference_performed": False,
        "source_media_published": False,
        "release_quality_approved": False,
    }


def test_full_four_track_control_aggregates_without_model_claims():
    cases = [_receipt(track) for track in control.TRACKS]
    result = control.aggregate_controls(cases)
    assert result["case_count"] == 4
    assert result["macro_music21_reference_roundtrip"] == {
        "onset_f1": 0.8,
        "onset_offset_f1": 0.8,
        "instrument_onset_offset_f1": 0.8,
    }
    assert result["model_inference_performed"] is False
    assert result["release_quality_approved"] is False
    assert "musicxml" not in json.dumps(result["reference_sha256"])


def test_missing_mismatched_and_fake_control_metrics_are_rejected():
    cases = [_receipt(track) for track in control.TRACKS]
    with pytest.raises(ValueError, match="Missing or reordered"):
        control.aggregate_controls(cases[:-1])
    altered = [dict(case) for case in cases]
    altered[0]["track_id"] = control.TRACKS[1]
    with pytest.raises(ValueError, match="Missing or reordered"):
        control.aggregate_controls(altered)
    altered = [_receipt(track) for track in control.TRACKS]
    altered[0]["music21_roundtrip"]["f1"]["onset_f1"] = float("nan")
    with pytest.raises(ValueError, match="invalid"):
        control.aggregate_controls(altered)
    altered = [_receipt(track) for track in control.TRACKS]
    altered[1]["release_quality_approved"] = True
    with pytest.raises(ValueError, match="unapproved"):
        control.aggregate_controls(altered)

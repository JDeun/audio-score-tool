"""Owned tiny WAV/MIDI fixtures for domain-dataset pair integrity; no model runs."""
from __future__ import annotations

import copy
import hashlib
import json
import wave
from pathlib import Path

import mido
import pytest

from audio_score_tool.tier2_benchmark import load_manifest
from scripts.validate_tier2_dataset_pairs import validate_pairs


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> tuple[dict, dict, Path]:
    corpus = tmp_path / "private"
    (corpus / "audio").mkdir(parents=True)
    (corpus / "reference").mkdir()
    audio = corpus / "audio" / "piano.wav"
    with wave.open(str(audio), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(8000)
        stream.writeframes(b"\0\0" * 8000)
    midi = mido.MidiFile()
    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.append(mido.Message("note_on", note=60, velocity=70, time=0))
    track.append(mido.Message("note_off", note=60, velocity=0, time=480))
    reference = corpus / "reference" / "piano.mid"
    midi.save(str(reference))
    registry = {"schema_version": 1, "datasets": [{
        "id": "owned-piano", "task": "piano_amt",
        "source": "https://example.org/owned", "license": "CC-BY-4.0",
        "audio_included": True, "status": "verified_for_evaluation",
    }]}
    plan = {"schema_version": 1, "cases": [{
        "id": "piano-1", "dataset_id": "owned-piano",
        "recording_id": "owned-recording-001",
        "split": "test", "rights_reviewed": True, "license": "CC-BY-4.0",
        "audio": {"locator": "private://audio/piano.wav", "sha256": _sha(audio)},
        "reference_midi": {
            "locator": "private://reference/piano.mid", "sha256": _sha(reference),
        },
    }]}
    return plan, registry, corpus


def test_verified_pair_generates_tier2_manifest_without_model_or_media_copy(tmp_path: Path):
    plan, registry, corpus = _fixture(tmp_path)
    report, tier2 = validate_pairs(plan, registry, corpus_root=corpus)
    assert report["case_count"] == 1
    assert report["cases"][0]["reference_note_on_count"] == 1
    assert report["cases"][0]["audio_duration_seconds"] == pytest.approx(1.0)
    assert report["source_audio_published"] is False
    assert report["model_inference_performed"] is False
    assert report["upstream_rights_independently_verified"] is False
    assert tier2["cases"][0]["audio"]["redistributable"] is False
    test_manifest = tmp_path / "tier2-manifest.json"
    test_manifest.write_text(json.dumps(tier2), encoding="utf-8")
    version, cases = load_manifest(test_manifest)
    assert version.startswith("paired-")
    assert cases[0].reference_midi == "private://reference/piano.mid"


def test_missing_rights_review_rejected(tmp_path: Path):
    plan, registry, corpus = _fixture(tmp_path)
    plan["cases"][0]["rights_reviewed"] = False
    with pytest.raises(ValueError, match="rights review"):
        validate_pairs(plan, registry, corpus_root=corpus)


def test_registry_status_cannot_claim_unverified_dataset_ready(tmp_path: Path):
    plan, registry, corpus = _fixture(tmp_path)
    registry["datasets"][0]["status"] = "planned"
    with pytest.raises(ValueError, match="reviewed evaluation status"):
        validate_pairs(plan, registry, corpus_root=corpus)


def test_repackaged_dataset_license_conflict_fails(tmp_path: Path):
    plan, registry, corpus = _fixture(tmp_path)
    plan["cases"][0]["license"] = "CC-BY-NC-4.0"
    with pytest.raises(ValueError, match="license does not match"):
        validate_pairs(plan, registry, corpus_root=corpus)


def test_noncommercial_cannot_enter_commercial_pipeline(tmp_path: Path):
    plan, registry, corpus = _fixture(tmp_path)
    registry["datasets"][0]["license"] = "CC-BY-NC-4.0"
    plan["cases"][0]["license"] = "CC-BY-NC-4.0"
    with pytest.raises(ValueError, match="commercial"):
        validate_pairs(plan, registry, corpus_root=corpus, commercial=True)
    report, _ = validate_pairs(plan, registry, corpus_root=corpus)
    assert report["commercial_model_approved"] is False


def test_tampered_reference_midi_fails_before_measuring_notes(tmp_path: Path):
    plan, registry, corpus = _fixture(tmp_path)
    (corpus / "reference" / "piano.mid").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        validate_pairs(plan, registry, corpus_root=corpus)


def test_unsafe_private_locator_is_rejected(tmp_path: Path):
    plan, registry, corpus = _fixture(tmp_path)
    plan["cases"][0]["audio"]["locator"] = "private://../outside.wav"
    with pytest.raises(ValueError, match="unsafe"):
        validate_pairs(plan, registry, corpus_root=corpus)


def test_same_audio_cannot_leak_between_test_and_train(tmp_path: Path):
    plan, registry, corpus = _fixture(tmp_path)
    another = json.loads(json.dumps(plan["cases"][0]))
    another["id"] = "piano-2"
    another["recording_id"] = "second-alias"
    another["split"] = "train"
    plan["cases"].append(another)
    with pytest.raises(ValueError, match="cross-split"):
        validate_pairs(plan, registry, corpus_root=corpus)


def test_explicit_unverified_registry_license_blocks_pairing(tmp_path: Path):
    plan, registry, corpus = _fixture(tmp_path)
    registry["datasets"][0]["license"] = "verify_upstream"
    plan["cases"][0]["license"] = "verify_upstream"
    with pytest.raises(ValueError, match="unresolved"):
        validate_pairs(plan, registry, corpus_root=corpus)


def test_invalid_midi_after_matching_pinned_hash_is_still_rejected(tmp_path: Path):
    plan, registry, corpus = _fixture(tmp_path)
    midi = corpus / "reference" / "piano.mid"
    midi.write_bytes(b"not a midi")
    plan["cases"][0]["reference_midi"]["sha256"] = _sha(midi)
    with pytest.raises((ValueError, EOFError), match="reference MIDI"):
        validate_pairs(plan, registry, corpus_root=corpus)


def test_more_than_128_paired_cases_flow_through_existing_tier2_manifest(tmp_path: Path):
    plan, registry, corpus = _fixture(tmp_path)
    original = plan["cases"][0]
    plan["cases"] = []
    for number in range(129):
        case = copy.deepcopy(original)
        case["id"] = f"piano-{number:03d}"
        case["recording_id"] = f"owned-recording-{number:03d}"
        plan["cases"].append(case)
    report, tier2 = validate_pairs(plan, registry, corpus_root=corpus)
    assert report["case_count"] == 129
    assert len(tier2["cases"]) == 129
    manifest = tmp_path / "large-tier2-manifest.json"
    manifest.write_text(json.dumps(tier2), encoding="utf-8")
    _version, loaded = load_manifest(manifest)
    assert len(loaded) == 129
    assert all(case.reference_midi == "private://reference/piano.mid" for case in loaded)

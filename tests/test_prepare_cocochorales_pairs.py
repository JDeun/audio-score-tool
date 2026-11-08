"""Synthetic offline CocoChorales tiny mix/audio reference-pair contracts.

The test fixtures are original silence and tiny MIDI notes, never dataset media.
"""
from __future__ import annotations

import hashlib
import json
import wave
from pathlib import Path

import mido
import pytest

from scripts import prepare_cocochorales_pairs as coco
from scripts.validate_tier2_dataset_pairs import validate_pairs


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _fixture(tmp_path: Path):
    root = tmp_path / "private-dataset"
    track_id = "string_track000001"
    subdir = root / track_id
    subdir.mkdir(parents=True)
    wav = subdir / "mix.wav"
    with wave.open(str(wav), "wb") as wave_file:
        wave_file.setnchannels(1)
        wave_file.setsampwidth(2)
        wave_file.setframerate(16000)
        wave_file.writeframes(b"\x00\x00" * 16000 * 2)
    mid = mido.MidiFile(ticks_per_beat=480)
    voices = mido.MidiTrack()
    mid.tracks.append(voices)
    voices.append(mido.Message("note_on", note=60, velocity=75, time=0))
    voices.append(mido.Message("note_off", note=60, velocity=0, time=480))
    voices.append(mido.Message("note_on", note=64, velocity=75, time=0))
    voices.append(mido.Message("note_off", note=64, velocity=0, time=480))
    mid.save(str(subdir / "mix.mid"))
    (subdir / "metadata.yaml").write_text("ensemble: string\n", encoding="utf-8")
    review = {
        "schema_version": 1,
        "dataset_id": "cocochorales",
        "official_source": "https://magenta.tensorflow.org/datasets/cocochorales",
        "source_release_revision": "cocochorales-official-tiny-v1",
        "license": "CC-BY-4.0",
        "rights_reviewed": False,
        "tracks": [{"track_id": track_id, "split": "test"}],
    }
    return root, review, track_id


def test_exact_official_mix_wav_and_midi_yield_sha_bound_private_manifest(tmp_path):
    root, selected, track_id = _fixture(tmp_path)
    pairs, report = coco.prepare_pairs(selected, corpus_root=root)
    entry = pairs["cases"][0]
    assert entry["dataset_id"] == "cocochorales"
    assert entry["recording_id"] == track_id
    assert entry["license"] == "CC-BY-4.0"
    assert entry["rights_reviewed"] is False
    assert entry["audio"]["locator"] == f"private://{track_id}/mix.wav"
    assert entry["reference_midi"]["locator"] == f"private://{track_id}/mix.mid"
    assert entry["audio"]["sha256"] == coco._digest(root / track_id / "mix.wav")
    assert entry["reference_midi"]["sha256"] == coco._digest(root / track_id / "mix.mid")
    assert report["case_count"] == 1
    assert report["tracks"][0]["reference_note_on_count"] == 2
    assert report["tracks"][0]["duration_seconds"] == 2
    assert report["model_inference_performed"] is False
    assert report["rights_reviewed_by_operator_only"] is False
    assert report["source_media_published"] is False
    assert str(root) not in json.dumps(report)


def test_reviewed_local_pair_can_feed_existing_real_tier2_pair_validator(tmp_path):
    root, selected, _ = _fixture(tmp_path)
    selected["rights_reviewed"] = True
    pairs, report = coco.prepare_pairs(selected, corpus_root=root)
    # This registry copy represents a separately completed human review, not
    # production's planned registry entry, which stays unapproved.
    registry = {
        "schema_version": 1,
        "datasets": [{
            "id": "cocochorales",
            "task": "ensemble_amt",
            "source": coco._SOURCE,
            "license": "CC-BY-4.0",
            "status": "verified_for_evaluation",
            "audio_included": True,
        }],
    }
    result, benchmark = validate_pairs(
        pairs, registry, corpus_root=root, commercial=True,
    )
    assert result["case_count"] == 1
    assert result["cases"][0]["reference_note_on_count"] == 2
    assert result["model_inference_performed"] is False
    assert result["upstream_rights_independently_verified"] is False
    assert benchmark["cases"][0]["audio"]["redistributable"] is False
    assert report["rights_reviewed_by_operator_only"] is True


def test_unreviewed_pair_never_passes_tier2_quality_gate(tmp_path):
    root, selected, _ = _fixture(tmp_path)
    pairs, _ = coco.prepare_pairs(selected, corpus_root=root)
    registry = {
        "schema_version": 1,
        "datasets": [{
            "id": "cocochorales", "task": "ensemble_amt",
            "source": coco._SOURCE, "license": "CC-BY-4.0",
            "status": "planned", "audio_included": True,
        }],
    }
    with pytest.raises(ValueError, match="reviewed evaluation status"):
        validate_pairs(pairs, registry, corpus_root=root)


@pytest.mark.parametrize("change", (
    {"dataset_id": "other"},
    {"official_source": "https://example.org/replica"},
    {"license": "CC-BY-NC-SA-4.0"},
    {"source_release_revision": "unknown"},
    {"source_release_revision": ""},
    {"tracks": []},
    {"tracks": [{"track_id": "../../escape", "split": "test"}]},
    {"tracks": [{"track_id": "string_track000001", "split": "unreviewed"}]},
    {"tracks": [
        {"track_id": "string_track000001", "split": "test"},
        {"track_id": "string_track000001", "split": "train"},
    ]},
))
def test_invalid_dataset_identity_or_duplicate_track_never_passes(tmp_path, change):
    root, selected, _ = _fixture(tmp_path)
    selected.update(change)
    with pytest.raises(ValueError):
        coco.prepare_pairs(selected, corpus_root=root)


def test_corrupt_tiny_midi_or_wrong_sampling_rate_rejected(tmp_path):
    root, selected, track = _fixture(tmp_path)
    (root / track / "mix.mid").write_bytes(b"not a MIDI")
    with pytest.raises(ValueError, match="MIDI"):
        coco.prepare_pairs(selected, corpus_root=root)

    root, selected, track = _fixture(tmp_path)
    wav = root / track / "mix.wav"
    with wave.open(str(wav), "wb") as wave_file:
        wave_file.setnchannels(1)
        wave_file.setsampwidth(2)
        wave_file.setframerate(44100)
        wave_file.writeframes(b"\x00\x00" * 44100)
    with pytest.raises(ValueError, match="16kHz"):
        coco.prepare_pairs(selected, corpus_root=root)


def test_symlinked_or_incomplete_dataset_track_is_rejected(tmp_path):
    root, selected, track = _fixture(tmp_path)
    midi = root / track / "mix.mid"
    raw = midi.read_bytes()
    midi.unlink()
    foreign = tmp_path / "outside.mid"
    foreign.write_bytes(raw)
    midi.symlink_to(foreign)
    with pytest.raises(ValueError, match="linked"):
        coco.prepare_pairs(selected, corpus_root=root)
    midi.unlink()
    with pytest.raises(ValueError, match="missing"):
        coco.prepare_pairs(selected, corpus_root=root)


def test_dry_metadata_cli_never_overwrites_existing_file(tmp_path, monkeypatch):
    root, selected, track = _fixture(tmp_path)
    source = tmp_path / "track-selection.json"
    source.write_text(json.dumps(selected), encoding="utf-8")
    pairs = tmp_path / "pairs.json"
    audit = tmp_path / "audit.json"
    monkeypatch.setattr(
        "sys.argv",
        ["prepare_cocochorales_pairs.py", str(source), "--corpus-root", str(root),
         "--pairs", str(pairs), "--report", str(audit)],
    )
    assert coco.main() == 0
    saved = json.loads(pairs.read_text(encoding="utf-8"))
    assert saved["cases"][0]["recording_id"] == track
    assert json.loads(audit.read_text(encoding="utf-8"))["case_count"] == 1
    with pytest.raises(ValueError, match="outside git"):
        coco.main()
    assert json.loads(pairs.read_text(encoding="utf-8")) == saved


def test_invalid_metadata_output_destination_fails_before_write(tmp_path, monkeypatch):
    root, selected, _ = _fixture(tmp_path)
    source = tmp_path / "track-selection.json"
    source.write_text(json.dumps(selected), encoding="utf-8")
    monkeypatch.setattr(coco, "_ROOT", tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        ["prepare_cocochorales_pairs.py", str(source), "--corpus-root", str(root),
         "--pairs", str(tmp_path / "pairs.json"), "--report", str(tmp_path / "audit.json")],
    )
    with pytest.raises(ValueError, match="outside the repository"):
        coco.main()
    assert not (tmp_path / "pairs.json").exists()

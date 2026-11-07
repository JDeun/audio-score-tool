"""No network/model weights are required for hybrid handoff security tests."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from music21 import instrument, note, stream

from scripts import run_tier2_hybrid_smoke as handoff


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _base(tmp_path: Path, *, model: str = "yourmt3") -> tuple[Path, Path]:
    audio = tmp_path / "owned.wav"
    audio.write_bytes(b"owned and deterministic audio fixture")
    root = tmp_path / model
    root.mkdir()
    score = stream.Score()
    part = stream.Part()
    part.insert(0, instrument.Piano())
    part.append(note.Note("C4", quarterLength=1))
    score.append(part)
    midi = root / "score.mid"
    xml = root / "score.musicxml"
    score.write("midi", fp=str(midi))
    score.write("musicxml", fp=str(xml))
    from scripts.run_tier2_model_smoke import verify_model_outputs

    counts = verify_model_outputs(midi, xml)
    receipt = {
        "model": model,
        "note_events_detected": True,
        "audio_sha256": _sha(audio),
        "midi_sha256": _sha(midi),
        "musicxml_sha256": _sha(xml),
        "runtime": {"mt3_infer": "0.2.0"},
        "checkpoint": {"verified": False},
        **counts,
    }
    (root / "smoke-result.json").write_text(json.dumps(receipt), encoding="utf-8")
    return audio, root


def _events(tmp_path: Path, *, label: str = "C:maj") -> Path:
    path = tmp_path / "sheetsage2.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "model": "sheetsage2",
        "chords": [{"time_seconds": 0.0, "label": label}],
        "beats": [{"time_seconds": 0.0}, {"time_seconds": 0.5}],
        "keys": [],
    }), encoding="utf-8")
    return path


def test_base_handoff_rechecks_real_audio_and_score_hashes(tmp_path: Path):
    audio, root = _base(tmp_path)
    verified = handoff.verify_base(audio, root, model="yourmt3")
    assert verified["notes"] > 0
    assert verified["midi_notes"] > 0


def test_re_downloaded_audio_cannot_silently_mix_with_previous_amt(tmp_path: Path):
    audio, root = _base(tmp_path)
    audio.write_bytes(b"different rendition of nominally same YouTube source")
    with pytest.raises(ValueError, match="audio_sha256 mismatch"):
        handoff.verify_base(audio, root, model="yourmt3")


def test_tampered_base_score_cannot_be_used_for_fusion(tmp_path: Path):
    audio, root = _base(tmp_path)
    (root / "score.musicxml").write_text("<score-partwise/>", encoding="utf-8")
    with pytest.raises(ValueError, match="musicxml_sha256 mismatch"):
        handoff.verify_base(audio, root, model="yourmt3")


def test_wrong_model_identity_does_not_inherit_other_variant(tmp_path: Path):
    audio, root = _base(tmp_path)
    with pytest.raises(ValueError, match="model identity"):
        handoff.verify_base(audio, root, model="mr_mt3")


def test_false_note_success_or_missing_receipt_fails_closed(tmp_path: Path):
    audio, root = _base(tmp_path)
    payload_path = root / "smoke-result.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    payload["note_events_detected"] = False
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="note-success flag"):
        handoff.verify_base(audio, root, model="yourmt3")
    payload_path.unlink()
    with pytest.raises(ValueError, match="receipt"):
        handoff.verify_base(audio, root, model="yourmt3")


def test_real_hybrid_merge_preserves_amt_notes_and_writes_metadata_only(tmp_path: Path):
    audio, root = _base(tmp_path)
    events = _events(tmp_path)
    target = tmp_path / "hybrid.musicxml"
    result = handoff.merge_verified(
        audio, root, model="yourmt3", events_file=events, destination=target,
    )
    assert result["model"] == "yourmt3+sheetsage2"
    assert result["performed_notes_preserved"] == 1
    assert result["added"]["chords"] == 1
    assert result["commercial_approval"] is False
    assert result["checkpoint"]["sheetsage_verified"] is False
    assert result["hybrid_musicxml_sha256"] == _sha(target)
    assert result["audio_sha256"] == _sha(audio)
    assert "audio" not in {p.name for p in root.iterdir()}
    assert (root / "hybrid-result.json").is_file()


def test_hybrid_never_succeeds_on_empty_analysis(tmp_path: Path):
    audio, root = _base(tmp_path)
    events = _events(tmp_path, label="N")
    target = tmp_path / "hybrid.musicxml"
    with pytest.raises(ValueError, match="no usable harmony"):
        handoff.merge_verified(
            audio, root, model="yourmt3", events_file=events, destination=target,
        )
    assert not target.exists()
    assert not (root / "hybrid-result.json").exists()


def test_untrusted_events_model_identity_is_not_accepted(tmp_path: Path):
    audio, root = _base(tmp_path)
    events = _events(tmp_path)
    payload = json.loads(events.read_text(encoding="utf-8"))
    payload["model"] = "sheetsage1"
    events.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="model/schema identity"):
        handoff.merge_verified(
            audio, root, model="yourmt3", events_file=events,
            destination=tmp_path / "hybrid.musicxml",
        )

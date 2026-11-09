"""Synthetic-only contracts for reuse of issue #154's genuine source-bound sample.

No Hugging Face credential, third-party audio, or private model weight is used.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from music21 import instrument, note, stream

from scripts import run_muscriptor_source_qa as qa


def _note_artifacts(root: Path) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    score = stream.Score()
    part = stream.Part()
    part.insert(0, instrument.Piano())
    part.append(note.Note("C4", quarterLength=1))
    part.append(note.Note("E4", quarterLength=1))
    score.append(part)
    midi = root / f"coco-{qa.TRACK}.mid"
    xml = root / f"coco-{qa.TRACK}.musicxml"
    score.write("midi", fp=str(midi))
    score.write("musicxml", fp=str(xml))
    return midi, xml


def _checkpoint(tmp_path: Path, monkeypatch) -> Path:
    weight = tmp_path / ("c" * 40) / "model.safetensors"
    weight.parent.mkdir(parents=True)
    weight.write_bytes(b"FAKE WEIGHT ONLY" * 1000)
    monkeypatch.setattr(
        qa, "cached_muscriptor_checkpoint",
        lambda variant: weight if variant == "small" else None,
    )
    return weight


def _original_case(tmp_path: Path):
    corpus = tmp_path / "private-corpus"
    song_dir = corpus / qa.TRACK
    song_dir.mkdir(parents=True)
    audio = song_dir / "mix.wav"
    audio.write_bytes(b"synthetic-for-tests-not-real-author-recording")
    meta = tmp_path / "private-evidence"
    meta.mkdir()
    data = {
        "pairs.json": {
            "cases": [{
                "id": f"coco-{qa.TRACK}",
                "reference_midi": {"sha256": "d" * 64},
            }],
        },
        "reviewed-registry.json": {"datasets": [{"id": "cocochorales"}]},
        "source-proof.pending.json": {
            "source_repository": "lukewys/lukewys.github.io",
            "source_revision": "7a0b15e7be365a6b062027c38ce0f8d57ed1d98a",
            "archive_sha256": "e" * 64,
        },
        "tier2-manifest.json": {"schema_version": 1, "cases": []},
    }
    for name, obj in data.items():
        (meta / name).write_text(json.dumps(obj), encoding="utf-8")
    return audio, corpus, meta


def test_existing_author_audio_flows_through_real_engine_and_reference_scorer(
    tmp_path, monkeypatch,
):
    weight = _checkpoint(tmp_path, monkeypatch)
    audio, corpus, meta = _original_case(tmp_path)
    predicted = tmp_path / "private-predictions"
    evidence = tmp_path / "pending" / "verification.pending.json"
    captured = {}

    def fake_generate(_manifest, *, corpus_root, predictions_root, **kwargs):
        assert corpus_root == corpus
        assert predictions_root == predicted
        captured.update(kwargs)
        midi, xml = _note_artifacts(predictions_root)
        return [{
            "case_id": f"coco-{qa.TRACK}",
            "midi": str(midi),
            "musicxml": str(xml),
        }]

    def fake_score(_pairs, _registry, _source, *, corpus_root, predictions_root):
        assert corpus_root == corpus
        assert predictions_root == predicted
        midi = predicted / f"coco-{qa.TRACK}.mid"
        xml = predicted / f"coco-{qa.TRACK}.musicxml"
        return {
            "scored_case_count": 1, "case_count": 1,
            "source_evidence_sha256": "f" * 64,
            "cases": [{
                "case_id": f"coco-{qa.TRACK}",
                "status": "scored",
                "prediction_midi_sha256": hashlib.sha256(midi.read_bytes()).hexdigest(),
                "prediction_musicxml_sha256": hashlib.sha256(xml.read_bytes()).hexdigest(),
                "reference_note_count": 109,
                "note_onset_f1": 0.65,
                "note_onset_offset_f1": 0.43,
                "instrument_onset_offset_f1": 0.22,
                "model_inference_seconds": 17.5,
            }],
        }

    monkeypatch.setattr(qa, "generate_tier2_predictions", fake_generate)
    monkeypatch.setattr(qa, "score_cocochorales", fake_score)
    report = qa.run_qa(
        audio, source_kind="cocochorales-author-train",
        destination=evidence, private_predictions_root=predicted,
        corpus_root=corpus, evidence_root=meta,
    )
    assert report == json.loads(evidence.read_text(encoding="utf-8"))
    assert captured["engine_id"] == "muscriptor"
    assert captured["model"] == "small"
    assert captured["device"] == "cpu"
    assert captured["model_revision"] == f"sha256:{hashlib.sha256(weight.read_bytes()).hexdigest()}"
    assert captured["artifact_sha256"] == hashlib.sha256(weight.read_bytes()).hexdigest()
    assert report["recording_id"] == qa.TRACK
    assert report["dataset_split"] == "train"
    assert report["reference_note_count"] == 109
    assert report["note_onset_f1"] == 0.65
    assert report["instrument_onset_offset_f1"] == 0.22
    assert report["midi_note_events"] > 0 and report["musicxml_parts"] == 1
    assert report["checkpoint_revision_pinned_before_download"] is False
    assert report["release_quality_approved"] is False
    assert report["heldout_generalization_measured"] is False
    assert report["redistribution_approved"] is False
    assert str(tmp_path) not in evidence.read_text(encoding="utf-8")
    assert not (tmp_path / "pending" / "score.mid").exists()


def test_missing_model_denies_execution_before_any_source_is_scored(tmp_path, monkeypatch):
    audio, corpus, meta = _original_case(tmp_path)
    monkeypatch.setattr(qa, "cached_muscriptor_checkpoint", lambda _: None)
    monkeypatch.setattr(
        qa, "generate_tier2_predictions",
        lambda *_args, **_kwargs: pytest.fail("must not execute without gated model"),
    )
    destination = tmp_path / "pending.json"
    with pytest.raises(RuntimeError, match="not installed"):
        qa.run_qa(
            audio, source_kind="cocochorales-author-train",
            destination=destination,
            private_predictions_root=tmp_path / "private-predictions",
            corpus_root=corpus, evidence_root=meta,
        )
    assert not destination.exists()


def test_official_sample_audio_must_be_exact_expected_private_locator(
    tmp_path, monkeypatch,
):
    _checkpoint(tmp_path, monkeypatch)
    audio, corpus, meta = _original_case(tmp_path)
    alternate = tmp_path / "unreviewed.wav"
    alternate.write_bytes(audio.read_bytes())
    with pytest.raises(ValueError, match="audio path disagrees"):
        qa.run_qa(
            alternate, source_kind="cocochorales-author-train",
            destination=tmp_path / "pending.json",
            private_predictions_root=tmp_path / "out",
            corpus_root=corpus, evidence_root=meta,
        )


def test_missing_evidence_or_unauthorized_source_never_starts_model(tmp_path, monkeypatch):
    _checkpoint(tmp_path, monkeypatch)
    audio, corpus, meta = _original_case(tmp_path)
    for source_kind in ("unreviewed-external-url", "", "synthetic-instead-of-real"):
        with pytest.raises(ValueError, match="Unsupported or unreviewed"):
            qa.run_qa(
                audio, source_kind=source_kind, destination=tmp_path / "out.json",
                private_predictions_root=tmp_path / "private-predictions",
            )
    with pytest.raises(ValueError, match="requires existing private source evidence"):
        qa.run_qa(
            audio, source_kind="cocochorales-author-train",
            destination=tmp_path / "out.json",
            private_predictions_root=tmp_path / "private-predictions",
        )
    assert not (tmp_path / "out.json").exists()


def test_authorized_youtube_lacks_reference_so_no_f1_can_be_claimed(
    tmp_path, monkeypatch,
):
    _checkpoint(tmp_path, monkeypatch)
    audio = tmp_path / "operator-reviewed.wav"
    audio.write_bytes(b"synthetic-authorized-fixture")
    predicted = tmp_path / "predictions"

    class FakeEngine:
        def __init__(self, settings):
            assert settings.usage_mode == "personal"

        def transcribe(self, actual, root, *, device):
            assert actual == audio and device == "cpu"
            midi, xml = _note_artifacts(root)
            return SimpleNamespace(midi_path=midi, musicxml_path=xml)

    monkeypatch.setattr(qa, "MuScriptorEngine", FakeEngine)
    receipt = qa.run_qa(
        audio, source_kind="authorized-youtube",
        private_predictions_root=predicted,
        destination=tmp_path / "verification.pending.json",
    )
    assert receipt["status"] == "executed"
    assert receipt["reference_midi_sha256"] is None
    assert receipt["note_onset_f1"] is None
    assert receipt["instrument_onset_offset_f1"] is None
    assert receipt["source_processing_rights_independently_verified"] is False
    assert receipt["release_quality_approved"] is False


def test_existing_receipt_or_private_predictions_are_never_overwritten(
    tmp_path, monkeypatch,
):
    _checkpoint(tmp_path, monkeypatch)
    audio, corpus, meta = _original_case(tmp_path)
    receipt = tmp_path / "verification.pending.json"
    receipt.write_text("previous evidence")
    with pytest.raises(ValueError, match="must not already exist"):
        qa.run_qa(
            audio, source_kind="cocochorales-author-train",
            destination=receipt, private_predictions_root=tmp_path / "predictions",
            corpus_root=corpus, evidence_root=meta,
        )
    assert receipt.read_text() == "previous evidence"

from __future__ import annotations

import json
from pathlib import Path

from audio_score_tool.config import Settings
from audio_score_tool.tier2_prediction import (
    generate_tier2_predictions,
    load_tier2_prediction_provenance,
)
from audio_score_tool.transcription_engine import TranscriptionArtifacts


class _FakeEngine:
    def ready(self) -> bool:
        return True

    def describe(self) -> dict[str, object]:
        return {"key": "fake", "ready": True}

    def transcribe(self, audio_path: Path, output_dir: Path, *, device: str):
        assert audio_path.read_bytes() == b"audio"
        assert device == "cpu"
        output_dir.mkdir(parents=True, exist_ok=True)
        midi = output_dir / "score.mid"
        xml = output_dir / "score.musicxml"
        midi.write_bytes(b"midi")
        xml.write_text("<score-partwise version=\"4.0\"/>", encoding="utf-8")
        return TranscriptionArtifacts(midi_path=midi, musicxml_path=xml)


def test_generate_tier2_predictions_uses_manifest_audio_and_writes_provenance(
    tmp_path: Path,
    monkeypatch,
):
    corpus = tmp_path / "corpus"
    audio = corpus / "audio" / "case.wav"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"audio")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "corpus_version": "1",
                "cases": [
                    {
                        "id": "case-001",
                        "title": "Example",
                        "category": "band",
                        "genre": "pop",
                        "audio": {"locator": "private://audio/case.wav"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    predictions = tmp_path / "predictions"

    monkeypatch.setattr(
        "audio_score_tool.tier2_prediction.runtime_settings",
        lambda: Settings(transcription_engine="mt3_infer"),
    )
    monkeypatch.setattr(
        "audio_score_tool.tier2_prediction.resolve_transcription_engine",
        lambda _settings: _FakeEngine(),
    )

    generated = generate_tier2_predictions(
        manifest,
        corpus_root=corpus,
        predictions_root=predictions,
        engine_id="mt3_infer",
        model="yourmt3",
        model_revision="model-rev",
        runtime_revision="runtime-rev",
        artifact_sha256="a" * 64,
    )

    assert generated[0]["case_id"] == "case-001"
    assert (predictions / "case-001.mid").read_bytes() == b"midi"
    assert (predictions / "case-001.musicxml").is_file()
    corpus_version, identity, case_ids, payload = load_tier2_prediction_provenance(predictions)
    assert corpus_version == "1"
    assert identity.id == "mt3_infer"
    assert identity.model_revision == "model-rev"
    assert identity.runtime_revision == "runtime-rev"
    assert identity.artifact_sha256 == "a" * 64
    assert case_ids == ("case-001",)
    assert payload["device"] == "cpu"

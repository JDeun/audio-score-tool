"""Real, optional MuScriptor CPU QA on an already-reviewed original audio source.

No network downloads here. For the CocoChorales author sample, reuses the
existing strict source/rights validator, AMT product engine, independent
reference MIDI scorer, and provenance recorder. Metadata-only output; never
publish original audio, a model weight, or predicted MIDI/MusicXML.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

from audio_score_tool.config import Settings
from audio_score_tool.muscriptor_cache import cached_muscriptor_checkpoint
from audio_score_tool.tier2_prediction import generate_tier2_predictions
from audio_score_tool.transcription_engine import MuScriptorEngine
from scripts.run_tier2_model_smoke import verify_model_outputs
from scripts.score_cocochorales_tiny import score_cocochorales

MODEL_REPO = "MuScriptor/muscriptor-small"
UPSTREAM_COMMIT = "8a1ef88672cc23c26619adaff37ec48d82c0b906"
TRACK = "string_track001010"
_ALLOWED_SOURCES = {"cocochorales-author-train", "authorized-youtube"}


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for piece in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(piece)
    return digest.hexdigest()


def run_qa(
    audio: Path,
    *,
    source_kind: str,
    destination: Path,
    private_predictions_root: Path,
    corpus_root: Path | None = None,
    evidence_root: Path | None = None,
) -> dict:
    """Actually run the small model, reject empty outputs, and bind provenance.

    Official train samples have independent reference-MIDI F1; authorized
    YouTube sources do not have a scored reference and must report N/A.
    This function never treats train-only evaluation as held-out accuracy.
    """
    if source_kind not in _ALLOWED_SOURCES:
        raise ValueError("Unsupported or unreviewed MuScriptor source")
    if destination.exists() or destination.is_symlink():
        raise ValueError("MuScriptor evidence destination must not already exist")
    if audio.is_symlink() or not audio.is_file() or audio.stat().st_size <= 0:
        raise ValueError("MuScriptor input audio is missing or linked")

    checkpoint = cached_muscriptor_checkpoint("small")
    if checkpoint is None:
        raise RuntimeError("MuScriptor small checkpoint/config is not installed in HF cache")
    checkpoint_sha256 = _sha(checkpoint)
    if private_predictions_root.exists() or private_predictions_root.is_symlink():
        raise ValueError("MuScriptor private prediction directory must be new")
    # Cache presence and a measured SHA are not independently preapproved
    # immutable upstream weights or redistribution permissions.
    common = {
        "schema_version": 1,
        "status": "executed",
        "task": "private-noncommercial-multi-instrument-amt",
        "model": MODEL_REPO,
        "snapshot_revision": checkpoint.parent.name,
        "checkpoint_sha256": checkpoint_sha256,
        "checkpoint_revision_pinned_before_download": False,
        "upstream_runtime_commit": UPSTREAM_COMMIT,
        "audio_sha256": _sha(audio),
        "source_kind": source_kind,
        "commercial_default_selected": False,
        "redistribution_approved": False,
        "release_quality_approved": False,
        "heldout_generalization_measured": False,
        "media_or_model_bytes_published": False,
        "performed_with_embedded_midi_converter": True,
    }

    if source_kind == "cocochorales-author-train":
        if corpus_root is None or evidence_root is None:
            raise ValueError("Official author sample requires existing private source evidence")
        audio_expected = corpus_root / TRACK / "mix.wav"
        if audio.absolute() != audio_expected.absolute():
            raise ValueError("Official sample audio path disagrees with the verified corpus")
        pairs = json.loads((evidence_root / "pairs.json").read_text(encoding="utf-8"))
        registry = json.loads(
            (evidence_root / "reviewed-registry.json").read_text(encoding="utf-8")
        )
        source_proof = json.loads(
            (evidence_root / "source-proof.pending.json").read_text(encoding="utf-8")
        )
        manifest = evidence_root / "tier2-manifest.json"
        generated = generate_tier2_predictions(
            manifest,
            corpus_root=corpus_root,
            predictions_root=private_predictions_root,
            engine_id="muscriptor",
            model="small",
            model_revision=f"sha256:{checkpoint_sha256}",
            runtime_revision=f"muscriptor-git-{UPSTREAM_COMMIT}",
            artifact_sha256=checkpoint_sha256,
            device="cpu",
        )
        if len(generated) != 1 or generated[0]["case_id"] != f"coco-{TRACK}":
            raise RuntimeError("MuScriptor original author case identity is inconsistent")
        prediction = generated[0]
        midi_path = Path(prediction["midi"])
        xml_path = Path(prediction["musicxml"])
        note_summary = verify_model_outputs(midi_path, xml_path)
        score = score_cocochorales(
            pairs, registry, source_proof,
            corpus_root=corpus_root, predictions_root=private_predictions_root,
        )
        if score["scored_case_count"] != 1 or score["case_count"] != 1:
            raise RuntimeError("MuScriptor source-bound scoring did not evaluate the sole case")
        case = score["cases"][0]
        if case["status"] != "scored" or case["case_id"] != f"coco-{TRACK}":
            raise RuntimeError("MuScriptor scored output mismatched the author sample")
        if (case["prediction_midi_sha256"] != _sha(midi_path)
                or case["prediction_musicxml_sha256"] != _sha(xml_path)):
            raise RuntimeError("MuScriptor scoring evidence output hash mismatch")
        common.update({
            "dataset": "CocoChorales",
            "dataset_split": "train",
            "recording_id": TRACK,
            "source_repository": source_proof["source_repository"],
            "source_revision": source_proof["source_revision"],
            "source_archive_sha256": source_proof["archive_sha256"],
            "source_evidence_sha256": score["source_evidence_sha256"],
            "reference_midi_sha256": pairs["cases"][0]["reference_midi"]["sha256"],
            "reference_note_count": case["reference_note_count"],
            "note_onset_f1": case["note_onset_f1"],
            "note_onset_offset_f1": case["note_onset_offset_f1"],
            "instrument_onset_offset_f1": case["instrument_onset_offset_f1"],
            "model_inference_seconds": case["model_inference_seconds"],
            "product_publish_time_measured": False,
            "rights_reviewed_scope": "official pinned author sample, CC-BY-4.0",
        })
    else:
        # This is an explicit, operator-selected source. There is no independent
        # reference MIDI, so do not invent note/instrument F1 scores.
        private_predictions_root.mkdir(parents=True)
        started = time.perf_counter()
        artifacts = MuScriptorEngine(Settings(
            usage_mode="personal",
            transcription_engine="muscriptor",
            muscriptor_cmd="muscriptor",
            muscriptor_model="small",
        )).transcribe(audio, private_predictions_root, device="cpu")
        seconds = round(time.perf_counter() - started, 6)
        midi_path, xml_path = artifacts.midi_path, artifacts.musicxml_path
        note_summary = verify_model_outputs(midi_path, xml_path)
        common.update({
            "dataset": None,
            "dataset_split": None,
            "reference_midi_sha256": None,
            "note_onset_f1": None,
            "note_onset_offset_f1": None,
            "instrument_onset_offset_f1": None,
            "model_inference_seconds": seconds,
            "source_processing_rights_independently_verified": False,
        })

    common.update({
        "midi_sha256": _sha(midi_path),
        "musicxml_sha256": _sha(xml_path),
        "midi_note_events": note_summary["midi_notes"],
        "musicxml_note_events": note_summary["notes"],
        "musicxml_parts": note_summary["parts"],
    })
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(common, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    return common


def main() -> int:
    parser = argparse.ArgumentParser(description="Run explicit MuScriptor real-model QA")
    parser.add_argument("--audio", required=True, type=Path)
    parser.add_argument("--source-kind", choices=sorted(_ALLOWED_SOURCES), required=True)
    parser.add_argument("--predictions-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--corpus-root", type=Path)
    parser.add_argument("--evidence-root", type=Path)
    args = parser.parse_args()
    receipt = run_qa(
        args.audio, source_kind=args.source_kind,
        destination=args.output, private_predictions_root=args.predictions_root,
        corpus_root=args.corpus_root, evidence_root=args.evidence_root,
    )
    print(json.dumps({
        "status": receipt["status"],
        "source_kind": receipt["source_kind"],
        "midi_note_events": receipt["midi_note_events"],
        "reference_midi_scored": receipt["reference_midi_sha256"] is not None,
        "commercial_default_selected": False,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

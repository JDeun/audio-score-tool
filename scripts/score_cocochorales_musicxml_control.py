"""Reference-only MusicXML round-trip control for CocoChorales author samples.

Separate the note losses introduced by music21 MIDI→MusicXML→MIDI conversion
from losses in a neural model's predicted MusicXML. No model or checkpoint is
downloaded. All actual source WAV/MIDI are kept in a private runner directory;
only reference/source hashes and aggregated note metrics are published.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import tempfile
from pathlib import Path
from statistics import mean
from typing import Any

from audio_score_tool.notation_backend import midi_to_musicxml
from scripts.aggregate_cocochorales_author_samples import TRACKS
from scripts.prepare_cocochorales_official_sample import SOURCE_COMMIT
from scripts.score_cocochorales_tiny import (
    _score_musicxml_fidelity,
    _source_receipt,
)
from scripts.validate_tier2_dataset_pairs import validate_pairs

_SCORE_KEYS = ("onset_f1", "onset_offset_f1", "instrument_onset_offset_f1")


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as data:
        for chunk in iter(lambda: data.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha_json(obj: dict) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def reference_roundtrip(reference: Path, *, scratch_root: Path, original_parts: int) -> dict:
    """Perform a genuine music21 conversion with no model predictions.

    This is the calibration control: how much note/instrument fidelity is lost
    when a ground-truth MIDI passes through the very same score codec.
    """
    if reference.is_symlink() or not reference.is_file() or not 0 < reference.stat().st_size < 32 * 1024 * 1024:
        raise ValueError("Reference MIDI must be a bounded regular file")
    with tempfile.TemporaryDirectory(prefix=".reference-score-control-", dir=scratch_root) as temp:
        score = Path(temp) / "reference.musicxml"
        midi_to_musicxml(reference, score)
        fidelity = _score_musicxml_fidelity(
            score, reference, reference,
            scratch_root=Path(temp), original_part_count=original_parts,
        )
        return {
            "source_note_count": fidelity["reference_note_count"],
            "roundtrip_note_count": fidelity["score_playable_note_count"],
            "f1": fidelity["against_reference"],
            "reference_musicxml_part_count": fidelity["reference_part_count"],
            "conversion_method": "music21_midi_to_musicxml_to_midi",
        }


def score_original_author_sample(
    pairs: dict, registry: dict, source: dict, *, corpus_root: Path,
) -> dict:
    """Score a *verified* author WAV/reference MIDI pair; fail closed on rights."""

    validated, _manifest = validate_pairs(pairs, registry, corpus_root=corpus_root)
    cases = pairs.get("cases")
    if not isinstance(cases, list) or len(cases) != 1:
        raise ValueError("Control requires exactly one author pair")
    case = cases[0]
    track = case.get("recording_id")
    if track not in TRACKS or case.get("split") != "train":
        raise ValueError("Control must use the registered four author train examples")
    if source.get("source_kind") != "official-sample-zip" or source.get("source_revision") != SOURCE_COMMIT:
        raise ValueError("Control requires the pinned original author ZIP")
    _source_receipt(source, split="train", paired=pairs)
    original_parts = len(source["tracks"][0]["instruments"])
    if original_parts != 4:
        raise ValueError("Control expects exactly four original SATB voices")
    locator = case["reference_midi"]["locator"]
    if not isinstance(locator, str) or not locator.startswith("private://"):
        raise ValueError("Reference MIDI path must be a private locator")
    root = corpus_root.expanduser().resolve()
    reference = (root / locator.removeprefix("private://")).resolve()
    if not reference.is_relative_to(root):
        raise ValueError("Reference MIDI path escaped the private corpus")

    observed = reference_roundtrip(
        reference, scratch_root=corpus_root, original_parts=original_parts,
    )
    if observed["source_note_count"] < 1 or observed["roundtrip_note_count"] < 1:
        raise ValueError("No performed notes in reference control")
    return {
        "schema_version": 1,
        "purpose": "reference-only-musicxml-conversion-control",
        "source": "CocoChorales official author-published sample",
        "dataset_split": "train",
        "track_id": track,
        "source_revision": SOURCE_COMMIT,
        "source_proof_sha256": _sha_json(source),
        "paired_fingerprint": validated["recording_pairs_fingerprint"],
        "reference_midi_sha256": _sha(reference),
        "source_audio_sha256": case["audio"]["sha256"],
        "music21_roundtrip": observed,
        "model_inference_performed": False,
        "model_checkpoint_downloaded": False,
        "source_media_published": False,
        "release_quality_approved": False,
        "heldout_generalization_measured": False,
        "commercial_default_selected": False,
    }


def aggregate_controls(cases: list[dict]) -> dict[str, Any]:
    """Require all four original controls before publishing a macro baseline."""
    if len(cases) != len(TRACKS) or [c.get("track_id") for c in cases] != list(TRACKS):
        raise ValueError("Missing or reordered official reference control cases")
    for case in cases:
        if (
            case.get("schema_version") != 1
            or case.get("purpose") != "reference-only-musicxml-conversion-control"
            or case.get("dataset_split") != "train"
            or case.get("source_revision") != SOURCE_COMMIT
            or case.get("source_media_published") is not False
            or case.get("model_inference_performed") is not False
            or case.get("release_quality_approved") is not False
        ):
            raise ValueError("Reference control is not an original unapproved train sample")
        data = case.get("music21_roundtrip")
        scores = data.get("f1") if isinstance(data, dict) else None
        if not isinstance(scores, dict) or any(
            type(scores.get(field)) not in (int, float)
            or not math.isfinite(scores[field])
            or not 0 <= scores[field] <= 1
            for field in _SCORE_KEYS
        ):
            raise ValueError("Reference round-trip metrics are invalid")
        for digest in ("reference_midi_sha256", "source_audio_sha256", "source_proof_sha256"):
            field = case.get(digest)
            if not isinstance(field, str) or len(field) != 64 or any(
                char not in "0123456789abcdef" for char in field
            ):
                raise ValueError("Original source proof SHA-256 is absent or malformed")

    return {
        "schema_version": 1,
        "purpose": "reference-only-musicxml-conversion-control",
        "case_count": len(cases),
        "original_track_ids": list(TRACKS),
        "source_revision": SOURCE_COMMIT,
        "raw_source_sha256": [c["source_audio_sha256"] for c in cases],
        "reference_sha256": [c["reference_midi_sha256"] for c in cases],
        "macro_music21_reference_roundtrip": {
            key: round(mean(c["music21_roundtrip"]["f1"][key] for c in cases), 8)
            for key in _SCORE_KEYS
        },
        "per_track": [{
            "track_id": c["track_id"],
            "source_sha256": c["source_proof_sha256"],
            "roundtrip_metrics": c["music21_roundtrip"],
        } for c in cases],
        "model_inference_performed": False,
        "model_redistribution_approved": False,
        "source_media_published": False,
        "release_quality_approved": False,
        "heldout_generalization_measured": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="MusicXML conversion control on original author reference MIDI")
    parser.add_argument("--pairs", type=Path)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--source-proof", type=Path)
    parser.add_argument("--corpus-root", type=Path)
    parser.add_argument("--reports-root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error("Control receipt must be a new metadata-only output")
    if args.reports_root:
        if not args.reports_root.is_dir() or args.reports_root.is_symlink():
            parser.error("Control reports root must be a real directory")
        cases = []
        for track in TRACKS:
            path = args.reports_root / f"{track}.pending.json"
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 128 * 1024:
                parser.error("Missing or unsafe per-track control receipt")
            cases.append(json.loads(path.read_text(encoding="utf-8")))
        report = aggregate_controls(cases)
    else:
        if not all((args.pairs, args.registry, args.source_proof, args.corpus_root)):
            parser.error("Single control requires pairs, registry, source-proof and corpus-root")
        report = score_original_author_sample(
            json.loads(args.pairs.read_text(encoding="utf-8")),
            json.loads(args.registry.read_text(encoding="utf-8")),
            json.loads(args.source_proof.read_text(encoding="utf-8")),
            corpus_root=args.corpus_root,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as destination:
        json.dump(report, destination, indent=2, ensure_ascii=False, sort_keys=True)
        destination.write("\n")
    print(json.dumps({
        "purpose": report["purpose"],
        "case_count": report.get("case_count", 1),
        "reference_roundtrip_macro": report.get("macro_music21_reference_roundtrip"),
        "model_inference_performed": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

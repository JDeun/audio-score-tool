"""Score actual AMT MIDI/MusicXML against verified CocoChorales pairs.

Requires already-generated predictions and an original official-shard receipt.
Never runs or downloads a model, music, or third-party binaries. Onset-only
and onset+offset note F1 are separate; matching GM program is an additional
strict instrument-aware metric. This does not measure human publish time.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

import mido
from defusedxml import ElementTree as ET

from audio_score_tool.metrics import MidiNote, evaluate_midi_files, midi_notes
from audio_score_tool.notation_backend import NotationBackendError, musicxml_to_midi
from audio_score_tool.tier2_prediction import load_tier2_prediction_provenance
from scripts.extract_cocochorales_tiny import (
    _OFFICIAL_FORMAT_COMMIT,
    _OFFICIAL_MD5,
    _RELEASE,
    _SHARD_SPLIT,
)
from scripts.prepare_cocochorales_official_sample import (
    SAMPLE_BLOBS,
    SAMPLE_ROOT,
    SOURCE_COMMIT,
    SOURCE_FORMAT_COMMIT,
    SOURCE_PAGE,
    SOURCE_RELEASE,
    SOURCE_REPO,
)
from scripts.prepare_cocochorales_pairs import _ROOT, official_split
from scripts.validate_tier2_dataset_pairs import validate_pairs

_SHA = re.compile(r"[a-f0-9]{64}\Z")


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _score_matching(
    predicted: list[MidiNote], reference: list[MidiNote], *,
    require_instrument: bool,
) -> dict[str, Any]:
    """One-to-one pitch/onset/offset matching with deterministic tie breaks."""
    claimed: set[int] = set()
    matched = 0
    for ref in reference:
        best = None
        best_error = float("inf")
        for i, pred in enumerate(predicted):
            if i in claimed or pred.pitch != ref.pitch:
                continue
            if require_instrument and pred.instrument_key != ref.instrument_key:
                continue
            onset_error = abs(pred.onset - ref.onset)
            offset_error = abs(pred.offset - ref.offset)
            offset_tolerance = max(0.05, 0.2 * max(0, ref.offset - ref.onset))
            if onset_error > 0.05 or offset_error > offset_tolerance:
                continue
            error = onset_error + offset_error
            if error < best_error:
                best, best_error = i, error
        if best is not None:
            claimed.add(best)
            matched += 1
    precision = matched / len(predicted) if predicted else 0.0
    recall = matched / len(reference) if reference else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "matched": matched, "predicted": len(predicted), "reference": len(reference),
        "precision": round(precision, 8), "recall": round(recall, 8),
        "f1": round(f1, 8),
    }


def _musicxml_summary(path: Path) -> dict[str, int]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("prediction MusicXML file is missing or exceeds safe size")
    try:
        document = ET.parse(path)
    except (ET.ParseError, OSError, ValueError) as exc:
        raise ValueError("prediction MusicXML is invalid") from exc
    root = document.getroot()
    if root.tag.rpartition("}")[-1] != "score-partwise":
        raise ValueError("prediction is not MusicXML score-partwise")
    parts = [element for element in root if element.tag.rpartition("}")[-1] == "part"]
    note_count = 0
    for part in parts:
        for note in part.iter():
            if note.tag.rpartition("}")[-1] != "note":
                continue
            is_rest = any(child.tag.rpartition("}")[-1] == "rest" for child in note)
            if not is_rest:
                note_count += 1
    if not parts or not note_count:
        raise ValueError("prediction MusicXML is empty")
    return {"parts": len(parts), "notes": note_count}



def _score_musicxml_fidelity(
    musicxml: Path, predicted_midi: Path, reference_midi: Path, *,
    scratch_root: Path, original_part_count: int,
) -> dict[str, Any]:
    """Compare the *rendered notation* to ground truth, separately from raw MIDI.

    The app's own music21 MusicXML -> MIDI conversion gives a common,
    tempo-aware note-event representation. The ephemeral round-trip MIDI is
    never published. This detects note loss, wrong pitch/offset, and changed
    GM program during score serialization; it is not a PDF/engraving or human
    edit-time quality metric.
    """
    with tempfile.TemporaryDirectory(prefix=".coco-score-roundtrip-", dir=scratch_root) as temp:
        roundtrip = Path(temp) / "roundtrip.mid"
        musicxml_to_midi(musicxml, roundtrip)
        xml_notes = midi_notes(roundtrip)
        if not xml_notes:
            raise ValueError("MusicXML is parseable but has no playable notes")
        reference_notes = midi_notes(reference_midi)
        prediction_notes = midi_notes(predicted_midi)
        if not reference_notes or not prediction_notes:
            raise ValueError("MIDI or reference has no performed notes")

        def compare(notes: list[MidiNote], target: list[MidiNote]) -> dict[str, Any]:
            onset = _score_matching(
                notes, target, require_instrument=False,
            )  # full offset-aware match, separately named below
            instrument = _score_matching(notes, target, require_instrument=True)
            # Direct onset-only matching uses the exact same 50 ms tolerance
            # as evaluate_midi_files; note-offset validation stays separate.
            onset_only = _onset_note_f1(notes, target)
            return {
                "onset_f1": onset_only,
                "onset_offset_f1": onset["f1"],
                "instrument_onset_offset_f1": instrument["f1"],
                "matched_onset_offset_notes": onset["matched"],
                "matched_instrument_notes": instrument["matched"],
            }

        # Reuse the original raw MIDI and reference to expose serialization
        # loss separately from model transcription errors.
        return {
            "method": "music21_musicxml_to_midi_temp_roundtrip",
            "note_onset_tolerance_seconds": 0.05,
            "reference_note_count": len(reference_notes),
            "score_playable_note_count": len(xml_notes),
            "predicted_midi_note_count": len(prediction_notes),
            "against_reference": compare(xml_notes, reference_notes),
            "against_prediction_midi": compare(xml_notes, prediction_notes),
            "reference_part_count": original_part_count,
        }


def _onset_note_f1(predicted: list[MidiNote], reference: list[MidiNote]) -> float:
    """Onset-only F1 with maximum one-to-one pitch+50 ms pairs.

    Matches the existing note-onset evaluator's tolerance and matching
    convention, without writing another comparison MIDI to disk.
    """
    claimed: set[int] = set()
    matched = 0
    for ref in reference:
        best_index = None
        best_error = float("inf")
        for i, pred in enumerate(predicted):
            if i in claimed or pred.pitch != ref.pitch:
                continue
            error = abs(pred.onset - ref.onset)
            if error <= 0.05 and error < best_error:
                best_index, best_error = i, error
        if best_index is not None:
            claimed.add(best_index)
            matched += 1
    precision = matched / len(predicted) if predicted else 0.0
    recall = matched / len(reference) if reference else 0.0
    return round(
        2 * precision * recall / (precision + recall) if precision + recall else 0.0, 8
    )


def _midi_program_diagnostics(
    predicted_midi: Path, reference_midi: Path,
    predicted_notes: list[MidiNote], reference_notes: list[MidiNote],
    *,
    original_instruments: list[dict[str, Any]],
    musicxml_parts: int,
    strict_note_matches: int,
) -> dict[str, Any]:
    """Record actual GM/channel/MIDI track evidence without changing predictions.

    Note counts use the same program interpretation as instrument-aware F1.
    The raw MIDI track summaries distinguish engine part collapse from a
    *possible* MIDI→MusicXML conversion collapse; neither infers a root cause.
    """

    def programs(notes: list[MidiNote]) -> list[dict[str, Any]]:
        counter = Counter((note.is_drum, note.program) for note in notes)
        return [
            {"is_drum": is_drum, "program": program, "note_count": counter[(is_drum, program)]}
            for is_drum, program in sorted(counter)
        ]

    def tracks(path: Path) -> dict[str, int]:
        midi = mido.MidiFile(str(path))
        return {
            "total_tracks": len(midi.tracks),
            "note_bearing_tracks": sum(
                any(event.type == "note_on" and event.velocity > 0 for event in track)
                for track in midi.tracks
            ),
        }

    predicted_keys = {note.instrument_key for note in predicted_notes}
    reference_keys = {note.instrument_key for note in reference_notes}
    expected_programs = sorted({
        part["midi_program"] for part in original_instruments
        if isinstance(part, dict) and type(part.get("midi_program")) is int
        and 0 <= part["midi_program"] <= 127
    })
    predicted_structure = tracks(predicted_midi)
    reference_structure = tracks(reference_midi)
    return {
        "source_declared_gm_programs": expected_programs,
        "reference_gm_program_note_counts": programs(reference_notes),
        "prediction_gm_program_note_counts": programs(predicted_notes),
        "reference_note_channels": sorted({note.channel for note in reference_notes}),
        "prediction_note_channels": sorted({note.channel for note in predicted_notes}),
        "shared_gm_programs": [
            program for is_drum, program in sorted(reference_keys & predicted_keys)
            if not is_drum
        ],
        "reference_midi": reference_structure,
        "prediction_midi": predicted_structure,
        "prediction_musicxml_part_count": musicxml_parts,
        "strict_instrument_note_matches": strict_note_matches,
        "no_shared_program_explains_strict_zero": (
            not (predicted_keys & reference_keys) and strict_note_matches == 0
        ),
        "midi_to_musicxml_track_count_reduction_observed": (
            predicted_structure["note_bearing_tracks"] > musicxml_parts
        ),
        "diagnosis_is_observation_not_causal_proof": True,
    }


def _source_receipt(
    record: dict, *, split: str, paired: dict,
) -> None:
    if record.get("source_kind") == "official-sample-zip":
        tracks = paired.get("cases", [])
        track = tracks[0].get("recording_id") if len(tracks) == 1 else None
        pinned = SAMPLE_BLOBS.get(track)
        if (
            pinned is None or split != "train"
            or record.get("official_release") != SOURCE_RELEASE
            or record.get("official_source") != "https://magenta.tensorflow.org/datasets/cocochorales"
            or record.get("official_sample_page") != SOURCE_PAGE
            or record.get("source_repository") != SOURCE_REPO
            or record.get("source_revision") != SOURCE_COMMIT
            or record.get("official_format_source_commit") != SOURCE_FORMAT_COMMIT
            or record.get("official_archive_path") != f"{SAMPLE_ROOT}/{track}.zip"
            or record.get("archive_git_blob_sha1") != pinned[0]
            or record.get("archive_bytes") != pinned[1]
            or record.get("track_count") != 1
            or record.get("operator_rights_reviewed") is not True
            or record.get("source_media_published") is not False
            or record.get("upstream_rights_independently_verified") is not False
            or not isinstance(record.get("archive_sha256"), str)
            or _SHA.fullmatch(record["archive_sha256"]) is None
        ):
            raise ValueError("Official CocoChorales sample archive provenance is invalid")
    elif (
        record.get("schema_version") != 1
        or record.get("dataset") != "cocochorales"
        or record.get("official_release") != _RELEASE
        or record.get("official_format_source_commit") != _OFFICIAL_FORMAT_COMMIT
        or record.get("official_shard") != f"main_dataset/{_SHARD_SPLIT[split]}/1.tar.bz2"
        or record.get("official_published_md5_verified") is not True
        or record.get("archive_md5") != _OFFICIAL_MD5[split]
        or not isinstance(record.get("archive_sha256"), str)
        or _SHA.fullmatch(record["archive_sha256"]) is None
        or record.get("operator_rights_reviewed") is not True
        or record.get("source_media_published") is not False
        or record.get("upstream_rights_independently_verified") is not False
    ):
        raise ValueError("Official CocoChorales shard provenance or rights receipt is invalid")
    entries = record.get("tracks")
    if not isinstance(entries, list) or len(entries) != len(paired["cases"]):
        raise ValueError("Official shard proof case count differs")
    expected = {c["recording_id"]: c for c in paired["cases"]}
    seen = set()
    for row in entries:
        if not isinstance(row, dict):
            raise ValueError("Official shard proof track entry is invalid")
        track = row.get("track_id")
        if track not in expected or track in seen or row.get("split") != split:
            raise ValueError("Official shard proof contains an unexpected track/split")
        seen.add(track)
        original = expected[track]
        if (
            row.get("mix_wav_sha256") != original["audio"]["sha256"]
            or row.get("mix_midi_sha256") != original["reference_midi"]["sha256"]
            or not isinstance(row.get("instruments"), list)
            or len(row["instruments"]) != 4
        ):
            raise ValueError("Official shard WAV/MIDI digest or instrument evidence differs")


def score_cocochorales(
    pairs: dict, registry: dict, source_proof: dict, *,
    corpus_root: Path, predictions_root: Path,
) -> dict:
    if not isinstance(pairs, dict) or not isinstance(source_proof, dict):
        raise ValueError("CocoChorales paired manifest and source proof must be objects")
    records = pairs.get("cases")
    if not isinstance(records, list) or not records:
        raise ValueError("CocoChorales benchmark requires at least one pair")
    for case in records:
        if not isinstance(case, dict) or case.get("dataset_id") != "cocochorales":
            raise ValueError("Mixed datasets cannot enter CocoChorales-only evaluation")
        if official_split(case.get("recording_id")) != case.get("split"):
            raise ValueError("CocoChorales official split disagrees with recorded track")
    splits = {row["split"] for row in records}
    if len(splits) != 1:
        raise ValueError("One official source shard cannot span multiple splits")
    split = next(iter(splits))
    verified, benchmark_manifest = validate_pairs(pairs, registry, corpus_root=corpus_root)
    _source_receipt(source_proof, split=split, paired=pairs)
    root = predictions_root.expanduser().absolute()
    if root.is_relative_to(_ROOT) or root.is_symlink() or not root.is_dir():
        raise ValueError("Actual AMT predictions must be in a private directory outside git")
    version, engine, ids, prediction_source = load_tier2_prediction_provenance(root)
    case_ids = tuple(x["id"] for x in records)
    if (
        version != benchmark_manifest["corpus_version"] or ids != case_ids
        or engine.id not in {"mt3_infer", "mr-mt3", "muscriptor"}
    ):
        raise ValueError("Actual AMT prediction provenance differs from verified paired corpus")
    raw_times = prediction_source.get("case_inference_seconds")
    if raw_times is not None and (
        not isinstance(raw_times, dict) or set(raw_times) != set(case_ids)
        or any(type(n) not in {int, float} or not math.isfinite(n) or n < 0 for n in raw_times.values())
    ):
        raise ValueError("AMT inference time provenance is incomplete or invalid")

    measured = []
    for case in records:
        case_id = case["id"]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}", case_id):
            raise ValueError("Invalid CocoChorales case ID")
        pred_midi = root / f"{case_id}.mid"
        xml = root / f"{case_id}.musicxml"
        if any(p.is_symlink() or not p.is_file() for p in (pred_midi, xml)):
            measured.append({"case_id": case_id, "status": "failed",
                             "failure_reason": "prediction-artifact-missing-or-linked"})
            continue
        reference = corpus_root.expanduser().resolve() / case["reference_midi"]["locator"].removeprefix("private://")
        original = next(
            (item for item in source_proof["tracks"] if item["track_id"] == case["recording_id"]),
            None,
        )
        if original is None:
            raise ValueError("CocoChorales source proof case lacks instrument metadata")
        try:
            predicted_notes = midi_notes(pred_midi)
            reference_notes = midi_notes(reference)
            xml_summary = _musicxml_summary(xml)
            score_fidelity = _score_musicxml_fidelity(
                xml, pred_midi, reference,
                scratch_root=root, original_part_count=len(original["instruments"]),
            )
            onset = evaluate_midi_files(pred_midi, reference).as_dict()
            full = _score_matching(predicted_notes, reference_notes, require_instrument=False)
            instrument = _score_matching(predicted_notes, reference_notes, require_instrument=True)
            diagnostics = _midi_program_diagnostics(
                pred_midi, reference, predicted_notes, reference_notes,
                original_instruments=original["instruments"],
                musicxml_parts=xml_summary["parts"],
                strict_note_matches=instrument["matched"],
            )
        except (OSError, ValueError, EOFError, NotationBackendError):
            measured.append({"case_id": case_id, "status": "failed",
                             "failure_reason": "invalid-prediction-midi-or-musicxml"})
            continue
        measured.append({
            "case_id": case_id,
            "status": "scored" if predicted_notes else "failed",
            "failure_reason": None if predicted_notes else "zero-predicted-notes",
            "reference_note_count": len(reference_notes),
            "prediction_note_count": len(predicted_notes),
            "note_onset_f1": onset["note_f1"],
            "note_onset_offset_f1": full["f1"],
            "instrument_onset_offset_f1": instrument["f1"],
            "matched_onset_offset_notes": full["matched"],
            "matched_instrument_onset_offset_notes": instrument["matched"],
            "onset_mae_ms": onset["onset_mae_ms"],
            "offset_mae_ms": onset["offset_mae_ms"],
            "musicxml": xml_summary,
            "score_musicxml_reference_fidelity": score_fidelity,
            "score_part_count_absolute_error": abs(
                xml_summary["parts"] - len(original["instruments"])
            ),
            "instrument_part_diagnostics": diagnostics,
            "prediction_midi_sha256": _sha(pred_midi),
            "prediction_musicxml_sha256": _sha(xml),
            "model_inference_seconds": raw_times[case_id] if raw_times is not None else None,
            "peak_memory_bytes": None,
            "peak_memory_measured": False,
            "human_publish_time_seconds": None,
        })
    return {
        "schema_version": 1,
        "purpose": (
            "cocochorales-muscriptor-note-evaluation"
            if engine.id == "muscriptor" else "cocochorales-tiny-mt3-note-evaluation"
        ),
        "dataset_id": "cocochorales",
        "dataset_kind": "synthetic_satb_chorale_not_real_commercial_music",
        "split": split,
        "case_count": len(records),
        "paired_fingerprint": verified["recording_pairs_fingerprint"],
        "official_archive_sha256": source_proof["archive_sha256"],
        "source_evidence_sha256": hashlib.sha256(
            json.dumps(source_proof, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        (
            "muscriptor_prediction_evidence_sha256"
            if engine.id == "muscriptor" else "mt3_prediction_evidence_sha256"
        ): _sha(root / "tier2-prediction-provenance.json"),
        "engine": {
            "id": engine.id, "model_revision": engine.model_revision,
            "runtime_revision": engine.runtime_revision, "artifact_sha256": engine.artifact_sha256,
        },
        "cases": measured,
        "scored_case_count": sum(c["status"] == "scored" for c in measured),
        "model_inference_performed_by_this_command": False,
        "source_rights_independently_verified": False,
        "model_redistribution_approved": False,
        "product_publish_time_measured": False,
        "release_quality_approved": False,
        "source_media_published": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Score real AMT predictions on verified CocoChorales audio/MIDI pairs")
    parser.add_argument("--pairs", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--source-proof", type=Path, required=True)
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--predictions-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.expanduser().absolute()
    if output.is_relative_to(_ROOT) or output.exists() or output.is_symlink():
        parser.error("Scoring metadata must be new and remain outside git")
    try:
        report = score_cocochorales(
            json.loads(args.pairs.read_text(encoding="utf-8")),
            json.loads(args.registry.read_text(encoding="utf-8")),
            json.loads(args.source_proof.read_text(encoding="utf-8")),
            corpus_root=args.corpus_root, predictions_root=args.predictions_root,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as file:
            json.dump(report, file, ensure_ascii=False, sort_keys=True, indent=2)
            file.write("\n")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.exit(2, f"CocoChorales score refused: {exc}\n")
    print(json.dumps({"scored": report["scored_case_count"], "cases": report["case_count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

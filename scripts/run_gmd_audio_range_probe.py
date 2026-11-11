"""CPU-only real aligned GMD drum audio feasibility; no model default changes."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import time
import zipfile
import wave
from pathlib import Path

from scripts.drum_meter_probe import Hit, infer, parse_midi
from scripts.gmd_audio_range_probe import (
    ANALYZE_SECONDS,
    FULL_ZIP_URL,
    RangeNotSupported,
    RangeZipReader,
    decode_excerpt,
    detect_audio_roles,
    guarded_wav_member,
    match_times,
    select_audio_rows,
)
from scripts.run_drum_meter_probe import (
    ARCHIVE_SHA256,
    manifest,
    safe_member,
    sha,
)


def evaluate_audio(wav_zip, midi_zip, base, row):
    source_wav = base + row["audio_filename"]
    raw, member_crc, size = guarded_wav_member(wav_zip, source_wav)
    samples, duration, original_sample_rate = decode_excerpt(raw)
    raw_midi = safe_member(midi_zip, base + row["midi_filename"])
    hits, _signatures, _tempos = parse_midi(raw_midi)
    ref = [x for x in hits if x.time < duration and x.role in {"kick", "backbeat"}]
    predicted = detect_audio_roles(samples)
    all_rows = {}
    for role in ("kick", "backbeat"):
        all_rows[role] = match_times(
            [x.time for x in ref if x.role == role],
            [t for t, detected_role, _ in predicted if detected_role == role],
        )
    all_rows["all_roles_unlabeled"] = match_times(
        [x.time for x in ref],
        [t for t, _role, _w in predicted],
    )
    bpm = float(row["bpm"])
    meter = int(row["time_signature"].split("-")[0])
    raw_event = infer(tuple(ref), bpm=bpm, meter=meter)
    predicted_event = infer(tuple(
        Hit(float(t), role, max(1e-4, float(weight)))
        for t, role, weight in predicted
    ), bpm=bpm, meter=meter)
    return {
        "id": row["id"], "split": row["split"], "meter": row["time_signature"],
        "status": "scored", "beat_type": row["beat_type"],
        "bpm_supplied_as_diagnostic": bpm, "sample_rate": original_sample_rate,
        "audio_crc32": member_crc, "audio_bytes": size,
        "audio_sha256": hashlib.sha256(raw).hexdigest(),
        "midi_sha256": hashlib.sha256(raw_midi).hexdigest(),
        "excerpt_seconds": duration,
        "audio_onset_metrics": all_rows,
        "human_midi_role_count": len(ref), "raw_detector_role_count": len(predicted),
        "audio_infer_status": predicted_event["status"],
        "audio_phase_selected": predicted_event["phase"],
        "midi_event_phase_selected": raw_event["phase"],
        "audio_meter_is_supplied": True,
        "audio_bpm_is_supplied": True,
        "raw_audio_detection_not_validated_for_full_mix": True,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--midi-zip", required=True, type=Path)
    p.add_argument("--report", required=True, type=Path)
    args = p.parse_args()
    if args.report.exists() or args.report.is_symlink():
        p.error("output must be newly created")
    if args.midi_zip.is_symlink() or sha(args.midi_zip.read_bytes()) != ARCHIVE_SHA256:
        p.error("MIDI metadata ZIP does not match pinned publisher checksum")
    if os.getenv("HF_TOKEN") or os.getenv("HUGGING_FACE_HUB_TOKEN"):
        p.error("No credentials permitted")
    started = time.monotonic()
    report = {
        "status": "started", "original_midi_zip_sha256": ARCHIVE_SHA256,
        "full_source_zip_uri": FULL_ZIP_URL,
        "full_source_zip_sha256_verified": False,
        "source_revision": os.getenv("GITHUB_SHA"),
        "scope": "paired actual Roland drum-kit WAV excerpt and human MIDI reference",
        "real_audio_onset_detection": True, "full_band_mix": False,
        "source_role_labels_given_to_detector": False,
        "ground_truth_midi_supplied_to_phase_test_only": False,
        "tempo_and_meter_supplied_to_phase_test": True,
        "external_bpm_provider_called": False, "training": False,
        "model_default_changes": False,
        "python": platform.python_version(),
        "cases": [], "planned_ids": [], "quality_approved": False,
    }

    def save():
        args.report.parent.mkdir(parents=True, exist_ok=True)
        tmp = args.report.with_suffix(".tmp")
        tmp.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
        tmp.replace(args.report)

    save()
    with zipfile.ZipFile(args.midi_zip) as local:
        base, metadata = manifest(local)
        selection = select_audio_rows(metadata)
        report["planned_ids"] = [row["id"] for row in selection]
        save()
        if not selection:
            report["status"] = "blocked_no_short_eligible_recordings"
            save()
            return 0
        remote = None
        try:
            remote = RangeZipReader()
            with zipfile.ZipFile(remote) as wav_zip:
                source_metadata = wav_zip.read(base + "info.csv")
                original_metadata = safe_member(local, base + "info.csv")
                if hashlib.sha256(source_metadata).digest() != hashlib.sha256(
                    original_metadata
                ).digest():
                    raise ValueError("Full and MIDI-only archive metadata mismatch")
                report["info_csv_sha256"] = sha(source_metadata)
                report["full_archive_size"] = remote.size
                for row in selection:
                    try:
                        value = evaluate_audio(wav_zip, local, base, row)
                    except (KeyError, ValueError, OSError, EOFError, wave.Error) as exc:
                        value = {"id": row["id"], "status": "member_unavailable",
                                 "reason": type(exc).__name__}
                    report["cases"].append(value)
                    save()
        except (RangeNotSupported, OSError, ValueError) as exc:
            report["status"] = "blocked_range_or_metadata"
            report["reason"] = type(exc).__name__
        finally:
            if remote is not None:
                report["range_bytes_fetched"] = remote.bytes_fetched
                report["range_requests"] = remote.requests_made
                remote.close()
        if report["status"] == "started":
            report["status"] = ("complete" if len(report["cases"]) == len(selection)
                                else "incomplete")
    report["elapsed_seconds"] = time.monotonic() - started
    save()
    return 0 if report["status"] in ("complete", "blocked_range_or_metadata",
                                     "blocked_no_short_eligible_recordings") else 1


if __name__ == "__main__":
    raise SystemExit(main())

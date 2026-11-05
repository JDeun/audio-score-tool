"""Normalize legally supplied/manual chord-grid CSV to the SheetSage event contract.

This is NOT a Chordify API or automated export client. It neither logs in nor
scrapes competitors. The caller must verify the recording and annotation rights.
CSV schema: time_seconds,chord. Optional beat CSV: time_seconds,kind
where kind is "beat" or "downbeat".
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from pathlib import Path

_SHA = re.compile(r"^[a-fA-F0-9]{64}$")
_ROOT = r"(?P<root>[A-Ga-g][#b]?)"
_HARTE = re.compile(rf"^{_ROOT}:(?P<quality>maj|min|7|maj7|min7|dim|aug|sus2|sus4|hdim7)$")
_SIMPLE = re.compile(rf"^{_ROOT}(?P<suffix>m7|maj7|M7|m|7|dim|aug|sus2|sus4|m7b5)?$")
_QUALITY = {
    "": "maj", "m": "min", "7": "7", "maj7": "maj7", "M7": "maj7",
    "m7": "min7", "dim": "dim", "aug": "aug", "sus2": "sus2",
    "sus4": "sus4", "m7b5": "hdim7",
}


def normalize_chord(label: str) -> str:
    """Only normalize unambiguous chord qualities; never guess inversions."""
    label = label.strip()
    if label.upper() in {"N", "NC", "N.C.", "NO_CHORD"}:
        return "N"
    found = _HARTE.fullmatch(label)
    if found:
        tonic = found["root"][0].upper() + found["root"][1:]
        return tonic + ":" + found["quality"]
    found = _SIMPLE.fullmatch(label)
    if found:
        tonic = found["root"][0].upper() + found["root"][1:]
        return f"{tonic}:{_QUALITY[found['suffix'] or '']}"
    raise ValueError(f"unsupported or ambiguous chord label: {label!r}")


def _csv(path: Path, required: tuple[str, ...]) -> list[dict[str, str]]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"CSV source must be an existing regular file: {path.name}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        names = tuple(reader.fieldnames or ())
        if len(set(names)) != len(names) or not set(required) <= set(names):
            raise ValueError(f"CSV requires the columns {', '.join(required)}")
        rows = list(reader)
    if not rows:
        raise ValueError(f"CSV contains no rows: {path.name}")
    if any(None in item or any(val is None for val in item.values()) for item in rows):
        raise ValueError("CSV row has an unexpected column count")
    return rows


def _timestamp(text: str, *, duration: float, last: float, what: str) -> float:
    try:
        value = float(text)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{what} time_seconds must be numeric") from exc
    if not math.isfinite(value) or not 0 <= value < duration or value <= last:
        raise ValueError(f"{what} times must be strictly ordered within recording duration")
    return value


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(data)
    return digest.hexdigest()


def import_manual_chord_chart(
    chords_csv: Path,
    *,
    duration_seconds: float,
    recording_sha256: str,
    beats_csv: Path | None = None,
) -> dict:
    """Return only metadata and normalized events; no protected audio."""
    if isinstance(duration_seconds, bool) or not math.isfinite(duration_seconds) or duration_seconds <= 0:
        raise ValueError("duration_seconds must be finite and positive")
    if not _SHA.fullmatch(recording_sha256):
        raise ValueError("recording_sha256 requires a 64-hex digest supplied by the operator")
    chords = []
    previous = -1.0
    for item in _csv(chords_csv, ("time_seconds", "chord")):
        timestamp = _timestamp(
            item["time_seconds"], duration=duration_seconds, last=previous, what="chord",
        )
        chords.append({"time_seconds": timestamp, "label": normalize_chord(item["chord"])})
        previous = timestamp

    beats: list[dict[str, float]] = []
    downbeats: list[dict[str, float]] = []
    if beats_csv is not None:
        previous = -1.0
        for item in _csv(beats_csv, ("time_seconds", "kind")):
            at = _timestamp(
                item["time_seconds"], duration=duration_seconds, last=previous, what="beat",
            )
            kind = item["kind"].strip().lower()
            if kind not in {"beat", "downbeat"}:
                raise ValueError(f"unexpected beat kind: {kind}")
            beats.append({"time_seconds": at})
            if kind == "downbeat":
                downbeats.append({"time_seconds": at})
            previous = at

    return {
        "schema_version": 1,
        "recording_sha256": recording_sha256.lower(),
        "duration_seconds": duration_seconds,
        "source": {
            "type": "manual-user-provided-chord-grid",
            "provider_label": "Chordify/manual",
            "chords_csv_sha256": _hash(chords_csv),
            "beats_csv_sha256": _hash(beats_csv) if beats_csv else None,
            "recording_identity_verified": False,
            "third_party_rights_verified": False,
        },
        "chords": chords,
        "beats": beats,
        "downbeats": downbeats,
        "keys": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize user-supplied chord/beat CSV")
    parser.add_argument("chords_csv", type=Path)
    parser.add_argument("output_json", type=Path)
    parser.add_argument("--beats-csv", type=Path)
    parser.add_argument("--duration-seconds", type=float, required=True)
    parser.add_argument("--recording-sha256", required=True)
    args = parser.parse_args()
    output = import_manual_chord_chart(
        args.chords_csv,
        duration_seconds=args.duration_seconds,
        recording_sha256=args.recording_sha256,
        beats_csv=args.beats_csv,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(f"Normalized {len(output['chords'])} chords, {len(output['beats'])} beats")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

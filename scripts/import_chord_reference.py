"""Import authorized multi-annotator JAMS or interval LAB chord references.

Metadata-only conversion; no source audio, scraping, login or model inference.
Recording identity/rights remain explicit operator attestations, never
independently verified by this tool.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from pathlib import Path

SHA = re.compile(r"^[a-f0-9]{64}$")
DATASETS = frozenset({"casd", "isophonics", "billboard", "choco", "manual"})
PERMISSIVE = frozenset({"cc0-1.0", "cc-by-4.0", "apache-2.0", "mit"})
ROOT = Path(__file__).resolve().parents[1]


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _normalize(label: str) -> str:
    label = label.strip()
    if label.upper() in {"N", "N.C.", "NC", "NO_CHORD"}:
        return "N"
    if not label:
        raise ValueError("empty chord label")
    return label


def _clean_intervals(rows: list[dict], *, duration: float) -> list[dict]:
    """Require complete annotations; never infer unlabelled gaps as N."""
    if not rows:
        raise ValueError("chord annotation has no intervals")
    checked = []
    last_end = 0.0
    for row in sorted(rows, key=lambda x: x["start"]):
        start, end = row["start"], row["end"]
        if (isinstance(start, bool) or isinstance(end, bool)
                or not isinstance(start, (float, int)) or not isinstance(end, (float, int))
                or not math.isfinite(start) or not math.isfinite(end)
                or start < 0 or end <= start or end > duration + 1e-6):
            raise ValueError("invalid chord interval timing")
        if abs(start - last_end) > 1e-5:
            raise ValueError("chord reference has a gap or overlap; label N explicitly")
        checked.append({"start": float(start), "end": float(end),
                        "label": _normalize(row["label"])})
        last_end = float(end)
    if abs(last_end - duration) > 1e-5:
        raise ValueError("chord annotation must cover the full declared recording duration")
    return checked


def _jams(path: Path, *, duration: float) -> list[list[dict]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("annotations"), list):
        raise ValueError("invalid JAMS annotations")
    results = []
    for ann in data["annotations"]:
        if not isinstance(ann, dict) or ann.get("namespace") != "chord":
            continue
        rows = []
        for item in ann.get("data", []):
            if not isinstance(item, dict) or not isinstance(item.get("value"), str):
                raise ValueError("JAMS chord labels must be strings")
            at, length = item.get("time"), item.get("duration")
            if (isinstance(at, bool) or isinstance(length, bool)
                    or not isinstance(at, (int, float))
                    or not isinstance(length, (int, float))):
                raise ValueError("invalid JAMS chord timing")
            rows.append({"start": at, "end": at + length, "label": item["value"]})
        results.append(_clean_intervals(rows, duration=duration))
    if not results:
        raise ValueError("no chord namespace annotations in JAMS")
    return results


def _lab(path: Path, *, duration: float) -> list[list[dict]]:
    rows = []
    for index, original in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = original.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(maxsplit=2)
        if len(parts) != 3:
            raise ValueError(f"LAB line {index} requires start end chord label")
        try:
            start, end = float(parts[0]), float(parts[1])
        except ValueError as exc:
            raise ValueError(f"invalid LAB time at line {index}") from exc
        rows.append({"start": start, "end": end, "label": parts[2]})
    return [_clean_intervals(rows, duration=duration)]


def _beat_annotations(path: Path, *, duration: float) -> tuple[list[dict], list[dict]]:
    beat, downbeat = [], []
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if not {"time_seconds", "kind"} <= set(reader.fieldnames or []):
            raise ValueError("beat reference CSV requires time_seconds,kind")
        previous = -1.0
        for row in reader:
            try:
                at = float(row["time_seconds"])
            except (ValueError, TypeError) as exc:
                raise ValueError("beat time must be numeric") from exc
            if not math.isfinite(at) or not previous < at < duration or at < 0:
                raise ValueError("beat times must be ordered within duration")
            kind = row["kind"].strip().lower()
            if kind not in {"beat", "downbeat"}:
                raise ValueError("beat kind must be beat or downbeat")
            beat.append({"time_seconds": at})
            if kind == "downbeat":
                downbeat.append({"time_seconds": at})
            previous = at
    return beat, downbeat


def import_chord_reference(
    sources: list[Path],
    *,
    format: str,
    dataset: str,
    license: str,
    rights_reviewed: bool,
    recording_sha256: str,
    duration_seconds: float,
    beats_csv: Path | None = None,
    commercial: bool = False,
) -> dict:
    if format not in {"lab", "jams"} or dataset not in DATASETS:
        raise ValueError("unsupported chord reference format or dataset")
    if not rights_reviewed:
        raise ValueError("operator must review source rights before importing")
    if not isinstance(license, str) or any(
        word in license.lower() for word in ("unknown", "verify", "other", "per_source")
    ) or not license.strip():
        raise ValueError("source-specific license is unresolved")
    if dataset == "casd" and license.lower().replace("_", "-") != "cc-by-nc-sa-4.0":
        raise ValueError("CASD annotation rights must be recorded as CC-BY-NC-SA-4.0")
    if commercial and license.lower() not in PERMISSIVE:
        raise ValueError("non-permissive chord reference cannot enter commercial evaluation")
    if not isinstance(recording_sha256, str) or not SHA.fullmatch(recording_sha256):
        raise ValueError("recording_sha256 must be 64 lowercase hex characters")
    if (isinstance(duration_seconds, bool) or not isinstance(duration_seconds, (float, int))
            or not math.isfinite(duration_seconds) or duration_seconds <= 0):
        raise ValueError("duration_seconds must be finite and positive")
    if not sources or len(sources) > 16:
        raise ValueError("provide 1 to 16 authorized source files")
    annotators = []
    source_manifest = []
    for file in sources:
        if file.is_symlink() or not file.is_file():
            raise ValueError("chord reference must be an existing regular local file")
        groups = _jams(file, duration=duration_seconds) if format == "jams" else _lab(
            file, duration=duration_seconds,
        )
        source_manifest.append({"name": file.name, "sha256": _sha(file),
                                "annotators": len(groups)})
        for group in groups:
            annotators.append({"index": len(annotators), "intervals": group})
    beats, downbeats = (_beat_annotations(beats_csv, duration=duration_seconds)
                        if beats_csv else ([], []))
    return {
        "schema_version": 1,
        "dataset": dataset,
        "license": license,
        "recording_sha256": recording_sha256,
        "duration_seconds": float(duration_seconds),
        "annotators": annotators,
        "beats": beats,
        "downbeats": downbeats,
        "source_annotations": source_manifest,
        "beats_sha256": _sha(beats_csv) if beats_csv else None,
        "rights_reviewed_by_operator_only": True,
        "audio_recording_identity_independently_verified": False,
        "source_audio_included": False,
        "harte_label_semantics_independently_validated": False,
        "commercial_model_approved": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert local JAMS/LAB chord references")
    parser.add_argument("sources", nargs="+", type=Path)
    parser.add_argument("--format", choices=("jams", "lab"), required=True)
    parser.add_argument("--dataset", choices=sorted(DATASETS), required=True)
    parser.add_argument("--license", required=True)
    parser.add_argument("--rights-reviewed", action="store_true")
    parser.add_argument("--recording-sha256", required=True)
    parser.add_argument("--duration-seconds", type=float, required=True)
    parser.add_argument("--beats-csv", type=Path)
    parser.add_argument("--commercial", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    reference = import_chord_reference(
        args.sources, format=args.format, dataset=args.dataset,
        license=args.license, rights_reviewed=args.rights_reviewed,
        recording_sha256=args.recording_sha256, duration_seconds=args.duration_seconds,
        beats_csv=args.beats_csv, commercial=args.commercial,
    )
    target = args.output.expanduser().resolve()
    if target == ROOT or target.is_relative_to(ROOT):
        raise ValueError("source-dependent reference output must remain outside the repository")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(reference, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(json.dumps({"annotators": len(reference["annotators"]),
                      "source_audio_included": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

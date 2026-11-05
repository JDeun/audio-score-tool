"""Convert CASD multi-annotator JAMS chord labels to evaluation-ready intervals.

Annotations are CC BY-NC-SA 4.0; audio is NOT distributed with CASD.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def extract_casd(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    annotations = payload.get("annotations", [])
    annotators = []
    for index, ann in enumerate(annotations):
        if ann.get("namespace") != "chord":
            continue
        intervals = []
        for item in ann.get("data", []):
            time = item.get("time")
            duration = item.get("duration")
            value = item.get("value")
            if not isinstance(time, (int, float)) or not isinstance(duration, (int, float)):
                raise ValueError("Invalid JAMS chord timing")
            if time < 0 or duration <= 0 or not isinstance(value, str):
                raise ValueError("Invalid JAMS chord interval")
            intervals.append({"start": float(time), "end": float(time + duration), "label": value})
        intervals.sort(key=lambda e: e["start"])
        annotators.append({"index": index, "intervals": intervals})
    if not annotators:
        raise ValueError("No chord annotations in CASD JAMS")
    return {"schema_version": 1, "dataset": "CASD", "license": "CC BY-NC-SA 4.0",
            "source": path.name, "annotators": annotators,
            "audio_included": False}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = extract_casd(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"CASD annotators: {len(result['annotators'])}")


if __name__ == "__main__":
    main()

"""Validate Tier-2 benchmark dataset provenance before any downloads or evaluation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse


KNOWN_TASKS = {
    "chord", "chord_beat", "multi_instrument_amt", "piano_amt",
    "guitar_amt", "ensemble_amt", "classical_amt", "drum_amt",
    "bass_amt", "pop_amt",
}
REQUIRED = {"id", "task", "source", "audio_included", "license", "status"}


def validate_registry(payload: dict, *, commercial: bool = False) -> dict:
    if payload.get("schema_version") != 1 or not isinstance(payload.get("datasets"), list):
        raise ValueError("Expected schema_version=1 with datasets array")
    ids: set[str] = set()
    ready: list[str] = []
    blocked: dict[str, str] = {}
    for item in payload["datasets"]:
        if not isinstance(item, dict) or not REQUIRED.issubset(item):
            raise ValueError("Dataset entry missing required fields")
        identifier = item["id"]
        if not isinstance(identifier, str) or not identifier or identifier in ids:
            raise ValueError(f"Duplicate or invalid dataset ID: {identifier!r}")
        ids.add(identifier)
        if item["task"] not in KNOWN_TASKS:
            raise ValueError(f"Unknown task for {identifier}")
        url = urlparse(item["source"])
        if url.scheme != "https" or not url.netloc:
            raise ValueError(f"Invalid HTTPS source for {identifier}")
        if not isinstance(item["audio_included"], bool):
            raise ValueError(f"audio_included must be boolean: {identifier}")
        license_value = item["license"].upper()
        if "VERIFY" in license_value or "PER_SOURCE" in license_value:
            blocked[identifier] = "license_requires_verification"
        elif commercial and ("-NC" in license_value or "NONCOMMERCIAL" in license_value):
            blocked[identifier] = "noncommercial_license"
        elif not item["audio_included"]:
            blocked[identifier] = "no_audio_in_dataset"
        else:
            ready.append(identifier)
    return {"schema_version": 1, "commercial": commercial, "dataset_count": len(ids),
            "audio_candidates": ready, "blocked": blocked,
            "warning": "Candidate status does not confer audio rights; verify upstream terms and local files."}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("registry", type=Path)
    parser.add_argument("--commercial", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = validate_registry(json.loads(args.registry.read_text(encoding="utf-8")),
                               commercial=args.commercial)
    output = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()

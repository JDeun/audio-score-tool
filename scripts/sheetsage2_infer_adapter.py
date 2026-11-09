"""Run the genuine SheetSage2 backend via the pinned OpenMIRLab facade."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path


def normalize_result(result: object) -> dict:
    """Convert typed shared SheetSage2 events to AudioScoreTool protocol."""
    statuses = getattr(result, "statuses", {})
    for field in ("chords", "beats"):
        status = statuses.get(field) if isinstance(statuses, dict) else None
        if status is not None and getattr(status, "state", "ok") != "ok":
            raise ValueError(f"SheetSage2 {field} status: {status}")
    chords = getattr(result, "chords", None)
    beats = getattr(result, "beats", None)
    if chords is None or beats is None:
        raise ValueError("SheetSage2 returned no chords or beat track")
    payload = {
        "schema_version": 1,
        "provider": "openmirlab-sheetsage-infer",
        "model": "sheetsage2",
        "chords": [{"time_seconds": float(x.start), "label": x.label} for x in chords],
        "beats": [{"time_seconds": float(x.time)} for x in beats],
        "downbeats": [{"time_seconds": float(x.time)} for x in beats if x.is_downbeat],
        "keys": [{"time_seconds": float(x.start), "label": x.label}
                 for x in (getattr(result, "keys", None) or [])],
    }
    meters = getattr(result, "meters", None) or []
    if meters:
        first = meters[0]
        payload["meter"] = f"{first.numerator}/{first.denominator}"
    for name in ("chords", "beats", "downbeats", "keys"):
        events = payload[name]
        events.sort(key=lambda x: x["time_seconds"])
        for event in events:
            if not math.isfinite(event["time_seconds"]) or event["time_seconds"] < 0:
                raise ValueError(f"Invalid {name} timestamp")
        payload[name] = [
            event for i, event in enumerate(events)
            if i == 0 or event["time_seconds"] > events[i - 1]["time_seconds"]
        ]
    return payload


def load_native_model(model_dir: Path, base_dir: Path):
    from scripts.fetch_pinned_sheetsage2 import PINS, verify_files

    if os.environ.get("AST_USAGE_MODE", "research").lower() == "commercial":
        raise ValueError("SheetSage2 public weights are noncommercial")
    for kind, root in (("model", model_dir), ("mert", base_dir)):
        verify_files(root, PINS[kind]["files"])
    import torch
    from transformers import AutoModel

    return AutoModel.from_pretrained(
        str(model_dir), base_model_path=str(base_dir), trust_remote_code=True,
        local_files_only=True, torch_dtype=torch.float32,
    ).eval()


def normalize_native_result(result: dict) -> dict:
    """Use official key-spelled LAB exports, retaining meter changes and inversions."""
    from scripts.fetch_pinned_sheetsage2 import PINS

    labs = result.get("labs")
    if not isinstance(labs, dict):
        raise ValueError("Official SheetSage2 result has no LAB exports")

    def rows(name, size):
        source = labs.get(name, "")
        if not isinstance(source, str) or len(source) > 16 * 1024 * 1024:
            raise ValueError(f"Invalid SheetSage2 {name} LAB")
        output = [line.split("\t") for line in source.splitlines() if line.strip()]
        if any(len(row) != size for row in output):
            raise ValueError(f"Invalid SheetSage2 {name} columns")
        return output

    payload = {"schema_version": 1, "provider": "official-huggingface-sheetsage2",
               "model": "sheetsage2", "model_revision": PINS["model"]["revision"],
               "base_model_revision": PINS["mert"]["revision"],
               "chords": [], "keys": [], "beats": [], "downbeats": [], "meters": []}
    for name, target in (("chord", "chords"), ("key", "keys")):
        for start, end, label in rows(name, 3):
            start, end = float(start), float(end)
            if not math.isfinite(end) or end <= start or not label.strip():
                raise ValueError(f"Invalid SheetSage2 {name} interval")
            payload[target].append({"time_seconds": start, "end_seconds": end, "label": label})
    previous_meter = None
    for at, beat, numerator, denominator in rows("beat", 4):
        at, beat, numerator, denominator = float(at), int(beat), int(numerator), int(denominator)
        if not 1 <= beat <= numerator or denominator <= 0 or denominator & (denominator - 1):
            raise ValueError("Invalid SheetSage2 beat/meter")
        event = {"time_seconds": at, "beat": beat,
                 "numerator": numerator, "denominator": denominator}
        payload["beats"].append(event)
        if beat == 1:
            payload["downbeats"].append(dict(event))
        if (numerator, denominator) != previous_meter:
            payload["meters"].append({"time_seconds": at, "numerator": numerator, "denominator": denominator})
            previous_meter = (numerator, denominator)
    if payload["meters"]:
        first = payload["meters"][0]
        payload["meter"] = f"{first['numerator']}/{first['denominator']}"
    for name in ("chords", "keys", "beats", "downbeats"):
        last = -1.0
        for event in payload[name]:
            at = event["time_seconds"]
            if not math.isfinite(at) or at < 0 or at <= last:
                raise ValueError(f"Invalid or nonchronological SheetSage2 {name} time")
            last = at
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--base-model-dir", type=Path)
    args = parser.parse_args()
    if os.environ.get("AST_USAGE_MODE", "research").lower() == "commercial":
        parser.error("SheetSage2 public weights are noncommercial")
    if args.model_dir:
        if args.base_model_dir is None:
            parser.error("--model-dir requires --base-model-dir")
        import soundfile as sf
        import torch

        torch.set_num_threads(4)
        model = load_native_model(args.model_dir, args.base_model_dir).to(args.device)
        audio, rate = sf.read(args.audio, dtype="float32", always_2d=True)
        result = model.transcribe(audio.T, sampling_rate=rate,
                                  output_dir=args.output.parent / "native", dtype="fp32")
        payload = normalize_native_result(result)
    else:
        from sheetsage import SheetSageTranscriber

        with SheetSageTranscriber("sheetsage2", device=args.device) as model:
            result = model.infer(str(args.audio))
        payload = normalize_result(result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: len(payload[k]) for k in ("chords", "beats", "keys")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

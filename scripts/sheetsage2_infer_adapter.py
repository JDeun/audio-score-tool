"""Run the genuine SheetSage2 backend via the pinned OpenMIRLab facade."""
from __future__ import annotations

import argparse
import json
import math
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()
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

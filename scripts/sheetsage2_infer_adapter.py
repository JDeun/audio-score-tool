"""Official pinned SheetSage2, plus the existing OpenMIRLab protocol adapter."""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
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
               "checkpoint_sha256": PINS["model"]["files"]["model.safetensors"],
               "base_model_revision": PINS["mert"]["revision"],
               "base_checkpoint_sha256": PINS["mert"]["files"]["model.safetensors"],
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


def rebuild_vocal_notation(model_dir: Path, context: Path, vocal_midi: Path, output: Path, beat_track: Path | None = None) -> dict:
    """Use pinned notation code without loading MERT or running another model."""
    import shutil

    import pretty_midi

    from audio_score_tool.lead_notation import vocal_grid
    from audio_score_tool.metrics import midi_notes
    from scripts.fetch_pinned_sheetsage2 import PINS, verify_files

    verify_files(model_dir, PINS["model"]["files"])
    sys.path.insert(0, str(model_dir.parent))
    from model.midi_sheetsage2 import build_playback
    from model.notation_sheetsage2 import build_rebuilt_abc_score_from_data, score_to_abc

    rows = {}
    for name in ("beats", "chords", "keys", "structures"):
        path = context / "notation" / f"song_{name}.txt"
        if (path.is_symlink() or path.parent.is_symlink() or not path.is_file()
                or path.stat().st_size > 16 * 1024 * 1024):
            raise ValueError("Missing or unsafe fixed-recipe notation context")
        rows[name] = [line.split("\t") for line in path.read_text().splitlines() if line.strip()]
    source = context / "playback.json"
    if source.is_symlink() or not source.is_file() or source.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("Missing or unsafe fixed-recipe source clock")
    duration = json.loads(source.read_text())["duration"]
    if type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0:
        raise ValueError("Invalid fixed-recipe source duration")
    clock_info = None
    if beat_track is not None:
        import numpy as np
        from model import notation_sheetsage2 as notation

        from audio_score_tool.beat_clock import beat_rows

        with np.load(beat_track, allow_pickle=False) as observed:
            beat_data, down_data = observed["beats"], observed["downbeats"]
        mapped_beats, clock_info = beat_rows(beat_data, down_data, duration, rows["beats"])
        placeholder_chords = [["0", mapped_beats[-1][0], "N"]]
        placeholder_keys = [["0", mapped_beats[-1][0], rows["keys"][0][2]]]
        score = build_rebuilt_abc_score_from_data(pretty_midi.PrettyMIDI(), mapped_beats,
                                                 placeholder_chords, placeholder_keys, rows["structures"])
    else:
        score = build_rebuilt_abc_score_from_data(pretty_midi.PrettyMIDI(), rows["beats"],
                                                 rows["chords"], rows["keys"], rows["structures"])
    clipped = score.subbeat_times[-1] > duration
    if clipped:
        start, end = score.beats[-2].time, score.beats[-1].time
        if not start < duration:
            raise ValueError("Source duration does not cover the final notated beat")
        tail = score.subbeat_times >= start
        score.subbeat_times[tail] = start + (score.subbeat_times[tail] - start) * (duration - start) / (end - start)
    if beat_track is not None:
        chords = notation._parse_chords(notation._row_entries(rows["chords"], "chords"), "chords")
        keys = notation._parse_keys(notation._row_entries(rows["keys"], "keys"), "keys")
        structures = notation._parse_structures(notation._row_entries(rows["structures"], "structures"), "structures")
        score.chord_arr = notation._fill_intervals(chords, score.subbeat_times, default="N", dtype="<U64")
        score.key_arr = notation._fill_intervals(keys, score.subbeat_times, default=keys[0][2], dtype="<U16")
        score.structure_events = notation._structure_events(structures, score.subbeat_times)
    cells, report = vocal_grid(midi_notes(vocal_midi), score.subbeat_times)
    score.voice_arrs["Vocal"] = cells
    report["grid_audio_seconds"] = score.subbeat_times.tolist()
    report["terminal_beat_clipped"] = bool(clipped)
    if clock_info is not None:
        report["beat_clock"] = clock_info
    melody = pretty_midi.PrettyMIDI(str(vocal_midi))
    for instrument in melody.instruments:
        instrument.name = "Vocal"
    playback, midis = build_playback(melody, rows["chords"], score, duration)
    text = score_to_abc(score)
    output.mkdir(parents=True, exist_ok=False)
    (output / "score.abc").write_text(text)
    (output / "playback.json").write_text(json.dumps(playback, indent=2) + "\n")
    shutil.copy2(vocal_midi, output / "melody_vocal.mid")
    for name, data in midis.items():
        (output / f"{name}.mid").write_bytes(data)
    (output / "notation").mkdir()
    for name in rows:
        shutil.copy2(context / "notation" / f"song_{name}.txt", output / "notation")
    if beat_track is not None:
        (output / "notation/song_beats.txt").write_text("".join("\t".join(row) + "\n" for row in mapped_beats))
    report["production_quality_approved"] = False
    return report


def main() -> int:
    if not __package__:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--base-model-dir", type=Path)
    parser.add_argument("--vocal-midi", type=Path)
    parser.add_argument("--context-dir", type=Path)
    parser.add_argument("--beat-track", type=Path)
    args = parser.parse_args()
    if os.environ.get("AST_USAGE_MODE", "research").lower() == "commercial":
        parser.error("SheetSage2 public weights are noncommercial")
    if os.environ.get("AST_FIXED_LEAD_V1") == "1":
        from audio_score_tool.fixed_lead_recipe import STRUCTURE_RUNTIME, require_runtime

        require_runtime(STRUCTURE_RUNTIME)
    if args.vocal_midi or args.context_dir:
        if not (args.vocal_midi and args.context_dir and args.model_dir):
            parser.error("Vocal notation requires --vocal-midi, --context-dir and --model-dir")
        report = rebuild_vocal_notation(args.model_dir, args.context_dir, args.vocal_midi,
                                       args.output.parent / "native", args.beat_track)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
        return 0
    if args.model_dir:
        if args.base_model_dir is None:
            parser.error("--model-dir requires --base-model-dir")
        import soundfile as sf
        import torch

        torch.set_num_threads(4)
        torch.manual_seed(0)
        model = load_native_model(args.model_dir, args.base_model_dir).to(args.device)
        audio, rate = sf.read(args.audio, dtype="float32", always_2d=True)
        result = model.transcribe(audio.T, sampling_rate=rate,
                                  output_dir=args.output.parent / "native", dtype="fp32", preset="default")
        payload = normalize_native_result(result)
        import hashlib
        import platform
        from importlib.metadata import version

        payload["runtime"] = {
            "python": platform.python_version(), "platform": platform.platform(),
            "packages": {name: version(name) for name in ("torch", "transformers", "numpy", "soundfile")},
            "adapter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "device": args.device, "dtype": "fp32", "preset": "default", "seed": 0,
            "threads": 4, "sampling_rate": rate,
        }
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

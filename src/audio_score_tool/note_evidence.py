"""Conservative links from retained vocal events to written MusicXML notes."""
from __future__ import annotations

import hashlib
import json
import math
import tempfile
import wave
import xml.etree.ElementTree as ET
from pathlib import Path

from music21 import converter, harmony, tempo

from .lead_notation import vocal_grid
from .metrics import midi_notes
from .model_evidence import _owned, preserve_model_evidence
from .score_timing import score_audio_origin, score_time_clocks


def score_hash(xml: str) -> str:
    return hashlib.sha256(xml.encode("utf-8")).hexdigest()


def clock_signature(xml: str) -> tuple:
    score = converter.parseData(xml, format="musicxml")
    marks = []
    for mark in score.recurse().getElementsByClass(tempo.MetronomeMark):
        bpm = mark.getQuarterBPM()
        if bpm is not None:
            marks.append((float(mark.getOffsetInHierarchy(score)), float(bpm)))
    if not marks or min(position for position, _ in marks) != 0:
        raise ValueError("unsupported_clock")
    score_time_clocks(score)
    return score_audio_origin(score), tuple(sorted(set(marks)))


def written_notes(xml: str) -> list[dict]:
    root = ET.fromstring(xml)
    ns = root.tag.split("}")[0] + "}" if root.tag.startswith("{") else ""
    if root.tag != f"{ns}score-partwise":
        raise ValueError("unsupported_score")
    rows = []
    for p, part in enumerate(root.findall(f"{ns}part")):
        position = 0.0
        divisions = None
        for m, measure in enumerate(part.findall(f"{ns}measure")):
            if measure.find(f"{ns}backup") is not None or measure.find(f"{ns}forward") is not None:
                raise ValueError("unsupported_polyphony")
            n = 0
            for node in measure:
                if node.tag == f"{ns}attributes":
                    value = node.findtext(f"{ns}divisions")
                    if value is not None:
                        divisions = int(value)
                    if divisions is not None and divisions <= 0:
                        raise ValueError("invalid_divisions")
                if node.tag != f"{ns}note":
                    continue
                if divisions is None or node.find(f"{ns}chord") is not None or node.find(f"{ns}grace") is not None:
                    raise ValueError("unsupported_note")
                duration = int(node.findtext(f"{ns}duration", "0")) / divisions
                if duration <= 0:
                    raise ValueError("invalid_duration")
                pitch_node = node.find(f"{ns}pitch")
                pitch = None
                spelling = None
                if pitch_node is not None:
                    step = pitch_node.findtext(f"{ns}step")
                    alter = int(pitch_node.findtext(f"{ns}alter", "0"))
                    octave = int(pitch_node.findtext(f"{ns}octave", "-1"))
                    if step not in "CDEFGAB" or alter not in range(-2, 3) or not 0 <= octave <= 9:
                        raise ValueError("invalid_pitch")
                    pitch = (octave + 1) * 12 + {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}[step] + alter
                    if not 0 <= pitch <= 127:
                        raise ValueError("invalid_pitch")
                    spelling = [step, alter, octave]
                elif node.find(f"{ns}rest") is None:
                    raise ValueError("unsupported_note")
                ties = sorted(t.get("type") for t in node.findall(f"{ns}tie"))
                if any(t not in ("start", "stop") for t in ties) or len(set(ties)) != len(ties):
                    raise ValueError("invalid_tie")
                rows.append({"note_id": f"p{p}-m{m}-n{n}", "pitch": pitch, "spelling": spelling,
                             "start": position, "end": position + duration, "ties": ties,
                             "voice": node.findtext(f"{ns}voice"), "staff": node.findtext(f"{ns}staff")})
                position += duration
                n += 1
    return rows


def _chains(rows: list[dict]) -> list[list[dict]]:
    chains = []
    active = None
    for row in rows:
        if row["pitch"] is None:
            if active:
                raise ValueError("broken_tie")
            continue
        if "stop" in row["ties"]:
            if (not active or active[-1]["pitch"] != row["pitch"]
                    or active[-1]["note_id"].split("-")[0] != row["note_id"].split("-")[0]
                    or active[-1]["voice"] != row["voice"] or active[-1]["staff"] != row["staff"]
                    or abs(active[-1]["end"] - row["start"]) > 1e-8):
                raise ValueError("broken_tie")
            active.append(row)
        else:
            if active:
                raise ValueError("broken_tie")
            active = [row]
        if "start" not in row["ties"]:
            chains.append(active)
            active = None
    if active:
        raise ValueError("broken_tie")
    return chains


def _validate_score_positions(score, rows: list[dict]) -> None:
    from music21 import note, stream

    found = []
    for p, part in enumerate(score.parts):
        for m, measure in enumerate(part.getElementsByClass(stream.Measure)):
            events = [event for event in measure.recurse().notesAndRests if not isinstance(event, harmony.Harmony)]
            for n, event in enumerate(events):
                if not isinstance(event, (note.Note, note.Rest)):
                    raise ValueError("unsupported_note")
                found.append((f"p{p}-m{m}-n{n}", float(event.getOffsetInHierarchy(part)),
                              float(event.quarterLength), event.pitch.midi if isinstance(event, note.Note) else None))
    if len(found) != len(rows):
        raise ValueError("unsupported_positions")
    for (locator, start, duration, pitch), row in zip(found, rows):
        if (locator != row["note_id"] or pitch != row["pitch"] or abs(start - row["start"]) > 1e-8
                or abs(duration - (row["end"] - row["start"])) > 1e-8):
            raise ValueError("unsupported_positions")


def _source_audio_duration(asset_root: Path, song_id: str, manifest: dict, recipe: dict,
                           verified, grid: list) -> float | None:
    try:
        song_root = asset_root / song_id
        candidates = list(song_root.glob("original-audio.*"))
        if len(candidates) != 1:
            return None
        audio = candidates[0]
        if (audio.suffix.lower() != ".wav" or not _owned(audio, asset_root) or not audio.is_file()
                or audio.stat().st_size > 1024 * 1024 * 1024):
            return None
        with audio.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        if (manifest.get("source_audio_sha256") != digest or recipe.get("source_audio_sha256") != digest
                or recipe.get("model_audio_sha256") != digest or recipe.get("model_audio_normalized") is not False):
            return None
        context = json.loads(verified("context/music_structure.json"))
        playback = json.loads(verified("native/playback.json"))
        origin = context.get("media_start_seconds")
        if context.get("trimmed") is not False or type(origin) not in (int, float) or origin != 0:
            return None
        with wave.open(str(audio), "rb") as wav:
            if wav.getcomptype() != "NONE" or wav.getframerate() <= 0:
                return None
            frames, rate = wav.getnframes(), wav.getframerate()
            frame_bytes = wav.getnchannels() * wav.getsampwidth()
            size = 0
            while chunk := wav.readframes(65536):
                size += len(chunk)
            if not frame_bytes or size != frames * frame_bytes:
                return None
        with audio.open("rb") as handle:
            if not _owned(audio, asset_root) or hashlib.file_digest(handle, "sha256").hexdigest() != digest:
                return None
        duration = frames / rate
        played = playback.get("duration")
        if (type(played) not in (int, float) or not math.isfinite(played) or duration <= 0
                or abs(played - duration) > .002 or abs(grid[-1] - played) > .002):
            return None
        if recipe.get("recipe_version", 1) == 3:
            beat = json.loads(verified("beat.runtime.json"))
            beat_hash = hashlib.sha256(verified("beat.npz")).hexdigest()
            clock = recipe.get("beat_clock") or {}
            if (beat.get("source_sha256") != digest or beat.get("prediction_sha256") != beat_hash
                    or beat.get("source_frames") != frames or beat.get("source_sample_rate") != rate
                    or clock.get("source_sha256") != digest or clock.get("prediction_sha256") != beat_hash):
                return None
        return duration
    except Exception:
        return None


def baseline(asset_root: Path, song_id: str) -> tuple[dict, list[dict], tuple, str]:
    """Return all proven links, or raise rather than guess a mapping."""
    root = asset_root / song_id / "model-evidence"
    if not root.exists():
        raise ValueError("model_evidence_missing")
    receipt = root / "manifest.json"
    if not _owned(receipt, asset_root) or not receipt.is_file() or receipt.stat().st_size > 1024 * 1024:
        raise ValueError("incomplete_evidence")
    preliminary = json.loads(receipt.read_text())
    if not isinstance(preliminary, dict) or not isinstance(preliminary.get("files"), list) or len(preliminary["files"]) > 256:
        raise ValueError("incomplete_evidence")
    manifest = preserve_model_evidence({"job_id": song_id}, jobs_root=asset_root, asset_root=asset_root)
    if manifest != preliminary:
        raise ValueError("incomplete_evidence")
    if manifest.get("selection", {}).get("transcription_engine") != "vocal_lead_v1":
        raise ValueError("not_fixed_vocal_recipe")
    entries = manifest["files"]
    names = [entry["path"] for entry in entries]
    required = {"score.musicxml", "vocal/selected.mid", "interpretation.json", "recipe.json"}
    if len(names) != len(set(names)) or not required.issubset(names):
        raise ValueError("incomplete_evidence")
    def verified(name: str) -> bytes:
        entry = next(entry for entry in entries if entry["path"] == name)
        path = root / name
        if not _owned(path, root) or path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("incomplete_evidence")
        data = path.read_bytes()
        if len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise ValueError("incomplete_evidence")
        return data

    recipe = json.loads(verified("recipe.json"))
    if (recipe.get("engine") != "vocal_lead_v1" or type(recipe.get("recipe_version", 1)) is not int
            or recipe.get("recipe_version", 1) not in (1, 2, 3)
            or recipe.get("status") != "completed"):
        raise ValueError("unsupported_recipe")
    interpretation = json.loads(verified("interpretation.json"))
    if interpretation.get("algorithm") != "dominant_overlap_on_audio_sixteenth_grid_v1":
        raise ValueError("unsupported_interpretation")
    with tempfile.TemporaryDirectory(prefix="ast-evidence-") as folder:
        midi_path = Path(folder) / "selected.mid"
        midi_path.write_bytes(verified("vocal/selected.mid"))
        notes = midi_notes(midi_path)
    grid = interpretation["grid_audio_seconds"]
    indices = interpretation["source_note_indices"]
    if (not isinstance(grid, list) or not isinstance(indices, list) or len(grid) != len(indices) + 1
            or len(grid) < 2 or len(grid) > 65_537 or len(notes) > 8192
            or any(type(t) not in (int, float) or not math.isfinite(t) or t < 0 for t in grid)
            or any(b <= a for a, b in zip(grid, grid[1:]))
            or any(type(i) is not int or i < -1 or i >= len(notes) for i in indices)
            or any(n.is_drum or n.onset < 0 or n.offset <= n.onset for n in notes)):
        raise ValueError("invalid_interpretation")
    _, regenerated = vocal_grid(notes, grid)
    if regenerated["source_note_indices"] != indices:
        raise ValueError("invalid_interpretation")
    audio_duration = _source_audio_duration(asset_root, song_id, manifest, recipe, verified, grid)
    original = verified("score.musicxml").decode("utf-8")
    rows = written_notes(original)
    # shortcut: bound matching to 8192 written notes; index it before expanding this limit.
    if len(rows) > 8192:
        raise ValueError("evidence_limit_exceeded")
    clock = clock_signature(original)
    chains = _chains(rows)
    score = converter.parseData(original, format="musicxml")
    _validate_score_positions(score, rows)
    to_seconds, _ = score_time_clocks(score)
    runs = []
    for cell, index in enumerate(indices):
        if index < 0:
            continue
        if cell and indices[cell - 1] == index:
            runs[-1][2] = grid[cell + 1]
        else:
            runs.append([index, grid[cell], grid[cell + 1]])
    if len({run[0] for run in runs}) != len(runs):
        raise ValueError("repeated_source_run")
    midi_sha = next(entry["sha256"] for entry in entries if entry["path"] == "vocal/selected.mid")
    hashes = {entry["path"]: entry["sha256"] for entry in entries}
    links = {}
    used = set()
    for index, start, end in runs:
        event = notes[index]
        matches = [chain for chain in chains if chain[0]["pitch"] == event.pitch
                   and abs(to_seconds(chain[0]["start"]) - start) <= .002
                   and abs(to_seconds(chain[-1]["end"]) - end) <= .002]
        if len(matches) != 1:
            raise ValueError("ambiguous_mapping" if len(matches) > 1 else "mapping_not_found")
        chain = matches[0]
        if chain[0]["note_id"] in used:
            raise ValueError("ambiguous_mapping")
        used.add(chain[0]["note_id"])
        source_id = f"selected-midi-v1:{midi_sha}:{index}"
        link = {"source_id": source_id, "source_index": index,
                "selected_midi_sha256": midi_sha,
                "performed_seconds": {"start": event.onset, "end": event.offset},
                "grid_seconds": {"start": start, "end": end},
                "written_quarters": {"start": chain[0]["start"], "end": chain[-1]["end"]},
                "locators": [row["note_id"] for row in chain],
                "provenance": {"engine": "vocal_lead_v1", "recipe_version": recipe.get("recipe_version", 1),
                               "interpretation_algorithm": interpretation["algorithm"],
                               "interpretation_sha256": hashes["interpretation.json"],
                               "original_score_sha256": hashes["score.musicxml"],
                               "source_audio_sha256": manifest.get("source_audio_sha256")},
                "source_audio_seek_seconds": start if audio_duration is not None and start <= audio_duration else None,
                "source_audio_seek_basis": "interpreted_grid" if audio_duration is not None else None}
        for row in chain:
            links[row["note_id"]] = link
    fingerprint = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    return links, rows, clock, fingerprint


def baseline_fingerprint(links: dict, rows: list, clock: tuple, manifest_hash: str) -> str:
    stable_links = {locator: {key: value for key, value in link.items()
                             if key not in {"source_audio_seek_seconds", "source_audio_seek_basis"}}
                    for locator, link in links.items()}
    return hashlib.sha256(json.dumps([stable_links, rows, clock, manifest_hash], sort_keys=True).encode()).hexdigest()

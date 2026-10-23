"""Deterministic note-level consensus ensemble for two AMT MIDI predictions."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pretty_midi


def ensemble(first: Path, second: Path, output: Path, *,
             onset_tolerance: float = 0.09, min_overlap: float = 0.35) -> dict:
    """Retain notes agreed upon by both models, avoiding duplicate note unions.

    Matching is pitch- and instrument-program-aware. This conservative baseline
    prioritizes precision; recall may decrease. Drum tracks match drum tracks.
    """
    if onset_tolerance <= 0 or not 0 < min_overlap <= 1:
        raise ValueError("Invalid consensus thresholds")
    a, b = pretty_midi.PrettyMIDI(str(first)), pretty_midi.PrettyMIDI(str(second))
    result = pretty_midi.PrettyMIDI(initial_tempo=120)
    matches = 0
    count_a = sum(len(ins.notes) for ins in a.instruments)
    count_b = sum(len(ins.notes) for ins in b.instruments)
    for source in a.instruments:
        candidate_instruments = [
            other for other in b.instruments
            if other.is_drum == source.is_drum
            and (source.is_drum or other.program == source.program)
        ]
        candidates = [(other, note) for other in candidate_instruments for note in other.notes]
        used: set[int] = set()
        target = pretty_midi.Instrument(source.program, is_drum=source.is_drum, name=source.name)
        for note in sorted(source.notes, key=lambda n: (n.start, n.pitch)):
            best = None
            best_score = float("-inf")
            for index, (_, other) in enumerate(candidates):
                if index in used or other.pitch != note.pitch:
                    continue
                if abs(note.start - other.start) > onset_tolerance:
                    continue
                intersection = max(0.0, min(note.end, other.end) - max(note.start, other.start))
                duration = max(note.end - note.start, other.end - other.start)
                overlap = intersection / duration if duration > 0 else 0.0
                if overlap < min_overlap:
                    continue
                score = overlap - abs(note.start - other.start)
                if score > best_score:
                    best, best_score = index, score
            if best is None:
                continue
            used.add(best)
            other = candidates[best][1]
            start = (note.start + other.start) / 2
            end = (note.end + other.end) / 2
            if end <= start:
                continue
            target.notes.append(pretty_midi.Note(
                velocity=round((note.velocity + other.velocity) / 2),
                pitch=note.pitch, start=start, end=end,
            ))
            matches += 1
        if target.notes:
            result.instruments.append(target)
    output.parent.mkdir(parents=True, exist_ok=True)
    result.write(str(output))
    return {"method": "pitch_program_onset_overlap_consensus",
            "source_notes": [count_a, count_b], "matched_notes": matches,
            "onset_tolerance_seconds": onset_tolerance, "min_overlap": min_overlap}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(ensemble(args.first, args.second, args.output)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

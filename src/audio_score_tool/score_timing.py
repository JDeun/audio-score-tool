"""Convert between an existing score's quarter positions and elapsed seconds."""
from __future__ import annotations

import bisect
import math

AUDIO_ORIGIN_FIELD = "audio-score-tool:audio-origin-seconds"


def score_audio_origin(score) -> float:
    values = score.metadata.getCustom(AUDIO_ORIGIN_FIELD) if score.metadata else ()
    if not values:
        return 0.0
    if len(values) != 1:
        raise ValueError("Score contains conflicting audio origins")
    origin = float(str(values[0]))
    if not math.isfinite(origin) or origin < 0:
        raise ValueError("Score audio origin must be finite and nonnegative")
    return origin


def apply_midi_audio_origin(path, origin: float) -> None:
    """Delay the generated performance while retaining an initial tempo at tick 0."""
    if not math.isfinite(origin) or origin < 0:
        raise ValueError("MIDI audio origin must be finite and nonnegative")
    if not origin:
        return
    import io

    import mido

    midi = mido.MidiFile(path)
    initial = []
    for track in midi.tracks:
        absolute = 0
        for message in track:
            absolute += message.time
            if absolute > 0:
                break
            if message.type == "set_tempo":
                initial.append(message.tempo)
    if len(set(initial)) > 1:
        raise ValueError("MIDI contains conflicting initial tempos")
    tempo = initial[0] if initial else 500000
    ticks = round(mido.second2tick(origin, midi.ticks_per_beat, tempo))
    for track in midi.tracks:
        if track:
            track[0].time += ticks
    midi.tracks[0].insert(0, mido.MetaMessage("set_tempo", tempo=tempo, time=0))
    output = io.BytesIO()
    midi.save(file=output)
    path.write_bytes(output.getvalue())


def score_time_clocks(score, *, fallback_bpm: float = 120.0):
    from music21 import tempo

    if not math.isfinite(fallback_bpm) or fallback_bpm <= 0:
        raise ValueError("Score fallback tempo must be positive and finite")
    changes = {0.0: fallback_bpm}
    explicit = {}
    for mark in score.recurse().getElementsByClass(tempo.MetronomeMark):
        bpm = mark.getQuarterBPM()
        if bpm is None:
            continue  # A text-only tempo direction does not establish a numeric rate.
        position = float(mark.getOffsetInHierarchy(score))
        if not math.isfinite(bpm) or bpm <= 0 or not math.isfinite(position) or position < 0:
            raise ValueError("Score contains an invalid tempo or tempo position")
        if position in explicit and explicit[position] != bpm:
            raise ValueError("Score contains conflicting simultaneous tempos")
        explicit[position] = bpm
    changes.update(explicit)
    quarters = sorted(changes)
    rates = [60.0 / changes[at] for at in quarters]
    seconds = [score_audio_origin(score)]
    for index in range(1, len(quarters)):
        seconds.append(seconds[-1] + (quarters[index] - quarters[index - 1]) * rates[index - 1])

    def to_seconds(position):
        index = max(0, bisect.bisect_right(quarters, position) - 1)
        return seconds[index] + (position - quarters[index]) * rates[index]

    def to_quarters(position):
        index = max(0, bisect.bisect_right(seconds, position) - 1)
        return quarters[index] + (position - seconds[index]) / rates[index]

    return to_seconds, to_quarters

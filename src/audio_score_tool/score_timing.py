"""Convert between an existing score's quarter positions and elapsed seconds."""
from __future__ import annotations

import bisect
import math


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
    seconds = [0.0]
    for index in range(1, len(quarters)):
        seconds.append(seconds[-1] + (quarters[index] - quarters[index - 1]) * rates[index - 1])

    def to_seconds(position):
        index = max(0, bisect.bisect_right(quarters, position) - 1)
        return seconds[index] + (position - quarters[index]) * rates[index]

    def to_quarters(position):
        index = max(0, bisect.bisect_right(seconds, position) - 1)
        return quarters[index] + (position - seconds[index]) / rates[index]

    return to_seconds, to_quarters

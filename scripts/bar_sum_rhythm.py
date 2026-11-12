"""Bounded monophonic notation research, not an audio estimator or product editor."""
from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

Q = 12  # ticks per quarter; both binary sixteenths and eighth triplets are exact
DURATIONS = (3, 4, 6, 8, 9, 12, 18, 24, 36, 48)
TOKENS = (1, 2) + DURATIONS  # small tied/rest fragments remain representable
SETTINGS = {
    'ticks_per_quarter': Q, 'durations': DURATIONS, 'start_radius_ticks': 3,
    'minimum_end_radius_ticks': 12, 'onset_sigma_ticks': 1.25,
    'offset_sigma_ticks': 2.0, 'offset_weight': .35,
    'notation_weight': .15, 'extra_tie_weight': .08,
    'phase_margin_per_note': .02, 'accent_weight': 4.0,
    'accent_flat_range': .12, 'accent_sigma_ticks': 1.2,
    'training': False, 'audio_estimation': False, 'quality_approved': False,
}


@dataclass(frozen=True)
class Clock:
    numerator: int
    denominator: int
    bpm: float
    beat_quarters: float = 1.0

    def __post_init__(self):
        if (type(self.numerator) is not int or type(self.denominator) is not int
                or (self.numerator, self.denominator) not in {(4, 4), (3, 4), (6, 8)}
                or not all(math.isfinite(v) and v > 0 for v in (self.bpm, self.beat_quarters))):
            raise ValueError('unsupported fixed clock')

    @property
    def bar(self):
        return Q * 4 * self.numerator // self.denominator

    @property
    def tick_seconds(self):
        return 60.0 / self.bpm / self.beat_quarters / Q


@dataclass(frozen=True)
class Observation:
    id: str
    pitch: int
    onset: float
    offset: float
    voice: int = 0


@dataclass(frozen=True)
class WrittenNote:
    id: str
    pitch: int
    start: int
    duration: int

    @property
    def end(self):
        return self.start + self.duration


@dataclass(frozen=True)
class Solution:
    phase: int
    cost: float
    notes: tuple[WrittenNote, ...]


def validate(observations, clock):
    if not isinstance(clock, Clock) or not observations:
        raise ValueError('nonempty monophonic input required')
    ids = set()
    last = -1.0
    for x in observations:
        if (x.id in ids or x.voice != 0 or not isinstance(x.pitch, int)
                or not 0 <= x.pitch <= 127 or not math.isfinite(x.onset)
                or not math.isfinite(x.offset) or x.onset < 0 or x.onset <= last
                or x.offset <= x.onset):
            raise ValueError('invalid events or unsupported voice assignment')
        ids.add(x.id)
        last = x.onset


def candidates(observation, clock):
    s = observation.onset / clock.tick_seconds
    e = observation.offset / clock.tick_seconds
    center = int(math.floor(s + .5))
    radius = max(12.0, e - s)
    result = []
    for start in range(max(0, center - 3), center + 4):
        for duration in DURATIONS:
            if abs(start + duration - e) > radius + 1e-10:
                continue
            cost = ((start - s) / 1.25) ** 2 + .35 * ((start + duration - e) / 2.0) ** 2
            result.append((WrittenNote(observation.id, observation.pitch, start, duration), cost))
    return tuple(result)


@lru_cache(maxsize=4096)
def token_cost(length):
    """Abstract duration vocabulary only; not complete engraving/tuplet semantics."""
    if length < 0:
        raise ValueError('negative interval')
    costs = [0.0] + [math.inf] * length
    for n in range(1, length + 1):
        costs[n] = min(costs[n - d] + (4.0 if d < 3 else 1.25 if d in (4, 8) else 1.0)
                       for d in TOKENS if d <= n)
    return costs[length]


def pieces(start, end, phase, bar):
    """Split at bar lines; partial first/last intervals are never padded to a full bar."""
    if end < start or start < 0 or bar <= 0 or not 0 <= phase < bar:
        raise ValueError('invalid written interval')
    out = []
    cursor = start
    while cursor < end:
        boundary = phase + ((cursor - phase) // bar + 1) * bar
        stop = min(end, boundary)
        out.append((cursor, stop))
        cursor = stop
    return tuple(out)


@lru_cache(maxsize=200000)
def notation_cost(start, end, phase, bar, is_note):
    spans = pieces(start, end, phase, bar)
    return .15 * sum(token_cost(b - a) for a, b in spans) + (
        .08 * max(0, len(spans) - 1) if is_note else 0.0)


def solve(observations, clock, phase, mode='joint_sum'):
    """Exact DP over the bounded candidate lattice; no reference is an input."""
    validate(observations, clock)
    if not isinstance(phase, int) or not 0 <= phase < clock.bar:
        raise ValueError('invalid phase')
    if mode not in {'independent', 'joint_sum', 'joint_notation'}:
        raise ValueError('invalid mode')
    options = [candidates(x, clock) for x in observations]
    if mode == 'independent':
        chosen = [min(row, key=lambda z: (z[1], z[0].start, z[0].duration)) for row in options]
        return Solution(phase, sum(c for _, c in chosen), tuple(n for n, _ in chosen))
    complex_cost = mode == 'joint_notation'
    # End time is a sufficient DP state for this additive objective.
    states = {0: (0.0, ())}
    for row in options:
        incoming = {}
        for start in sorted({n.start for n, _ in row}):
            choices = [(cost + (notation_cost(end, start, phase, clock.bar, False)
                                if complex_cost else 0.0), path)
                       for end, (cost, path) in sorted(states.items()) if end <= start]
            if choices:
                incoming[start] = min(choices, key=lambda z: z[0])
        updated = {}
        for note, cost in row:
            if note.start not in incoming:
                continue
            value, path = incoming[note.start]
            value += cost + (notation_cost(note.start, note.end, phase, clock.bar, True)
                             if complex_cost else 0.0)
            if note.end not in updated or value < updated[note.end][0] - 1e-12:
                updated[note.end] = (value, path + (note,))
        if not updated:
            raise ValueError('no legal path in frozen lattice')
        states = updated
    cost, notes = min(states.values(), key=lambda z: z[0])
    return Solution(phase, cost, notes)


def accent_cost(accents, phase, bar):
    if not accents:
        return 0.0
    if any(not math.isfinite(t) or t < 0 or not math.isfinite(a) or not 0 <= a <= 1
           for t, a in accents):
        raise ValueError('invalid accent observations')
    if max(a for _, a in accents) - min(a for _, a in accents) < .12:
        return 0.0  # no metrical information in a flat strength sequence
    error = 0.0
    for t, a in accents:
        distance = abs((t - phase + bar / 2) % bar - bar / 2)
        expected = .25 + .75 * math.exp(-.5 * (distance / 1.2) ** 2)
        error += (a - expected) ** 2
    return 4.0 * error / len(accents)


def search_phases(observations, clock, accents=()):
    """A set of near-optimal phases, not a calibrated confidence interval."""
    solutions = []
    for phase in range(clock.bar):
        solution = solve(observations, clock, phase, 'joint_notation')
        value = solution.cost / len(observations) + accent_cost(accents, phase, clock.bar)
        solutions.append((value, solution))
    solutions.sort(key=lambda x: (x[0], x[1].phase))
    best = solutions[0][0]
    retained = [s.phase for value, s in solutions if value <= best + .02 + 1e-12]
    return {
        'selected_phase': retained[0] if len(retained) == 1 else None,
        'candidate_phases': retained, 'best': solutions[0][1],
        'phase_costs': {s.phase: value for value, s in solutions},
        'runner_up_margin': solutions[1][0] - best,
    }


def rests(notes):
    result, end = [], 0
    for n in notes:
        if n.start > end:
            result.append((end, n.start))
        end = max(end, n.end)
    return tuple(result)


def structural_check(solution, clock, observations):
    notes = solution.notes
    invariant = [(n.id, n.pitch) for n in notes] == [(o.id, o.pitch) for o in observations]
    nonoverlap = all(a.end <= b.start for a, b in zip(notes, notes[1:]))
    if not invariant or not nonoverlap:
        return {'invariant': invariant, 'nonoverlap': nonoverlap, 'bar_sums_exact': False,
                'complete_bars': 0, 'barline_ties': 0}
    covered = [(n.start, n.end) for n in notes] + list(rests(notes))
    end = notes[-1].end
    full = list(range(solution.phase, end - clock.bar + 1, clock.bar))
    sums = [sum(max(0, min(b, start + clock.bar) - max(a, start)) for a, b in covered)
            for start in full]
    return {'invariant': True, 'nonoverlap': True, 'bar_sums_exact': all(x == clock.bar for x in sums),
            'complete_bars': len(full), 'barline_ties': sum(
                len(pieces(n.start, n.end, solution.phase, clock.bar)) - 1 for n in notes)}

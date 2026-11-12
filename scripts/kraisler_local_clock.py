"""Local, source-only clock support without repairing or bridging anchors.

The frozen whole-recording admission remains a separate baseline. This module
keeps every original median piano anchor, quarantines both ends of non-increasing
edges, and admits complete observed beat cells only. Public audits contain counts
and hashes, never note arrays or clock-point arrays.

Beat ``candidate_time_at`` and ``period_at`` deliberately ignore local support:
unsupported score competitors must remain visible to the caller's candidate
graph. They must never be used as proof that a pair or duration is supported.
"""
from __future__ import annotations

import bisect
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from fractions import Fraction

from scripts.kraisler_correspondence import (
    MAX_CANDIDATES,
    MAX_CLOCK_GAP_Q,
    MAX_CLOCK_GAP_S,
    symbolic_beats,
)

MAX_POINTS = 20_000
MAX_CLOCK_DISAGREEMENT_S = .1
Point = tuple[Fraction, float]
Component = tuple[Fraction, Fraction]


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def _quarter(value) -> Fraction:
    if isinstance(value, bool):
        raise ValueError('boolean score position is invalid')
    try:
        result = Fraction(value)
        if not math.isfinite(float(result)):
            raise ValueError('nonfinite score position')
    except (TypeError, ValueError, OverflowError, ZeroDivisionError) as exc:
        raise ValueError('finite rational score position required') from exc
    return result


def _seconds(value) -> float:
    if isinstance(value, bool):
        raise ValueError('boolean clock time is invalid')
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError('finite nonnegative clock time required') from exc
    if not math.isfinite(result) or result < 0:
        raise ValueError('finite nonnegative clock time required')
    return result


def _interpolate(points: tuple[Point, ...], positions: tuple[Fraction, ...],
                 q: Fraction) -> float | None:
    index = bisect.bisect_left(positions, q)
    if index < len(points) and positions[index] == q:
        return points[index][1]
    if index == 0 or index == len(points):
        return None
    left_q, left_t = points[index - 1]
    right_q, right_t = points[index]
    return left_t + float((q - left_q) / (right_q - left_q)) * (right_t - left_t)


def _components(points: tuple[Point, ...], accepted: tuple[bool, ...]) -> tuple[Component, ...]:
    """Merge adjacent original edges, never connect across a rejected edge."""
    result = []
    for i, good in enumerate(accepted):
        if not good:
            continue
        start, end = points[i][0], points[i + 1][0]
        if result and result[-1][1] == start:
            result[-1] = (result[-1][0], end)
        else:
            result.append((start, end))
    return tuple(result)


@dataclass(frozen=True)
class LocalClock:
    """Original interpolation restricted to connected accepted beat cells.

    Components are closed score intervals. A healthy/rejected cell boundary
    may support a point, but a positive symmetric time band must still fit
    entirely within that point's one component. Quarantined points never count
    as supported, including exact Fraction queries. No numerical epsilon is
    used to expand component boundaries.
    """

    _points: tuple[Point, ...] = field(repr=False)
    _components: tuple[Component, ...] = field(repr=False)
    _blocked_q: frozenset[Fraction] = field(default_factory=frozenset, repr=False)
    _positions: tuple[Fraction, ...] = field(init=False, repr=False)
    _component_starts: tuple[Fraction, ...] = field(init=False, repr=False)

    def __post_init__(self):
        object.__setattr__(self, '_positions', tuple(p[0] for p in self._points))
        object.__setattr__(self, '_component_starts', tuple(c[0] for c in self._components))

    def _component_at(self, q: Fraction) -> Component | None:
        if q in self._blocked_q:
            return None
        index = bisect.bisect_right(self._component_starts, q) - 1
        if index >= 0 and q <= self._components[index][1]:
            return self._components[index]
        return None

    def time_at(self, q) -> float | None:
        q = _quarter(q)
        if self._component_at(q) is None:
            return None
        return _interpolate(self._points, self._positions, q)

    def supports_interval(self, start, end) -> bool:
        start, end = _quarter(start), _quarter(end)
        if start >= end:
            return False
        component = self._component_at(start)
        return (component is not None and end <= component[1]
                and self._component_at(end) == component)

    def supports_time_band(self, q, halfwidth_seconds) -> bool:
        q, width = _quarter(q), _seconds(halfwidth_seconds)
        component = self._component_at(q)
        if component is None:
            return False
        center = _interpolate(self._points, self._positions, q)
        left = _interpolate(self._points, self._positions, component[0])
        right = _interpolate(self._points, self._positions, component[1])
        if center is None or left is None or right is None:
            return False
        # Exact comparisons of the returned floats avoid rounding a tiny
        # boundary-crossing positive width back onto the component endpoint.
        center, width = Fraction(center), Fraction(width)
        return center - width >= Fraction(left) and center + width <= Fraction(right)


@dataclass(frozen=True)
class LocalBeatClock(LocalClock):
    def candidate_time_at(self, q) -> float | None:
        """Full structural beat interpolation for ambiguity accounting only."""
        return _interpolate(self._points, self._positions, _quarter(q))

    def period_at(self, q) -> float | None:
        """Observed pulse seconds, even in unsupported/gapped beat cells.

        At an exact internal beat boundary use the smaller adjacent period;
        at the first/last observed point only the existing adjacent period is
        available. Nothing is extrapolated beyond these original endpoints.
        """
        q = _quarter(q)
        if q < self._positions[0] or q > self._positions[-1]:
            return None
        index = bisect.bisect_left(self._positions, q)
        if self._positions[index] != q:
            return self._points[index][1] - self._points[index - 1][1]
        adjacent = []
        if index:
            adjacent.append(self._points[index][1] - self._points[index - 1][1])
        if index + 1 < len(self._points):
            adjacent.append(self._points[index + 1][1] - self._points[index][1])
        return min(adjacent) if adjacent else None


def _compatible(score, piano) -> bool:
    if (not score.admissible_for_alignment or not piano.admissible_for_alignment
            or not score.measures or len(score.measures) != len(piano.measures)
            or len({m.part for m in score.measures}) != 1
            or len({m.part for m in piano.measures}) != 1):
        return False
    fields = ('onset_q', 'end_q', 'time_signature', 'pickup', 'short_final')
    return all(all(getattr(v, key) == getattr(p, key) for key in fields)
               for v, p in zip(score.measures, piano.measures))


def _unadmitted(audit, reason):
    audit.update(status='unadmitted', reason=reason)
    return None, None, audit


def build_local_clocks(score, piano, match, beats):
    """Return (beat_clock, piano_clock, audit) without reading violin notes.

    Scientific unadmission returns (None, None, audit). Malformed nonfinite or
    unordered beat inputs raise ValueError; the frozen source parsers normally
    reject these before this function. The observed beat span is the support
    denominator, while whole-score length is reported separately.
    """
    beats = tuple(beats)
    cells = max(0, len(beats) - 1)
    whole = max((_quarter(m.end_q) for m in score.measures), default=Fraction(0))
    audit = {
        'status': 'unadmitted', 'reason': None,
        'beat_cells': cells, 'supported_beat_cells': 0, 'unsupported_beat_cells': cells,
        'supported_score_quarters': 0., 'observed_score_quarters': None,
        'supported_score_quarters_exact': '0', 'observed_score_quarters_exact': None,
        'whole_score_quarters': float(whole), 'support_components': 0,
        'support_denominator': 'observed structural beat range',
        'structural_candidate_count': None, 'rejection_counts_are_nonexclusive': True,
        'max_gap_quarters': float(MAX_CLOCK_GAP_Q), 'max_gap_seconds': MAX_CLOCK_GAP_S,
        'max_clock_disagreement_seconds': MAX_CLOCK_DISAGREEMENT_S,
        'fitted_shift_or_warp': False, 'deleted_anchor_bridging': False,
    }
    if not match.strict_score_consistency:
        return _unadmitted(audit, 'piano_match_not_symbolically_consistent')
    if not _compatible(score, piano):
        return _unadmitted(audit, 'violin_piano_measures_unsupported_or_incompatible')
    if not 2 <= len(beats) <= MAX_POINTS:
        return _unadmitted(audit, 'bounded_at_least_two_observed_beats_required')
    beat_times = tuple(_seconds(b.time) for b in beats)
    if any(b <= a for a, b in zip(beat_times, beat_times[1:])):
        raise ValueError('observed beat times must be strictly increasing')
    grid = symbolic_beats(score)
    candidates = []
    for start in range(max(0, len(grid) - len(beats) + 1)):
        if all((kind, meter) == (beat.kind, beat.meter)
               for (_, kind, meter), beat in zip(grid[start:start + len(beats)], beats)):
            candidates.append(start)
            if len(candidates) > MAX_CANDIDATES:
                audit.update(structural_candidate_count=len(candidates),
                             structural_candidate_count_is_lower_bound=True)
                return _unadmitted(audit, 'structural_candidate_budget_exceeded')
    audit['structural_candidate_count'] = len(candidates)
    if len(candidates) != 1:
        return _unadmitted(audit, 'exactly_one_purely_structural_beat_sequence_required')
    start = candidates[0]
    selected = grid[start:start + len(beats)]
    beat_points = tuple((q, time) for (q, _, _), time in zip(selected, beat_times))
    observed = beat_points[-1][0] - beat_points[0][0]
    audit.update(
        observed_score_quarters=float(observed), observed_score_quarters_exact=str(observed),
        unsupported_score_quarters=float(observed),
        symbolic_prefix_beats=start, symbolic_suffix_beats=len(grid) - start - len(beats),
        beat_mapping_sha256=_digest([[str(q), t] for q, t in beat_points]),
    )
    if not 2 <= len(match.anchors) <= MAX_POINTS:
        return _unadmitted(audit, 'bounded_at_least_two_piano_anchor_notes_required')
    grouped, original = defaultdict(list), []
    for anchor in match.anchors:
        q, time = _quarter(anchor.q), _seconds(anchor.time)
        if not 0 <= q <= whole:
            raise ValueError('piano anchor lies outside symbolic score')
        grouped[q].append(time)
        original.append((q, time))
    points = tuple((q, statistics.median(times)) for q, times in sorted(grouped.items()))
    audit.update(
        eligible_piano_anchor_notes=len(original), piano_anchor_groups=len(points),
        piano_original_anchors_sha256=_digest([[str(q), t] for q, t in sorted(original)]),
        piano_median_anchors_sha256=_digest([[str(q), t] for q, t in points]),
        coincident_group_max_spread_seconds=max(max(v) - min(v) for v in grouped.values()),
    )
    if len(points) < 2:
        return _unadmitted(audit, 'at_least_two_distinct_piano_positions_required')
    nonincreasing = tuple(i for i in range(len(points) - 1) if points[i + 1][1] <= points[i][1])
    blocked_indices = {j for i in nonincreasing for j in (i, i + 1)}
    blocked_q = frozenset(points[i][0] for i in blocked_indices)
    piano_reasons, trusted = [], []
    for i, ((q0, t0), (q1, t1)) in enumerate(zip(points, points[1:])):
        reasons = []
        if i in blocked_indices or i + 1 in blocked_indices:
            reasons.append('quarantined_anchor_incident')
        if q1 - q0 > MAX_CLOCK_GAP_Q:
            reasons.append('piano_quarter_gap')
        if t1 - t0 > MAX_CLOCK_GAP_S:
            reasons.append('piano_seconds_gap')
        piano_reasons.append(tuple(reasons))
        trusted.append(not reasons)
    source_components = _components(points, tuple(trusted))
    source_clock = LocalClock(points, source_components, blocked_q)
    audit.update(
        piano_adjacent_edges=len(points) - 1, piano_nonincreasing_edges=len(nonincreasing),
        piano_reversal_edges=sum(points[i + 1][1] < points[i][1] for i in nonincreasing),
        piano_equal_time_edges=sum(points[i + 1][1] == points[i][1] for i in nonincreasing),
        piano_quarantined_anchor_groups=len(blocked_indices), piano_trusted_edges=sum(trusted),
        piano_source_support_components=len(source_components),
        piano_edge_rejection_counts=dict(Counter(r for row in piano_reasons for r in row)),
        piano_edge_mask_sha256=_digest(piano_reasons),
    )
    accepted, cell_reasons, residual_maxima = [], [], []
    positions = tuple(q for q, _ in points)
    for (q0, t0), (q1, t1) in zip(beat_points, beat_points[1:]):
        reasons = []
        if q1 - q0 > MAX_CLOCK_GAP_Q:
            reasons.append('beat_quarter_gap')
        if t1 - t0 > MAX_CLOCK_GAP_S:
            reasons.append('beat_seconds_gap')
        if not source_clock.supports_interval(q0, q1):
            reasons.append('piano_interval_unsupported')
        else:
            interior = positions[bisect.bisect_right(positions, q0):bisect.bisect_left(positions, q1)]
            residual = max(abs(t0 + float((q - q0) / (q1 - q0)) * (t1 - t0)
                               - source_clock.time_at(q)) for q in (q0, *interior, q1))
            residual_maxima.append(residual)
            if residual > MAX_CLOCK_DISAGREEMENT_S + 1e-12:
                reasons.append('clock_disagreement')
        cell_reasons.append(tuple(reasons))
        accepted.append(not reasons)
    components = _components(beat_points, tuple(accepted))
    supported = sum((b - a for a, b in components), Fraction(0))
    audit.update(
        supported_beat_cells=sum(accepted), unsupported_beat_cells=cells - sum(accepted),
        supported_score_quarters=float(supported), supported_score_quarters_exact=str(supported),
        unsupported_score_quarters=float(observed - supported),
        supported_fraction_of_observed_score=float(supported / observed),
        support_components=len(components),
        beat_cell_rejection_counts=dict(Counter(r for row in cell_reasons for r in row)),
        beat_cell_mask_sha256=_digest(cell_reasons),
        accepted_components_sha256=_digest([[str(a), str(b)] for a, b in components]),
        compared_beat_cells=len(residual_maxima),
        maximum_compared_clock_disagreement_seconds=max(residual_maxima, default=None),
    )
    if not components:
        return _unadmitted(audit, 'no_supported_beat_cells')
    audit.update(status='admitted', reason=None)
    return (LocalBeatClock(beat_points, components, blocked_q),
            LocalClock(points, components, blocked_q), audit)

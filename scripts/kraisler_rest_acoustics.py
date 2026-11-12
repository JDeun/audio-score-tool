"""Continuous gate context for the frozen KRAISLER written-rest ranges.

The original source projection is reproduced and checked against the frozen
range helper. Private interval unions are available to the caller for separate
waveform descriptors. Public output contains summaries and hashes only. A gate
closed cell is a property of the declared RMS procedure, not acoustic silence,
and a region without a note annotation is not asserted to be silent.
"""
from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

import numpy as np

from scripts.kraisler_rhythm_ranges import (
    BOUNDARY_MAX_S,
    BOUNDARY_MIN_S,
    BOUNDARY_PULSE_RATIO,
    rest_range_context,
)

REGIONS = ('envelope', 'core', 'boundary_uncertain')
MAX_GATE_CELLS = 2_000_000
CONSERVATION_TOLERANCE_S = 1e-12
Intervals = tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class RegionIntervals:
    """Private original-time unions; never serialize this object as a report."""

    whole: Intervals
    annotated_note_overlap: Intervals
    uncovered_by_note_annotations: Intervals


@dataclass(frozen=True)
class RestAcousticResult:
    public: dict
    regions: Mapping[str, RegionIntervals]


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'),
                     ensure_ascii=True, allow_nan=False).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def _union(intervals) -> Intervals:
    merged = []
    for start, end in sorted(intervals):
        _require(not isinstance(start, bool) and not isinstance(end, bool)
                 and math.isfinite(start) and math.isfinite(end) and start < end,
                 'positive finite interval required')
        start, end = float(start), float(end)
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return tuple(merged)


def _intersection(left: Intervals, right: Intervals) -> Intervals:
    """Intersect already ordered disjoint unions without rounding boundaries."""
    result = []
    i = j = 0
    while i < len(left) and j < len(right):
        start = max(left[i][0], right[j][0])
        end = min(left[i][1], right[j][1])
        if start < end:
            result.append((start, end))
        if left[i][1] <= right[j][1]:
            i += 1
        else:
            j += 1
    return tuple(result)


def _difference(whole: Intervals, remove: Intervals) -> Intervals:
    result = []
    for start, end in whole:
        cursor = start
        for left, right in remove:
            if right <= cursor:
                continue
            if left >= end:
                break
            if left > cursor:
                result.append((cursor, min(left, end)))
            cursor = max(cursor, right)
            if cursor >= end:
                break
        if cursor < end:
            result.append((cursor, end))
    return tuple(result)


def _duration(intervals: Intervals) -> float:
    return math.fsum(end - start for start, end in intervals)


def _same_sum(total, *parts):
    _require(abs(total - math.fsum(parts)) <= CONSERVATION_TOLERANCE_S,
             'continuous-time duration conservation failed')


def _statistics(values):
    values = sorted(values)
    if not values:
        return dict(count=0, sum=0., mean=None, min=None, p10=None,
                    median=None, p90=None, max=None)

    def quantile(p):
        rank = (len(values) - 1) * p
        lo, hi = math.floor(rank), math.ceil(rank)
        return values[lo] + (rank - lo) * (values[hi] - values[lo])

    total = math.fsum(values)
    return dict(count=len(values), sum=total, mean=total / len(values), min=values[0],
                p10=quantile(.1), median=statistics.median(values),
                p90=quantile(.9), max=values[-1])


def _project(start, end, bclock, pclock):
    if bclock is None or pclock is None:
        return None, 'source_clock_unavailable'
    if start >= end:
        return None, 'nonpositive_score_interval'
    if not all(clock.supports_interval(start, end) for clock in (bclock, pclock)):
        return None, 'interval_not_supported_by_both_clocks'
    projected = []
    for clock in (bclock, pclock):
        left, right = clock.time_at(start), clock.time_at(end)
        if (left is None or right is None or not math.isfinite(left)
                or not math.isfinite(right) or right <= left):
            return None, 'nonpositive_or_unavailable_projection'
        projected.append((left, right))
    return tuple(projected), None


def _source_regions(score, references, bclock, pclock):
    """Reconstruct the declared ranges, then compare every numeric source field."""
    baseline = rest_range_context(score, references, bclock, pclock)
    envelopes, cores, guards, expanded_widths = [], [], [], []
    reasons = Counter()
    projected_count = collapsed_count = 0
    for rest in score.global_rests:
        if not score.admissible_for_alignment or score.counts['parts'] != 1:
            projections, reason = None, 'score_structure_unadmitted'
        else:
            projections, reason = _project(rest.onset_q, rest.end_q, bclock, pclock)
        if reason is not None:
            reasons[reason] += 1
            continue
        (bstart, bend), (pstart, pend) = projections
        rest_guards, rest_widths = [], []
        for q, tb, tp in ((rest.onset_q, bstart, pstart), (rest.end_q, bend, pend)):
            period = bclock.period_at(q)
            if period is None or not math.isfinite(period) or period <= 0:
                reason = 'boundary_pulse_period_unavailable'
                break
            guard = min(BOUNDARY_MAX_S, max(BOUNDARY_MIN_S, BOUNDARY_PULSE_RATIO * period))
            width = guard + abs(tb - tp)
            if not all(clock.supports_time_band(q, width) for clock in (bclock, pclock)):
                reason = 'expanded_boundary_band_not_supported_by_both_clocks'
                break
            rest_guards.append(guard)
            rest_widths.append(width)
        if reason is not None:
            reasons[reason] += 1
            continue
        start_guard, end_guard = rest_guards
        envelopes.append((min(bstart, pstart) - start_guard,
                          max(bend, pend) + end_guard))
        core = (max(bstart, pstart) + start_guard, min(bend, pend) - end_guard)
        if core[0] < core[1]:
            cores.append(core)
        else:
            collapsed_count += 1
        projected_count += 1
        guards.extend(rest_guards)
        expanded_widths.extend(rest_widths)

    unions = {'envelope': _union(envelopes), 'core': _union(cores)}
    unions['boundary_uncertain'] = _difference(unions['envelope'], unions['core'])
    _require(_union(unions['core'] + unions['boundary_uncertain']) == unions['envelope']
             and not _intersection(unions['core'], unions['boundary_uncertain']),
             'rest core and uncertain rim must partition the envelope')
    annotated = _union((ref.onset, ref.offset) for ref in references)
    regions = {
        name: RegionIntervals(whole, _intersection(whole, annotated),
                              _difference(whole, annotated))
        for name, whole in unions.items()
    }
    reconstructed = {
        'explicit_rest_elements': len(score.rests),
        'instrument_wide_rest_intervals': len(score.global_rests),
        'unknown_score_intervals': len(score.unknown_intervals),
        'projected_rest_intervals': projected_count,
        'unprojectable_rest_intervals': len(score.global_rests) - projected_count,
        'unprojectable_reasons': dict(reasons),
        'nonempty_core_source_intervals': len(cores),
        'collapsed_core_intervals': collapsed_count,
        'projections': {},
        'boundary_guards_s': _statistics(guards),
        'expanded_boundary_support_widths_s': _statistics(expanded_widths),
        'guard_policy': {
            'pulse_ratio': BOUNDARY_PULSE_RATIO,
            'minimum_seconds': BOUNDARY_MIN_S,
            'maximum_seconds': BOUNDARY_MAX_S,
            'expanded_support_adds_absolute_clock_disagreement': True,
        },
    }
    for name, region in regions.items():
        duration = _duration(region.whole)
        overlap = _duration(region.annotated_note_overlap)
        reconstructed['projections'][name] = {
            'interval_count': len(region.whole), 'duration_s': duration,
            'annotated_note_overlap_s': overlap,
            'uncovered_by_note_annotations_s': max(0., duration - overlap),
        }
    _require({key: baseline.get(key) for key in reconstructed} == reconstructed,
             'frozen rest projection summary changed')
    _require(not baseline['clipping_performed'] and not baseline['extrapolation'],
             'frozen rest projection must not clip or extrapolate')
    return baseline, regions


def _gate_intervals(edges, quiet):
    edges, quiet = np.asarray(edges), np.asarray(quiet)
    _require(edges.ndim == 1 and edges.dtype.kind in 'fiu'
             and 2 <= len(edges) <= MAX_GATE_CELLS + 1,
             'bounded one-dimensional gate edges required')
    _require(quiet.ndim == 1 and quiet.dtype.kind == 'b'
             and len(quiet) == len(edges) - 1,
             'boolean gate mask must match its cells')
    # Unsigned integer differences can wrap and falsely appear increasing.
    edges = edges.astype(np.float64, copy=False)
    _require(np.isfinite(edges).all() and edges[0] == 0.
             and np.all(np.diff(edges) > 0),
             'finite increasing original audio edges starting at zero required')
    intervals = {True: [], False: []}
    start = 0
    for i in range(1, len(quiet) + 1):
        if i == len(quiet) or quiet[i] != quiet[start]:
            intervals[bool(quiet[start])].append((float(edges[start]), float(edges[i])))
            start = i
    return (float(edges[-1]), tuple(intervals[True]), tuple(intervals[False]),
            {'frame_count': len(quiet), 'quiet_frame_count': int(np.count_nonzero(quiet)),
             'mask_sha256': hashlib.sha256(quiet.astype(np.uint8).tobytes()).hexdigest()})


def _gate_summary(intervals, quiet_intervals, active_intervals):
    duration = _duration(intervals)
    quiet = _duration(_intersection(intervals, quiet_intervals))
    active = _duration(_intersection(intervals, active_intervals))
    _same_sum(duration, quiet, active)
    return {'interval_count': len(intervals), 'interval_sha256': _digest(intervals),
            'duration_s': duration, 'quiet_s': quiet, 'active_s': active,
            'quiet_fraction': quiet / duration if duration else None}


def rest_acoustic_context(score, references, bclock, pclock, edges, quiet) -> RestAcousticResult:
    """Measure original gate-cell intersections, with no clipping or inference.

    ``edges`` are the complete original-audio cell edges and ``quiet`` is the
    frozen gate's boolean mask. Partial boundary cells contribute their exact
    intersection length, not an all-or-nothing centre-frame vote. If any source
    interval falls outside the provided audio, fail closed instead of changing
    the frozen projection denominator or inventing gate evidence outside audio.
    """
    audio_duration, quiet_intervals, active_intervals, gate_identity = _gate_intervals(edges, quiet)
    source_projection, regions = _source_regions(score, references, bclock, pclock)
    _require(all(0 <= ref.onset < ref.offset <= audio_duration for ref in references),
             'reference outside original audio coverage; clipping forbidden')
    _require(all(0 <= start < end <= audio_duration for region in regions.values()
                 for start, end in region.whole),
             'projected rest outside original audio coverage; clipping forbidden')
    published = {}
    for name, region in regions.items():
        _require(_union(region.annotated_note_overlap + region.uncovered_by_note_annotations)
                 == region.whole
                 and not _intersection(region.annotated_note_overlap,
                                       region.uncovered_by_note_annotations),
                 'annotation overlap and uncovered regions must form a disjoint partition')
        row = _gate_summary(region.whole, quiet_intervals, active_intervals)
        row['annotated_note_overlap'] = _gate_summary(
            region.annotated_note_overlap, quiet_intervals, active_intervals)
        row['uncovered_by_note_annotations'] = _gate_summary(
            region.uncovered_by_note_annotations, quiet_intervals, active_intervals)
        for key in ('duration_s', 'quiet_s', 'active_s'):
            _same_sum(row[key], row['annotated_note_overlap'][key],
                      row['uncovered_by_note_annotations'][key])
        published[name] = row
    for subset in (None, 'annotated_note_overlap', 'uncovered_by_note_annotations'):
        rows = {name: row if subset is None else row[subset] for name, row in published.items()}
        for key in ('duration_s', 'quiet_s', 'active_s'):
            _same_sum(rows['envelope'][key], rows['core'][key], rows['boundary_uncertain'][key])
    public = {
        'schema_version': 1, 'reference_notes': len(references),
        'source_projection': source_projection,
        'source_projection_verified': True,
        'waveform_duration_s': audio_duration, 'gate_trace': gate_identity,
        'regions': published,
        'interval_hash_encoding': 'SHA256 of UTF-8 compact JSON, sorted keys; ordered float-second pairs',
        'continuous_gate_cell_intersections': True,
        'conservation_tolerance_seconds': CONSERVATION_TOLERANCE_S,
        'conservation_checked': True,
        'clipping_performed': False, 'extrapolation': False,
        'acoustic_silence_verified': False, 'written_rest_accuracy_measured': False,
        'annotation_uncovered_is_silence': False, 'prediction_occupancy_available': False,
        'new_model_inferences': 0,
        'interpretation': 'frozen gate context within source-defined rest ranges; no acoustic truth or prediction endpoints',
    }
    return RestAcousticResult(public, MappingProxyType(regions))

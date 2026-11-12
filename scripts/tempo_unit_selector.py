"""Frozen no-reference pulse-unit selection research; not a score exporter."""
from __future__ import annotations

import bisect
import math
import statistics
from functools import lru_cache

UNITS = (0.5, 1.0, 2.0)
METHODS = ('keep_quarter', 'tempo_prior', 'notation_only',
           'notation_prior', 'notation_margin')
# All costs are hand-set experimental priors, NOT learned/calibrated probabilities.
SETTINGS = {
    'pulse_subdivisions': 12, 'quarter_ticks': 24,
    'meters_quarters': [3, 4], 'phase_step_quarter_ticks': 6,
    'tempo_prior_center': 120., 'tempo_prior_weight': .25,
    'notation_abstain_margin': .10, 'minimum_events': 8,
    'minimum_seconds': 4., 'tolerance': .04,
    'grid_shared_in_seconds': True, 'reference_or_meter_input': False,
    'note_offsets_used': False, 'scores_are_not_confidences': True,
}
# (duration in 1/24 quarter, complexity): plain, dotted and triplet spellings.
SPELLINGS = ((96, 1.), (72, 1.15), (48, 1.), (36, 1.15), (24, 1.),
             (18, 1.25), (12, 1.15), (9, 1.5), (6, 1.4), (3, 1.8),
             (64, 1.45), (32, 1.45), (16, 1.45), (8, 1.6),
             (4, 1.85), (2, 2.1), (1, 3.))


def validated(pulses, events):
    pulses = tuple(float(x) for x in pulses)
    if (len(pulses) < 4 or any(not math.isfinite(x) or x < 0 for x in pulses)
            or any(b <= a for a, b in zip(pulses, pulses[1:]))):
        raise ValueError('four strictly ordered nonnegative pulse times required')
    events = tuple((float(t), str(role)) for t, role in events)
    if any(not math.isfinite(t) or t < 0 or role not in ('kick', 'backbeat', 'all')
           for t, role in events):
        raise ValueError('invalid observed onset')
    if any(b[0] < a[0] for a, b in zip(events, events[1:])):
        raise ValueError('onsets must be chronological')
    return pulses, events


def pulse_coordinate(t, pulses):
    """Piecewise affine measured clock. No nominal tempo or bar anchor."""
    i = min(max(bisect.bisect_right(pulses, t) - 1, 0), len(pulses) - 2)
    return i + (t - pulses[i]) / (pulses[i + 1] - pulses[i])


def coordinate_seconds(p, pulses):
    i = min(max(math.floor(p), 0), len(pulses) - 2)
    return pulses[i] + (p - i) * (pulses[i + 1] - pulses[i])


@lru_cache(maxsize=1)
def duration_costs():
    # Exact shortest spelling of a span no longer than one 4/4 measure.
    dp = [0.] + [math.inf] * 96
    for length in range(1, 97):
        dp[length] = min(dp[length - d] + c for d, c in SPELLINGS if d <= length)
    return tuple(dp)


def split_span(start, end, bar, phase):
    """Exact partition at hypothetical barlines; partial edge bars are permitted."""
    if end <= start or bar not in (72, 96) or not 0 <= phase < bar:
        raise ValueError('invalid span or measure')
    lengths = []
    while start < end:
        boundary = ((start - phase) // bar + 1) * bar + phase
        right = min(end, boundary)
        lengths.append(right - start)
        start = right
    return lengths


def notation_cost(snapped, unit):
    """Score INTER-ONSET SPANS, not claimed percussion note or rest durations.

    Treat each role separately; never add simultaneous roles' durations. Every
    unit can fill measures. This is only a compactness prior over that valid set.
    """
    if unit not in UNITS:
        raise ValueError('unsupported pulse unit')
    groups = {}
    factor = int(unit * 2)  # pulse tick is 1/12 pulse; quarter tick is 1/24 q.
    for tick, role in snapped:
        groups.setdefault(role, []).append(tick * factor)
    gaps = [(a, b) for positions in groups.values()
            for a, b in zip(positions, positions[1:]) if b > a]
    collisions = sum(b == a for positions in groups.values()
                     for a, b in zip(positions, positions[1:]))
    if not gaps:
        return None
    dp = duration_costs()
    alternatives = []
    for bar in (72, 96):
        for phase in range(0, bar, 6):
            parts = [split_span(a, b, bar, phase) for a, b in gaps]
            value = sum(sum(dp[d] for d in lengths) + .15 * (len(lengths) - 1)
                        for lengths in parts) / len(gaps)
            alternatives.append((value, bar, phase))
    best = min(alternatives)
    return {'cost': best[0], 'diagnostic_meter_quarters': best[1] / 24,
            'diagnostic_phase_q': best[2] / 24,
            'near_tied_meter_phases': sum(abs(x[0] - best[0]) <= 1e-12
                                         for x in alternatives),
            'positive_spans': len(gaps), 'snapped_collisions': collisions,
            'bar_spans_partition_exactly': True}


def choose(rows, key, margin=0.):
    ranked = sorted(rows, key=lambda r: (r[key], abs(math.log2(r['unit'])), r['unit']))
    gap = ranked[1][key] - ranked[0][key]
    abstain = gap <= margin + 1e-12
    winner = ranked[0]
    return {'status': 'abstained' if abstain else 'selected',
            'unit': None if abstain else winner['unit'],
            'qpm': None if abstain else winner['qpm'],
            'cost_gap': gap, 'diagnostic_winner': winner['unit']}


def infer_units(pulses, events):
    """No reference BPM, meter, title, path, fold, score or MIDI tempo argument."""
    pulses, events = validated(pulses, events)
    intervals = [b - a for a, b in zip(pulses, pulses[1:])]
    period = statistics.median(intervals)
    rate = 60. / period
    raw = {'status': 'selected', 'unit': 1., 'qpm': rate}
    base_rows = [{'unit': u, 'qpm': rate * u,
                  'tempo_cost': .5 * math.log2(rate * u / 120.) ** 2} for u in UNITS]
    methods = {'keep_quarter': raw, 'tempo_prior': choose(base_rows, 'tempo_cost')}
    if len(events) < 8 or pulses[-1] - pulses[0] < 4.:
        methods.update({m: {'status': 'insufficient_context', 'unit': None, 'qpm': None}
                        for m in METHODS[2:]})
        return {'methods': methods, 'candidates': base_rows, 'pulse_rate': rate,
                'input_event_count': len(events), 'notation_available': False}
    snapped, residuals = [], []
    for t, role in events:
        p = pulse_coordinate(t, pulses)
        tick = round(p * 12)
        snapped.append((tick, role))
        residuals.append(abs(coordinate_seconds(tick / 12, pulses) - t))
    rows = []
    for candidate in base_rows:
        notation = notation_cost(snapped, candidate['unit'])
        if notation is None:
            methods.update({m: {'status': 'no_distinct_spans', 'unit': None, 'qpm': None}
                            for m in METHODS[2:]})
            return {'methods': methods, 'candidates': base_rows, 'pulse_rate': rate,
                    'input_event_count': len(events), 'notation_available': False}
        rows.append({**candidate, 'notation': notation, 'notation_cost': notation['cost'],
                     'joint_cost': notation['cost'] + .25 * candidate['tempo_cost']})
    methods['notation_only'] = choose(rows, 'notation_cost')
    methods['notation_prior'] = choose(rows, 'joint_cost')
    methods['notation_margin'] = choose(rows, 'notation_cost', .10)
    return {'methods': methods, 'candidates': rows, 'pulse_rate': rate,
            'input_event_count': len(events), 'notation_available': True,
            'shared_grid_mean_error_seconds': statistics.mean(residuals),
            'shared_grid_max_error_seconds': max(residuals),
            'same_physical_fit_for_all_units': True,
            'pulse_interval_outliers': sum(dt > 1.5 * period or dt < .67 * period
                                           for dt in intervals),
            'automatic_score_changes': False}


def evaluate(prediction, reference):
    """Evaluator only: reference is not used in candidate ranking."""
    if not math.isfinite(reference) or reference <= 0:
        raise ValueError('bad evaluator reference')
    value = prediction['qpm']
    if value is None:
        return {'selected': False, 'correct': False, 'error_type': 'unselected'}
    delta = abs(value / reference - 1.)
    alias = any(abs(value / (reference * ratio) - 1.) <= .04 + 1e-12
                for ratio in (.5, 2.))
    return {'selected': True, 'correct': delta <= .04 + 1e-12,
            'relative_error': delta,
            'error_type': 'nominal' if delta <= .04 + 1e-12 else
                          'half_double' if alias else 'other'}


def identifiability_control():
    """Identical physical observations, two different valid written conventions."""
    pulses = tuple(i * .4 for i in range(41))
    events = tuple((i * .4, 'kick' if i % 2 == 0 else 'backbeat') for i in range(40))
    prediction = infer_units(pulses, events)
    return {'identical_observations': True, 'reference_qpm': [75., 150.],
            'prediction': prediction,
            'evaluation_only': {str(q): {m: evaluate(p, q)
                                        for m, p in prediction['methods'].items()}
                                for q in (75., 150.)},
            'both_conventions_have_identical_seconds': True,
            'can_establish_original_written_unit_from_audio_alone': False}

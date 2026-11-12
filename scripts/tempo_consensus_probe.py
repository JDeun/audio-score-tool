"""Frozen, tempo-only multi-scale consensus. No meter, phase or label inputs."""
from __future__ import annotations

import math

import numpy as np
from scipy.signal import correlate

RATE = 100
BPMS = np.arange(40., 241.)
METHODS = ('mean8_prior120', 'consensus_prior120',
           'mean8_selective', 'consensus_selective')
SETTINGS = {
    'rate_hz': RATE, 'bpm_min': 40, 'bpm_max': 240, 'bpm_step': 1,
    'scales_seconds': [4, 8, 12], 'overlap_fraction': .5,
    'lag_multipliers': [1, 2, 4], 'lag_weights': [1., .5, .25],
    'prior_center': 120, 'prior_sigma_octaves': 1.,
    'minimum_seconds': 4., 'minimum_active_bins': 4,
    'window_minimum_raw_peak': .12,
    'consensus_median_weight': .5, 'consensus_mean_weight': .5,
    'minimum_informative_windows': 3, 'minimum_distinct_scales': 2,
    'minimum_winner_support': .60, 'maximum_alias_relative_score': .85,
    'minimum_relative_margin': .08, 'matching_tolerance': .04,
    'top_k': 3, 'candidate_separation': .08,
    'meter_or_downbeat_required': False, 'reference_bpm_input': False,
    'long_midi_seconds': 60., 'primary_seconds': 24.,
    'parameters_calibrated': False, 'quality_approved': False,
}
PRIOR = np.exp(-.5 * np.log2(BPMS / 120.) ** 2)


def validate(env):
    env = np.asarray(env, dtype=float)
    if env.ndim != 1 or not np.isfinite(env).all() or np.any(env < 0):
        raise ValueError('invalid envelope')
    if len(env) / RATE < 4:
        return env, 'too_short'
    maximum = float(env.max(initial=0))
    if maximum <= 1e-10 or np.count_nonzero(env > .1 * maximum) < 4:
        return env, 'no_periodic_evidence'
    return env, None


def window_scores(env, seconds):
    """Retain the earlier ACF calculation exactly; expose each window's score."""
    length = min(len(env), int(seconds * RATE))
    if length < 400:
        return []
    starts = list(range(0, len(env) - length + 1, int(seconds * RATE / 2)))
    if starts[-1] != len(env) - length:
        starts.append(len(env) - length)
    rows = []
    for start in starts:
        centered = env[start:start + length] - float(env[start:start + length].mean())
        energy = float(np.dot(centered, centered))
        if energy < 1e-10:
            rows.append({'start': start, 'length': length, 'energy': energy,
                         'scores': None})
            continue
        maximum = min(length - 2, 6 * RATE)
        numerator = correlate(centered, centered, mode='full', method='fft')[length - 1:]
        cumulative = np.concatenate(([0.], np.cumsum(centered ** 2)))
        lag = np.arange(maximum + 1)
        denominator = np.sqrt((cumulative[length] - cumulative[lag]) * cumulative[length - lag])
        curve = np.divide(numerator[:maximum + 1], denominator,
                          out=np.zeros(maximum + 1), where=denominator > 1e-10)
        curve = np.clip(curve, 0, 1)
        target = 60 * RATE / BPMS
        scores = sum(weight * np.interp(multiplier * target, np.arange(len(curve)),
                                        curve, left=0, right=0)
                     for multiplier, weight in zip((1, 2, 4), (1., .5, .25))) / 1.75
        rows.append({'start': start, 'length': length, 'energy': energy,
                     'scores': scores})
    return rows


def rank(scores):
    selected = []
    for index in np.argsort(-scores, kind='stable'):
        bpm = float(BPMS[index])
        if all(abs(bpm / value['bpm'] - 1) >= .08 for value in selected):
            selected.append({'bpm': bpm, 'score': float(scores[index])})
        if len(selected) == 3:
            break
    return selected


def selection(scores, records):
    """Apply identical abstention to both methods; never choose a reference alias."""
    candidates = rank(scores)
    winner = candidates[0]['bpm']
    peak = candidates[0]['score']
    informative = [r for r in records if r['scores'] is not None and
                   float(r['scores'].max()) >= SETTINGS['window_minimum_raw_peak']]
    by_scale = {}
    for r in informative:
        local = float(BPMS[np.argmax(r['scores'] * PRIOR)])
        by_scale.setdefault(r['scale'], []).append(abs(local / winner - 1) <= .04)
    support = float(np.mean([np.mean(v) for v in by_scale.values()])) if by_scale else 0.
    aliases = [ratio * winner for ratio in (.5, 2.)]
    alias_bins = np.array([any(abs(b / a - 1) <= .04 for a in aliases) for b in BPMS])
    rival = float(scores[alias_bins].max(initial=0))
    alias_ratio = rival / peak if peak > 0 else 1.
    margin = (peak - candidates[1]['score']) / peak if peak > 0 else 0.
    reasons = []
    if len(informative) < 3 or len(by_scale) < 2:
        reasons.append('insufficient_multiwindow_context')
    if support < .60:
        reasons.append('inconsistent_window_winners')
    if alias_ratio >= .85:
        reasons.append('half_double_ambiguity')
    if margin < .08:
        reasons.append('weak_score_margin')
    return {
        'bpm': None if reasons else winner,
        'status': 'abstained' if reasons else 'estimated',
        'diagnostic_winner_not_deployed_if_abstained': winner,
        'candidates': candidates, 'reasons': reasons,
        'informative_windows': len(informative), 'distinct_scales': len(by_scale),
        'window_winner_support': support, 'alias_relative_score': alias_ratio,
        'relative_margin': margin,
    }


def estimate(env):
    """Primary A/B same input and same prior; no output depends on meter/downbeat."""
    env, unavailable = validate(env)
    if unavailable:
        return {m: {'status': unavailable, 'bpm': None, 'candidates': []}
                for m in METHODS}, {'windows': []}
    records, scale_scores = [], []
    available_scales = [s for s in SETTINGS['scales_seconds'] if len(env) >= s * RATE]
    # Always compute exact old8 baseline, even for 4..8s files.
    original_rows = window_scores(env, 8)
    original = [r['scores'] for r in original_rows if r['scores'] is not None]
    baseline = (np.mean(original, axis=0) if original else np.zeros_like(BPMS)) * PRIOR
    for scale in available_scales:
        rows = window_scores(env, scale)
        for r in rows:
            r['scale'] = scale
        records.extend(rows)
        normalized = [r['scores'] / r['scores'].max() for r in rows
                      if r['scores'] is not None and float(r['scores'].max()) >= .12]
        if normalized:
            matrix = np.stack(normalized)
            scale_scores.append(.5 * np.median(matrix, axis=0) + .5 * np.mean(matrix, axis=0))
    consensus = (np.mean(scale_scores, axis=0) if scale_scores else np.zeros_like(BPMS)) * PRIOR
    results = {}
    for plain, selective, scores in (
        (METHODS[0], METHODS[2], baseline), (METHODS[1], METHODS[3], consensus)
    ):
        if float(scores.max()) <= 1e-8:
            for name in (plain, selective):
                results[name] = {'status': 'no_periodic_evidence', 'bpm': None, 'candidates': []}
            continue
        chosen = selection(scores, records)
        results[selective] = chosen
        candidates = rank(scores)
        results[plain] = {'status': 'estimated', 'bpm': candidates[0]['bpm'],
                          'candidates': candidates}
    diagnostics = {'windows': [
        {'scale_seconds': r['scale'], 'start_seconds': r['start'] / RATE,
         'length_seconds': r['length'] / RATE,
         'peak': float(r['scores'].max()) if r['scores'] is not None else 0.,
         'top1': float(BPMS[np.argmax(r['scores'] * PRIOR)]) if r['scores'] is not None else None}
        for r in records
    ], 'informative_scale_count': len(scale_scores)}
    return results, diagnostics


def score(result, truth):
    if not math.isfinite(truth) or truth <= 0:
        raise ValueError('invalid evaluation truth')
    bpm = result['bpm']
    if bpm is None:
        alias, error = 'unavailable', None
    else:
        error = abs(bpm / truth - 1)
        alias = ('nominal' if error <= .04 else 'half_double' if any(
            abs(bpm / (truth * factor) - 1) <= .04 for factor in (.5, 2.)) else 'other')
    return {'status': result['status'], 'alias': alias,
            'relative_error': error, 'within_4pct': alias == 'nominal',
            'candidate_recall_at3': any(abs(c['bpm'] / truth - 1) <= .04
                                      for c in result.get('candidates', []))}

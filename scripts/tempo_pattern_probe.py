"""CPU tempo-only research. Neither meter, bar phase nor target BPM is an input."""
from __future__ import annotations

import hashlib
import math
from collections import Counter

import numpy as np
from scipy.signal import correlate

ENV_RATE = 100
BPMS = np.arange(40.0, 241.0)
METHODS = ('count_negative_control', 'acf_flat', 'acf_prior120', 'librosa_prior120')
SETTINGS = {
    'envelope_hz': ENV_RATE, 'bpm_min': 40, 'bpm_max': 240, 'bpm_step': 1,
    'acf_window_seconds': 8, 'acf_hop_seconds': 4,
    'lag_multipliers': [1, 2, 4], 'lag_weights': [1.0, 0.5, 0.25],
    'prior_center_bpm': 120, 'prior_sigma_octaves': 1.0,
    'top_k': 3, 'candidate_separation_fraction': .08,
    'minimum_seconds': 4.0, 'minimum_active_bins': 4,
    'relative_tempo_tolerance': .04,
    'known_meter_required': False, 'known_bar_phase_required': False,
    'truth_bpm_used_by_estimator': False, 'training': False,
}


def fingerprint(obj):
    import json

    return hashlib.sha256(json.dumps(obj, sort_keys=True, allow_nan=False).encode()).hexdigest()


def event_envelope(events, duration):
    """Events contain seconds and strength only; simultaneous hits share a bin."""
    if not math.isfinite(duration) or duration <= 0 or duration > 600:
        raise ValueError('invalid observed duration')
    env = np.zeros(int(math.ceil(duration * ENV_RATE)) + 1)
    times = set()
    for time, weight in events:
        if (not math.isfinite(time) or not math.isfinite(weight)
                or time < 0 or weight <= 0 or weight > 1):
            raise ValueError('invalid observed hit')
        if time >= duration:
            continue
        index = min(len(env) - 1, int(round(time * ENV_RATE)))
        env[index] += weight
        times.add(index)
    # Same smoothing for every recording and every role group.
    env = np.convolve(env, np.array([.25, .5, .25]), mode='same')
    return env, len(times)


def audio_flux(samples, sr=16000):
    """Continuous multiband novelty, NOT kick/snare classification or beat labels."""
    if (sr != 16000 or samples.ndim != 1 or len(samples) < 1200
            or not np.isfinite(samples).all()):
        raise ValueError('expected finite mono 16kHz waveform')
    size, hop = 1024, 160
    starts = range(0, len(samples) - size + 1, hop)
    frames = np.stack([samples[i:i + size] for i in starts])
    spectrum = np.log1p(np.abs(np.fft.rfft(frames * np.hanning(size), axis=1)))
    flux = np.maximum(spectrum[1:] - spectrum[:-1], 0)
    freq = np.fft.rfftfreq(size, 1 / sr)
    bands = []
    for lo, hi in ((45, 210), (210, 2000), (2000, 7000)):
        env = flux[:, (freq >= lo) & (freq < hi)].mean(axis=1)
        scale = float(np.percentile(env, 99))
        bands.append(np.clip(env / scale, 0, 1) if scale > 1e-12 else np.zeros_like(env))
    return np.mean(bands, axis=0)


def _validated(env):
    env = np.asarray(env, dtype=float)
    if env.ndim != 1 or not np.isfinite(env).all() or np.any(env < 0):
        raise ValueError('invalid onset envelope')
    if len(env) / ENV_RATE < SETTINGS['minimum_seconds']:
        return env, 'too_short'
    peak = float(env.max(initial=0))
    if peak <= 1e-10 or np.count_nonzero(env > .1 * peak) < 4:
        return env, 'no_periodic_evidence'
    return env, None


def _acf_curve(env):
    """Windowed normalized correlations. Reference tempo/phase never consulted."""
    length = min(len(env), 8 * ENV_RATE)
    starts = list(range(0, len(env) - length + 1, 4 * ENV_RATE))
    if starts[-1] != len(env) - length:
        starts.append(len(env) - length)
    curves = []
    for start in starts:
        block = env[start:start + length]
        centered = block - float(block.mean())
        if float(np.dot(centered, centered)) < 1e-10:
            continue
        maximum = min(length - 2, 6 * ENV_RATE)
        numerator = correlate(centered, centered, mode='full', method='fft')[length - 1:]
        cumulative = np.concatenate(([0.], np.cumsum(centered ** 2)))
        lag = np.arange(maximum + 1)
        denominator = np.sqrt((cumulative[length] - cumulative[lag]) * cumulative[length - lag])
        curve = np.divide(numerator[:maximum + 1], denominator,
                          out=np.zeros(maximum + 1), where=denominator > 1e-10)
        curves.append(np.clip(curve, 0, 1))
    if not curves:
        return np.zeros_like(BPMS)
    scores = []
    for curve in curves:
        lag = 60 * ENV_RATE / BPMS
        score = sum(weight * np.interp(multiplier * lag, np.arange(len(curve)), curve,
                                        left=0, right=0)
                    for multiplier, weight in zip((1, 2, 4), (1., .5, .25))) / 1.75
        scores.append(score)
    return np.mean(scores, axis=0)


def _rank(scores):
    selected = []
    for index in np.argsort(-scores, kind='stable'):
        bpm = float(BPMS[index])
        if all(abs(bpm / x['bpm'] - 1) >= .08 for x in selected):
            selected.append({'bpm': bpm, 'score': float(scores[index])})
        if len(selected) == 3:
            break
    return selected


def estimate(env, *, unique_hit_count, duration):
    """Same envelope -> four fixed tempo methods; output is not barline inference."""
    if (type(unique_hit_count) is not int or unique_hit_count < 0
            or not math.isfinite(duration) or duration <= 0):
        raise ValueError('invalid observation summary')
    env, unavailable = _validated(env)
    if unavailable is not None:
        return {name: {'status': unavailable, 'bpm': None, 'candidates': []}
                for name in METHODS}
    results = {'count_negative_control': {
        'status': 'estimated', 'bpm': 60. * unique_hit_count / duration,
        'candidates': [], 'not_a_valid_general_tempo_estimator': True,
    }}
    raw = _acf_curve(env)
    prior = np.exp(-.5 * np.log2(BPMS / 120.) ** 2)
    for name, scores in (('acf_flat', raw), ('acf_prior120', raw * prior)):
        ranked = _rank(scores)
        if float(scores.max()) <= 1e-8:
            results[name] = {'status': 'no_periodic_evidence', 'bpm': None, 'candidates': []}
        else:
            results[name] = {'status': 'estimated', 'bpm': ranked[0]['bpm'],
                             'candidates': ranked,
                             'top_score_margin': ranked[0]['score'] - ranked[1]['score']}
    import librosa

    value = librosa.feature.tempo(onset_envelope=env, sr=ENV_RATE, hop_length=1,
                                 start_bpm=120, std_bpm=1.0, ac_size=8,
                                 max_tempo=241, aggregate=np.mean)
    bpm = float(np.asarray(value).reshape(-1)[0])
    if not math.isfinite(bpm) or bpm <= 0:
        raise ValueError('librosa produced invalid tempo')
    results['librosa_prior120'] = {'status': 'estimated', 'bpm': bpm, 'candidates': [],
                                 'minimum_tempo_not_forced': True}
    return results


def score_tempo(result, truth):
    """Reference is accepted ONLY by this evaluator, never by estimate()."""
    if not math.isfinite(truth) or truth <= 0:
        raise ValueError('invalid nominal reference tempo')
    bpm = result['bpm']
    if bpm is None:
        return {'status': result['status'], 'within_4pct': False, 'relative_error': None,
                'alias': 'unavailable', 'candidate_recall_at_3': False}
    error = abs(bpm / truth - 1)
    alias = ('nominal' if error <= .04 else 'half_double' if any(
        abs(bpm / (truth * x) - 1) <= .04 for x in (.5, 2.)) else 'other')
    return {'status': 'estimated', 'within_4pct': alias == 'nominal', 'relative_error': error,
            'alias': alias, 'candidate_recall_at_3': any(
                abs(v['bpm'] / truth - 1) <= .04 for v in result.get('candidates', []))}


def select_audio(rows, old_ids):
    """Six unseen beat + two fill excerpts, metadata-only deterministic selection."""
    by_id = {r['id']: r for r in rows}
    if not set(old_ids).issubset(by_id):
        raise ValueError('previous source cases missing from publisher metadata')
    planned = [(by_id[i], 'previous_audio_cases') for i in old_ids]
    for kind, minimum, maximum, cap in (('beat', 12., 40., 6), ('fill', 4., 15., 2)):
        eligible = [r for r in rows if r['split'] == 'test' and r['time_signature'] == '4-4'
                    and r['beat_type'] == kind and minimum <= float(r['duration']) <= maximum
                    and r['id'] not in old_ids]
        eligible.sort(key=lambda r: hashlib.sha256(('tempo-only-v1/' + r['id']).encode()).hexdigest())
        planned.extend((r, 'additional_test_audio') for r in eligible[:cap])
    return planned


def summarize(rows, planned_ids):
    """Failures remain in total. No success-subset rates disguised as whole-corpus."""
    if (len(rows) != len(planned_ids) or len(set(planned_ids)) != len(planned_ids)
            or {x['id'] for x in rows} != set(planned_ids)):
        return None
    output = {'planned': len(planned_ids), 'statuses': dict(Counter(r['status'] for r in rows)),
              'all_cases_evaluated': all(r['status'] == 'scored' for r in rows), 'groups': {}}
    groups = sorted({(r['cohort'], rep) for r in rows if r['status'] == 'scored'
                     for rep in r['representations']})
    for cohort, representation in groups:
        group = [r for r in rows if r['cohort'] == cohort]
        scored = [r for r in group if r['status'] == 'scored']
        methods = {}
        for name in METHODS:
            values = [r['representations'][representation]['methods'][name]['evaluation'] for r in scored]
            valid = [v for v in values if v['status'] == 'estimated']
            correct = sum(v['within_4pct'] for v in values)
            methods[name] = {
                'planned': len(group), 'evaluated': len(scored), 'estimated': len(valid),
                'unavailable_or_failed': len(group) - len(valid),
                'within_4pct': correct,
                'within_4pct_rate_all_planned': correct / len(group),
                'half_double': sum(v['alias'] == 'half_double' for v in valid),
                'other_wrong': sum(v['alias'] == 'other' for v in valid),
                'median_relative_error_estimated_only': float(np.median(
                    [v['relative_error'] for v in valid])) if valid else None,
                'candidate_recall_at_3_count': sum(v['candidate_recall_at_3'] for v in values),
            }
        output['groups'][cohort + '/' + representation] = methods
    return output

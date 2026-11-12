"""Frozen offset-only research hypotheses; never a production correction policy."""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import asdict, dataclass, replace

import numpy as np

ARMS = ('raw', 'activation_tail', 'activation_tail_pyin')
SETTINGS = {
    'frame_threshold': 0.3, 'seed_high_frames': 3, 'release_low_frames': 4,
    'seed_start_after_onset_s': 0.03, 'seed_end_after_onset_s': 0.15,
    'minimum_source_duration_s': 0.12, 'minimum_result_duration_s': 0.08,
    'maximum_offset_shift_s': 0.15, 'maximum_duration_fraction_shift': 0.4,
    'minimum_offset_shift_s': 0.02, 'pyin_window_s': 0.05,
    'pyin_pitch_cents': 70., 'pyin_before_agreement': 0.7,
    'pyin_after_agreement_max': 0.3, 'pyin_probability': 0.5,
    'tempo_grid_used': False, 'reference_used': False,
}


@dataclass(frozen=True)
class Event:
    pitch: int
    onset: float
    offset: float
    channel: int = 0
    program: int = 0
    is_drum: bool = False


def checked_events(notes):
    result = [Event(**{k: getattr(n, k) for k in Event.__dataclass_fields__}) for n in notes]
    for n in result:
        if (not all(math.isfinite(v) for v in (n.pitch, n.onset, n.offset))
                or n.pitch != int(n.pitch) or not 0 <= n.pitch <= 127
                or n.onset < 0 or n.offset <= n.onset):
            raise ValueError('invalid event')
    return result


def overlap(a, b):
    return min(a.offset, b.offset) - max(a.onset, b.onset) > 1e-8


def assert_offset_only(before, after):
    if len(before) != len(after):
        raise ValueError('changed event count')
    for i, (old, new) in enumerate(zip(before, after)):
        a, b = asdict(old), asdict(new)
        a.pop('offset')
        b.pop('offset')
        if a != b or not math.isfinite(new.offset) or new.offset <= new.onset:
            raise ValueError('non-offset mutation')
        if old.offset != new.offset:
            limit = min(0.15, 0.4 * (old.offset - old.onset))
            if abs(new.offset - old.offset) > limit + 1e-8 or new.offset - new.onset < .08:
                raise ValueError('offset edit outside bound')
            if any(j != i and not other.is_drum and not overlap(old, before[j])
                   and overlap(new, other) for j, other in enumerate(after)):
                raise ValueError('new overlap')


def _validate_track(times, values):
    if (times.ndim != 1 or len(times) < 4 or values.shape[0] != len(times)
            or not np.isfinite(times).all() or not np.isfinite(values).all()
            or times[0] < 0 or np.any(np.diff(times) <= 0)):
        raise ValueError('invalid observed timeline')


def tail_candidate(notes, index, times, activations, audio_duration):
    """First sustained activation release after an early high-confidence seed.

    Timeline MUST come from the upstream Basic Pitch model_frames_to_time function.
    The choice receives no references, beat grid, key or song identifier.
    """
    n = notes[index]
    if n.is_drum or n.offset - n.onset < .12 or not 21 <= n.pitch <= 108:
        return None, 'short_drum_or_pitch_range'
    if n.offset > audio_duration:
        return None, 'source_outside_audio'
    if any(j != index and not other.is_drum and overlap(n, other)
           for j, other in enumerate(notes)):
        return None, 'overlapping_source'
    values = activations[:, n.pitch - 21]
    seed_ids = np.flatnonzero((times >= n.onset + .03)
                             & (times < min(n.onset + .15, n.offset - .02)))
    seed = None
    for k in seed_ids:
        if k + 2 in seed_ids and np.all(values[k:k + 3] >= .3):
            seed = int(k + 2)
            break
    if seed is None:
        return None, 'no_early_sustain'
    limit = min(.15, .4 * (n.offset - n.onset))
    last = min(audio_duration, n.offset + limit + .06)
    release = None
    for k in range(seed + 1, len(times) - 3):
        if times[k + 3] > last:
            break
        if np.all(values[k:k + 4] < .3):
            release = float(times[k])
            break
    if release is None:
        return None, 'no_observed_release'
    if abs(release - n.offset) < .02:
        return None, 'already_near_release'
    if (abs(release - n.offset) > limit + 1e-8
            or release - n.onset < .08 or release > audio_duration):
        return None, 'release_outside_bound'
    proposed = replace(n, offset=release)
    if any(j != index and not other.is_drum and overlap(proposed, other)
           for j, other in enumerate(notes)):
        return None, 'would_overlap_next_event'
    return release, 'proposed'


def pyin_supports_release(pitch, release, times, hz, probability):
    """Local corroboration only: not a new whole-track voicing mask."""
    before = (times >= release - .05) & (times < release)
    after = (times >= release) & (times < release + .05)
    if int(before.sum()) < 4 or int(after.sum()) < 4:
        return False
    pitch_hz = 440 * 2 ** ((pitch - 69) / 12)
    cents = np.full(hz.shape, np.inf)
    positive = hz > 0
    cents[positive] = np.abs(1200 * np.log2(hz[positive] / pitch_hz))
    match = (cents <= 70) & (probability >= .5)
    return bool(np.mean(match[before]) >= .7 and np.mean(match[after]) <= .3)


def propose(notes, times, activations, audio_duration, f0_times, hz, probability):
    notes = checked_events(notes)
    times, activations = np.asarray(times), np.asarray(activations)
    f0_times, hz, probability = map(np.asarray, (f0_times, hz, probability))
    _validate_track(times, activations)
    _validate_track(f0_times, hz)
    if (activations.ndim != 2 or activations.shape[1] != 88
            or probability.shape != hz.shape or hz.ndim != 1
            or not np.isfinite(probability).all() or np.any(hz < 0)
            or np.any(probability < 0) or np.any(probability > 1)
            or not math.isfinite(audio_duration) or audio_duration <= 0):
        raise ValueError('invalid release evidence')
    frame_only, confirmed = list(notes), list(notes)
    reasons = Counter()
    confirmation = Counter()
    for i, n in enumerate(notes):
        value, reason = tail_candidate(notes, i, times, activations, audio_duration)
        reasons[reason] += 1
        if value is None:
            continue
        frame_only[i] = replace(n, offset=value)
        if pyin_supports_release(n.pitch, value, f0_times, hz, probability):
            confirmed[i] = replace(n, offset=value)
            confirmation['accepted'] += 1
        else:
            confirmation['not_corroborated'] += 1
    arms = dict(zip(ARMS, (notes, frame_only, confirmed)))
    for candidate in arms.values():
        assert_offset_only(notes, candidate)
    return arms, {'screening': dict(reasons), 'pyin_confirmation': dict(confirmation)}


def anchor_diagnostics(before, after, intervals, reference_hz):
    """Scoring only; unique pitch/onset anchors, not human-confirmed repair labels."""
    counts = dict.fromkeys(('changed', 'unique_anchor', 'unassessable', 'repaired',
                           'harmed', 'both_offset_match', 'both_offset_miss'), 0)
    pitch_hz = np.array([440 * 2 ** ((n.pitch - 69) / 12) for n in before])
    starts = np.array([n.onset for n in before])
    edges = ((np.abs(starts[:, None] - intervals[None, :, 0]) <= .05)
             & (np.abs(1200 * np.log2(pitch_hz[:, None] / reference_hz[None, :])) <= 50))
    before_errors, after_errors = [], []
    for i, (old, new) in enumerate(zip(before, after)):
        if old.offset == new.offset:
            continue
        counts['changed'] += 1
        ids = np.flatnonzero(edges[i])
        if len(ids) != 1 or int(edges[:, ids[0]].sum()) != 1 or old.is_drum:
            counts['unassessable'] += 1
            continue
        j = int(ids[0])
        counts['unique_anchor'] += 1
        tolerance = max(.05, .2 * (intervals[j, 1] - intervals[j, 0]))
        e0, e1 = abs(old.offset - intervals[j, 1]), abs(new.offset - intervals[j, 1])
        a, b = e0 <= tolerance, e1 <= tolerance
        category = ('both_offset_match' if a and b else 'both_offset_miss' if not a and not b
                    else 'repaired' if b else 'harmed')
        counts[category] += 1
        before_errors.append(float(e0))
        after_errors.append(float(e1))
    return {**counts, 'absolute_error_sum_before_s': sum(before_errors),
            'absolute_error_sum_after_s': sum(after_errors)}


def aggregate(rows, planned, bases):
    if (len(rows) != len(planned) or {r['id'] for r in rows} != set(planned)
            or any(r.get('status') != 'scored' or set(r.get('bases', {})) != set(bases)
                   for r in rows)):
        return None
    result = {}
    for base in bases:
        if any(set(r['bases'][base]['arms']) != set(ARMS) for r in rows):
            return None
        result[base] = {}
        for arm in ARMS:
            result[base][arm] = {}
            for metric in ('onset_f1', 'onset_offset_f1'):
                scores = np.array([np.mean([r['bases'][base]['arms'][arm]['annotators'][a][metric]
                                           for a in ('A1', 'A2')]) for r in rows])
                raw = np.array([np.mean([r['bases'][base]['arms']['raw']['annotators'][a][metric]
                                        for a in ('A1', 'A2')]) for r in rows])
                if not np.isfinite(scores).all() or not np.isfinite(raw).all():
                    raise ValueError('nonfinite score')
                delta = scores - raw
                boot = np.random.default_rng(0).choice(delta, (2000, len(delta))).mean(axis=1)
                result[base][arm][metric] = {
                    'macro': float(scores.mean()), 'delta_vs_raw': float(delta.mean()),
                    'improved': int((delta > 1e-8).sum()), 'worse': int((delta < -1e-8).sum()),
                    'recording_bootstrap95': np.quantile(boot, [.025, .975]).tolist(),
                }
            result[base][arm]['changed_offsets'] = sum(
                r['bases'][base]['arms'][arm]['changed_offsets'] for r in rows)
    return result


def bar_times(numerator, denominator, bpm, beat_quarters, downbeat, count):
    """Analytic constant-tempo control, NOT audio beat detection or note snapping."""
    if (type(numerator) is not int or numerator <= 0 or denominator not in (1, 2, 4, 8, 16, 32)
            or not all(math.isfinite(x) for x in (bpm, beat_quarters, downbeat))
            or bpm <= 0 or beat_quarters <= 0 or type(count) is not int or count < 1):
        raise ValueError('invalid explicit meter/tempo/anchor')
    seconds = 60 / bpm * (numerator * 4 / denominator) / beat_quarters
    return [downbeat + i * seconds for i in range(count)]


def metrical_controls():
    """Designed examples with known clocks; not evidence about an actual song."""
    cases = []
    for name, n, d, bpm, unit, anchor, first in (
            ('four_four_downbeat', 4, 4, 120, 1, 2., 2.),
            ('three_four_downbeat', 3, 4, 120, 1, 2., 2.),
            ('four_four_pickup_one_quarter', 4, 4, 120, 1, 2., 1.5),
            ('four_four_rest_before_entry', 4, 4, 120, 1, 2., 3.),
            ('six_eight_dotted_quarter', 6, 8, 60, 1.5, 2., 2.)):
        correct = bar_times(n, d, bpm, unit, anchor, 5)
        naive = bar_times(n, d, bpm, unit, first, 5)
        cases.append({'case': name, 'true_bar_times_s': correct,
                      'first_note_anchored_bar_times_s': naive,
                      'maximum_same_index_error_s': max(abs(a-b) for a, b in zip(correct, naive))})
    true_bars = bar_times(4, 4, 120, 1, 0, 51)
    wrong_bars = bar_times(4, 4, 121, 1, 0, 51)
    # Four bars at120 followed by four at100: a piecewise ground-truth clock.
    changed = [0., 2., 4., 6., 8., 10.4, 12.8, 15.2, 17.6]
    fixed = bar_times(4, 4, 120, 1, 0, len(changed))
    return {'scope': 'constructed analytic controls; no audio meter/tempo estimator', 'cases': cases,
            'one_bpm_error_after_50_bars_s': abs(true_bars[-1] - wrong_bars[-1]),
            'tempo_change_true_bar_times_s': changed,
            'constant_tempo_error_at_end_s': abs(changed[-1] - fixed[-1]),
            'used_in_offset_experiment': False}

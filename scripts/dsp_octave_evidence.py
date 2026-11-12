"""Frozen research-only DSP octave evidence; not an automatic product editor."""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, replace

import numpy as np

SR, HOP, FRAME = 16000, 160, 2048
SETTINGS = {
    'sr': SR, 'hop': HOP, 'frame': FRAME, 'fmin': 55., 'fmax': 880.,
    'center': True, 'a4_hz': 440., 'voiced_fraction': .8, 'voiced_probability': .8,
    'pitch_spread_semitones': .8, 'pitch_distance_semitones': .25,
    'minimum_frames': 6, 'minimum_note_seconds': .16, 'spectral_windows': 5,
    'rms_floor_dbfs': -50., 'periodicity_minimum': .85,
    'harmonic_coverage_minimum': .65, 'lower_odd_energy_minimum': .08,
    'downward_period_advantage': .1, 'downward_coverage_advantage': .08,
    'upward_lower_odd_energy_maximum': .02,
    'range_margin_ratio': 2 ** (1 / 12), 'spectral_band_hz': [60., 4000.],
    'spectral_fft': 8192, 'harmonic_half_width_bins': 1.5,
    'maximum_spectral_harmonic': 64, 'frame_voicing_periodicity': .8,
}
ARMS = ('raw', 'pyin_octave', 'corroborated_octave')


@dataclass(frozen=True)
class Note:
    pitch: int
    onset: float
    offset: float
    channel: int = 0
    program: int = 0
    is_drum: bool = False


def freeze_notes(notes):
    out = [Note(**{k: getattr(n, k) for k in Note.__dataclass_fields__}) for n in notes]
    for n in out:
        if (type(n.pitch) not in (int, np.int64, np.int32) or not 0 <= n.pitch <= 127
                or not math.isfinite(n.onset) or not math.isfinite(n.offset)
                or n.onset < 0 or n.offset <= n.onset):
            raise ValueError('invalid predicted note')
    return out


def fingerprint(notes):
    return hashlib.sha256(json.dumps([asdict(n) for n in notes], sort_keys=True,
                                    allow_nan=False).encode()).hexdigest()


def periodicity(x, hz):
    """Fractional-lag correlation. High subharmonic values are not proof of F0."""
    x = np.asarray(x, dtype=float)
    if x.ndim != 1 or len(x) < 32 or not np.isfinite(x).all() or not 30 <= hz <= 2000:
        raise ValueError('invalid period input')
    x = x - x.mean()
    lag = SR / hz
    count = int(len(x) - math.ceil(lag))
    if count < 16:
        return 0.
    a = x[:count]
    b = np.interp(np.arange(count) + lag, np.arange(len(x)), x)
    denominator = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.clip(np.dot(a, b) / denominator, -1., 1.)) if denominator > 1e-12 else 0.


def spectral_evidence(x, hz):
    """Energy explained by harmonic bands; heuristic scores, not probabilities."""
    x = np.asarray(x, dtype=float)
    if x.shape != (FRAME,) or not np.isfinite(x).all() or not 30 <= hz <= 2000:
        raise ValueError('invalid spectrum input')
    x = x - x.mean()
    power = np.abs(np.fft.rfft(x * np.hanning(FRAME), n=8192)) ** 2
    freq = np.fft.rfftfreq(8192, 1 / SR)
    band = (freq >= 60.) & (freq <= 4000.)
    cover = np.zeros(len(freq), dtype=bool)
    odd = np.zeros(len(freq), dtype=bool)
    width = max(1.5 * SR / FRAME, .015 * hz)
    for k in range(1, min(64, int(4000. / hz)) + 1):
        mask = np.abs(freq - k * hz) <= width
        cover |= mask
        if k % 2:
            odd |= mask
    total = float(power[band].sum())
    if total < 1e-12:
        return {'coverage': 0., 'odd_energy': 0., 'periodicity': 0.}
    return {'coverage': float(power[cover & band].sum() / total),
            'odd_energy': float(power[odd & band].sum() / total),
            'periodicity': periodicity(x, hz)}


def spectral_gate(raw, target, direction):
    if direction not in (-12, 12):
        raise ValueError('octave proposals only')
    if target['periodicity'] < .85 or target['coverage'] < .65:
        return False
    if direction == -12:
        return bool(target['periodicity'] - raw['periodicity'] >= .1
                    and target['coverage'] - raw['coverage'] >= .08
                    and target['odd_energy'] >= .08)
    return bool(raw['odd_energy'] <= .02)


def interior_proposal(note, hz, probability):
    """No reference input, and no inferred global tuning or time shift."""
    duration = note.offset - note.onset
    if note.is_drum or duration < .16:
        return None, 'short_or_drum'
    margin = max(.04, min(.1, duration * .15))
    times = np.arange(len(hz)) * HOP / SR
    mask = (times >= note.onset + margin) & (times < note.offset - margin)
    values = hz[mask]
    good = values > 0
    if len(values) < 6 or good.sum() < 6 or good.mean() < .8:
        return None, 'insufficient_voicing'
    if float(np.median(probability[mask][good])) < .8:
        return None, 'low_voiced_probability'
    pitches = 69 + 12 * np.log2(values[good] / 440.)
    median = float(np.median(pitches))
    target = int(round(median))
    if (np.quantile(pitches, .9) - np.quantile(pitches, .1) > .8
            or abs(median - target) > .25):
        return None, 'unstable_pitch'
    observed = 440. * 2 ** ((median - 69.) / 12.)
    if not 55. * 2 ** (1 / 12) < observed < 880. / 2 ** (1 / 12):
        return None, 'range_edge'
    if target == note.pitch:
        return None, 'pitch_agrees'
    if abs(target - note.pitch) != 12 or not 0 <= target <= 127:
        return None, 'not_one_octave'
    raw_frequency = observed * 2 ** ((note.pitch - target) / 12.)
    if not 30 <= raw_frequency <= 2000:
        return None, 'comparison_range'
    return (target, observed), 'proposed'


def propose(notes, samples, hz, probability):
    """Compare frozen raw, pYIN-only and corroborated octave arms on identical notes."""
    y = np.asarray(samples, dtype=float)
    hz, probability = np.asarray(hz, dtype=float), np.asarray(probability, dtype=float)
    if (y.ndim != 1 or not len(y) or not np.isfinite(y).all() or hz.ndim != 1
            or hz.shape != probability.shape or not np.isfinite(hz).all()
            or not np.isfinite(probability).all() or np.any(hz < 0)
            or np.any(probability < 0) or np.any(probability > 1)):
        raise ValueError('invalid observations')
    before = fingerprint(notes)
    pyin, hybrid, rows = list(notes), list(notes), []
    for i, n in enumerate(notes):
        row = {'prediction_index': i}
        overlap = any(j != i and not m.is_drum
                      and min(n.offset, m.offset) - max(n.onset, m.onset) > 1e-6
                      for j, m in enumerate(notes))
        if overlap:
            row['reason'] = 'overlapping_model_events'
        else:
            proposal, reason = interior_proposal(n, hz, probability)
            row['reason'] = reason
            if proposal:
                target, observed = proposal
                pyin[i] = replace(n, pitch=target)
                row['direction'] = target - n.pitch
                raw_frequency = observed * 2 ** ((n.pitch - target) / 12.)
                first = int(math.ceil(n.onset * SR)) + FRAME // 2
                last = min(len(y), int(math.floor(n.offset * SR))) - FRAME // 2
                votes, measurements = [], []
                for center in sorted(set(np.linspace(first, last, 5).astype(int))) if last >= first else []:
                    frame = y[center - FRAME // 2:center + FRAME // 2]
                    if len(frame) != FRAME:
                        continue
                    rms = float(np.sqrt(np.mean(frame ** 2)))
                    a, b = spectral_evidence(frame, raw_frequency), spectral_evidence(frame, observed)
                    vote = rms >= 10 ** (-50 / 20) and spectral_gate(a, b, target - n.pitch)
                    votes.append(vote)
                    measurements.append({'raw': a, 'target': b, 'rms': rms})
                accepted = len(votes) >= 3 and sum(votes) / len(votes) >= .8
                if accepted:
                    hybrid[i] = replace(n, pitch=target)
                row.update(spectral_windows=len(votes), supporting_windows=sum(votes),
                           corroborated=accepted, measurements=measurements)
        rows.append(row)
    if fingerprint(notes) != before:
        raise ValueError('raw changed')
    for out in (pyin, hybrid):
        if len(out) != len(notes) or any(replace(a, pitch=b.pitch) != b for a, b in zip(notes, out)):
            raise ValueError('nonpitch mutation')
    return dict(zip(ARMS, (list(notes), pyin, hybrid))), rows


def frame_gate(samples, hz, probability):
    """Voicing-only ablation; no F0 replacements, gap fill or time shifts."""
    y = np.asarray(samples, dtype=float)
    out = np.asarray(hz, dtype=float).copy()
    padded = np.pad(y, (FRAME // 2, FRAME // 2))
    for i in np.flatnonzero(out > 0):
        frame = padded[i * HOP:i * HOP + FRAME]
        if (len(frame) != FRAME or probability[i] < .8
                or np.sqrt(np.mean(frame ** 2)) < 10 ** (-50 / 20)
                or periodicity(frame, float(out[i])) < .8):
            out[i] = 0.
    return out


def anchored_transitions(before, after, intervals, reference_hz):
    """Unique temporal overlap anchors; conditional diagnostic, not causal truth."""
    if len(before) != len(after):
        raise ValueError('unaligned prediction IDs')
    edges = {}
    for i, n in enumerate(before):
        matches = []
        for j, (start, end) in enumerate(intervals):
            intersection = max(0., min(end, n.offset) - max(start, n.onset))
            union = max(end, n.offset) - min(start, n.onset)
            if abs(n.onset - start) <= .05 and intersection / union >= .5:
                matches.append(j)
        edges[i] = matches
    reverse = {}
    for i, js in edges.items():
        for j in js:
            reverse.setdefault(j, []).append(i)
    counts = dict(anchored=0, correct_before=0, changed_anchored=0, repaired=0,
                  damaged=0, wrong_to_wrong=0, changed_unanchored=0)
    for i, (a, b) in enumerate(zip(before, after)):
        js = edges[i]
        if len(js) != 1 or len(reverse[js[0]]) != 1:
            counts['changed_unanchored'] += a.pitch != b.pitch
            continue
        hz = reference_hz[js[0]]
        ca = abs(1200 * math.log2((440 * 2 ** ((a.pitch - 69) / 12)) / hz)) <= 50
        cb = abs(1200 * math.log2((440 * 2 ** ((b.pitch - 69) / 12)) / hz)) <= 50
        counts['anchored'] += 1
        counts['correct_before'] += ca
        counts['changed_anchored'] += a.pitch != b.pitch
        counts['repaired'] += not ca and cb
        counts['damaged'] += ca and not cb
        counts['wrong_to_wrong'] += a.pitch != b.pitch and not ca and not cb
    return counts

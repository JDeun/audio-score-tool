"""Reference-free one-edit candidates and explicitly reference-using diagnostics.

No production correction. Ordered matching categories are heuristic and priority
sensitive, not human-confirmed error causes. Oracle scores never select a product
prediction. Windows are picked before any annotation is read.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, replace

import numpy as np


@dataclass(frozen=True)
class Note:
    pitch: int
    onset: float
    offset: float
    channel: int = 0
    program: int = 0
    is_drum: bool = False


def validate(notes):
    for n in notes:
        if (not all(math.isfinite(float(v)) for v in (n.pitch, n.onset, n.offset))
                or int(n.pitch) != n.pitch or not 0 <= n.pitch <= 127
                or n.onset < 0 or n.offset <= n.onset):
            raise ValueError('invalid event')


def fingerprint(notes):
    return hashlib.sha256(json.dumps([asdict(n) for n in notes], sort_keys=True,
                                    allow_nan=False).encode()).hexdigest()


def from_notes(notes):
    result = [Note(**{k: getattr(n, k) for k in Note.__dataclass_fields__}) for n in notes]
    validate(result)
    return result


def windows(recording_id, duration, width=4.0, maximum=3):
    """Outcome-independent selection of at most three complete four-second windows."""
    if not math.isfinite(duration) or duration <= 0 or width <= 0 or maximum < 1:
        raise ValueError('invalid timeline')
    starts = [i * width for i in range(int(duration // width))]
    ordered = sorted(starts, key=lambda t: hashlib.sha256(
        f'candidate-v1:{recording_id}:{t}'.encode()).digest())[:maximum]
    return [(t, t + width) for t in sorted(ordered)]


def candidates(notes, peaks, start, end, limit=17):
    """Keep plus chronological one-edit alternatives; no reference parameter.

    Only notes fully inside the window are edited. Boundary-crossing and drum
    notes remain unchanged. Every change has explicit original local indices.
    No crop, octave normalization, threshold tuning or multi-edit beam search.
    """
    validate(notes)
    if not math.isfinite(start + end) or start < 0 or end <= start or limit < 1:
        raise ValueError('invalid window')
    peaks = np.asarray(peaks, dtype=float)
    if peaks.ndim != 1 or not np.isfinite(peaks).all() or np.any(np.diff(peaks) <= 0):
        raise ValueError('invalid attacks')
    base = tuple(sorted(notes, key=lambda n: (n.onset, n.offset, n.pitch)))
    answer = [{'kind': 'keep', 'notes': base, 'source_indices': []}]
    seen = {fingerprint(base)}

    def add(kind, value, indices):
        value = tuple(sorted(value, key=lambda n: (n.onset, n.offset, n.pitch)))
        validate(value)
        key = fingerprint(value)
        if key not in seen and len(answer) < limit:
            seen.add(key)
            answer.append({'kind': kind, 'notes': value, 'source_indices': indices})

    for i, n in enumerate(base):
        if n.is_drum or n.onset < start + .08 or n.offset > end - .08:
            continue
        # Only isolated monophonic events are eligible. Known polyphony is not flattened.
        if any(j != i and min(n.offset, p.offset) - max(n.onset, p.onset) > 1e-6
               for j, p in enumerate(base)):
            continue
        near = peaks[(np.abs(peaks - n.onset) <= .08) & (peaks >= start + .08)]
        for p in near:
            p = float(p)
            if n.offset - p >= .08 and not any(j != i and
                    min(n.offset, q.offset) - max(p, q.onset) > 1e-6
                    for j, q in enumerate(base)):
                add('onset', base[:i] + (replace(n, onset=p),) + base[i+1:], [i])
        inside = peaks[(peaks >= n.onset + .08) & (peaks <= n.offset - .08)]
        for p in inside:
            p = float(p)
            add('split', base[:i] + (replace(n, offset=p), replace(n, onset=p))
                + base[i+1:], [i])
        if i + 1 < len(base):
            nxt = base[i+1]
            if (not nxt.is_drum and (n.pitch, n.program, n.channel) ==
                    (nxt.pitch, nxt.program, nxt.channel)
                    and 0 <= nxt.onset - n.offset <= .08 and nxt.offset <= end - .08
                    and not any(j not in (i, i+1) and
                        min(nxt.offset, q.offset) - max(n.onset, q.onset) > 1e-6
                        for j, q in enumerate(base))):
                add('merge', base[:i] + (replace(n, offset=nxt.offset),) + base[i+2:], [i, i+1])
    return answer


def arrays(notes):
    pitched = [n for n in notes if not n.is_drum]
    return (np.array([(n.onset, n.offset) for n in pitched]).reshape(-1, 2),
            np.array([440 * 2 ** ((n.pitch-69)/12) for n in pitched]))


def metrics(notes, ref_intervals, ref_hz):
    import mir_eval.transcription as mt

    est_i, est_p = arrays(notes)
    nr, ne = len(ref_hz), len(est_p)
    result = {'reference_count': nr, 'prediction_count': ne}
    for name, offset in (('onset', None), ('onset_offset', .2)):
        matches = mt.match_notes(ref_intervals, ref_hz, est_i, est_p,
                                onset_tolerance=.05, pitch_tolerance=50,
                                offset_ratio=offset, offset_min_tolerance=.05) if nr and ne else []
        result[name + '_matched'] = len(matches)
        result[name + '_f1'] = 2 * len(matches) / (nr + ne) if nr + ne else None
    return result


def error_partition(notes, ref_i, ref_p):
    """One-to-one residual matching in a FIXED priority; no inferred causal truth."""
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import maximum_bipartite_matching

    est_i, est_p = arrays(notes)
    remaining_r, remaining_e = set(range(len(ref_p))), set(range(len(est_p)))
    out = {}
    for category in ('full_match', 'pitch_onset_offset_mismatch', 'same_pitch_150ms',
                     'octave_at_50ms', 'other_pitch_at_50ms'):
        rs, es = sorted(remaining_r), sorted(remaining_e)
        if not rs or not es:
            out[category] = 0
            continue
        onset = np.abs(ref_i[rs, 0, None] - est_i[None, es, 0])
        cents = np.abs(1200 * np.log2(ref_p[rs, None] / est_p[None, es]))
        if category == 'full_match':
            tolerance = np.maximum(.05, .2 * (ref_i[rs, 1]-ref_i[rs, 0]))[:, None]
            edges = (onset <= .05) & (cents <= 50) & (
                np.abs(ref_i[rs, 1, None]-est_i[None, es, 1]) <= tolerance)
        elif category == 'pitch_onset_offset_mismatch':
            edges = (onset <= .05) & (cents <= 50)
        elif category == 'same_pitch_150ms':
            edges = (onset <= .15) & (cents <= 50)
        elif category == 'octave_at_50ms':
            edges = (onset <= .05) & (np.abs(cents - 1200) <= 50)
        else:
            edges = (onset <= .05) & (cents > 50)
        match = maximum_bipartite_matching(csr_matrix(edges), perm_type='column')
        pairs = [(rs[r], es[int(e)]) for r, e in enumerate(match) if e >= 0]
        remaining_r.difference_update(r for r, _ in pairs)
        remaining_e.difference_update(e for _, e in pairs)
        out[category] = len(pairs)
    out.update(unmatched_reference=len(remaining_r), unmatched_prediction=len(remaining_e),
               reference_count=len(ref_p), prediction_count=len(est_p))
    return out


def window_oracle(options, ref_i, ref_p):
    """Evaluation ONLY: best of pre-generated candidates, not a deployable selector."""
    values = [metrics(c['notes'], ref_i, ref_p) for c in options]
    if not len(ref_p):
        return {'scorable': False, 'reason': 'empty_reference',
                'candidate_count': len(options), 'baseline': values[0]}
    best = {}
    for metric in ('onset_f1', 'onset_offset_f1'):
        i = max(range(len(values)), key=lambda k: (values[k][metric], -k))
        best[metric] = {'value': values[i][metric], 'candidate_index': i,
                        'edit_kind': options[i]['kind'],
                        'gain': values[i][metric] - values[0][metric]}
    return {'scorable': True, 'candidate_count': len(options), 'baseline': values[0],
            'oracle': best}

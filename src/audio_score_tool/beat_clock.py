"""Pinned beat-clock observations and conservative meter mapping."""
from __future__ import annotations

import math
from statistics import median

import numpy as np


def observed_tempo_bpm(beats):
    periods = [(b['time_seconds'] - a['time_seconds']) * a['denominator'] / 4
               for a, b in zip(beats, beats[1:])
               if a['numerator'] == b['numerator'] and a['denominator'] == b['denominator']
               and b['beat'] == a['beat'] % a['numerator'] + 1
               and b['time_seconds'] > a['time_seconds']]
    return round(60 / median(periods), 2)


def beat_rows(beats, downbeats, duration, meter_rows):
    """Map BeatThis beats to a constant simple quarter-note meter without fallback."""
    beats = np.asarray(beats, dtype=float)
    downs = np.asarray(downbeats, dtype=float)
    for values in (beats, downs):
        if (values.ndim != 1 or not np.isfinite(values).all()
                or np.any(values < 0) or np.any(np.diff(values) <= 0)):
            raise ValueError('Invalid beat-clock observation')
    if len(beats) < 2 or len(beats) > 100_000 or len(downs) > 100_000 or not math.isfinite(duration) or duration <= 0:
        raise ValueError('Incomplete beat-clock observation')
    if np.any(beats > duration) or np.any(downs > duration):
        raise ValueError('Beat observation exceeds source duration')
    meters = {(int(row[2]), int(row[3])) for row in meter_rows}
    if len(meters) != 1 or next(iter(meters)) not in {(3, 4), (4, 4)}:
        raise ValueError('Unsupported changing or ambiguous meter for beat clock')
    numerator, denominator = next(iter(meters))
    positions = np.searchsorted(beats, downs)
    matched = []
    for time, pos in zip(downs, positions):
        options = [int(i) for i in (pos - 1, pos) if 0 <= i < len(beats)]
        index = min(options, key=lambda i: abs(beats[i] - time))
        if abs(beats[index] - time) > .08:
            raise ValueError('Downbeat does not match an observed beat')
        matched.append(index)
    if len(set(matched)) != len(matched):
        raise ValueError('Multiple downbeats map to the same observed beat')
    votes = [sum(i % numerator == phase for i in matched) for phase in range(numerator)]
    ranked = sorted(votes, reverse=True)
    # Development guard chosen after observed phase conflict, not a calibrated quality threshold.
    if not ranked[0] or ranked[0] <= sum(ranked[1:]) or ranked[0] < 2 * ranked[1]:
        raise ValueError('Ambiguous downbeat phase for beat clock')
    phase = int(np.argmax(votes))
    original_count = len(beats)
    last_step = float(beats[-1] - beats[-2])
    period = float(np.median(np.diff(beats[:min(original_count, 33)])))
    leading_ratio = float(beats[0]) / period if period > 0 else math.inf
    trailing_ratio = float(max(0., duration - beats[-1])) / last_step if last_step > 0 else math.inf
    if not math.isfinite(leading_ratio) or not math.isfinite(trailing_ratio):
        raise ValueError('Beat clock exceeds derived event limit')
    leading_bound = math.ceil(leading_ratio) + 1
    trailing_bound = math.ceil(trailing_ratio)
    if len(beats) + leading_bound + trailing_bound > 100_000:
        raise ValueError('Beat clock exceeds derived event limit')
    times = beats.tolist()
    trailing = 0
    while times[-1] < duration:
        times.append(times[-1] + last_step)
        trailing += 1
    prefix = []
    at = float(beats[0]) - period
    while at > 0:
        prefix.append(at)
        at -= period
    prefix.sort()
    if beats[0] > 0:
        prefix.insert(0, 0.0)
    combined = prefix + times
    rows = [[repr(float(t)), str((i - len(prefix) - phase) % numerator + 1),
             str(numerator), str(denominator)] for i, t in enumerate(combined)]
    observed_rows = [{'time_seconds': float(t), 'beat': (i - phase) % numerator + 1,
                      'numerator': numerator, 'denominator': denominator} for i, t in enumerate(beats)]
    observed_downbeats = [dict(observed_rows[i], time_seconds=float(t)) for i, t in zip(matched, downs)]
    return rows, {'observed_beat_rows': observed_rows, 'observed_downbeat_rows': observed_downbeats,
                  'observed_beats': original_count, 'observed_downbeats': len(downs),
                  'nominal_tempo_bpm': observed_tempo_bpm(observed_rows),
                  'phase': phase, 'phase_votes': votes, 'unmatched_downbeats': 0,
                  'phase_incompatible_downbeats': len(matched) - votes[phase],
                  'leading_derived_count': len(prefix),
                  'leading_period_seconds': period, 'trailing_derived_count': trailing,
                  'terminal_beat_clipped': times[-1] > duration, 'duration_seconds': duration,
                  'meter': f'{numerator}/{denominator}', 'quality_approved': False}


def fixed_beat_track(source, output, *, settings, cancel_event=None):
    """Run and authenticate the pinned whole-audio beat observation."""
    import hashlib
    import json
    import zipfile
    from pathlib import Path

    from .fixed_lead_recipe import BEAT_RUNTIME
    from .runner import run_command

    run_command(settings.fixed_vocal_cmd, ['beat', source, output, '--snapshot', settings.fixed_lead_snapshot],
                timeout_seconds=1800, cancel_event=cancel_event,
                env={'PYTHONHASHSEED': '0', 'OMP_NUM_THREADS': '2', 'MKL_NUM_THREADS': '2'})
    receipt_path = output.with_suffix('.runtime.json')
    if any(p.is_symlink() or not p.is_file() or p.stat().st_size > limit
           for p, limit in ((output, 16 * 1024 * 1024), (receipt_path, 65536))):
        raise ValueError('Missing or unsafe beat observation')
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()
    receipt = json.loads(receipt_path.read_text())
    expected = {'provider': 'beat-this', 'model': 'final0', 'device': 'cpu', 'threads': 2, 'seed': 0,
                'dbn': True, 'source_revision': 'b95c8ab0c58c2d9fcfd40508ae8dffbc05ac4f5c',
                'checkpoint_sha256': '8c328b45f59d8dd3dff219253ff6a8d6482be57d0133a29140e2febbf8eb8331',
                'source_tree_sha256': '3f8d310da05e5b26fb455645dfcad5b835570b23a511003e351ce0f33b45fd04',
                'madmom_source_revision': '27f032e8947204902c675e5e341a3faf5dc86dae',
                'madmom_tree_sha256': '43edae0d91e5813ccea423d9fe0693f315514e3139616c9d1d37f05e9dc4a995',
                'madmom_pretrained_weights': False,
                'dbn_parameters': {'fps': 50, 'beats_per_bar': [3, 4], 'min_bpm': 55.0,
                                   'max_bpm': 215.0, 'transition_lambda': 100}}
    if (not isinstance(receipt, dict) or any(receipt.get(k) != v for k, v in expected.items())
            or receipt.get('source_sha256') != digest(source) or receipt.get('prediction_sha256') != digest(output)
            or receipt.get('adapter_sha256') != digest(Path(__file__).with_name('fixed_vocal_infer.py'))
            or not isinstance(receipt.get('python'), str) or not receipt['python'].startswith('3.11.')
            or not isinstance(receipt.get('runtime'), dict)
            or any(receipt['runtime'].get(k) != v for k, v in BEAT_RUNTIME.items())):
        raise ValueError('Fixed beat observation provenance mismatch')
    try:
        with zipfile.ZipFile(output) as archive:
            members = archive.infolist()
            if sorted(x.filename for x in members) != ['beat_logits.npy', 'beats.npy', 'downbeat_logits.npy', 'downbeats.npy'] or sum(x.file_size for x in members) > 32 * 1024 * 1024:
                raise ValueError('Invalid or oversized beat arrays')
        with np.load(output, allow_pickle=False) as data:
            beats, downs = np.asarray(data['beats']), np.asarray(data['downbeats'])
            beat_logits, downbeat_logits = np.asarray(data['beat_logits']), np.asarray(data['downbeat_logits'])
    except (OSError, EOFError, zipfile.BadZipFile) as exc:
        raise ValueError('Invalid beat archive') from exc
    for values in (beats, downs):
        if (values.ndim != 1 or values.dtype.kind not in 'fi' or not np.isfinite(values).all()
                or np.any(values < 0) or np.any(np.diff(values) <= 0)):
            raise ValueError('Invalid beat observation')
    if len(beats) < 2 or not len(downs):
        raise ValueError('Incomplete beat observation')
    if (beat_logits.ndim != 1 or not len(beat_logits) or beat_logits.shape != downbeat_logits.shape
            or beat_logits.dtype.kind not in 'fi' or downbeat_logits.dtype.kind not in 'fi'
            or not np.isfinite(beat_logits).all() or not np.isfinite(downbeat_logits).all()):
        raise ValueError('Invalid beat logits')
    if (hashlib.sha256(beat_logits.tobytes()).hexdigest() != receipt.get('beat_logits_sha256')
            or hashlib.sha256(downbeat_logits.tobytes()).hexdigest() != receipt.get('downbeat_logits_sha256')):
        raise ValueError('Beat logits evidence SHA mismatch')
    return receipt

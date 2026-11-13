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
    compatible_downbeats = [row for row in observed_downbeats if row['beat'] == 1]
    bar_periods = np.diff(beats[phase::numerator]) / numerator
    nominal_tempo = round(60 / float(np.median(bar_periods)), 2) if len(bar_periods) else observed_tempo_bpm(observed_rows)
    return rows, {'observed_beat_rows': observed_rows, 'observed_downbeat_rows': observed_downbeats,
                  'phase_compatible_downbeat_rows': compatible_downbeats,
                  'observed_beats': original_count, 'observed_downbeats': len(downs),
                  'nominal_tempo_bpm': nominal_tempo,
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
                'madmom_python_sha256': '28255419eddab6a2c801b240df2e8f418e4e8d2704d6caaa1146d41661f8167e',
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
    native = receipt.get('madmom_native_sha256')
    pyx = receipt.get('madmom_pyx_sha256')
    allowed_pyx = {
        'audio/comb_filters.pyx': '3d4c7102835b582f262e1c9197c23d4199500758736d8e90abf571c29d4cfcbc',
        'features/beats_crf.pyx': '52181fb6ff7cf347ee52c7465a0d46828918fab8c4abd594169447e44ce6a6ca',
        'ml/hmm.pyx': '0c1ff63bd9c23e66169246546ac7ba9ad8acc3fdf9b9bab57b42c00e6326500a',
    }
    if (not isinstance(native, dict) or not native or not isinstance(pyx, dict)
            or any(allowed_pyx.get(k) != v for k, v in pyx.items())
            or not isinstance(receipt.get('madmom_native_platform'), str)
            or not receipt['madmom_native_platform']
            or any(not isinstance(k, str) or Path(k).is_absolute() or '..' in Path(k).parts
                   or Path(k).suffix not in {'.so', '.pyd'} or not isinstance(v, str)
                   or len(v) != 64 or any(ch not in '0123456789abcdef' for ch in v)
                   for k, v in native.items())):
        raise ValueError('Invalid madmom source or native build provenance')
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
    frames, rate = receipt.get('source_frames'), receipt.get('source_sample_rate')
    if (type(frames) is not int or type(rate) is not int or frames <= 0 or rate <= 0
            or abs(len(beat_logits) - (1 + (frames * 22050 // rate) // 441)) > 1):
        raise ValueError('Beat logits do not cover the whole source')
    if (hashlib.sha256(beat_logits.tobytes()).hexdigest() != receipt.get('beat_logits_sha256')
            or hashlib.sha256(downbeat_logits.tobytes()).hexdigest() != receipt.get('downbeat_logits_sha256')):
        raise ValueError('Beat logits evidence SHA mismatch')
    return receipt

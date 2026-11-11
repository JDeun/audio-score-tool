"""Research-only pYIN-to-note baselines. No reference-informed edits or product use."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
import platform
import resource
import time
import zipfile
from dataclasses import asdict, dataclass
from importlib.metadata import distributions, version
from pathlib import Path

import numpy as np

SR, HOP, FRAME = 16000, 160, 2048
DT, MIN_SECONDS, CHANGE_FRAMES = HOP / SR, 0.080, 5
ARMS = ('pitch_runs', 'pitch_hysteresis', 'pitch_hysteresis_reattack')
CASES = tuple(f'vocadito_{i}' for i in range(1, 41))
ARCHIVE_BYTES, ARCHIVE_MD5 = 58492257, 'dea40fd18f14d899643c4ba221b33a46'
SETTINGS = {
    'sr': SR, 'hop': HOP, 'frame': FRAME, 'fmin': 55., 'fmax': 880.,
    'center': True, 'a4_hz': 440., 'minimum_note_seconds': MIN_SECONDS,
    'change_support_frames': CHANGE_FRAMES, 'gap_fill': False,
    'time_shift_seconds': 0., 'global_tuning_correction': False,
    'attack_n_fft': 512, 'attack_n_mels': 64, 'attack_delta': .2, 'attack_wait_frames': 8,
    'reattack_stability_half_window_frames': 3,
    'reattack_median_pitch_distance': .35, 'reattack_pitch_spread': .75,
    'reattack_voiced_probability': .8,
}


@dataclass(frozen=True)
class Note:
    pitch: int
    onset: float
    offset: float
    is_drum: bool = False


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def labels_from_hz(hz, support=1):
    """Never fill unvoiced gaps; persistent changes are backdated to first evidence."""
    hz = np.asarray(hz, dtype=float)
    if hz.ndim != 1 or not np.isfinite(hz).all() or np.any(hz < 0) or support < 1:
        raise ValueError('invalid F0 observations')
    voiced = hz > 0
    raw = np.full(hz.shape, -1, dtype=int)
    raw[voiced] = np.rint(69 + 12 * np.log2(hz[voiced] / 440)).astype(int)
    if np.any(raw[voiced] < 0) or np.any(raw[voiced] > 127):
        raise ValueError('pitch outside MIDI domain')
    out = np.full_like(raw, -1)
    state, pending, begin = -1, -1, 0
    for i, pitch in enumerate(raw):
        if pitch < 0:
            state, pending = -1, -1
            continue
        if state < 0:
            state = int(pitch)
        out[i] = state
        if pitch == state:
            pending = -1
            continue
        if pitch != pending:
            pending, begin = int(pitch), i
        if i - begin + 1 >= support:
            state = pending
            out[begin:i + 1] = state
            pending = -1
    return out


def notes_from_labels(labels, duration):
    labels = np.asarray(labels)
    if (labels.ndim != 1 or not np.issubdtype(labels.dtype, np.integer)
            or np.any(labels < -1) or np.any(labels > 127)
            or not math.isfinite(duration) or duration < 0):
        raise ValueError('invalid segment input')
    result, begin = [], 0
    for end in range(1, len(labels) + 1):
        if end == len(labels) or labels[end] != labels[begin]:
            start_time, end_time = begin * DT, min(end * DT, duration)
            if labels[begin] >= 0 and end_time - start_time >= MIN_SECONDS - 1e-10:
                result.append(Note(int(labels[begin]), start_time, end_time))
            begin = end
    return result


def reattack_split(notes, attacks, hz, voiced_probability):
    """Only split stable interiors; do not move existing note onsets or offsets."""
    attacks = np.asarray(attacks, dtype=float)
    hz, prob = np.asarray(hz, dtype=float), np.asarray(voiced_probability, dtype=float)
    if (attacks.ndim != 1 or not np.isfinite(attacks).all() or np.any(attacks < 0)
            or np.any(np.diff(attacks) <= 0) or hz.ndim != 1 or prob.shape != hz.shape
            or not np.isfinite(hz).all() or np.any(hz < 0)
            or not np.isfinite(prob).all() or np.any(prob < 0) or np.any(prob > 1)):
        raise ValueError('invalid reattack observations')
    result = []
    for note in notes:
        start = note.onset
        for attack in attacks:
            if attack - start < MIN_SECONDS or note.offset - attack < MIN_SECONDS:
                continue
            frame = int(round(attack / DT))
            lo, hi = frame - 3, frame + 4
            if lo < 0 or hi > len(hz) or np.any(hz[lo:hi] <= 0):
                continue
            pitch = 69 + 12 * np.log2(hz[lo:hi] / 440)
            if (abs(float(np.median(pitch)) - note.pitch) > .35
                    or float(np.ptp(pitch)) > .75 or float(np.median(prob[lo:hi])) < .8):
                continue
            result.append(Note(note.pitch, start, float(attack)))
            start = float(attack)
        result.append(Note(note.pitch, start, note.offset))
    return result


def infer(samples):
    import librosa

    samples = np.asarray(samples, dtype=np.float32)
    if samples.ndim != 1 or not len(samples) or not np.isfinite(samples).all():
        raise ValueError('invalid audio')
    hz, voiced, probability = librosa.pyin(
        samples, sr=SR, fmin=55, fmax=880, frame_length=FRAME, hop_length=HOP,
        center=True, fill_na=np.nan, pad_mode='constant',
    )
    hz = np.where(voiced & np.isfinite(hz), hz, 0.)
    env = librosa.onset.onset_strength(y=samples, sr=SR, hop_length=HOP, n_fft=512, n_mels=64, center=True)
    attacks = librosa.onset.onset_detect(
        onset_envelope=env, sr=SR, hop_length=HOP, units='time', backtrack=False,
        normalize=True, pre_max=3, post_max=3, pre_avg=10, post_avg=10, wait=8, delta=.2,
    )
    duration = len(samples) / SR
    raw = notes_from_labels(labels_from_hz(hz), duration)
    stable = notes_from_labels(labels_from_hz(hz, CHANGE_FRAMES), duration)
    arms = dict(zip(ARMS, (raw, stable, reattack_split(stable, attacks, hz, probability))))
    return hz, probability, attacks, arms


def harmonic_evidence(samples, candidate_hz):
    """Diagnostic scores, NOT calibrated confidence or automatic octave correction."""
    x = np.asarray(samples, dtype=float)
    if x.ndim != 1 or len(x) < 32 or not np.isfinite(x).all() or not 55 <= candidate_hz <= 880:
        raise ValueError('invalid spectral input')
    x = x - np.mean(x)
    power = float(np.dot(x, x))
    if power < 1e-12:
        return {'periodicity': 0., 'harmonic_sum': 0.}
    lag = int(round(SR / candidate_hz))
    if lag >= len(x):
        raise ValueError('too short for periodicity')
    denom = np.linalg.norm(x[:-lag]) * np.linalg.norm(x[lag:])
    correlation = float(np.dot(x[:-lag], x[lag:]) / denom) if denom else 0.
    spectrum = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    frequencies = np.fft.rfftfreq(len(x), 1 / SR)
    weights = 1 / np.arange(1, 7, dtype=float)
    amplitudes = np.interp(candidate_hz * np.arange(1, 7), frequencies, spectrum)
    score = float(np.dot(weights, amplitudes) / (max(float(spectrum.max()), 1e-12) * weights.sum()))
    return {'periodicity': correlation, 'harmonic_sum': score}


def synthetic_receipt():
    """Known source-owned waves; diagnostic, not a real-music accuracy benchmark."""
    t = np.arange(SR * 2) / SR
    def sine(f):
        return np.sin(2 * np.pi * f * t)

    envelope = np.where(((t >= .2) & (t < .9)) | ((t >= 1.1) & (t < 1.8)), 1., 0.)
    examples = {
        'sine220': sine(220), 'sine440': sine(440), 'sine880': sine(880),
        'dominant_second': .2 * sine(220) + sine(440) + .5 * sine(660),
        'missing_fundamental': sine(440) + .5 * sine(660),
        'even_harmonics_ambiguous': sine(440) + .5 * sine(880),
        'vibrato': np.sin(2 * np.pi * np.cumsum(440 * 2 ** (.25 * np.sin(2 * np.pi * 5 * t) / 12)) / SR),
        'repeated440': sine(440) * envelope,
        'octave_leap': np.where(t < 1, sine(220), sine(440)),
        'silence': np.zeros(len(t)), 'noise': np.random.default_rng(0).normal(0, .05, len(t)),
    }
    rows = []
    for name, samples in examples.items():
        hz, _, _, arms = infer(samples)
        interior = hz[20:-20]
        v = interior[interior > 0]
        x = samples[int(.3 * SR):int(.8 * SR)]
        spectrum = np.abs(np.fft.rfft(x * np.hanning(len(x))))
        peak = float(np.fft.rfftfreq(len(x), 1 / SR)[int(np.argmax(spectrum))])
        rows.append({'case': name, 'signal_sha256': hashlib.sha256(samples.tobytes()).hexdigest(),
                     'fft_peak_hz': peak, 'voiced_fraction': float((interior > 0).mean()),
                     'median_voiced_hz': float(np.median(v)) if len(v) else None,
                     'note_counts': {a: len(n) for a, n in arms.items()},
                     'candidate_evidence': {str(f): harmonic_evidence(x, f) for f in (110, 220, 440, 880)}})
    return {'scope': 'owned synthetic signals; no production quality approval', 'cases': rows}


def aggregate(rows):
    if (len(rows) != 40 or {r['id'] for r in rows} != set(CASES)
            or any(r.get('status') != 'scored' or set(r.get('arms', {})) != set(ARMS) for r in rows)):
        return None
    result = {}
    for arm in ARMS:
        result[arm] = {}
        for metric in ('onset_f1', 'onset_offset_f1'):
            scores = np.array([np.mean([r['arms'][arm]['annotators'][a][metric] for a in ('A1', 'A2')]) for r in rows])
            base = np.array([np.mean([r['arms'][ARMS[0]]['annotators'][a][metric] for a in ('A1', 'A2')]) for r in rows])
            if not np.isfinite(scores).all() or not np.isfinite(base).all():
                raise ValueError('nonfinite scored metric')
            result[arm][metric] = {'macro': float(scores.mean()), 'delta_vs_runs': float((scores-base).mean()),
                                  'recordings_improved': int((scores > base + 1e-8).sum()),
                                  'recordings_worse': int((scores < base - 1e-8).sum())}
        result[arm]['predicted_notes'] = sum(r['arms'][arm]['count'] for r in rows)
    return result


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, indent=2, allow_nan=False) + '\n')
    temp.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--synthetic-only', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if (args.work.exists() or args.report.exists() or args.work.is_symlink() or args.report.is_symlink()
            or args.work.resolve().is_relative_to(root)
            or os.getenv('HF_TOKEN') or os.getenv('HUGGING_FACE_HUB_TOKEN')):
        parser.error('new private workspace/report and no model credentials required')
    args.work.mkdir(parents=True, mode=0o700)
    started = time.monotonic()
    report = {'status': 'started', 'source_revision': os.getenv('GITHUB_SHA'),
              'script_sha256': digest(Path(__file__)), 'settings': SETTINGS, 'cases': [],
              'python': platform.python_version(), 'platform': platform.platform(),
              'runtime': {d.metadata['Name']: d.version for d in distributions() if d.metadata['Name']},
              'quality_approved': False, 'heldout_generalization': False, 'all_cases_complete': False,
              'device': 'cpu', 'threads': 2, 'training': False, 'llm': False, 'reference_used_for_edits': False}
    save(args.report, report)
    try:
        expected = {'librosa': '0.10.2.post1', 'numpy': '1.26.4', 'scipy': '1.13.1',
                    'mir-eval': '0.8.2', 'numba': '0.60.0', 'soundfile': '0.13.1'}
        if any(version(k) != v for k, v in expected.items()):
            raise ValueError('pinned CPU runtime required')
        if args.synthetic_only:
            report.update(synthetic=synthetic_receipt(), status='synthetic_complete')
        else:
            import librosa
            import mir_eval.transcription as mt

            from scripts.run_cpu_vocadito_candidates import f0_metrics
            from scripts.vocadito_reference import read_notes, score_annotations

            archive = args.archive
            if (archive is None or archive.is_symlink() or archive.stat().st_size != ARCHIVE_BYTES
                    or hashlib.md5(archive.read_bytes()).hexdigest() != ARCHIVE_MD5):
                raise ValueError('original vocadito archive required')
            report.update(archive_sha256=digest(archive), planned_case_ids=list(CASES),
                          scorer_sha256=digest(root / 'scripts/vocadito_reference.py'),
                          f0_scorer_sha256=digest(root / 'scripts/run_cpu_vocadito_candidates.py'))
            with zipfile.ZipFile(archive) as package:
                for case in CASES:
                    directory = args.work / case
                    directory.mkdir()
                    audio = directory / 'source.wav'
                    audio.write_bytes(package.read(f'Audio/{case}.wav'))
                    row = {'id': case, 'audio_sha256': digest(audio), 'status': 'started', 'arms': {}}
                    tick = time.monotonic()
                    try:
                        with (directory / 'private.log').open('w') as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                            y, _ = librosa.load(audio, sr=SR, mono=True)
                            hz, probability, attacks, arms = infer(y)
                            np.savez_compressed(directory / 'observations.npz', hz=hz, probability=probability, attacks=attacks)
                        row['observation_sha256'] = digest(directory / 'observations.npz')
                        # References are first accessed AFTER all predictions have been frozen.
                        frozen = fingerprint({a: [asdict(n) for n in ns] for a, ns in arms.items()})
                        refs = {a: package.read(f'Annotations/Notes/{case}_notes{a}.csv') for a in ('A1', 'A2')}
                        f0_ref = package.read(f'Annotations/F0/{case}_f0.csv')
                        row['reference_sha256'] = {a: hashlib.sha256(v).hexdigest() for a, v in refs.items()}
                        row['f0_reference_sha256'] = hashlib.sha256(f0_ref).hexdigest()
                        row['f0_metrics'] = f0_metrics(f0_ref, np.arange(len(hz)) * DT, hz)
                        for arm, notes in arms.items():
                            save(directory / f'{arm}.json', [asdict(n) for n in notes])
                            entry = {'count': len(notes), 'event_sha256': digest(directory / f'{arm}.json'), 'annotators': {}}
                            for annotator, raw in refs.items():
                                metrics = score_annotations(notes, raw)
                                intervals, pitches = read_notes(raw)
                                pred = np.asarray([(n.onset, n.offset) for n in notes]).reshape(-1, 2)
                                freqs = np.asarray([440 * 2 ** ((n.pitch - 69) / 12) for n in notes])
                                pairs = mt.match_notes(intervals, pitches, pred, freqs, onset_tolerance=.05,
                                                      pitch_tolerance=50, offset_ratio=None) if notes else []
                                metrics.update(onset_matched=len(pairs), unmatched_reference=len(pitches)-len(pairs),
                                               unmatched_prediction=len(notes)-len(pairs),
                                               onset_precision=len(pairs)/len(notes) if notes else 0.,
                                               onset_recall=len(pairs)/len(pitches))
                                entry['annotators'][annotator] = metrics
                            row['arms'][arm] = entry
                        if frozen != fingerprint({a: [asdict(n) for n in ns] for a, ns in arms.items()}) or digest(audio) != row['audio_sha256']:
                            raise ValueError('prediction/source mutation')
                        row['status'] = 'scored'
                    except Exception as exc:
                        row.update(status='failed', error_type=type(exc).__name__)
                        (directory / 'error.txt').write_text(str(exc))
                    row['elapsed_seconds'] = time.monotonic() - tick
                    report['cases'].append(row)
                    save(args.report, report)
                    print(json.dumps({'case': case, 'status': row['status']}), flush=True)
            report['aggregate'] = aggregate(report['cases'])
            report['all_cases_complete'] = report['aggregate'] is not None
            report['status'] = 'complete' if report['all_cases_complete'] else 'incomplete'
    except Exception as exc:
        report.update(status='failed', error_type=type(exc).__name__)
        (args.work / 'error.txt').write_text(str(exc))
    finally:
        report.update(elapsed_seconds=time.monotonic()-started,
                      peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        save(args.report, report)
    return 0 if report['status'] in ('complete', 'synthetic_complete') else 1


if __name__ == '__main__':
    raise SystemExit(main())

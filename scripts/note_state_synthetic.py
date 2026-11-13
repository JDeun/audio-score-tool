"""Fixed authored-F0 controls for issue #291; no acoustic tracker or parameter search."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from scripts import dsp_note_probe as dsp
from scripts import note_state_hmm as legacy
from scripts.note_state_factors import FACTOR_ARMS, infer_factors

ARMS = ('pitch_runs', 'note_state_hmm', *FACTOR_ARMS)
PITCHES = (33, 45, 57, 69, 81)
LENGTHS = (8, 12, 20, 30, 50, 80, 120)
CONTEXTS = ('interior', 'start', 'end', 'full')
GAPS = (0, 1, 2, 5, 10, 30)


@dataclass(frozen=True)
class Case:
    id: str
    kind: str
    pitch: int = 57
    frames: int = 120
    context: str = 'interior'
    gap: int = 0
    interval: int = 0

    @property
    def accuracy_eligible(self):
        return self.kind not in ('silence', 'dropout') and not (self.kind == 'repeat' and self.gap == 0)


def cases():
    result = []

    def add(kind, **kwargs):
        result.append(Case(f'{kind}_{len(result) + 1:03d}', kind, **kwargs))

    for pitch in PITCHES:
        for frames in LENGTHS:
            for context in CONTEXTS:
                add('single', pitch=pitch, frames=frames, context=context)
    for pitch in (45, 57, 69):
        for frames in (12, 30, 80):
            for gap in GAPS:
                add('repeat', pitch=pitch, frames=frames, gap=gap)
    for pitch in (45, 57, 69):
        for interval in (1, 7, 12):
            for frames in (12, 50):
                for gap in (0, 5):
                    add('change', pitch=pitch, frames=frames, interval=interval, gap=gap)
    for frames in (20, 100, 200):
        add('silence', frames=frames, context='full')
    for pitch in (45, 57, 69):
        for kind in ('vibrato', 'drift'):
            add(kind, pitch=pitch)
    for pitch in (45, 57, 69):
        for gap in (1, 5):
            add('dropout', pitch=pitch, gap=gap)
    return tuple(result)


def layout(case):
    left = 30 if case.context in ('interior', 'end') else 0
    right = 30 if case.context in ('interior', 'start') else 0
    length = 2 * case.frames + case.gap if case.kind in ('repeat', 'change') else case.frames
    return left, left + length, left + length + right


def observations(case):
    """Only F0 and duration are passed to the predictor, never case metadata."""
    left, end, total = layout(case)
    midi = np.full(total + 1, np.nan)
    if case.kind != 'silence':
        midi[left:end] = case.pitch
    if case.kind in ('repeat', 'change'):
        midi[left + case.frames:left + case.frames + case.gap] = np.nan
        midi[left + case.frames + case.gap:end] = case.pitch + case.interval
    elif case.kind == 'vibrato':
        midi[left:end] += .3 * np.sin(2 * np.pi * 6 * np.arange(case.frames) * dsp.DT)
    elif case.kind == 'drift':
        midi[left:end] += np.linspace(-.3, .3, case.frames)
    elif case.kind == 'dropout':
        begin = left + case.frames // 2
        midi[begin:begin + case.gap] = np.nan
    if case.context in ('end', 'full') and case.kind != 'silence':
        # A clipped voiced ending must not acquire an artificial Silent observation.
        # The extra centered-clock sample is retained; event time is clipped to duration.
        midi[-1] = midi[-2]
    hz = np.where(np.isfinite(midi), 440 * 2 ** ((midi - 69) / 12), 0.)
    return hz, total * dsp.DT


def truth(case):
    left, end, _ = layout(case)
    if case.kind == 'silence':
        return []
    if case.kind in ('repeat', 'change'):
        return [dsp.Note(case.pitch, left * dsp.DT, (left + case.frames) * dsp.DT),
                dsp.Note(case.pitch + case.interval, (left + case.frames + case.gap) * dsp.DT,
                         end * dsp.DT)]
    return [dsp.Note(case.pitch, left * dsp.DT, end * dsp.DT)]


def alternative_truth(case):
    left, end, _ = layout(case)
    if case.kind == 'repeat' and case.gap == 0:
        return [dsp.Note(case.pitch, left * dsp.DT, end * dsp.DT)]
    if case.kind == 'dropout':
        middle = left + case.frames // 2
        return [dsp.Note(case.pitch, left * dsp.DT, middle * dsp.DT),
                dsp.Note(case.pitch, (middle + case.gap) * dsp.DT, end * dsp.DT)]
    return []


def identity(array):
    a = np.ascontiguousarray(array)
    return {'dtype': a.dtype.str, 'shape': list(a.shape), 'sha256': hashlib.sha256(a.tobytes()).hexdigest()}


def predict(hz, duration):
    labels = dsp.labels_from_hz(hz)
    arms = {'pitch_runs': dsp.notes_from_labels(labels, duration)}
    old = legacy.infer_note_states(hz, duration)
    factors = infer_factors(hz, duration)
    arms['note_state_hmm'] = old['arms']['note_state_hmm']
    arms.update(factors['arms'])
    paths = {'note_state_hmm': old['phase_path'], **factors['paths']}
    diagnostics = {'pitch_runs': {'predicted_notes': len(arms['pitch_runs'])}}
    raw = hz > 0
    for arm, path in paths.items():
        _, counts = legacy.notes_from_state_path(path, hz, duration)
        diagnostics[arm] = {key: value for key, value in counts.items() if not isinstance(value, list)}
        diagnostics[arm]['viterbi_path_log_weight'] = (
            old['diagnostics']['viterbi_path_log_weight'] if arm == 'note_state_hmm'
            else factors['diagnostics'][arm]['viterbi_path_log_weight'])
        voiced = path % 3 != 2
        diagnostics[arm].update(raw_voiced_frames=int(raw.sum()),
            raw_voiced_to_silent_frames=int((raw & ~voiced).sum()),
            raw_unvoiced_to_voiced_frames=int((~raw & voiced).sum()),
            voiced_coverage=float((raw & voiced).sum() / raw.sum()) if raw.any() else None)
    return arms, paths, diagnostics


def score(predicted, reference):
    import mir_eval.transcription as mt

    if not reference:
        raise ValueError('empty truth belongs to the separate silence control')
    ref_intervals = np.asarray([(n.onset, n.offset) for n in reference], dtype=float)
    pred_intervals = np.asarray([(n.onset, n.offset) for n in predicted], dtype=float).reshape(-1, 2)
    ref_hz = np.asarray([440 * 2 ** ((n.pitch - 69) / 12) for n in reference])
    pred_hz = np.asarray([440 * 2 ** ((n.pitch - 69) / 12) for n in predicted])
    result = {}
    for name, ratio in (('onset_f1', None), ('onset_offset_f1', .2)):
        pairs = mt.match_notes(ref_intervals, ref_hz, pred_intervals, pred_hz,
            onset_tolerance=.05, pitch_tolerance=50., offset_ratio=ratio,
            offset_min_tolerance=.05) if predicted else []
        result[name] = 2 * len(pairs) / (len(reference) + len(predicted))
    return result


def emission_analysis():
    """Analytic 2x2 mass table, not a decoded interaction performance arm."""
    grid = legacy.PITCHES
    self_probs = np.array([.9, .99, .9999]) ** (.01 / (256 / 44100))
    rows = []
    for pitch in PITCHES:
        distance = np.abs(pitch - grid)
        allowed = ((distance < 1e-10) | (distance >= 2 / 3 - 1e-10)) & (distance <= 13 + 1e-10)
        jump = np.where(allowed, np.exp(-distance / 2), 0.)
        jump /= jump.sum()
        entry_cost = -math.log((1 - self_probs[2]) * jump[np.argmin(distance)])
        for exponent in (.1, 1.):
            weights = np.stack([np.exp(exponent * (-.5 * ((pitch - grid) / sigma) ** 2
                                - math.log(sigma * math.sqrt(2 * math.pi)))) for sigma in (5., .9)])
            for normalization in ('joint', 'phase_balanced'):
                values = .5 * weights / weights.sum() if normalization == 'joint' else (
                    .25 * weights / weights.sum(axis=1)[:, None])
                silent = .5 / len(grid)
                rows.append({'pitch': pitch, 'gaussian_exponent': exponent,
                    'normalization': normalization, 'attack_mass': float(values[0].sum()),
                    'stable_mass': float(values[1].sum()),
                    'peak_stable_to_silent': float(values[1].max() / silent),
                    'legacy_same_pitch_silent_to_attack_log_cost': float(entry_cost),
                    'stable_vs_silent_log_gain_per_frame_with_legacy_self': float(
                        math.log(values[1].max() / silent) + math.log(self_probs[1] / self_probs[2]))})
    return rows


def summarize(rows):
    eligible = [row for row in rows if row['accuracy_eligible']]
    if len(rows) != 245 or len(eligible) != 227 or any(set(row['arms']) != set(ARMS) for row in rows):
        raise ValueError('incomplete fixed synthetic population')
    result = {}
    for arm in ARMS:
        result[arm] = {'all_cases_predicted_notes': sum(row['arms'][arm]['count'] for row in rows),
            'empty_output_cases': sum(row['arms'][arm]['count'] == 0 for row in rows),
            'silence_false_positive_notes': sum(row['arms'][arm]['count'] for row in rows if row['spec']['kind'] == 'silence'),
            'eligible_cases': len(eligible)}
        for metric in ('onset_f1', 'onset_offset_f1'):
            result[arm][metric] = float(np.mean([row['arms'][arm]['metrics'][metric] for row in eligible]))
        if arm != 'pitch_runs':
            raw = sum(row['arms'][arm]['diagnostics']['raw_voiced_frames'] for row in rows)
            dropped = sum(row['arms'][arm]['diagnostics']['raw_voiced_to_silent_frames'] for row in rows)
            result[arm].update(raw_voiced_frames=raw, raw_voiced_to_silent_frames=dropped,
                               voiced_coverage=1 - dropped / raw)
    return result


def run(work, report_path):
    started = time.monotonic()
    work.mkdir(mode=0o700)
    plan = cases()
    report = {'schema': 'note-state-synthetic-v1', 'status': 'started', 'cases': [],
        'source_revision': os.getenv('GITHUB_SHA'), 'protocol_head_revision': os.getenv('EXPERIMENT_HEAD_SHA'),
        'planned_cases': len(plan), 'planned_arms': list(ARMS), 'acoustic_extraction': False,
        'quality_approved': False, 'heldout_generalization': False,
        'emission_analysis': emission_analysis(), 'aggregate': None}
    dsp.save(report_path, report)
    try:
        for case in plan:
            hz, duration = observations(case)
            arms, paths, diagnostics = predict(hz, duration)
            directory = work / case.id
            directory.mkdir()
            np.savez_compressed(directory / 'observations.npz', hz=hz, **paths)
            row = {'id': case.id, 'spec': asdict(case), 'duration_seconds': duration,
                'accuracy_eligible': case.accuracy_eligible, 'observation': identity(hz), 'arms': {}}
            for arm in ARMS:
                path = directory / f'{arm}.json'
                dsp.save(path, [asdict(n) for n in arms[arm]])
                row['arms'][arm] = {'count': len(arms[arm]), 'event_sha256': dsp.digest(path),
                                    'diagnostics': diagnostics[arm]}
                if arm in paths:
                    row['arms'][arm]['state_path'] = identity(paths[arm])
            report['cases'].append(row)
        report['all_predictions_saved_before_scoring'] = True
        report['predictions_manifest_sha256'] = dsp.fingerprint({r['id']: {
            arm: r['arms'][arm]['event_sha256'] for arm in ARMS} for r in report['cases']})
        for case, row in zip(plan, report['cases'], strict=True):
            reference = truth(case)
            row['truth'] = [asdict(n) for n in reference]
            row['alternative_truth'] = [asdict(n) for n in alternative_truth(case)]
            for arm in ARMS:
                path = work / case.id / f'{arm}.json'
                if dsp.digest(path) != row['arms'][arm]['event_sha256']:
                    raise ValueError('synthetic prediction mutation')
                notes = [dsp.Note(**n) for n in json.loads(path.read_text())]
                row['arms'][arm]['events'] = [asdict(n) for n in notes]
                row['arms'][arm]['metrics'] = score(notes, reference) if case.accuracy_eligible else None
        report['aggregate'] = summarize(report['cases'])
        report['status'] = 'complete'
    except Exception as exc:
        report.update(status='failed', error_type=type(exc).__name__)
        (work / 'error.txt').write_text(str(exc))
    finally:
        report['elapsed_seconds'] = time.monotonic() - started
        dsp.save(report_path, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if any(path.exists() or path.is_symlink() or path.resolve().is_relative_to(root)
           for path in (args.work, args.report)):
        parser.error('new work and report outside checkout required')
    return 0 if run(args.work, args.report)['status'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())

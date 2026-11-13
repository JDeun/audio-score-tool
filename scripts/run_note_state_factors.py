"""Frozen one-factor CPU diagnosis of note-state decoding; research only."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import platform
import resource
import time
import zipfile
from dataclasses import asdict
from importlib.metadata import distributions, version
from pathlib import Path

import numpy as np

from scripts import dsp_note_probe as dsp
from scripts import run_note_state_experiment as legacy
from scripts.note_state_factors import FACTOR_ARMS, infer_factors
from scripts.note_state_factors import SETTINGS as FACTOR_SETTINGS
from scripts.note_state_hmm import SETTINGS as HMM_SETTINGS

ARMS = (*legacy.ARMS, *FACTOR_ARMS)
CASES = dsp.CASES
ANNOTATORS = ('A1', 'A2')
BASELINE_ZIP_SHA256 = '6bc477457a89403c7bb18f331d862555f4d963db4a227472bb19d63644d39541'
EXPECTED_RUNTIME = {
    'librosa': '0.10.2.post1', 'numpy': '1.26.4', 'scipy': '1.13.1',
    'mir-eval': '0.8.2', 'numba': '0.60.0', 'soundfile': '0.13.1',
    'resampy': '0.4.2', 'soxr': '1.1.0',
}
HMM_ZIP_SHA256 = '46ea77a90750172a905750599db3b419f09d70d165ef0be221e0004b8cd61b26'
HMM_RECEIPT = 'docs/research/receipts/note-state-hmm-43336542480.zip'
SOURCE_PATHS = (*legacy.SOURCE_PATHS,
    'scripts/note_state_factors.py', 'scripts/run_note_state_factors.py',
    'scripts/audit_note_state_factors.py', 'scripts/note_state_synthetic.py',
    'tests/test_note_state_factors.py', 'tests/test_run_note_state_factors.py',
    'tests/test_audit_note_state_factors.py', 'tests/test_note_state_synthetic.py',
    '.github/workflows/cpu-note-state-factors.yml',
    'docs/research/NOTE_STATE_FACTORS_PROTOCOL_2026-11-13.md',
    'docs/research/TONY_NOTE_HMM_SOURCE_AUDIT_2026-11-13.md', HMM_RECEIPT,
)



def array_identity(array):
    array = np.ascontiguousarray(array)
    if array.dtype.hasobject or not np.isfinite(array).all():
        raise ValueError('finite numeric observations required')
    return {'dtype': array.dtype.str, 'shape': list(array.shape),
            'sha256': hashlib.sha256(array.tobytes()).hexdigest()}


def scalar_diagnostics(value):
    """Publish counts/settings, not the private segment readouts or full paths."""
    if isinstance(value, dict):
        return {k: scalar_diagnostics(v) for k, v in value.items()
                if isinstance(v, (dict, str, int, float, bool)) or v is None}
    return value


def prediction_manifest(rows, work):
    if (len(rows) != len(CASES) or {r['id'] for r in rows} != set(CASES)
            or any(r.get('status') not in ('predicted', 'scored')
                   or set(r.get('arms', {})) != set(ARMS) for r in rows)):
        raise ValueError('all planned predictions must precede the first reference read')
    manifest = {}
    for row in rows:
        manifest[row['id']] = {}
        for arm in ARMS:
            actual = dsp.digest(work / row['id'] / f'{arm}.json')
            if actual != row['arms'][arm]['event_sha256']:
                raise ValueError('prediction changed after freezing')
            manifest[row['id']][arm] = actual
    return dsp.fingerprint(manifest)


def infer_recording(audio):
    # One unchanged pYIN extraction and all five old controls, then five OAT arms.
    arrays, arms, diagnostics, duration = legacy.infer_recording(audio)
    factors = infer_factors(arrays['hz'], duration)
    arms.update(factors['arms'])
    arrays.update({name + '_path': path for name, path in factors['paths'].items()})
    return arrays, arms, {'legacy': diagnostics, 'factors': factors['diagnostics']}, duration


def predict_all(package, work, report, report_path):
    """The only archive members opened in this entire pass are the forty WAVs."""
    for case in CASES:
        directory = work / case
        directory.mkdir()
        row = {'id': case, 'status': 'started', 'arms': {}}
        tick = time.monotonic()
        try:
            audio = directory / 'source.wav'
            audio.write_bytes(package.read(f'Audio/{case}.wav'))
            row['audio_sha256'] = dsp.digest(audio)
            with (directory / 'private.log').open('w') as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                arrays, arms, diagnostics, duration = infer_recording(audio)
            if set(arms) != set(ARMS):
                raise ValueError('missing or extra prediction arm')
            np.savez_compressed(directory / 'observations.npz', **arrays)
            row.update(duration_seconds=duration, observations={k: array_identity(v) for k, v in arrays.items()},
                       observation_sha256=dsp.digest(directory / 'observations.npz'),
                       diagnostics=scalar_diagnostics(diagnostics))
            for arm in ARMS:
                dsp.save(directory / f'{arm}.json', [asdict(n) for n in arms[arm]])
                row['arms'][arm] = {'count': len(arms[arm]),
                                    'event_sha256': dsp.digest(directory / f'{arm}.json'), 'annotators': {}}
            if dsp.digest(audio) != row['audio_sha256']:
                raise ValueError('source mutation during prediction')
            row['status'] = 'predicted'
        except Exception as exc:
            row.update(status='prediction_failed', error_type=type(exc).__name__)
            (directory / 'error.txt').write_text(str(exc))
        row['inference_seconds'] = time.monotonic() - tick
        report['cases'].append(row)
        dsp.save(report_path, report)
        print(json.dumps({'case': case, 'phase': 'prediction', 'status': row['status']}), flush=True)
    report['predictions_manifest_sha256'] = prediction_manifest(report['cases'], work)
    report['all_predictions_frozen_before_references'] = True
    dsp.save(report_path, report)


def matching_metrics(notes, raw):
    import mir_eval.transcription as mt

    from scripts.vocadito_reference import read_notes, score_annotations

    intervals, pitches = read_notes(raw)
    pred = np.asarray([(n.onset, n.offset) for n in notes], dtype=float).reshape(-1, 2)
    frequencies = np.asarray([440 * 2 ** ((n.pitch - 69) / 12) for n in notes])
    metrics = score_annotations(notes, raw)
    ids = {}
    for prefix, ratio in (('onset', None), ('onset_offset', .2)):
        pairs = mt.match_notes(intervals, pitches, pred, frequencies, onset_tolerance=.05,
                               pitch_tolerance=50, offset_ratio=ratio,
                               offset_min_tolerance=.05) if notes else []
        ids[prefix] = {int(i) for i, _ in pairs}
        precision, recall = len(pairs) / len(notes) if notes else 0., len(pairs) / len(pitches)
        metrics.update({prefix + '_matched': len(pairs), prefix + '_unmatched_reference': len(pitches) - len(pairs),
                        prefix + '_unmatched_prediction': len(notes) - len(pairs)})
        names = ('onset_precision', 'onset_recall') if prefix == 'onset' else ('offset_precision', 'offset_recall')
        metrics.update(zip(names, (precision, recall)))
    return metrics, ids


def score_case(package, row, work):
    from scripts.run_cpu_vocadito_candidates import f0_metrics

    directory = work / row['id']
    refs = {a: package.read(f"Annotations/Notes/{row['id']}_notes{a}.csv") for a in ANNOTATORS}
    raw_f0 = package.read(f"Annotations/F0/{row['id']}_f0.csv")
    row['reference_sha256'] = {a: hashlib.sha256(v).hexdigest() for a, v in refs.items()}
    row['f0_reference_sha256'] = hashlib.sha256(raw_f0).hexdigest()
    for a, raw in refs.items():
        (directory / f'{a}.csv').write_bytes(raw)
    (directory / 'f0.csv').write_bytes(raw_f0)
    with np.load(directory / 'observations.npz', allow_pickle=False) as observations:
        if {k: array_identity(observations[k]) for k in observations.files} != row['observations']:
            raise ValueError('observations changed before evaluation')
        hz = observations['hz']
        row['f0_metrics'] = f0_metrics(raw_f0, np.arange(len(hz)) * dsp.DT, hz)
    baseline_ids = {}
    for arm in ARMS:
        path = directory / f'{arm}.json'
        if dsp.digest(path) != row['arms'][arm]['event_sha256']:
            raise ValueError('prediction mutation before evaluation')
        notes = [dsp.Note(**n) for n in json.loads(path.read_text())]
        for a, raw in refs.items():
            metrics, ids = matching_metrics(notes, raw)
            if arm == ARMS[0]:
                baseline_ids[a] = ids
            for prefix in ids:
                metrics[prefix + '_gained_reference_ids'] = sorted(ids[prefix] - baseline_ids[a][prefix])
                metrics[prefix + '_lost_reference_ids'] = sorted(baseline_ids[a][prefix] - ids[prefix])
            row['arms'][arm]['annotators'][a] = metrics
    if dsp.digest(directory / 'source.wav') != row['audio_sha256']:
        raise ValueError('source mutation during evaluation')
    row['status'] = 'scored'


def evaluate_all(package, work, report, report_path):
    # Check the files again, not just an assertion recorded by the prediction pass.
    if prediction_manifest(report['cases'], work) != report['predictions_manifest_sha256']:
        raise ValueError('prediction manifest mutation')
    if not report.get('all_predictions_frozen_before_references'):
        raise ValueError('no frozen prediction barrier')
    report['reference_access_started_after_predicted_cases'] = len(report['cases'])
    for row in report['cases']:
        try:
            score_case(package, row, work)
        except Exception as exc:
            row.update(status='evaluation_failed', error_type=type(exc).__name__)
            (work / row['id'] / 'error.txt').write_text(str(exc))
        dsp.save(report_path, report)
        print(json.dumps({'case': row['id'], 'phase': 'evaluation', 'status': row['status']}), flush=True)
    if all(r['status'] == 'scored' for r in report['cases']):
        report['post_evaluation_predictions_manifest_sha256'] = prediction_manifest(report['cases'], work)
        if report['post_evaluation_predictions_manifest_sha256'] != report['predictions_manifest_sha256']:
            raise ValueError('prediction mutation after evaluation')


def aggregate(rows):
    if (len(rows) != len(CASES) or {r['id'] for r in rows} != set(CASES)
            or any(r.get('status') != 'scored' or set(r.get('arms', {})) != set(ARMS)
                   or any(set(r['arms'][arm].get('annotators', {})) != set(ANNOTATORS) for arm in ARMS)
                   for r in rows)):
        return None
    result = {}
    for arm in ARMS:
        result[arm] = {'predicted_notes': sum(r['arms'][arm]['count'] for r in rows)}
        for metric in ('onset_f1', 'onset_offset_f1'):
            values = np.asarray([[r['arms'][arm]['annotators'][a][metric] for a in ANNOTATORS] for r in rows])
            baseline = np.asarray([[r['arms'][ARMS[0]]['annotators'][a][metric] for a in ANNOTATORS] for r in rows])
            if not np.isfinite(values).all() or np.any(values < 0) or np.any(values > 1):
                raise ValueError('invalid score')
            delta = values.mean(axis=1) - baseline.mean(axis=1)
            result[arm][metric] = {'macro': float(values.mean()),
                'A1_macro': float(values[:, 0].mean()), 'A2_macro': float(values[:, 1].mean()),
                'delta_vs_runs': float(delta.mean()),
                'recordings_improved': int((delta > 1e-8).sum()),
                'recordings_worse': int((delta < -1e-8).sum()),
                'recordings_tied': int((np.abs(delta) <= 1e-8).sum())}
        for metric in ('onset_precision', 'onset_recall', 'offset_precision', 'offset_recall'):
            result[arm][metric] = float(np.mean([r['arms'][arm]['annotators'][a][metric]
                                               for r in rows for a in ANNOTATORS]))
        for prefix in ('onset', 'onset_offset'):
            for suffix in ('gained_reference_ids', 'lost_reference_ids'):
                result[arm][prefix + '_' + suffix.replace('_ids', '_count')] = sum(
                    len(r['arms'][arm]['annotators'][a][prefix + '_' + suffix]) for r in rows for a in ANNOTATORS)
    return result


def baseline_parity(report, path):
    if dsp.digest(path) != BASELINE_ZIP_SHA256:
        raise ValueError('wrong archived baseline ZIP')
    with zipfile.ZipFile(path) as archive:
        old = json.loads(archive.read('vocadito.json'))
    checks = {'archive': report['archive_sha256'] == old['archive_sha256'],
              'extractor': report['source_sha256']['scripts/dsp_note_probe.py'] == old['script_sha256'],
              'scorer': report['source_sha256']['scripts/vocadito_reference.py'] == old['scorer_sha256'],
              'f0_scorer': report['source_sha256']['scripts/run_cpu_vocadito_candidates.py'] == old['f0_scorer_sha256']}
    old_rows = {r['id']: r for r in old['cases']}
    differences = []
    for row in report['cases']:
        prior = old_rows[row['id']]
        for field in ('audio_sha256', 'reference_sha256', 'f0_reference_sha256', 'f0_metrics'):
            if row.get(field) != prior.get(field):
                differences.append({'case': row['id'], 'field': field})
        for arm in dsp.ARMS:
            current, previous = row['arms'][arm], prior['arms'][arm]
            for field in ('count', 'event_sha256'):
                if current[field] != previous[field]:
                    differences.append({'case': row['id'], 'arm': arm, 'field': field})
            for a in ANNOTATORS:
                for field in ('reference_note_count', 'onset_f1', 'onset_offset_f1',
                              'onset_matched', 'onset_precision', 'onset_recall'):
                    if current['annotators'][a][field] != previous['annotators'][a][field]:
                        differences.append({'case': row['id'], 'arm': arm, 'annotator': a, 'field': field})
    return {'baseline_zip_sha256': BASELINE_ZIP_SHA256, 'source_checks': checks,
            'differences': differences, 'all_equal': all(checks.values()) and not differences,
            'raw_historical_f0_bytes_available': False}


def historical_parity(report, path):
    """Compare exact stored identities, not unavailable old raw arrays."""
    if dsp.digest(path) != HMM_ZIP_SHA256:
        raise ValueError('wrong archived HMM ZIP')
    with zipfile.ZipFile(path) as archive:
        old = json.loads(archive.read('vocadito.json'))
    source_checks = {name: report['source_sha256'].get(name) == value
                     for name, value in old['source_sha256'].items()}
    source_checks['archive'] = report['archive_sha256'] == old['archive_sha256']
    prior_rows = {row['id']: row for row in old['cases']}
    differences = []
    compared_arrays = compared_predictions = 0
    for row in report['cases']:
        prior = prior_rows[row['id']]
        for field in ('audio_sha256', 'duration_seconds', 'reference_sha256',
                      'f0_reference_sha256', 'f0_metrics'):
            if row.get(field) != prior.get(field):
                differences.append({'case': row['id'], 'field': field})
        if row.get('diagnostics', {}).get('legacy') != prior.get('diagnostics'):
            differences.append({'case': row['id'], 'field': 'legacy_diagnostics'})
        for name, identity in prior['observations'].items():
            compared_arrays += 1
            if row.get('observations', {}).get(name) != identity:
                differences.append({'case': row['id'], 'observation': name})
        for arm in legacy.ARMS:
            compared_predictions += 1
            if row['arms'][arm] != prior['arms'][arm]:
                differences.append({'case': row['id'], 'arm': arm, 'field': 'prediction_and_scores'})
    return {'baseline_zip_sha256': HMM_ZIP_SHA256, 'source_checks': source_checks,
            'differences': differences, 'all_equal': all(source_checks.values()) and not differences
                and compared_arrays == 240 and compared_predictions == 200,
            'compared_observation_arrays': compared_arrays,
            'compared_prediction_files': compared_predictions,
            'raw_historical_arrays_available': False, 'array_identity_available': True}


def primary_summary(rows):
    """Paired recording-level descriptive interval on the reused development set."""
    if aggregate(rows) is None:
        raise ValueError('complete cohort required for primary contrast')
    by_id = {row['id']: row for row in rows}
    delta = np.asarray([np.mean([
        by_id[case]['arms']['gaussian_exponent_1']['annotators'][a]['onset_offset_f1']
        - by_id[case]['arms']['note_state_hmm']['annotators'][a]['onset_offset_f1']
        for a in ANNOTATORS]) for case in CASES])
    indices = np.random.default_rng(291).integers(0, len(CASES), size=(10000, len(CASES)))
    low, high = np.quantile(delta[indices].mean(axis=1), [.025, .975], method='linear')
    return {'candidate': 'gaussian_exponent_1', 'baseline': 'note_state_hmm',
            'metric': 'onset_offset_f1',
            'paired_recording_deltas': [{'id': case, 'delta': float(d)}
                                       for case, d in zip(CASES, delta, strict=True)],
            'mean_delta': float(delta.mean()),
            'recordings_improved': int((delta > 1e-8).sum()),
            'recordings_worse': int((delta < -1e-8).sum()),
            'recordings_tied': int((np.abs(delta) <= 1e-8).sum()),
            'bootstrap': {'resampling_unit': 'recording_mean_of_A1_A2', 'seed': 291,
                          'resamples': 10000, 'confidence_level': .95,
                          'method': 'paired_percentile_linear', 'low': float(low), 'high': float(high)},
            'heldout_generalization': False}


def finalize_results(report, baseline, previous):
    report['aggregate'] = aggregate(report['cases'])
    report['all_cases_complete'] = report['aggregate'] is not None
    if not report['all_cases_complete']:
        report['status'] = 'incomplete'
        return
    report['historical_baseline_parity'] = baseline_parity(report, baseline)
    report['historical_hmm_parity'] = historical_parity(report, previous)
    report['primary_result'] = primary_summary(report['cases'])
    report['status'] = ('complete' if report['historical_baseline_parity']['all_equal']
                        and report['historical_hmm_parity']['all_equal'] else 'baseline_parity_failed')


def run(archive, work, report_path, baseline, previous):
    root = Path(__file__).resolve().parents[1]
    started = time.monotonic()
    work.mkdir(mode=0o700)
    report = {'schema': 'note-state-factors-v1', 'status': 'started', 'cases': [],
        'planned_case_ids': list(CASES), 'planned_arms': list(ARMS),
        'source_revision': os.getenv('GITHUB_SHA'), 'protocol_head_revision': os.getenv('EXPERIMENT_HEAD_SHA'),
        'source_sha256': {p: dsp.digest(root / p) for p in SOURCE_PATHS},
        'python': platform.python_version(), 'platform': platform.platform(),
        'runtime': {d.metadata['Name']: d.version for d in distributions() if d.metadata['Name']},
        'f0_settings': dsp.SETTINGS, 'hmm_settings': HMM_SETTINGS, 'factor_settings': FACTOR_SETTINGS,
        'primary_comparison': {'candidate': 'gaussian_exponent_1', 'baseline': 'note_state_hmm', 'metric': 'onset_offset_f1'},
        'quality_approved': False, 'heldout_generalization': False, 'product_changes': False,
        'all_cases_complete': False, 'reference_used_for_edits': False, 'device': 'cpu', 'threads': 2,
        'aggregate': None, 'all_predictions_frozen_before_references': False}
    dsp.save(report_path, report)
    try:
        if any(version(k) != v for k, v in EXPECTED_RUNTIME.items()):
            raise ValueError('pinned research runtime required')
        if (archive.is_symlink() or archive.stat().st_size != dsp.ARCHIVE_BYTES
                or hashlib.md5(archive.read_bytes()).hexdigest() != dsp.ARCHIVE_MD5):
            raise ValueError('unchanged original vocadito archive required')
        report['archive_sha256'] = dsp.digest(archive)
        with zipfile.ZipFile(archive) as package:
            predict_all(package, work, report, report_path)
            evaluate_all(package, work, report, report_path)
        finalize_results(report, baseline, previous)
    except Exception as exc:
        report.update(status='failed', error_type=type(exc).__name__)
        (work / 'error.txt').write_text(str(exc))
    finally:
        report.update(elapsed_seconds=time.monotonic() - started,
                      peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        dsp.save(report_path, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--previous', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if (args.work.exists() or args.report.exists() or args.work.is_symlink() or args.report.is_symlink()
            or args.work.resolve().is_relative_to(root) or args.report.resolve().is_relative_to(root)
            or os.getenv('HF_TOKEN') or os.getenv('HUGGING_FACE_HUB_TOKEN')):
        parser.error('new private work/report outside checkout and no model credentials required')
    result = run(args.archive, args.work, args.report, args.baseline, args.previous)
    return 0 if result['status'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())

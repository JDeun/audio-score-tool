"""One frozen readout factor on shared Gaussian paths; all predictions precede refs."""
from __future__ import annotations

import argparse
import contextlib
import copy
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
from scripts import note_boundary_diagnostics as boundary
from scripts import run_note_boundary_diagnostics as prior
from scripts import run_note_state_factors as frozen
from scripts.audit_note_state_experiment import parse_notes, parse_reference
from scripts.note_boundary_readout import ARM, BASE_ARM, notes_from_state_path

ROOT = Path(__file__).resolve().parents[1]
CASES, ANNOTATORS = frozen.CASES, frozen.ANNOTATORS
ARMS = (*frozen.ARMS, ARM)
DIAGNOSTIC_ARMS = ('pitch_runs', BASE_ARM, 'note_state_hmm', ARM)
PREVIOUS = 'docs/research/receipts/note-boundary-diagnostics-43370790419.zip'
PREVIOUS_SHA256 = '43b439e665eb470ec1b24179697cc99d2733fecb6122d1da6a77125d8e3ccf31'
NEW_SOURCE_PATHS = (
    'scripts/note_boundary_readout.py', 'scripts/run_note_boundary_readout.py',
    'scripts/note_boundary_readout_synthetic.py', 'scripts/audit_note_boundary_readout.py',
    'tests/test_note_boundary_readout.py', 'tests/test_run_note_boundary_readout.py',
    'tests/test_note_boundary_readout_synthetic.py', 'tests/test_audit_note_boundary_readout.py',
    '.github/workflows/cpu-note-boundary-readout.yml',
    'docs/research/NOTE_BOUNDARY_READOUT_PROTOCOL_2026-11-13.md',
    'docs/research/NOTE_BOUNDARY_READOUT_EXECUTION_2026-11-13.md', PREVIOUS,
)
SOURCE_PATHS = (*prior.SOURCE_PATHS, *NEW_SOURCE_PATHS)
ROW_ADDITIONS = frozenset(('readout', 'readout_private_sha256',
                           'annotation_diagnostics', 'annotation_private_sha256'))
SETTINGS = {
    'candidate': ARM, 'baseline': BASE_ARM, 'raw_hysteresis_support_frames': 5,
    'candidate_cut': 'adjacent_nonnegative_different_global_raw_hysteresis_labels',
    'applied_cut': 'strictly_inside_original_G_pitch_segment_and_before_clipped_audio_end',
    'pitch': 'original_positive_raw_MIDI_median_then_numpy_rint_per_child',
    'minimum_seconds': .08, 'shared_G_path': True, 'raw_zero_gate_added': False,
    'existing_boundaries_removed': False, 'timestamp_shift_seconds': 0.,
    'bootstrap_seed': 296, 'bootstrap_resamples': 10000,
    'private_details': 'parent_child_times_pitches_and_annotation_pair_rows',
}


def prediction_manifest(rows, work):
    if (len(rows) != len(CASES) or {r['id'] for r in rows} != set(CASES)
            or any(r.get('status') not in ('predicted', 'scored')
                   or set(r.get('arms', {})) != set(ARMS) for r in rows)):
        raise ValueError('all 440 planned predictions must precede the first reference read')
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
    arrays, arms, diagnostics, duration = frozen.infer_recording(audio)
    notes, readout, trace = notes_from_state_path(
        arrays[BASE_ARM + '_path'], arrays['hz'], duration)
    if [asdict(n) for n in arms[BASE_ARM]] != [
            {'pitch': p['original']['pitch'], 'onset': p['original']['onset_seconds'],
             'offset': p['original']['offset_seconds'], 'is_drum': False}
            for p in trace['parents'] if p['original']['emitted']]:
        raise ValueError('original G parent reconstruction differs')
    arms[ARM] = notes
    return arrays, arms, diagnostics, duration, readout, trace


def predict_all(package, work, report, report_path):
    """Only WAV archive members are opened; all eleven arms share one pYIN pass."""
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
                arrays, arms, diagnostics, duration, readout, trace = infer_recording(audio)
            if set(arms) != set(ARMS):
                raise ValueError('missing or extra prediction arm')
            np.savez_compressed(directory / 'observations.npz', **arrays)
            dsp.save(directory / 'readout-private.json', trace)
            row.update(duration_seconds=duration,
                       observations={k: frozen.array_identity(v) for k, v in arrays.items()},
                       observation_sha256=dsp.digest(directory / 'observations.npz'),
                       diagnostics=frozen.scalar_diagnostics(diagnostics), readout=readout,
                       readout_private_sha256=dsp.digest(directory / 'readout-private.json'))
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


def comparison_sets(details, reference_count):
    result = {}
    for baseline in ('pitch_runs', BASE_ARM):
        result[baseline] = {}
        for criterion, field in (('onset', 'onset_pairs'), ('onset_offset', 'offset_pairs')):
            def ids(arm):
                return {p['reference_id'] if field == 'onset_pairs' else p[0]
                        for p in details[arm][field]}
            before, after = ids(baseline), ids(ARM)
            result[baseline][criterion] = {
                'retained': sorted(before & after), 'gained': sorted(after - before),
                'lost': sorted(before - after),
                'neither': sorted(set(range(reference_count)) - before - after)}
    return result


def pruning_harm(details, comparisons, trace):
    """Overlapping descriptors of lost G matches, not exclusive causal labels."""
    parents = {p['original']['prediction_index']: p for p in trace['parents']
               if p['original']['emitted']}
    result = {}
    for criterion, field in (('onset', 'onset_pairs'), ('onset_offset', 'offset_pairs')):
        pairs = {p['reference_id']: p['prediction_id'] for p in details[BASE_ARM][field]} if field == 'onset_pairs' else dict(details[BASE_ARM][field])
        lost = comparisons[BASE_ARM][criterion]['lost']
        matched = [parents[pairs[i]] for i in lost]
        result[criterion] = {
            'lost_references': len(lost),
            'lost_matched_parent_cut': sum(bool(p['applied_cut_frames']) for p in matched),
            'lost_matched_parent_with_short_children': sum(
                any(c['discard_reason'] == 'short' for c in p['children']) for p in matched),
            'lost_matched_parent_all_children_pruned': sum(
                not any(c['emitted'] for c in p['children']) for p in matched),
        }
    return result


def summarize_annotations(annotations):
    result = {'recording_annotations': len(annotations),
              'reference_notes': sum(a['reference_notes'] for a in annotations), 'arms': {}}
    for arm in DIAGNOSTIC_ARMS:
        details = [a['arms'][arm] for a in annotations]
        result['arms'][arm] = {
            'predicted_notes': sum(d['predicted_notes'] for d in details),
            'onset_matched': sum(len(d['onset_pairs']) for d in details),
            'offset_matched': sum(len(d['offset_pairs']) for d in details),
            'fixed_onset_pairs': boundary.fixed_pair_summary([p for d in details for p in d['onset_pairs']]),
        }
    result['comparisons'] = {baseline: {criterion: {
        part: sum(len(a['comparisons'][baseline][criterion][part]) for a in annotations)
        for part in ('retained', 'gained', 'lost', 'neither')}
        for criterion in ('onset', 'onset_offset')} for baseline in ('pitch_runs', BASE_ARM)}
    result['pruning_harm'] = {criterion: {
        key: sum(a['pruning_harm'][criterion][key] for a in annotations)
        for key in ('lost_references', 'lost_matched_parent_cut',
                    'lost_matched_parent_with_short_children',
                    'lost_matched_parent_all_children_pruned')}
        for criterion in ('onset', 'onset_offset')}
    return result


def analyze_annotations(row, work):
    directory = work / row['id']
    if dsp.digest(directory / 'readout-private.json') != row['readout_private_sha256']:
        raise ValueError('readout private trace changed')
    trace = prior.read_json(directory / 'readout-private.json')
    predictions = {}
    for arm in DIAGNOSTIC_ARMS:
        path = directory / f'{arm}.json'
        if dsp.digest(path) != row['arms'][arm]['event_sha256']:
            raise ValueError('diagnostic prediction changed')
        _, intervals, hz = parse_notes(path.read_bytes(), row['duration_seconds'])
        predictions[arm] = intervals, hz
    annotations = {}
    for annotator in ANNOTATORS:
        path = directory / f'{annotator}.csv'
        if dsp.digest(path) != row['reference_sha256'][annotator]:
            raise ValueError('diagnostic reference changed')
        reference = parse_reference(path.read_bytes())
        details = {arm: boundary._arm_detail(reference, predictions[arm]) for arm in DIAGNOSTIC_ARMS}
        comparisons = comparison_sets(details, len(reference[0]))
        annotations[annotator] = {
            'reference_notes': len(reference[0]), 'arms': details, 'comparisons': comparisons,
            'pruning_harm': pruning_harm(details, comparisons, trace),
        }
    dsp.save(directory / 'annotation-private.json', annotations)
    row['annotation_private_sha256'] = dsp.digest(directory / 'annotation-private.json')
    row['annotation_diagnostics'] = {a: summarize_annotations([annotations[a]]) for a in ANNOTATORS}


def score_case(package, row, work):
    # The unchanged scorer populates all ten old arms, references and F0 metrics.
    frozen.score_case(package, row, work)
    directory = work / row['id']
    path = directory / f'{ARM}.json'
    if dsp.digest(path) != row['arms'][ARM]['event_sha256']:
        raise ValueError('new prediction mutation before evaluation')
    notes = [dsp.Note(**n) for n in prior.read_json(path)]
    runs = [dsp.Note(**n) for n in prior.read_json(directory / 'pitch_runs.json')]
    for a in ANNOTATORS:
        raw = (directory / f'{a}.csv').read_bytes()
        metrics, ids = frozen.matching_metrics(notes, raw)
        _, baseline_ids = frozen.matching_metrics(runs, raw)
        for prefix in ids:
            metrics[prefix + '_gained_reference_ids'] = sorted(ids[prefix] - baseline_ids[prefix])
            metrics[prefix + '_lost_reference_ids'] = sorted(baseline_ids[prefix] - ids[prefix])
        row['arms'][ARM]['annotators'][a] = metrics
    analyze_annotations(row, work)
    row['status'] = 'scored'


def evaluate_all(package, work, report, report_path):
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


def legacy_rows(rows):
    return [{**{k: copy.deepcopy(v) for k, v in row.items() if k not in ROW_ADDITIONS and k != 'arms'},
             'arms': {arm: copy.deepcopy(row['arms'][arm]) for arm in frozen.ARMS}}
            for row in rows]


def aggregate(rows):
    if (len(rows) != len(CASES) or {r['id'] for r in rows} != set(CASES)
            or any(r.get('status') != 'scored' or set(r.get('arms', {})) != set(ARMS)
                   or any(set(r['arms'][arm].get('annotators', {})) != set(ANNOTATORS) for arm in ARMS)
                   for r in rows)):
        return None
    result = frozen.aggregate(legacy_rows(rows))
    result[ARM] = {'predicted_notes': sum(r['arms'][ARM]['count'] for r in rows)}
    for metric in ('onset_f1', 'onset_offset_f1'):
        values = np.asarray([[r['arms'][ARM]['annotators'][a][metric] for a in ANNOTATORS] for r in rows])
        baseline = np.asarray([[r['arms']['pitch_runs']['annotators'][a][metric] for a in ANNOTATORS] for r in rows])
        if not np.isfinite(values).all() or np.any(values < 0) or np.any(values > 1):
            raise ValueError('invalid score')
        delta = values.mean(axis=1) - baseline.mean(axis=1)
        result[ARM][metric] = {'macro': float(values.mean()),
            'A1_macro': float(values[:, 0].mean()), 'A2_macro': float(values[:, 1].mean()),
            'delta_vs_runs': float(delta.mean()), 'recordings_improved': int((delta > 1e-8).sum()),
            'recordings_worse': int((delta < -1e-8).sum()),
            'recordings_tied': int((np.abs(delta) <= 1e-8).sum())}
    for metric in ('onset_precision', 'onset_recall', 'offset_precision', 'offset_recall'):
        result[ARM][metric] = float(np.mean([r['arms'][ARM]['annotators'][a][metric]
                                           for r in rows for a in ANNOTATORS]))
    for prefix in ('onset', 'onset_offset'):
        for suffix in ('gained_reference_ids', 'lost_reference_ids'):
            result[ARM][prefix + '_' + suffix.replace('_ids', '_count')] = sum(
                len(r['arms'][ARM]['annotators'][a][prefix + '_' + suffix]) for r in rows for a in ANNOTATORS)
    return result


def primary_summary(rows):
    if aggregate(rows) is None:
        raise ValueError('complete cohort required for primary contrast')
    by_id = {row['id']: row for row in rows}
    delta = np.asarray([np.mean([
        by_id[case]['arms'][ARM]['annotators'][a]['onset_offset_f1']
        - by_id[case]['arms'][BASE_ARM]['annotators'][a]['onset_offset_f1']
        for a in ANNOTATORS]) for case in CASES])
    indices = np.random.default_rng(296).integers(0, len(CASES), size=(10000, len(CASES)))
    low, high = np.quantile(delta[indices].mean(axis=1), [.025, .975], method='linear')
    return {'candidate': ARM, 'baseline': BASE_ARM, 'metric': 'onset_offset_f1',
        'paired_recording_deltas': [{'id': case, 'delta': float(d)} for case, d in zip(CASES, delta, strict=True)],
        'mean_delta': float(delta.mean()), 'recordings_improved': int((delta > 1e-8).sum()),
        'recordings_worse': int((delta < -1e-8).sum()), 'recordings_tied': int((np.abs(delta) <= 1e-8).sum()),
        'bootstrap': {'resampling_unit': 'recording_mean_of_A1_A2', 'seed': 296,
            'resamples': 10000, 'confidence_level': .95, 'method': 'paired_percentile_linear',
            'low': float(low), 'high': float(high)}, 'heldout_generalization': False}


def legacy_projection(report, baseline, previous):
    keys = (*prior.CORPUS_FIELDS, 'source_revision', 'protocol_head_revision', 'python', 'platform',
            'runtime', 'source_sha256', 'cases', 'elapsed_seconds', 'peak_rss_kib')
    result = {k: copy.deepcopy(report[k]) for k in keys if k in report}
    result.update(schema='note-state-factors-v1', planned_arms=list(frozen.ARMS),
                  source_sha256={p: report['source_sha256'][p] for p in frozen.SOURCE_PATHS},
                  cases=legacy_rows(report['cases']),
                  primary_comparison={'candidate': BASE_ARM, 'baseline': 'note_state_hmm',
                                      'metric': 'onset_offset_f1'})
    manifest = dsp.fingerprint({r['id']: {a: r['arms'][a]['event_sha256'] for a in frozen.ARMS}
                                for r in result['cases']})
    result['predictions_manifest_sha256'] = manifest
    result['post_evaluation_predictions_manifest_sha256'] = manifest
    frozen.finalize_results(result, baseline, previous)
    return result


def historical_parity(report, legacy, previous=None):
    path = ROOT / PREVIOUS if previous is None else previous
    if path.is_symlink() or dsp.digest(path) != PREVIOUS_SHA256:
        raise ValueError('wrong original #295 ZIP')
    with zipfile.ZipFile(path) as archive:
        if sorted(archive.namelist()) != ['audit.json', 'diagnostics.json', 'replay-audit.json', 'synthetic.json', 'vocadito.json']:
            raise ValueError('original #295 inventory differs')
        old = json.loads(archive.read('vocadito.json'))
        previous_sources = json.loads(archive.read('diagnostics.json'))['source_sha256']
    differences = []
    source_checks = {p: (report['source_sha256'].get(p) == value and dsp.digest(ROOT / p) == value)
                     for p, value in previous_sources.items()}
    if set(previous_sources) != set(prior.SOURCE_PATHS):
        differences.append('source_inventory')
    for key in prior.CORPUS_FIELDS:
        if not prior.exact_equal(legacy.get(key), old[key]):
            differences.append('corpus/' + key)
    if [r['id'] for r in legacy['cases']] != list(CASES):
        differences.append('case_inventory')
    old_rows = {r['id']: r for r in old['cases']}
    for row in legacy['cases']:
        if not prior.exact_equal({k: v for k, v in row.items() if k not in prior.CASE_VOLATILE},
                                 {k: v for k, v in old_rows[row['id']].items() if k not in prior.CASE_VOLATILE}):
            differences.append('corpus/' + row['id'])
    predictions = sum(len(r['arms']) for r in legacy['cases'])
    arrays = sum(len(r['observations']) for r in legacy['cases'])
    return {'baseline_zip_sha256': PREVIOUS_SHA256, 'source_checks': source_checks,
            'compared_prediction_files': predictions, 'compared_observation_arrays': arrays,
            'all_equal': all(source_checks.values()) and not differences and predictions == 400 and arrays == 440,
            'differences': differences, 'raw_historical_arrays_available': False,
            'array_identity_available': True}


def finalize_results(report, work, baseline, previous, legacy_report_path):
    report['aggregate'] = aggregate(report['cases'])
    report['all_cases_complete'] = report['aggregate'] is not None
    if not report['all_cases_complete']:
        report['status'] = 'incomplete'
        return
    legacy = legacy_projection(report, baseline, previous)
    dsp.save(legacy_report_path, legacy)
    report['legacy_report_sha256'] = dsp.digest(legacy_report_path)
    report['historical_parity'] = historical_parity(report, legacy)
    if legacy['status'] != 'complete' or not report['historical_parity']['all_equal']:
        report.update(status='baseline_parity_failed', all_cases_complete=False,
                      aggregate=None, primary_result=None, boundary_summary=None)
        return
    report['primary_result'] = primary_summary(report['cases'])
    annotations = [prior.read_json(work / row['id'] / 'annotation-private.json') for row in report['cases']]
    report['boundary_summary'] = {
        'by_annotator': {a: summarize_annotations([r[a] for r in annotations]) for a in ANNOTATORS},
        'pooled_annotation_judgments': summarize_annotations([r[a] for r in annotations for a in ANNOTATORS]),
    }
    report['status'] = 'complete'


def run(archive, work, report_path, baseline, previous, legacy_report_path):
    started = time.monotonic()
    work.mkdir(mode=0o700)
    report = {'schema': 'note-boundary-readout-v1', 'status': 'started', 'cases': [],
        'planned_case_ids': list(CASES), 'planned_arms': list(ARMS),
        'source_revision': os.getenv('GITHUB_SHA'), 'protocol_head_revision': os.getenv('EXPERIMENT_HEAD_SHA'),
        'source_sha256': {p: dsp.digest(ROOT / p) for p in SOURCE_PATHS},
        'python': platform.python_version(), 'platform': platform.platform(),
        'runtime': {d.metadata['Name']: d.version for d in distributions() if d.metadata['Name']},
        'f0_settings': dsp.SETTINGS, 'hmm_settings': frozen.HMM_SETTINGS,
        'factor_settings': frozen.FACTOR_SETTINGS, 'readout_settings': SETTINGS,
        'primary_comparison': {'candidate': ARM, 'baseline': BASE_ARM, 'metric': 'onset_offset_f1'},
        'quality_approved': False, 'heldout_generalization': False, 'product_changes': False,
        'all_cases_complete': False, 'reference_used_for_edits': False, 'device': 'cpu', 'threads': 2,
        'aggregate': None, 'boundary_summary': None, 'all_predictions_frozen_before_references': False}
    dsp.save(report_path, report)
    try:
        if any(version(k) != v for k, v in frozen.EXPECTED_RUNTIME.items()):
            raise ValueError('pinned research runtime required')
        if (archive.is_symlink() or archive.stat().st_size != dsp.ARCHIVE_BYTES
                or hashlib.md5(archive.read_bytes()).hexdigest() != dsp.ARCHIVE_MD5):
            raise ValueError('unchanged original vocadito archive required')
        report['archive_sha256'] = dsp.digest(archive)
        with zipfile.ZipFile(archive) as package:
            predict_all(package, work, report, report_path)
            evaluate_all(package, work, report, report_path)
        finalize_results(report, work, baseline, previous, legacy_report_path)
    except Exception as exc:
        report.update(status='failed', error_type=type(exc).__name__, all_cases_complete=False,
                      aggregate=None, primary_result=None, boundary_summary=None)
        (work / 'error.txt').write_text(str(exc))
    finally:
        report.update(elapsed_seconds=time.monotonic() - started,
                      peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        dsp.save(report_path, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('archive', 'work', 'report', 'baseline', 'previous', 'legacy-report'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    outputs = (args.work, args.report, args.legacy_report)
    if (any(p.exists() or p.is_symlink() or p.resolve().is_relative_to(ROOT) for p in outputs)
            or len({p.resolve() for p in outputs}) != len(outputs)
            or os.getenv('HF_TOKEN') or os.getenv('HUGGING_FACE_HUB_TOKEN')):
        parser.error('distinct new private work/reports outside checkout and no model credentials required')
    result = run(args.archive, args.work, args.report, args.baseline, args.previous, args.legacy_report)
    print(json.dumps({'status': result['status'], 'all_cases_complete': result['all_cases_complete']}))
    return 0 if result['status'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())

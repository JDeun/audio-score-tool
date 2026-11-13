"""Freeze all 480 predictions before references; compare guard with G and split."""
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
from scripts import note_boundary_diagnostics as boundary
from scripts import run_note_boundary_diagnostics as parity
from scripts import run_note_boundary_readout as previous_study
from scripts.audit_note_state_experiment import parse_notes, parse_reference
from scripts.note_boundary_parent_guard import ARM, BASE_ARM, SPLIT_ARM, notes_from_state_path
from scripts.note_boundary_parent_guard import SETTINGS as CORE_SETTINGS

ROOT = Path(__file__).resolve().parents[1]
frozen = previous_study.frozen
CASES, ANNOTATORS = previous_study.CASES, previous_study.ANNOTATORS
ARMS = (*previous_study.ARMS, ARM)
BASELINES = (BASE_ARM, SPLIT_ARM)
DIAGNOSTIC_ARMS = (*previous_study.DIAGNOSTIC_ARMS, ARM)
CRITERIA, PARTITIONS = ('onset', 'onset_offset'), ('retained', 'gained', 'lost', 'neither')
PREVIOUS = 'docs/research/receipts/note-boundary-readout-43381098932-attempt-1.zip'
PREVIOUS_SHA256 = 'f34e88d2b5023df5762fba46b4149167265efbd24a837d30500375b30cd5758f'
NUMERIC_MANIFEST = 'docs/research/NOTE_BOUNDARY_PARENT_GUARD_NUMERIC_INPUTS_2026-11-13.json'
NEW_SOURCE_PATHS = (
    'scripts/note_boundary_parent_guard.py', 'scripts/run_note_boundary_parent_guard.py',
    'scripts/note_boundary_parent_guard_synthetic.py', 'scripts/audit_note_boundary_parent_guard.py',
    'tests/test_note_boundary_parent_guard.py', 'tests/test_run_note_boundary_parent_guard.py',
    'tests/test_note_boundary_parent_guard_synthetic.py', 'tests/test_audit_note_boundary_parent_guard.py',
    '.github/workflows/cpu-note-boundary-parent-guard.yml',
    'docs/research/NOTE_BOUNDARY_PARENT_GUARD_PROTOCOL_2026-11-13.md',
    'docs/research/NOTE_BOUNDARY_PARENT_GUARD_EXECUTION_2026-11-13.md',
    PREVIOUS, NUMERIC_MANIFEST,
)
SOURCE_PATHS = (*previous_study.SOURCE_PATHS, *NEW_SOURCE_PATHS)
ROW_ADDITIONS = frozenset(('guard', 'guard_private_sha256',
                           'guard_annotation_diagnostics', 'guard_annotation_private_sha256'))
REPORT_ADDITIONS = frozenset(('guard_settings', 'secondary_comparison', 'secondary_result',
                              'legacy_factor_report_sha256'))
LEGACY_VOLATILE = frozenset(('source_revision', 'protocol_head_revision', 'python', 'platform',
                             'runtime', 'numerical_environment', 'elapsed_seconds', 'peak_rss_kib',
                             'legacy_report_sha256'))
HARM_KEYS = ('lost_references', 'lost_matched_parent_proposed_cut', 'lost_matched_parent_accepted',
             'lost_matched_parent_rejected', 'lost_matched_parent_with_proposed_short_children',
             'lost_matched_parent_all_proposed_children_fail', 'lost_matched_parent_final_empty')
SETTINGS = {**CORE_SETTINGS, 'candidate': ARM, 'baseline': BASE_ARM,
            'shared_G_path': True, 'bootstrap_seed': 298, 'bootstrap_resamples': 10000,
            'private_details': 'original_proposed_final_segments_and_annotation_pair_rows',
            'pruning_harm_descriptors_are_overlapping_not_causal': True}


def json_projection(value):
    """Snapshot persisted values, including intentionally immutable live settings."""
    return json.loads(json.dumps(value, allow_nan=False))


def prediction_manifest(rows, work):
    if (len(rows) != len(CASES) or {row['id'] for row in rows} != set(CASES)
            or any(row.get('status') not in ('predicted', 'scored')
                   or set(row.get('arms', {})) != set(ARMS) for row in rows)):
        raise ValueError('all 480 planned predictions must precede the first reference read')
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
    arrays, arms, diagnostics, duration, readout, trace = previous_study.infer_recording(audio)
    notes, guard, guard_trace = notes_from_state_path(
        arrays[BASE_ARM + '_path'], arrays['hz'], duration, original_notes=arms[BASE_ARM])
    arms[ARM] = notes
    return arrays, arms, diagnostics, duration, readout, trace, guard, guard_trace


def predict_all(package, work, report, report_path):
    """Only WAV members are opened; all twelve arms share the original pYIN/path pass."""
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
                arrays, arms, diagnostics, duration, readout, trace, guard, guard_trace = infer_recording(audio)
            if set(arms) != set(ARMS):
                raise ValueError('missing or extra prediction arm')
            np.savez_compressed(directory / 'observations.npz', **arrays)
            dsp.save(directory / 'readout-private.json', trace)
            dsp.save(directory / 'guard-private.json', guard_trace)
            row.update(duration_seconds=duration,
                       observations={key: frozen.array_identity(value) for key, value in arrays.items()},
                       observation_sha256=dsp.digest(directory / 'observations.npz'),
                       diagnostics=frozen.scalar_diagnostics(diagnostics), readout=readout,
                       readout_private_sha256=dsp.digest(directory / 'readout-private.json'),
                       guard=guard, guard_private_sha256=dsp.digest(directory / 'guard-private.json'))
            for arm in ARMS:
                dsp.save(directory / f'{arm}.json', [asdict(note) for note in arms[arm]])
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
    for baseline in BASELINES:
        result[baseline] = {}
        for criterion, field in (('onset', 'onset_pairs'), ('onset_offset', 'offset_pairs')):
            def ids(arm):
                return {pair['reference_id'] if field == 'onset_pairs' else pair[0]
                        for pair in details[arm][field]}
            before, after = ids(baseline), ids(ARM)
            result[baseline][criterion] = {
                'retained': sorted(before & after), 'gained': sorted(after - before),
                'lost': sorted(before - after),
                'neither': sorted(set(range(reference_count)) - before - after)}
    return result


def parental_harm(details, comparisons, trace, split_trace):
    """Private lost-reference parent links and overlapping, noncausal descriptors."""
    parents = {parent['parent_id']: parent for parent in trace['parents']}
    if set(parents) != {parent['parent_id'] for parent in split_trace['parents']}:
        raise ValueError('original parent inventories differ')
    mappings = {
        BASE_ARM: {parent['original']['prediction_index']: parent['parent_id']
                   for parent in trace['parents'] if parent['original']['emitted']},
        SPLIT_ARM: {child['prediction_index']: parent['parent_id']
                    for parent in split_trace['parents'] for child in parent['children']
                    if child['emitted']},
    }
    result = {}
    for baseline in BASELINES:
        result[baseline] = {}
        for criterion, field in (('onset', 'onset_pairs'), ('onset_offset', 'offset_pairs')):
            pairs = ({pair['reference_id']: pair['prediction_id'] for pair in details[baseline][field]}
                     if field == 'onset_pairs' else dict(details[baseline][field]))
            lost = comparisons[baseline][criterion]['lost']
            matched = [parents[mappings[baseline][pairs[reference]]] for reference in lost]
            result[baseline][criterion] = {
                'lost_references': len(lost),
                'lost_matched_parent_proposed_cut': sum(bool(p['proposed_cut_frames']) for p in matched),
                'lost_matched_parent_accepted': sum(p['decision'] == 'accepted' for p in matched),
                'lost_matched_parent_rejected': sum(p['decision'] == 'rejected' for p in matched),
                'lost_matched_parent_with_proposed_short_children': sum(
                    any(c['discard_reason'] == 'short' for c in p['proposed_children']) for p in matched),
                'lost_matched_parent_all_proposed_children_fail': sum(
                    bool(p['proposed_children']) and not any(c['passes_readout'] for c in p['proposed_children'])
                    for p in matched),
                'lost_matched_parent_final_empty': sum(
                    not any(c['emitted'] for c in p['final_segments']) for p in matched),
                'lost_reference_parents': [{
                    'reference_id': reference, 'baseline_prediction_id': pairs[reference],
                    'parent_id': parent['parent_id'], 'decision': parent['decision'],
                    'proposed_cut_frames': parent['proposed_cut_frames'],
                    'accepted_cut_frames': parent['accepted_cut_frames'],
                    'proposed_child_discard_reasons': [child['discard_reason'] for child in parent['proposed_children']],
                    'final_prediction_indices': [child['prediction_index'] for child in parent['final_segments']
                                                 if child['emitted']],
                } for reference, parent in zip(lost, matched, strict=True)],
            }
    return result


def summarize_annotations(annotations):
    result = {'recording_annotations': len(annotations),
              'reference_notes': sum(annotation['reference_notes'] for annotation in annotations), 'arms': {}}
    for arm in DIAGNOSTIC_ARMS:
        details = [annotation['arms'][arm] for annotation in annotations]
        result['arms'][arm] = {
            'predicted_notes': sum(detail['predicted_notes'] for detail in details),
            'onset_matched': sum(len(detail['onset_pairs']) for detail in details),
            'offset_matched': sum(len(detail['offset_pairs']) for detail in details),
            'fixed_onset_pairs': boundary.fixed_pair_summary([pair for detail in details for pair in detail['onset_pairs']]),
        }
    result['comparisons'] = {baseline: {criterion: {
        part: sum(len(annotation['comparisons'][baseline][criterion][part]) for annotation in annotations)
        for part in PARTITIONS} for criterion in CRITERIA} for baseline in BASELINES}
    result['parental_harm'] = {baseline: {criterion: {
        key: sum(annotation['parental_harm'][baseline][criterion][key] for annotation in annotations)
        for key in HARM_KEYS} for criterion in CRITERIA} for baseline in BASELINES}
    return result


def analyze_annotations(row, work):
    directory = work / row['id']
    for name, key in (('guard-private.json', 'guard_private_sha256'),
                      ('readout-private.json', 'readout_private_sha256'),
                      ('annotation-private.json', 'annotation_private_sha256')):
        if dsp.digest(directory / name) != row[key]:
            raise ValueError('private diagnostic trace changed')
    trace = parity.read_json(directory / 'guard-private.json')
    split_trace = parity.read_json(directory / 'readout-private.json')
    prior_annotations = parity.read_json(directory / 'annotation-private.json')
    for arm in DIAGNOSTIC_ARMS:
        if dsp.digest(directory / f'{arm}.json') != row['arms'][arm]['event_sha256']:
            raise ValueError('diagnostic prediction changed')
    _, intervals, hz = parse_notes((directory / f'{ARM}.json').read_bytes(), row['duration_seconds'])
    annotations = {}
    for annotator in ANNOTATORS:
        path = directory / f'{annotator}.csv'
        if dsp.digest(path) != row['reference_sha256'][annotator]:
            raise ValueError('diagnostic reference changed')
        reference = parse_reference(path.read_bytes())
        details = {**prior_annotations[annotator]['arms'],
                   ARM: boundary._arm_detail(reference, (intervals, hz))}
        comparisons = comparison_sets(details, len(reference[0]))
        annotations[annotator] = {'reference_notes': len(reference[0]), 'arms': details,
            'comparisons': comparisons, 'parental_harm': parental_harm(details, comparisons, trace, split_trace)}
    dsp.save(directory / 'guard-annotation-private.json', annotations)
    row['guard_annotation_private_sha256'] = dsp.digest(directory / 'guard-annotation-private.json')
    row['guard_annotation_diagnostics'] = {a: summarize_annotations([annotations[a]]) for a in ANNOTATORS}


def score_case(package, row, work):
    previous_study.score_case(package, row, work)
    directory = work / row['id']
    path = directory / f'{ARM}.json'
    if dsp.digest(path) != row['arms'][ARM]['event_sha256']:
        raise ValueError('new prediction mutation before evaluation')
    notes = [dsp.Note(**note) for note in parity.read_json(path)]
    runs = [dsp.Note(**note) for note in parity.read_json(directory / 'pitch_runs.json')]
    for annotator in ANNOTATORS:
        raw = (directory / f'{annotator}.csv').read_bytes()
        metrics, ids = frozen.matching_metrics(notes, raw)
        _, baseline_ids = frozen.matching_metrics(runs, raw)
        for prefix in ids:
            metrics[prefix + '_gained_reference_ids'] = sorted(ids[prefix] - baseline_ids[prefix])
            metrics[prefix + '_lost_reference_ids'] = sorted(baseline_ids[prefix] - ids[prefix])
        row['arms'][ARM]['annotators'][annotator] = metrics
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
    if all(row['status'] == 'scored' for row in report['cases']):
        report['post_evaluation_predictions_manifest_sha256'] = prediction_manifest(report['cases'], work)
        if report['post_evaluation_predictions_manifest_sha256'] != report['predictions_manifest_sha256']:
            raise ValueError('prediction mutation after evaluation')


def legacy_rows(rows):
    return json_projection([{**{key: value for key, value in row.items()
                                if key not in ROW_ADDITIONS and key != 'arms'},
                             'arms': {arm: row['arms'][arm] for arm in previous_study.ARMS}}
                            for row in rows])


def aggregate(rows):
    if (len(rows) != len(CASES) or {row['id'] for row in rows} != set(CASES)
            or any(row.get('status') != 'scored' or set(row.get('arms', {})) != set(ARMS)
                   or any(set(row['arms'][arm].get('annotators', {})) != set(ANNOTATORS) for arm in ARMS)
                   for row in rows)):
        return None
    result = previous_study.aggregate(legacy_rows(rows))
    result[ARM] = {'predicted_notes': sum(row['arms'][ARM]['count'] for row in rows)}
    for metric in ('onset_f1', 'onset_offset_f1'):
        values = np.asarray([[row['arms'][ARM]['annotators'][a][metric] for a in ANNOTATORS] for row in rows])
        baseline = np.asarray([[row['arms']['pitch_runs']['annotators'][a][metric] for a in ANNOTATORS] for row in rows])
        if not np.isfinite(values).all() or np.any(values < 0) or np.any(values > 1):
            raise ValueError('invalid score')
        delta = values.mean(axis=1) - baseline.mean(axis=1)
        result[ARM][metric] = {'macro': float(values.mean()),
            'A1_macro': float(values[:, 0].mean()), 'A2_macro': float(values[:, 1].mean()),
            'delta_vs_runs': float(delta.mean()), 'recordings_improved': int((delta > 1e-8).sum()),
            'recordings_worse': int((delta < -1e-8).sum()),
            'recordings_tied': int((np.abs(delta) <= 1e-8).sum())}
    for metric in ('onset_precision', 'onset_recall', 'offset_precision', 'offset_recall'):
        result[ARM][metric] = float(np.mean([row['arms'][ARM]['annotators'][a][metric]
                                           for row in rows for a in ANNOTATORS]))
    for prefix in CRITERIA:
        for suffix in ('gained_reference_ids', 'lost_reference_ids'):
            result[ARM][prefix + '_' + suffix.replace('_ids', '_count')] = sum(
                len(row['arms'][ARM]['annotators'][a][prefix + '_' + suffix]) for row in rows for a in ANNOTATORS)
    return result


def contrast_summary(rows, baseline):
    if baseline not in BASELINES or aggregate(rows) is None:
        raise ValueError('complete cohort and declared baseline required for contrast')
    by_id = {row['id']: row for row in rows}
    delta = np.asarray([np.mean([
        by_id[case]['arms'][ARM]['annotators'][a]['onset_offset_f1']
        - by_id[case]['arms'][baseline]['annotators'][a]['onset_offset_f1']
        for a in ANNOTATORS]) for case in CASES])
    indices = np.random.default_rng(298).integers(0, len(CASES), size=(10000, len(CASES)))
    low, high = np.quantile(delta[indices].mean(axis=1), [.025, .975], method='linear')
    return {'candidate': ARM, 'baseline': baseline, 'metric': 'onset_offset_f1',
        'paired_recording_deltas': [{'id': case, 'delta': float(value)} for case, value in zip(CASES, delta, strict=True)],
        'mean_delta': float(delta.mean()), 'recordings_improved': int((delta > 1e-8).sum()),
        'recordings_worse': int((delta < -1e-8).sum()), 'recordings_tied': int((np.abs(delta) <= 1e-8).sum()),
        'bootstrap': {'resampling_unit': 'recording_mean_of_A1_A2', 'seed': 298,
            'resamples': 10000, 'confidence_level': .95, 'method': 'paired_percentile_linear',
            'low': float(low), 'high': float(high)}, 'heldout_generalization': False}


def legacy_projection(report, work, baseline, previous, legacy_factor_report_path):
    result = json_projection({key: value for key, value in report.items() if key not in REPORT_ADDITIONS})
    result.update(schema='note-boundary-readout-v1', planned_arms=list(previous_study.ARMS),
                  source_sha256={path: report['source_sha256'][path] for path in previous_study.SOURCE_PATHS},
                  cases=legacy_rows(report['cases']), readout_settings=previous_study.SETTINGS,
                  primary_comparison={'candidate': SPLIT_ARM, 'baseline': BASE_ARM, 'metric': 'onset_offset_f1'})
    manifest = dsp.fingerprint({row['id']: {arm: row['arms'][arm]['event_sha256'] for arm in previous_study.ARMS}
                                for row in result['cases']})
    result['predictions_manifest_sha256'] = result['post_evaluation_predictions_manifest_sha256'] = manifest
    previous_study.finalize_results(result, work, baseline, previous, legacy_factor_report_path)
    return result


def historical_parity(report, legacy, previous=None):
    path = ROOT / PREVIOUS if previous is None else previous
    if path.is_symlink() or dsp.digest(path) != PREVIOUS_SHA256:
        raise ValueError('wrong original #297 ZIP')
    with zipfile.ZipFile(path) as archive:
        if sorted(archive.namelist()) != ['audit.json', 'legacy-audit.json', 'legacy-synthetic.json',
                                         'legacy-vocadito.json', 'synthetic.json', 'vocadito.json']:
            raise ValueError('original #297 inventory differs')
        old = json.loads(archive.read('vocadito.json'))
    sources = old['source_sha256']
    source_checks = {name: report['source_sha256'].get(name) == value and dsp.digest(ROOT / name) == value
                     for name, value in sources.items()}
    differences = []
    if set(sources) != set(previous_study.SOURCE_PATHS):
        differences.append('source_inventory')
    if set(legacy) != set(old):
        differences.append('report_inventory')
    for key in old.keys() - LEGACY_VOLATILE - {'cases'}:
        if not parity.exact_equal(legacy.get(key), old[key]):
            differences.append('corpus/' + key)
    if [row['id'] for row in legacy['cases']] != list(CASES):
        differences.append('case_inventory')
    old_rows = {row['id']: row for row in old['cases']}
    for row in legacy['cases']:
        if row['id'] not in old_rows or not parity.exact_equal(
                {key: value for key, value in row.items() if key not in parity.CASE_VOLATILE},
                {key: value for key, value in old_rows[row['id']].items() if key not in parity.CASE_VOLATILE}):
            differences.append('corpus/' + row['id'])
    predictions = sum(len(row['arms']) for row in legacy['cases'])
    arrays = sum(len(row['observations']) for row in legacy['cases'])
    return {'baseline_zip_sha256': PREVIOUS_SHA256, 'source_checks': source_checks,
            'compared_prediction_files': predictions, 'compared_observation_arrays': arrays,
            'all_equal': all(source_checks.values()) and not differences and predictions == 440 and arrays == 440,
            'differences': sorted(differences), 'raw_historical_arrays_available': False,
            'array_identity_available': True}


def incomplete(report, status):
    report.update(status=status, all_cases_complete=False, aggregate=None,
                  primary_result=None, secondary_result=None, boundary_summary=None)


def finalize_results(report, work, baseline, previous, legacy_report_path, legacy_factor_report_path):
    report['aggregate'] = aggregate(report['cases'])
    if report['aggregate'] is None:
        incomplete(report, 'incomplete')
        return
    report['all_cases_complete'] = True
    legacy = legacy_projection(report, work, baseline, previous, legacy_factor_report_path)
    dsp.save(legacy_report_path, legacy)
    report['legacy_report_sha256'] = dsp.digest(legacy_report_path)
    report['legacy_factor_report_sha256'] = dsp.digest(legacy_factor_report_path)
    report['historical_parity'] = historical_parity(report, legacy)
    if legacy['status'] != 'complete' or not report['historical_parity']['all_equal']:
        incomplete(report, 'baseline_parity_failed')
        return
    report['primary_result'] = contrast_summary(report['cases'], BASE_ARM)
    report['secondary_result'] = contrast_summary(report['cases'], SPLIT_ARM)
    annotations = [parity.read_json(work / row['id'] / 'guard-annotation-private.json') for row in report['cases']]
    report['boundary_summary'] = {
        'by_annotator': {a: summarize_annotations([row[a] for row in annotations]) for a in ANNOTATORS},
        'pooled_annotation_judgments': summarize_annotations([row[a] for row in annotations for a in ANNOTATORS]),
    }
    report['status'] = 'complete'


def run(archive, work, report_path, baseline, previous, legacy_report_path, legacy_factor_report_path):
    from scripts.note_boundary_readout_synthetic import numerical_environment

    started = time.monotonic()
    work.mkdir(mode=0o700)
    report = {'schema': 'note-boundary-parent-guard-v1', 'status': 'started', 'cases': [],
        'planned_case_ids': list(CASES), 'planned_arms': list(ARMS),
        'source_revision': os.getenv('GITHUB_SHA'), 'protocol_head_revision': os.getenv('EXPERIMENT_HEAD_SHA'),
        'source_sha256': {path: dsp.digest(ROOT / path) for path in SOURCE_PATHS},
        'python': platform.python_version(), 'platform': platform.platform(),
        'runtime': {dist.metadata['Name']: dist.version for dist in distributions() if dist.metadata['Name']},
        'numerical_environment': numerical_environment(),
        'f0_settings': dsp.SETTINGS, 'hmm_settings': frozen.HMM_SETTINGS,
        'factor_settings': frozen.FACTOR_SETTINGS, 'readout_settings': previous_study.SETTINGS,
        'guard_settings': SETTINGS,
        'primary_comparison': {'candidate': ARM, 'baseline': BASE_ARM, 'metric': 'onset_offset_f1'},
        'secondary_comparison': {'candidate': ARM, 'baseline': SPLIT_ARM, 'metric': 'onset_offset_f1'},
        'quality_approved': False, 'heldout_generalization': False, 'product_changes': False,
        'all_cases_complete': False, 'reference_used_for_edits': False, 'device': 'cpu', 'threads': 2,
        'aggregate': None, 'boundary_summary': None, 'all_predictions_frozen_before_references': False}
    dsp.save(report_path, report)
    try:
        if any(version(key) != value for key, value in frozen.EXPECTED_RUNTIME.items()):
            raise ValueError('pinned research runtime required')
        if (archive.is_symlink() or archive.stat().st_size != dsp.ARCHIVE_BYTES
                or hashlib.md5(archive.read_bytes()).hexdigest() != dsp.ARCHIVE_MD5):
            raise ValueError('unchanged original vocadito archive required')
        report['archive_sha256'] = dsp.digest(archive)
        with zipfile.ZipFile(archive) as package:
            predict_all(package, work, report, report_path)
            evaluate_all(package, work, report, report_path)
        # The legacy audit requires the complete resource-field inventory too.
        # Snapshot current observations before constructing the legacy report;
        # the final new report is updated again after all finalization work.
        report.update(elapsed_seconds=time.monotonic() - started,
                      peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        finalize_results(report, work, baseline, previous, legacy_report_path, legacy_factor_report_path)
    except Exception as exc:
        incomplete(report, 'failed')
        report['error_type'] = type(exc).__name__
        (work / 'error.txt').write_text(str(exc))
    finally:
        report.update(elapsed_seconds=time.monotonic() - started,
                      peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        dsp.save(report_path, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('archive', 'work', 'report', 'baseline', 'previous', 'legacy-report', 'legacy-factor-report'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    outputs = (args.work, args.report, args.legacy_report, args.legacy_factor_report)
    if (any(path.exists() or path.is_symlink() or path.resolve().is_relative_to(ROOT) for path in outputs)
            or len({path.resolve() for path in outputs}) != len(outputs)
            or os.getenv('HF_TOKEN') or os.getenv('HUGGING_FACE_HUB_TOKEN')):
        parser.error('distinct new private work/reports outside checkout and no model credentials required')
    result = run(args.archive, args.work, args.report, args.baseline, args.previous,
                 args.legacy_report, args.legacy_factor_report)
    print(json.dumps({'status': result['status'], 'all_cases_complete': result['all_cases_complete']}))
    return 0 if result['status'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())

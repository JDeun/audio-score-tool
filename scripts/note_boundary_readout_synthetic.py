"""Fixed #296 readout comparison on the unchanged 245 authored-F0 controls.

The seven frozen predictions and their six paths are produced once.  The new
arm reads that same Gaussian path.  All eight event files for every case are
saved and hashed before the first truth is requested.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import time
import zipfile
from dataclasses import asdict
from pathlib import Path

import numpy as np

from scripts import dsp_note_probe as dsp
from scripts import note_boundary_readout as readout
from scripts import note_state_synthetic as frozen

ROOT = Path(__file__).resolve().parents[1]
ARM = 'gaussian_raw_hysteresis_split'
BASE_ARM = 'gaussian_exponent_1'
ARMS = (*frozen.ARMS, ARM)
PATH_ARMS = frozen.ARMS[1:]
PREVIOUS = 'docs/research/receipts/note-boundary-diagnostics-43370790419.zip'
PREVIOUS_SHA256 = '43b439e665eb470ec1b24179697cc99d2733fecb6122d1da6a77125d8e3ccf31'
VOLATILE = frozenset(('source_revision', 'protocol_head_revision', 'elapsed_seconds'))
LEGACY_FIELDS = (
    'status', 'source_revision', 'protocol_head_revision', 'planned_cases',
    'acoustic_extraction', 'quality_approved', 'heldout_generalization',
    'emission_analysis', 'all_predictions_saved_before_scoring', 'elapsed_seconds',
)
LEGACY_CASE_FIELDS = (
    'id', 'spec', 'duration_seconds', 'accuracy_eligible', 'observation',
    'truth', 'alternative_truth',
)
SEMITONE_CONTROL_IDS = (
    'change_195', 'change_197', 'change_207', 'change_209', 'change_219', 'change_221',
)


def predict(hz, duration):
    """Case metadata and truth are intentionally absent from this signature."""
    arms, paths, diagnostics = frozen.predict(hz, duration)
    if set(arms) != set(frozen.ARMS) or set(paths) != set(PATH_ARMS):
        raise ValueError('all seven frozen arms and six paths required')
    original_input = frozen.identity(hz)
    original_paths = {name: frozen.identity(path) for name, path in paths.items()}
    notes, public, trace = readout.notes_from_state_path(paths[BASE_ARM], hz, duration)
    if original_input != frozen.identity(hz) or original_paths != {
            name: frozen.identity(path) for name, path in paths.items()}:
        raise ValueError('readout mutated shared observations or paths')
    if public['applied_cut_count'] == 0 and notes != arms[BASE_ARM]:
        raise ValueError('no-cut Gaussian event identity changed')
    return {**arms, ARM: notes}, paths, diagnostics, public, trace


def require_population(rows):
    """Require the original ordered specifications and all eight event arms."""
    plan = frozen.cases()
    if (len(rows) != 245 or len(plan) != 245
            or [row.get('spec') for row in rows] != [asdict(case) for case in plan]
            or [row.get('id') for row in rows] != [case.id for case in plan]
            or any(type(row.get('accuracy_eligible')) is not bool
                   or row['accuracy_eligible'] != case.accuracy_eligible
                   or set(row.get('arms', {})) != set(ARMS)
                   for row, case in zip(rows, plan, strict=True))):
        raise ValueError('incomplete fixed synthetic population')
    counts = {
        'all_cases': len(rows),
        'accuracy_eligible_cases': sum(row['accuracy_eligible'] for row in rows),
        'ambiguous_cases': sum(row['spec']['kind'] == 'dropout' or (
            row['spec']['kind'] == 'repeat' and row['spec']['gap'] == 0) for row in rows),
        'silence_cases': sum(row['spec']['kind'] == 'silence' for row in rows),
    }
    if tuple(counts.values()) != (245, 227, 15, 3):
        raise ValueError('fixed synthetic denominator changed')
    return counts


def prediction_manifest(rows, arms=ARMS):
    require_population(rows)
    if tuple(arms) not in (ARMS, frozen.ARMS):
        raise ValueError('unknown prediction manifest arm inventory')
    return dsp.fingerprint({row['id']: {
        arm: row['arms'][arm]['event_sha256'] for arm in arms} for row in rows})


def verify_prediction_files(work, rows):
    """Recheck every saved event file, including those scored earlier."""
    for row in rows:
        for arm in ARMS:
            path = work / row['id'] / f'{arm}.json'
            if (path.is_symlink() or not path.is_file()
                    or dsp.digest(path) != row['arms'][arm]['event_sha256']):
                raise ValueError('synthetic prediction mutation')
        private_path = work / row['id'] / 'readout-private.json'
        if (private_path.is_symlink() or not private_path.is_file()
                or dsp.digest(private_path) != row['readout_private_sha256']):
            raise ValueError('private synthetic readout trace mutation')
    return prediction_manifest(rows)


def legacy_rows(rows):
    return [{**{key: copy.deepcopy(row[key]) for key in LEGACY_CASE_FIELDS},
             'arms': {arm: copy.deepcopy(row['arms'][arm]) for arm in frozen.ARMS}}
            for row in rows]


def legacy_projection(report):
    """Recreate the frozen seven-arm payload without rerunning a predictor."""
    if report.get('status') != 'complete':
        raise ValueError('complete synthetic report required for legacy projection')
    require_population(report['cases'])
    rows = legacy_rows(report['cases'])
    return {'schema': 'note-state-synthetic-v1',
            **{key: copy.deepcopy(report[key]) for key in LEGACY_FIELDS},
            'planned_arms': list(frozen.ARMS), 'cases': rows,
            'predictions_manifest_sha256': prediction_manifest(report['cases'], frozen.ARMS),
            'aggregate': frozen.summarize(rows)}


def summarize(rows):
    require_population(rows)
    result = frozen.summarize(legacy_rows(rows))
    eligible = [row for row in rows if row['accuracy_eligible']]
    candidate = {
        'all_cases_predicted_notes': sum(row['arms'][ARM]['count'] for row in rows),
        'empty_output_cases': sum(row['arms'][ARM]['count'] == 0 for row in rows),
        'silence_false_positive_notes': sum(row['arms'][ARM]['count'] for row in rows
                                          if row['spec']['kind'] == 'silence'),
        'eligible_cases': len(eligible),
    }
    for metric in ('onset_f1', 'onset_offset_f1'):
        candidate[metric] = float(np.mean([row['arms'][ARM]['metrics'][metric] for row in eligible]))
    raw = sum(row['arms'][ARM]['readout']['readout']['raw_voiced_frames'] for row in rows)
    dropped = sum(row['arms'][ARM]['readout']['readout']['raw_voiced_decoded_silent_frames'] for row in rows)
    candidate.update(raw_voiced_frames=raw, raw_voiced_to_silent_frames=dropped,
                     voiced_coverage=1 - dropped / raw)
    result[ARM] = candidate
    return result


def compare_case(row):
    base, candidate = row['arms'][BASE_ARM], row['arms'][ARM]
    result = {'baseline_arm': BASE_ARM, 'candidate_arm': ARM,
              'predicted_notes_change': candidate['count'] - base['count'],
              'event_identity_unchanged': candidate['event_sha256'] == base['event_sha256'],
              'no_added_cuts': candidate['readout']['applied_cut_count'] == 0,
              'onset_f1_change': None, 'onset_offset_f1_change': None,
              'baseline_perfect': None, 'candidate_perfect': None}
    if row['accuracy_eligible']:
        for metric in ('onset_f1', 'onset_offset_f1'):
            result[metric + '_change'] = candidate['metrics'][metric] - base['metrics'][metric]
        result['baseline_perfect'] = all(base['metrics'][m] == 1. for m in ('onset_f1', 'onset_offset_f1'))
        result['candidate_perfect'] = all(candidate['metrics'][m] == 1. for m in ('onset_f1', 'onset_offset_f1'))
    if result['no_added_cuts'] and not result['event_identity_unchanged']:
        raise ValueError('no-cut prediction file identity changed')
    return result


def comparison_summary(rows):
    population = require_population(rows)
    eligible = [row for row in rows if row['accuracy_eligible']]
    controls = [row for row in rows if row['spec']['kind'] == 'change'
                and row['spec']['interval'] == 1 and row['spec']['gap'] == 0]
    if tuple(row['id'] for row in controls) != SEMITONE_CONTROL_IDS:
        raise ValueError('fixed joined-semitone controls changed')
    previous_successes = [row for row in eligible if row['comparison']['baseline_perfect']]
    if len(previous_successes) != 221:
        raise ValueError('frozen Gaussian synthetic success population changed')
    result = {
        **population, 'baseline_arm': BASE_ARM, 'candidate_arm': ARM,
        'previous_gaussian_perfect_cases': len(previous_successes),
        'previous_gaussian_perfect_case_ids': [row['id'] for row in previous_successes],
        'damaged_previous_success_case_ids': [row['id'] for row in previous_successes
                                            if not row['comparison']['candidate_perfect']],
        'no_added_cut_cases': sum(row['comparison']['no_added_cuts'] for row in rows),
        'identical_event_cases': sum(row['comparison']['event_identity_unchanged'] for row in rows),
        'joined_semitone_controls': [], 'eligible_metric_changes': {},
    }
    for row in controls:
        base, candidate = row['arms'][BASE_ARM], row['arms'][ARM]
        result['joined_semitone_controls'].append({
            'id': row['id'], 'reference_notes': len(row['truth']),
            'baseline_predicted_notes': base['count'], 'candidate_predicted_notes': candidate['count'],
            'baseline_metrics': base['metrics'], 'candidate_metrics': candidate['metrics'],
            'candidate_two_notes_pitch_onset_offset_correct': (
                len(row['truth']) == candidate['count'] == 2 and row['comparison']['candidate_perfect']),
        })
    for metric in ('onset_f1', 'onset_offset_f1'):
        values = [row['comparison'][metric + '_change'] for row in eligible]
        result['eligible_metric_changes'][metric] = {
            'macro_change': float(np.mean(values)),
            'improved_cases': sum(value > 0 for value in values),
            'worse_cases': sum(value < 0 for value in values),
            'tied_cases': sum(value == 0 for value in values),
        }
    return result


def historical_parity(report, previous=None):
    previous = ROOT / PREVIOUS if previous is None else previous
    if previous.is_symlink() or not previous.is_file() or dsp.digest(previous) != PREVIOUS_SHA256:
        raise ValueError('wrong original #295 artifact')
    with zipfile.ZipFile(previous) as archive:
        if sorted(archive.namelist()) != [
                'audit.json', 'diagnostics.json', 'replay-audit.json', 'synthetic.json', 'vocadito.json']:
            raise ValueError('original artifact inventory differs')
        baseline = json.loads(archive.read('synthetic.json'))
    legacy = legacy_projection(report)

    def scientific(payload):
        return {key: value for key, value in payload.items() if key not in VOLATILE}

    exact = json.dumps(scientific(legacy), sort_keys=True, allow_nan=False) == json.dumps(
        scientific(baseline), sort_keys=True, allow_nan=False)
    counts = {'compared_prediction_files': sum(len(row['arms']) for row in legacy['cases']),
              'compared_input_arrays': len(legacy['cases']),
              'compared_state_paths': sum('state_path' in arm for row in legacy['cases']
                                          for arm in row['arms'].values())}
    return {'baseline_zip_sha256': PREVIOUS_SHA256, **counts,
            'all_equal': exact and tuple(counts.values()) == (1715, 245, 1470),
            'differences': [] if exact else ['legacy/full_scientific_payload']}


def run(work, report_path, legacy_report_path=None):
    from scripts.run_note_boundary_readout import SOURCE_PATHS

    started = time.monotonic()
    work.mkdir(mode=0o700)
    plan = frozen.cases()
    report = {
        'schema': 'note-boundary-readout-synthetic-v1', 'status': 'started', 'cases': [],
        'source_revision': os.getenv('GITHUB_SHA'), 'protocol_head_revision': os.getenv('EXPERIMENT_HEAD_SHA'),
        'source_sha256': {path: dsp.digest(ROOT / path) for path in SOURCE_PATHS},
        'planned_cases': len(plan), 'planned_arms': list(ARMS), 'acoustic_extraction': False,
        'quality_approved': False, 'heldout_generalization': False, 'product_changes': False,
        'emission_analysis': frozen.emission_analysis(), 'aggregate': None, 'comparisons': None,
        'all_predictions_saved_before_scoring': False, 'historical_parity': None,
    }
    dsp.save(report_path, report)
    try:
        for case in plan:
            hz, duration = frozen.observations(case)
            arms, paths, diagnostics, public, trace = predict(hz, duration)
            directory = work / case.id
            directory.mkdir()
            np.savez_compressed(directory / 'observations.npz', hz=hz, **paths)
            private_path = directory / 'readout-private.json'
            dsp.save(private_path, trace)
            row = {'id': case.id, 'spec': asdict(case), 'duration_seconds': duration,
                   'accuracy_eligible': case.accuracy_eligible, 'observation': frozen.identity(hz),
                   'readout_private_sha256': dsp.digest(private_path), 'arms': {}}
            for arm in ARMS:
                path = directory / f'{arm}.json'
                dsp.save(path, [asdict(note) for note in arms[arm]])
                row['arms'][arm] = {'count': len(arms[arm]), 'event_sha256': dsp.digest(path)}
                if arm == ARM:
                    row['arms'][arm].update(readout=public, shared_state_path=frozen.identity(paths[BASE_ARM]),
                                            shared_state_path_arm=BASE_ARM)
                else:
                    row['arms'][arm]['diagnostics'] = diagnostics[arm]
                    if arm in paths:
                        row['arms'][arm]['state_path'] = frozen.identity(paths[arm])
            report['cases'].append(row)
        report['predictions_manifest_sha256'] = verify_prediction_files(work, report['cases'])
        report['all_predictions_saved_before_scoring'] = True
        report['truth_access_started_after_prediction_files'] = sum(len(row['arms']) for row in report['cases'])
        dsp.save(report_path, report)
        for case, row in zip(plan, report['cases'], strict=True):
            reference = frozen.truth(case)
            row['truth'] = [asdict(note) for note in reference]
            row['alternative_truth'] = [asdict(note) for note in frozen.alternative_truth(case)]
            for arm in ARMS:
                path = work / case.id / f'{arm}.json'
                if dsp.digest(path) != row['arms'][arm]['event_sha256']:
                    raise ValueError('synthetic prediction mutation')
                notes = [dsp.Note(**note) for note in json.loads(path.read_text())]
                row['arms'][arm]['events'] = [asdict(note) for note in notes]
                row['arms'][arm]['metrics'] = frozen.score(notes, reference) if case.accuracy_eligible else None
            row['comparison'] = compare_case(row)
        report['post_evaluation_predictions_manifest_sha256'] = verify_prediction_files(work, report['cases'])
        if report['post_evaluation_predictions_manifest_sha256'] != report['predictions_manifest_sha256']:
            raise ValueError('synthetic manifest changed after scoring')
        report['aggregate'] = summarize(report['cases'])
        report['comparisons'] = comparison_summary(report['cases'])
        report['status'] = 'complete'
        report['elapsed_seconds'] = time.monotonic() - started
        report['historical_parity'] = historical_parity(report)
        if not report['historical_parity']['all_equal']:
            raise ValueError('frozen synthetic historical parity failed')
        if legacy_report_path is not None:
            dsp.save(legacy_report_path, legacy_projection(report))
    except Exception as exc:
        report.update(status='failed', error_type=type(exc).__name__, aggregate=None, comparisons=None)
        (work / 'error.txt').write_text(str(exc))
    finally:
        report['elapsed_seconds'] = time.monotonic() - started
        dsp.save(report_path, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('work', 'report'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--legacy-report', type=Path)
    args = parser.parse_args()
    paths = [args.work, args.report] + ([args.legacy_report] if args.legacy_report is not None else [])
    if (len({path.resolve() for path in paths}) != len(paths)
            or any(path.exists() or path.is_symlink() or path.resolve().is_relative_to(ROOT) for path in paths)
            or os.getenv('HF_TOKEN') or os.getenv('HUGGING_FACE_HUB_TOKEN')):
        parser.error('distinct new work and reports outside checkout, no model credentials required')
    return 0 if run(args.work, args.report, args.legacy_report)['status'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())

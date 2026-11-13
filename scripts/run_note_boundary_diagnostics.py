"""Diagnose frozen note boundaries only after exact #292 evidence replay.

This entry point performs no acoustic extraction, decoding, edits or search.
The workflow first executes the unchanged factor runners and private auditor.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import zipfile
from pathlib import Path

from scripts import dsp_note_probe as dsp
from scripts import run_note_state_factors as frozen

ROOT = Path(__file__).resolve().parents[1]
PREVIOUS = 'docs/research/receipts/note-state-factors-43344373779.zip'
PREVIOUS_SHA256 = 'b20495c8936f8b4263daf2660fb57ba282264904d6b30dda076463cc6e3881f6'
NEW_SOURCE_PATHS = (
    'scripts/note_boundary_diagnostics.py',
    'scripts/note_boundary_synthetic.py',
    'scripts/run_note_boundary_diagnostics.py',
    'scripts/audit_note_boundary_diagnostics.py',
    'tests/test_note_boundary_diagnostics.py',
    'tests/test_note_boundary_synthetic.py',
    'tests/test_run_note_boundary_diagnostics.py',
    'tests/test_audit_note_boundary_diagnostics.py',
    '.github/workflows/cpu-note-boundary-diagnostics.yml',
    'docs/research/NOTE_BOUNDARY_DIAGNOSTICS_PROTOCOL_2026-11-13.md',
    PREVIOUS,
)
SOURCE_PATHS = (*frozen.SOURCE_PATHS, *NEW_SOURCE_PATHS)
CORPUS_FIELDS = (
    'schema', 'status', 'planned_case_ids', 'planned_arms', 'f0_settings',
    'hmm_settings', 'factor_settings', 'primary_comparison', 'quality_approved',
    'heldout_generalization', 'product_changes', 'all_cases_complete',
    'reference_used_for_edits', 'device', 'threads', 'aggregate',
    'all_predictions_frozen_before_references', 'archive_sha256',
    'predictions_manifest_sha256', 'reference_access_started_after_predicted_cases',
    'post_evaluation_predictions_manifest_sha256', 'historical_baseline_parity',
    'historical_hmm_parity', 'primary_result',
)
SYNTHETIC_VOLATILE = frozenset(('source_revision', 'protocol_head_revision', 'elapsed_seconds'))
CASE_VOLATILE = frozenset(('observation_sha256', 'inference_seconds'))


def read_json(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('regular input file required')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON key: ' + key)
            result[key] = value
        return result

    return json.loads(path.read_text(), object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(
                          ValueError('non-finite JSON constant: ' + value)))


def exact_equal(actual, expected):
    # Python equality conflates bool/int and int/float; serialized evidence does not.
    if isinstance(actual, (set, frozenset)):
        actual = sorted(actual)
    if isinstance(expected, (set, frozenset)):
        expected = sorted(expected)
    return json.dumps(actual, sort_keys=True, allow_nan=False) == json.dumps(
        expected, sort_keys=True, allow_nan=False)


def replay_parity(corpus, synthetic, previous=None, root=ROOT):
    """Exact scientific identities; elapsed times and NPZ container bytes vary."""
    previous = root / PREVIOUS if previous is None else previous
    if previous.is_symlink() or dsp.digest(previous) != PREVIOUS_SHA256:
        raise ValueError('wrong original #292 artifact')
    with zipfile.ZipFile(previous) as archive:
        if sorted(archive.namelist()) != ['audit.json', 'synthetic.json', 'vocadito.json']:
            raise ValueError('original artifact inventory differs')
        old = json.loads(archive.read('vocadito.json'))
        old_synthetic = json.loads(archive.read('synthetic.json'))
    differences = []

    def same(actual, expected, label):
        if not exact_equal(actual, expected):
            differences.append(label)

    source_checks = {name: (corpus.get('source_sha256', {}).get(name) == expected
                            and dsp.digest(root / name) == expected)
                     for name, expected in old['source_sha256'].items()}
    same(set(corpus.get('source_sha256', {})), set(old['source_sha256']), 'source_inventory')
    same(set(old['source_sha256']), set(frozen.SOURCE_PATHS), 'frozen_source_inventory')
    for name in CORPUS_FIELDS:
        same(corpus.get(name), old[name], 'corpus/' + name)
    same([row.get('id') for row in corpus.get('cases', [])], list(frozen.CASES), 'corpus/case_inventory')
    old_rows = {row['id']: row for row in old['cases']}
    predictions = arrays = 0
    for row in corpus.get('cases', []):
        case = row.get('id')
        if case not in old_rows:
            differences.append('corpus/unknown_case')
            continue
        prior = old_rows[case]
        same({k: v for k, v in row.items() if k not in CASE_VOLATILE},
             {k: v for k, v in prior.items() if k not in CASE_VOLATILE}, 'corpus/' + case)
        predictions += len(row.get('arms', {}))
        arrays += len(row.get('observations', {}))
    same({k: v for k, v in synthetic.items() if k not in SYNTHETIC_VOLATILE},
         {k: v for k, v in old_synthetic.items() if k not in SYNTHETIC_VOLATILE}, 'synthetic/full_scientific_payload')
    synthetic_rows = synthetic.get('cases', [])
    synth_predictions = sum(len(row.get('arms', {})) for row in synthetic_rows)
    synth_inputs = sum('observation' in row for row in synthetic_rows)
    synth_paths = sum('state_path' in arm for row in synthetic_rows for arm in row.get('arms', {}).values())
    counts = {
        'compared_corpus_prediction_files': predictions,
        'compared_corpus_observation_arrays': arrays,
        'compared_synthetic_prediction_files': synth_predictions,
        'compared_synthetic_input_arrays': synth_inputs,
        'compared_synthetic_state_paths': synth_paths,
    }
    same(tuple(counts.values()), (400, 440, 1715, 245, 1470), 'complete_evidence_counts')
    return {'baseline_zip_sha256': PREVIOUS_SHA256,
            'source_checks': source_checks, **counts,
            'all_equal': all(source_checks.values()) and not differences,
            'differences': differences,
            'raw_historical_arrays_available': False,
            'array_identity_available': True}


def require_private_audit(audit, replay_path):
    required = {'schema': 'note-state-factors-audit-v1', 'status': 'pass',
                'audit_completed': True, 'complete_prediction_files_verified': 400,
                'observation_arrays_verified': 440, 'source_files_verified': 24,
                'report_sha256': dsp.digest(replay_path),
                'script_sha256': dsp.digest(ROOT / 'scripts/audit_note_state_factors.py')}
    if not exact_equal({key: audit.get(key) for key in required}, required):
        raise ValueError('successful private audit bound to this replay required')


def require_complete_diagnostics(corpus, synthetic, expected_corpus, expected_synthetic):
    """A module returning a partial payload cannot promote it to completed evidence."""
    expected_arms = {'pitch_runs', 'gaussian_exponent_1', 'note_state_hmm'}
    rows = corpus.get('cases', [])
    aggregate = corpus.get('aggregate')
    if (not isinstance(aggregate, dict)
            or [r.get('id') for r in rows] != [r['id'] for r in expected_corpus['cases']]
            or any(r.get('status') != 'complete' or set(r.get('annotators', {})) != {'A1', 'A2'}
                   or any(set(r['annotators'][a].get('arms', {})) != expected_arms for a in ('A1', 'A2'))
                   for r in rows)
            or aggregate.get('recordings') != 40 or aggregate.get('recording_annotations') != 80
            or set(aggregate.get('by_annotator', {})) != {'A1', 'A2'}
            or aggregate.get('pooled_annotation_judgments', {}).get('recording_annotations') != 80):
        raise ValueError('complete corpus diagnostic population required')
    if (synthetic.get('status') != 'complete'
            or [r.get('id') for r in synthetic.get('cases', [])] != [r['id'] for r in expected_synthetic['cases']]
            or synthetic.get('planned_cases') != 245
            or synthetic.get('planned_arms') != expected_synthetic['planned_arms']
            or synthetic.get('identities_checked') != {'event_files': 1715, 'input_arrays': 245, 'state_path_arrays': 1470}
            or not isinstance(synthetic.get('aggregate'), dict)
            or synthetic['aggregate'].get('all', {}).get('accuracy_eligible_cases') != 227
            or synthetic['aggregate'].get('all', {}).get('ambiguous_cases') != 15
            or synthetic['aggregate'].get('all', {}).get('silence_cases') != 3):
        raise ValueError('complete synthetic diagnostic population required')


def diagnose(work, corpus, synthetic_work, synthetic):
    # Imports are deliberately after the fail-closed replay gate in run().
    from scripts.note_boundary_diagnostics import analyze_private
    from scripts.note_boundary_synthetic import diagnose_report

    public, details = analyze_private(work, corpus)
    dsp.save(work / 'boundary-private.json', details)
    return public, diagnose_report(synthetic_work, synthetic)


def run(work, replay_path, synthetic_work, synthetic_path, replay_audit_path, report_path):
    started = time.monotonic()
    report = {'schema': 'note-boundary-diagnostics-v1', 'status': 'started',
              'source_revision': os.getenv('GITHUB_SHA'),
              'protocol_head_revision': os.getenv('EXPERIMENT_HEAD_SHA'),
              'source_sha256': {p: dsp.digest(ROOT / p) for p in SOURCE_PATHS},
              'input_reports_sha256': {name: dsp.digest(path) for name, path in (
                  ('vocadito', replay_path), ('synthetic', synthetic_path), ('replay_audit', replay_audit_path))},
              'replay_parity': None, 'corpus': None, 'synthetic': None,
              'quality_approved': False, 'heldout_generalization': False,
              'product_changes': False, 'reference_used_for_edits': False,
              'all_cases_complete': False}
    dsp.save(report_path, report)
    try:
        corpus, synthetic = read_json(replay_path), read_json(synthetic_path)
        require_private_audit(read_json(replay_audit_path), replay_path)
        report['replay_parity'] = replay_parity(corpus, synthetic)
        if not report['replay_parity']['all_equal']:
            report['status'] = 'replay_parity_failed'
        else:
            report['corpus'], report['synthetic'] = diagnose(work, corpus, synthetic_work, synthetic)
            require_complete_diagnostics(report['corpus'], report['synthetic'], corpus, synthetic)
            report.update(status='complete', all_cases_complete=True)
    except Exception as exc:
        report.update(status='failed', error_type=type(exc).__name__, corpus=None, synthetic=None)
        (work / 'boundary-error.txt').write_text(str(exc))
    finally:
        report['elapsed_seconds'] = time.monotonic() - started
        dsp.save(report_path, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('work', 'replay', 'synthetic-work', 'synthetic', 'replay-audit', 'report'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    private = (args.work, args.synthetic_work)
    if (any(p.is_symlink() or not p.is_dir() or p.resolve().is_relative_to(ROOT) for p in private)
            or args.report.exists() or args.report.is_symlink() or args.report.resolve().is_relative_to(ROOT)
            or os.getenv('HF_TOKEN') or os.getenv('HUGGING_FACE_HUB_TOKEN')):
        parser.error('existing private work and new report outside checkout, no model credentials required')
    result = run(args.work, args.replay, args.synthetic_work, args.synthetic, args.replay_audit, args.report)
    print(json.dumps({'status': result['status'], 'all_cases_complete': result['all_cases_complete']}))
    return 0 if result['status'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())

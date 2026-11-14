"""Version 2 CI qualification for the unchanged #298 numerical input contract.

This diagnostic calls input generators and the analytic table only. It never
calls a predictor, decoder, authored truth, reference reader, or scorer. Native
dispatch is observed, never changed. Exact differences fail qualification;
the original experiment sources, manifests, and tests remain byte-for-byte.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import io
import json
import os
import platform
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE_MANIFEST = 'docs/research/RESEARCH_NUMERIC_CI_V2_FROZEN_SOURCES_2026-11-14.json'
SOURCE_MANIFEST_SHA256 = 'f2a02900899ce62d10a010104e28948c5afb75478ba310636c241000b77f2ee2'
SCHEMA = 'research-numeric-qualification-v2'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def environment():
    """Record the imported module/build, not the unrelated product installation."""
    config = io.StringIO()
    with contextlib.redirect_stdout(config):
        np.show_config()
    runtime = io.StringIO()
    runtime_error = None
    try:
        with contextlib.redirect_stdout(runtime):
            np.show_runtime()
    except Exception as exc:
        runtime_error = f'{type(exc).__name__}: {exc}'
    backend = np.core._multiarray_umath
    cpu = Path('/proc/cpuinfo')
    cpu_models = []
    if cpu.is_file():
        cpu_models = sorted({line.split(':', 1)[1].strip()
                             for line in cpu.read_text().splitlines()
                             if line.startswith('model name')})
    return {
        'python': platform.python_version(), 'python_build': list(platform.python_build()),
        'executable': sys.executable, 'prefix': sys.prefix, 'platform': platform.platform(),
        'libc': list(platform.libc_ver()), 'numpy_version': np.__version__,
        'numpy_file': np.__file__, 'numpy_extension_file': backend.__file__,
        'numpy_extension_sha256': digest(backend.__file__), 'numpy_build': config.getvalue(),
        'numpy_runtime': runtime.getvalue(), 'numpy_runtime_error': runtime_error,
        'cpu_models': cpu_models,
        'cpu_features': {key: bool(value) for key, value in sorted(backend.__cpu_features__.items())},
        'cpu_baseline': list(backend.__cpu_baseline__), 'cpu_dispatch': list(backend.__cpu_dispatch__),
        'numpy_disable_cpu_features': os.environ.get('NPY_DISABLE_CPU_FEATURES'),
    }


def frozen_sources(root=ROOT):
    path = root / SOURCE_MANIFEST
    if path.is_symlink() or digest(path) != SOURCE_MANIFEST_SHA256:
        raise ValueError('v2_frozen_source_manifest_identity')
    manifest = json.loads(path.read_text())
    if manifest.get('source_count') != 66 or len(manifest.get('source_sha256', {})) != 66:
        raise ValueError('v2_frozen_source_inventory')
    differences = []
    for name, expected in manifest['source_sha256'].items():
        source = root / name
        actual = digest(source) if source.is_file() and not source.is_symlink() else None
        if actual != expected:
            differences.append({'path': name, 'expected_sha256': expected, 'actual_sha256': actual})
    receipt = root / manifest['source_receipt']
    actual_receipt = digest(receipt) if receipt.is_file() and not receipt.is_symlink() else None
    if actual_receipt != manifest['source_receipt_sha256']:
        differences.append({'path': manifest['source_receipt'],
                            'expected_sha256': manifest['source_receipt_sha256'],
                            'actual_sha256': actual_receipt})
    return {'manifest_sha256': SOURCE_MANIFEST_SHA256, 'source_files_compared': 66,
            'original_receipt_verified': actual_receipt == manifest['source_receipt_sha256'],
            'all_equal': not differences, 'differences': differences}


def compare_rows(actual, expected, differences):
    """Retain both identities, including dtype/shape, for every mismatching ID."""
    if [row['id'] for row in actual] != [row['id'] for row in expected]:
        raise ValueError('v2_exact_ordered_input_population')
    return [{'id': left['id'], 'difference_paths': differences(left, right, left['id']),
             'expected': right, 'actual': left}
            for left, right in zip(actual, expected, strict=True)
            if differences(left, right, left['id'])]


def qualify(*, arrays=None):
    """Observe before generating inputs; compare 245+216 arrays and 20 rows."""
    report = {'schema': SCHEMA, 'scope': 'input_identity_only', 'status': 'started',
              'environment': environment(), 'frozen_sources': frozen_sources(),
              'predictor_calls': 0, 'decoder_calls': 0, 'truth_or_reference_calls': 0,
              'scorer_calls': 0, 'scientific_trial': False}
    if not report['frozen_sources']['all_equal']:
        report.update(status='incompatible', reason='frozen_source_identity')
        return report
    # Importing frozen definitions performs no prediction or truth access.
    from scripts import audit_note_boundary_parent_guard as independent
    from scripts import note_boundary_parent_guard_synthetic as stress
    from scripts import note_boundary_readout_synthetic as prior
    from scripts import note_state_synthetic as legacy

    original = prior.read_numeric_manifest()
    stress_manifest = stress.read_numeric_manifest()
    rows = {'legacy': [], 'stress': [], 'independent_stress': []}
    for case in legacy.cases():
        hz, duration = legacy.observations(case)
        rows['legacy'].append(stress.input_identity(case, hz, duration))
        if arrays is not None:
            arrays[case.id] = hz
    for case in stress.stress_cases():
        hz, duration = stress.observations(case)
        rows['stress'].append(stress.input_identity(case, hz, duration))
        if arrays is not None:
            arrays[case.id] = hz
    for spec in independent.stress_specs():
        hz, duration = independent.stress_observations(spec)
        rows['independent_stress'].append({'id': spec['id'], 'duration_seconds': duration,
                                         'observation': independent.array_identity(hz)})
    analytic = legacy.emission_analysis()
    all_differences = {}
    for name, expected in (('legacy', original['cases']), ('stress', stress_manifest['cases']),
                           ('independent_stress', stress_manifest['cases'])):
        all_differences[name] = compare_rows(rows[name], expected, prior.numeric_difference_paths)
    analytic_differences = prior.numeric_difference_paths(
        analytic, original['emission_analysis'], '/emission_analysis')
    report.update(
        status='compatible' if not any(all_differences.values()) and not analytic_differences else 'incompatible',
        legacy_manifest_sha256=prior.NUMERIC_INPUTS_SHA256,
        stress_manifest_sha256=stress.NUMERIC_INPUTS_SHA256,
        generation_environment=stress_manifest['generation_environment'],
        compared_input_arrays=461, independently_regenerated_stress_arrays=216,
        compared_analytic_rows=20, observations=rows,
        input_differences=all_differences, analytic_difference_paths=analytic_differences,
        analytic_actual=analytic,
        first_input_difference=next((items[0] for items in all_differences.values() if items), None),
    )
    return report


def mutation_contract(qualification):
    """Qualify positively before checking seven *specific* rejection locations.

    This is a CI fixture contract, not an audit of past raw arrays. Its fixtures
    use only the two input-only manifests; no historical score/truth is loaded.
    """
    if qualification.get('schema') != SCHEMA or qualification.get('status') != 'compatible':
        raise ValueError('v2_positive_environment_qualification_required')
    from scripts import audit_note_boundary_parent_guard as audit
    from scripts import note_boundary_readout_synthetic as prior

    original = prior.read_numeric_manifest()
    rows = copy.deepcopy(qualification['observations']['legacy'] + qualification['observations']['stress'])
    legacy_gate = {'manifest_sha256': prior.NUMERIC_INPUTS_SHA256, 'compared_input_arrays': 245,
                   'compared_analytic_rows': 20, 'all_equal': True, 'input_differences': [],
                   'analytic_difference_paths': [], 'model_calls_before_preflight': 0}
    stress_gate = {'manifest_sha256': audit.NUMERIC_MANIFEST_SHA256, 'compared_input_arrays': 216,
                   'all_equal': True, 'input_differences': [], 'model_calls_before_preflight': 0}
    report = {'cases': rows, 'emission_analysis': qualification['analytic_actual'],
              'stress_timing_semantics': audit.TIMING_SEMANTICS,
              'preflight': {'schema': 'note-boundary-parent-guard-preflight-v1',
                            'legacy': legacy_gate, 'stress': stress_gate,
                            'compared_input_arrays': 461, 'compared_analytic_rows': 20,
                            'all_equal': True, 'model_calls_before_preflight': 0}}
    positive = audit.check_numeric_preflight(report, original, audit.Checks())
    labels = {
        'stress_input': 'same_stress_preflight_inputs_used',
        'legacy_input': 'same_preflight_inputs_used_by_predictions',
        'missing': 'same_stress_preflight_inputs_used',
        'models': 'independent_combined_input_only_preflight/model_calls_before_preflight',
        'stress_models': 'independent_combined_input_only_preflight/stress/model_calls_before_preflight',
        'extra_gate': 'independent_combined_input_only_preflight',
        'legacy_analytic': 'same_preflight_analytic_rows_used',
    }
    outcomes = {}
    for mutation, expected in labels.items():
        damaged = copy.deepcopy(report)
        if mutation in ('stress_input', 'legacy_input'):
            damaged['cases'][245 if mutation == 'stress_input' else 0]['observation']['sha256'] = '0' * 64
        elif mutation == 'missing':
            damaged['cases'].pop()
        elif mutation == 'models':
            damaged['preflight']['model_calls_before_preflight'] = 1
        elif mutation == 'stress_models':
            damaged['preflight']['stress']['model_calls_before_preflight'] = 1
        elif mutation == 'extra_gate':
            damaged['preflight']['new_parameter'] = .075
        else:
            damaged['emission_analysis'][0]['attack_mass'] += 1e-15
        try:
            audit.check_numeric_preflight(damaged, original, audit.Checks())
        except ValueError as exc:
            actual = str(exc)
            if actual.split(':', 1)[0] != expected:
                raise ValueError(f'v2_wrong_mutation_rejection/{mutation}: {actual}') from exc
            outcomes[mutation] = actual
        else:
            raise ValueError('v2_mutation_not_rejected/' + mutation)
    return {'status': 'pass', 'positive_compared_input_arrays': positive['compared_input_arrays'],
            'specific_rejections_verified': len(outcomes), 'rejection_messages': outcomes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--arrays-output', type=Path)
    args = parser.parse_args()
    arrays = {} if args.arrays_output is not None else None
    report = qualify(arrays=arrays)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    if args.arrays_output is not None:
        args.arrays_output.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(args.arrays_output, **arrays)
    print(json.dumps({'status': report['status'], 'output': str(args.output),
                      'first_input_difference': report.get('first_input_difference'),
                      'analytic_difference_paths': report.get('analytic_difference_paths')}), flush=True)
    return 0 if report['status'] == 'compatible' else 2


if __name__ == '__main__':
    raise SystemExit(main())

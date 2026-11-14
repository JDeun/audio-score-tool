"""Input-only dispatch diagnosis; never used to configure scientific runs or CI.

Compare native dispatch with AVX512F excluded in a separate child. The two
qualification reports and numerical differences are retained whether either
host qualification passes or fails. No predictor, truth, or score is used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def probe(directory):
    if os.environ.get('NPY_DISABLE_CPU_FEATURES'):
        raise ValueError('start this diagnostic with unmodified native dispatch')
    directory.mkdir(parents=True, exist_ok=False)
    runs = {}
    for name, disabled in (('native', None), ('diagnostic_avx512f_disabled', 'AVX512F')):
        environment = dict(os.environ)
        if disabled is not None:
            environment['NPY_DISABLE_CPU_FEATURES'] = disabled
        output, arrays = directory / (name + '.json'), directory / (name + '.npz')
        command = [sys.executable, '-m', 'scripts.research_numeric_qualification',
                   '--output', str(output), '--arrays-output', str(arrays)]
        process = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True,
                                 text=True, timeout=60, check=False)
        runs[name] = {'returncode': process.returncode, 'stderr': process.stderr,
                      'report': json.loads(output.read_text()) if output.is_file() else None}
    result = {'schema': 'research-numeric-dispatch-diagnosis-v2', 'scientific_trial': False,
              'dispatch_changed_only_in_diagnostic_child': True,
              'predictor_calls': 0, 'decoder_calls': 0, 'truth_or_reference_calls': 0,
              'scorer_calls': 0, 'runs': runs,
              'diagnostic_source_sha256': {
                  name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
                      'scripts/probe_research_numeric_dispatch.py',
                      'scripts/research_numeric_qualification.py')}}
    if any(run['returncode'] not in (0, 2) or run['report'] is None for run in runs.values()):
        result['status'] = 'diagnostic_error'
    else:
        result['status'] = 'complete'
        comparisons = {}
        with (np.load(directory / 'native.npz', allow_pickle=False) as native,
              np.load(directory / 'diagnostic_avx512f_disabled.npz', allow_pickle=False) as disabled):
            if native.files != disabled.files or len(native.files) != 461:
                raise ValueError('exact diagnostic array inventory required')
            for cohort in ('legacy', 'stress'):
                ids = [case for case in native.files if case.startswith('stress_') == (cohort == 'stress')]
                different, samples, maximum_absolute, maximum_ulp = [], 0, 0., 0
                for case in ids:
                    left, right = native[case], disabled[case]
                    if (left.dtype.str != '<f8' or right.dtype.str != '<f8' or left.shape != right.shape
                            or not np.all(np.isfinite(left)) or not np.all(np.isfinite(right))
                            or np.any(left < 0) or np.any(right < 0)):
                        raise ValueError('finite nonnegative equal-shape float64 inputs required')
                    changed = left.view(np.uint64) != right.view(np.uint64)
                    if np.any(changed):
                        different.append(case)
                        samples += int(changed.sum())
                        maximum_absolute = max(maximum_absolute, float(np.max(np.abs(left - right))))
                        low, high = np.minimum(left, right), np.maximum(left, right)
                        maximum_ulp = max(maximum_ulp, int(np.max(high.view(np.uint64) - low.view(np.uint64))))
                comparisons[cohort] = {'compared_arrays': len(ids), 'different_array_ids': different,
                                       'different_arrays': len(different), 'changed_samples': samples,
                                       'maximum_absolute_hz_difference': maximum_absolute,
                                       'maximum_ulp_difference': maximum_ulp}
        result['comparisons'] = comparisons
    output = directory / 'comparison.json'
    output.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    return result, output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory', type=Path, required=True)
    args = parser.parse_args()
    result, output = probe(args.output_directory.resolve())
    summary = {name: {key: value for key, value in comparison.items() if key != 'different_array_ids'}
               for name, comparison in result.get('comparisons', {}).items()}
    print(json.dumps({'status': result['status'], 'output': str(output),
                      'comparisons': summary}))
    return 0 if result['status'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())

"""Frozen #298 parent-guard comparison with 245 legacy and 216 new F0 controls.

Every one of the 461 x 9 event files is saved before either authored truth
function is called.  The old eight arms and six paths are produced once, then
the guard reads the same G path and original G Note objects.  No acoustic
tracker, parameter search, product setting or pooled synthetic accuracy exists
in this runner.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from scripts import dsp_note_probe as dsp
from scripts import note_boundary_parent_guard as guard
from scripts import note_boundary_readout_synthetic as previous
from scripts import note_state_synthetic as frozen

ROOT = Path(__file__).resolve().parents[1]
ARM, BASE_ARM, SPLIT_ARM = guard.ARM, guard.BASE_ARM, guard.SPLIT_ARM
ARMS = (*previous.ARMS, ARM)
PATH_ARMS = previous.PATH_ARMS
PREVIOUS = 'docs/research/receipts/note-boundary-readout-43381098932-attempt-1.zip'
PREVIOUS_SHA256 = 'f34e88d2b5023df5762fba46b4149167265efbd24a837d30500375b30cd5758f'
NUMERIC_INPUTS = 'docs/research/NOTE_BOUNDARY_PARENT_GUARD_NUMERIC_INPUTS_2026-11-13.json'
NUMERIC_INPUTS_SHA256 = 'faadd9f40129dbc2801c4e283b2d2946112113362d4786cc8be6cb731f8e6e6c'
COHORTS = ('legacy', 'single_expression', 'adjacent_semitone')
STRESS_PITCHES = (45, 57, 69)
DETUNINGS = (-.4, 0., .4)
AMPLITUDES = (.3, .6)
FREQUENCIES_HZ = (3, 6)
VOICED_FRAMES = (24, 48, 96)
SILENCE_FRAMES = 10
TIMING_SEMANTICS = {
    'frame_seconds': .01,
    'leading_silence_frames': 10,
    'trailing_silence_intervals': 10,
    'sample_count': 'voiced_frames + 21',
    'voiced_frame_interval': '[10, 10 + voiced_frames)',
    'duration_seconds': '(voiced_frames + 20) * 0.01',
    'terminal_sample': 'zero Hz at duration; no extra audio interval',
    'modulation_time': 'local voiced integer frame * 0.01; phase 0',
    'adjacent_change_frame': '10 + voiced_frames // 2; continuous modulation phase',
    'hz_conversion': '440 * 2 ** ((fractional_midi - 69) / 12)',
    'audio_duration_clipping': 'unchanged frozen readout',
}
LEGACY_CASE_FIELDS = (*previous.LEGACY_CASE_FIELDS, 'readout_private_sha256', 'comparison')
LEGACY_SCALAR_FIELDS = (*previous.LEGACY_FIELDS, 'product_changes', 'numerical_environment')
VOLATILE = previous.VOLATILE | {'numerical_environment'}


@dataclass(frozen=True)
class StressCase:
    id: str
    kind: str
    pitch: int
    detuning: float
    amplitude: float
    frequency_hz: int
    frames: int

    @property
    def accuracy_eligible(self):
        return True


def stress_cases():
    result = []
    for kind in COHORTS[1:]:
        index = 0
        for pitch in STRESS_PITCHES:
            for detuning in DETUNINGS:
                for amplitude in AMPLITUDES:
                    for frequency in FREQUENCIES_HZ:
                        for frames in VOICED_FRAMES:
                            index += 1
                            result.append(StressCase(f'stress_{kind}_{index:03d}', kind,
                                pitch, detuning, amplitude, frequency, frames))
    return tuple(result)


def cases():
    return (*frozen.cases(), *stress_cases())


def cohort(case):
    return case.kind if isinstance(case, StressCase) else 'legacy'


def observations(case):
    """Generate input only; the predictor never receives this case specification."""
    if not isinstance(case, StressCase):
        return frozen.observations(case)
    if case.kind not in COHORTS[1:] or case.frames not in VOICED_FRAMES:
        raise ValueError('unknown authored stress specification')
    local_frames = np.arange(case.frames, dtype=np.float64)
    midi = case.pitch + case.detuning + case.amplitude * np.sin(
        2 * np.pi * case.frequency_hz * local_frames * dsp.DT)
    if case.kind == 'adjacent_semitone':
        midi[case.frames // 2:] += 1.
    total = 2 * SILENCE_FRAMES + case.frames
    hz = np.zeros(total + 1, dtype=np.float64)
    hz[SILENCE_FRAMES:SILENCE_FRAMES + case.frames] = 440 * 2 ** ((midi - 69) / 12)
    return hz, total * dsp.DT


def truth(case):
    """Independent authored intent; fractional pitch centers remain unrounded."""
    if not isinstance(case, StressCase):
        return frozen.truth(case)
    onset = SILENCE_FRAMES * dsp.DT
    offset = (SILENCE_FRAMES + case.frames) * dsp.DT
    center = case.pitch + case.detuning
    if case.kind == 'single_expression':
        return [dsp.Note(center, onset, offset)]
    if case.kind != 'adjacent_semitone':
        raise ValueError('unknown authored truth specification')
    middle = (SILENCE_FRAMES + case.frames // 2) * dsp.DT
    return [dsp.Note(center, onset, middle), dsp.Note(center + 1., middle, offset)]


def alternative_truth(case):
    return [] if isinstance(case, StressCase) else frozen.alternative_truth(case)


def numerical_environment():
    return previous.numerical_environment()


def input_identity(case, hz, duration):
    return {'id': case.id, 'duration_seconds': duration, 'observation': frozen.identity(hz)}


def make_numeric_manifest():
    """Input-only authoring step; never decode a path or read authored truth.

    The original 245 inputs and 20 analytic rows must first reproduce their
    immutable numeric whitelist.  Only the new 216 input identities are added;
    their generation process is recorded without changing CPU dispatch.
    """
    if np.__version__ != previous.EXPECTED_RUNTIME['numpy']:
        raise ValueError('NumPy 1.26.4 is required to author numeric inputs')
    _prepared, _analytic, old_preflight = previous.prepare_inputs(frozen.cases())
    if not old_preflight['all_equal']:
        raise ValueError('original input-only numeric preflight must pass')
    return {
        'schema': 'note-boundary-parent-guard-numeric-inputs-v1',
        'baseline_zip_sha256': PREVIOUS_SHA256,
        'legacy_numeric_manifest_sha256': previous.NUMERIC_INPUTS_SHA256,
        'timing_semantics': TIMING_SEMANTICS,
        'generation_environment': numerical_environment(),
        'cases': [input_identity(case, *observations(case)) for case in stress_cases()],
    }


def read_numeric_manifest():
    path = ROOT / NUMERIC_INPUTS
    if path.is_symlink() or not path.is_file() or dsp.digest(path) != NUMERIC_INPUTS_SHA256:
        raise ValueError('immutable parent-guard numeric input manifest required')
    manifest = json.loads(path.read_text())
    environment_keys = {'python', 'executable', 'platform', 'numpy_version', 'numpy_file',
        'runtime', 'cpu_features', 'cpu_baseline', 'cpu_dispatch', 'numpy_disable_cpu_features'}
    if (set(manifest) != {'schema', 'baseline_zip_sha256', 'legacy_numeric_manifest_sha256',
                         'timing_semantics', 'generation_environment', 'cases'}
            or manifest['schema'] != 'note-boundary-parent-guard-numeric-inputs-v1'
            or manifest['baseline_zip_sha256'] != PREVIOUS_SHA256
            or manifest['legacy_numeric_manifest_sha256'] != previous.NUMERIC_INPUTS_SHA256
            or previous.numeric_difference_paths(manifest['timing_semantics'], TIMING_SEMANTICS, '/timing')
            or set(manifest['generation_environment']) != environment_keys
            or manifest['generation_environment']['numpy_version'] != '1.26.4'
            or len(manifest['cases']) != 216
            or [row['id'] for row in manifest['cases']] != [case.id for case in stress_cases()]
            or any(set(row) != {'id', 'duration_seconds', 'observation'}
                   or set(row['observation']) != {'dtype', 'shape', 'sha256'} for row in manifest['cases'])):
        raise ValueError('exact input-only parent-guard manifest inventory required')
    return manifest


def compare_stress_inputs(prepared, manifest):
    if [case.id for case, _hz, _duration in prepared] != [row['id'] for row in manifest['cases']]:
        raise ValueError('exact ordered stress input manifest population required')
    differences = [case.id for (case, hz, duration), expected in
                   zip(prepared, manifest['cases'], strict=True)
                   if previous.numeric_difference_paths(input_identity(case, hz, duration), expected, case.id)]
    return {'manifest_sha256': NUMERIC_INPUTS_SHA256,
            'compared_input_arrays': len(prepared), 'all_equal': not differences,
            'input_differences': differences, 'model_calls_before_preflight': 0}


def prepare_inputs(plan):
    if [asdict(case) for case in plan] != [asdict(case) for case in cases()]:
        raise ValueError('original ordered 461-case specifications required')
    manifest = read_numeric_manifest()
    old, analytic, old_preflight = previous.prepare_inputs(tuple(case for case in plan
                                                                if cohort(case) == 'legacy'))
    new = [(case, *observations(case)) for case in plan if cohort(case) != 'legacy']
    new_preflight = compare_stress_inputs(new, manifest)
    preflight = {
        'schema': 'note-boundary-parent-guard-preflight-v1',
        'legacy': old_preflight, 'stress': new_preflight,
        'compared_input_arrays': len(old) + len(new), 'compared_analytic_rows': len(analytic),
        'all_equal': old_preflight['all_equal'] and new_preflight['all_equal'],
        'model_calls_before_preflight': 0,
    }
    return [*old, *new], analytic, preflight


def predict(hz, duration):
    """Case metadata and truth are intentionally absent from this signature."""
    arms, paths, diagnostics, split_public, split_trace = previous.predict(hz, duration)
    if set(arms) != set(previous.ARMS) or set(paths) != set(PATH_ARMS):
        raise ValueError('all eight frozen arms and six paths required')
    before_hz = frozen.identity(hz)
    before_paths = {name: frozen.identity(path) for name, path in paths.items()}
    notes, public, trace = guard.notes_from_state_path(paths[BASE_ARM], hz, duration,
                                                     original_notes=arms[BASE_ARM])
    if before_hz != frozen.identity(hz) or before_paths != {
            name: frozen.identity(path) for name, path in paths.items()}:
        raise ValueError('guard mutated shared observations or paths')
    if public['accepted_cut_count'] == 0 and notes != arms[BASE_ARM]:
        raise ValueError('no-accepted-cut Gaussian event identity changed')
    if dsp.fingerprint(guard.interval_union(notes)) != dsp.fingerprint(guard.interval_union(arms[BASE_ARM])):
        raise ValueError('guard changed emitted interval union')
    return {**arms, ARM: notes}, paths, diagnostics, split_public, split_trace, public, trace


def require_population(rows):
    plan = cases()
    if (len(rows) != 461 or len(plan) != 461
            or [row.get('spec') for row in rows] != [asdict(case) for case in plan]
            or [row.get('id') for row in rows] != [case.id for case in plan]
            or any(row.get('cohort') != cohort(case)
                   or type(row.get('accuracy_eligible')) is not bool
                   or row['accuracy_eligible'] != case.accuracy_eligible
                   or set(row.get('arms', {})) != set(ARMS)
                   for row, case in zip(rows, plan, strict=True))):
        raise ValueError('incomplete fixed parent-guard synthetic population')
    old = legacy_rows(rows, scored=False)
    old_counts = previous.require_population(old)
    counts = {'legacy': old_counts,
              **{name: {'all_cases': sum(row['cohort'] == name for row in rows),
                        'accuracy_eligible_cases': sum(row['cohort'] == name and row['accuracy_eligible']
                                                       for row in rows)} for name in COHORTS[1:]}}
    if counts['single_expression'] != {'all_cases': 108, 'accuracy_eligible_cases': 108} or (
            counts['adjacent_semitone'] != {'all_cases': 108, 'accuracy_eligible_cases': 108}):
        raise ValueError('fixed 108/108 stress denominators changed')
    return counts


def prediction_manifest(rows):
    require_population(rows)
    return dsp.fingerprint({row['id']: {arm: row['arms'][arm]['event_sha256'] for arm in ARMS}
                            for row in rows})


def verify_prediction_files(work, rows):
    """Check all saved predictions, both traces and every input/path array."""
    for row in rows:
        for arm in ARMS:
            path = work / row['id'] / f'{arm}.json'
            if path.is_symlink() or not path.is_file() or dsp.digest(path) != row['arms'][arm]['event_sha256']:
                raise ValueError('synthetic prediction mutation')
        for filename, key in (('readout-private.json', 'readout_private_sha256'),
                              ('guard-private.json', 'guard_private_sha256')):
            path = work / row['id'] / filename
            if path.is_symlink() or not path.is_file() or dsp.digest(path) != row[key]:
                raise ValueError('private synthetic trace mutation')
        path = work / row['id'] / 'observations.npz'
        if path.is_symlink() or not path.is_file():
            raise ValueError('saved synthetic observations missing')
        with np.load(path, allow_pickle=False) as arrays:
            if (set(arrays.files) != {'hz', *PATH_ARMS}
                    or frozen.identity(arrays['hz']) != row['observation']
                    or any(frozen.identity(arrays[arm]) != row['arms'][arm]['state_path']
                           for arm in PATH_ARMS)):
                raise ValueError('synthetic observations or state path mutation')
    return prediction_manifest(rows)


def snapshot(value):
    """Plain JSON projection also accepts immutable dict subclasses."""
    return json.loads(json.dumps(value, allow_nan=False))


def legacy_rows(rows, *, scored=True):
    fields = LEGACY_CASE_FIELDS if scored else ('id', 'spec', 'accuracy_eligible')
    return [{**{key: snapshot(row[key]) for key in fields},
             'arms': {arm: snapshot(row['arms'][arm]) for arm in previous.ARMS}}
            for row in rows if row['cohort'] == 'legacy']


def legacy_projection(report):
    """Recreate the complete #297 eight-arm report without prediction calls."""
    from scripts.run_note_boundary_readout import SOURCE_PATHS

    if report.get('status') != 'complete':
        raise ValueError('complete parent-guard synthetic report required for legacy projection')
    require_population(report['cases'])
    rows = legacy_rows(report['cases'])
    manifest = previous.prediction_manifest(rows)
    result = {
        'schema': 'note-boundary-readout-synthetic-v1',
        **{key: snapshot(report[key]) for key in LEGACY_SCALAR_FIELDS},
        'planned_cases': 245, 'planned_arms': list(previous.ARMS), 'cases': rows,
        'source_sha256': {path: report['source_sha256'][path] for path in SOURCE_PATHS},
        'preflight': snapshot(report['preflight']['legacy']),
        'predictions_manifest_sha256': manifest,
        'post_evaluation_predictions_manifest_sha256': manifest,
        'truth_access_started_after_prediction_files': 1960,
        'aggregate': previous.summarize(rows), 'comparisons': previous.comparison_summary(rows),
    }
    result['historical_parity'] = previous.historical_parity(result)
    return result


def note_evaluation(predicted, reference):
    """Diagnostic pitch errors among timing-matched pairs; no new acceptance rule."""
    import mir_eval.transcription as mt

    if not reference:
        raise ValueError('eligible nonempty authored truth required')
    ref_intervals = np.asarray([(note.onset, note.offset) for note in reference], dtype=float)
    pred_intervals = np.asarray([(note.onset, note.offset) for note in predicted], dtype=float).reshape(-1, 2)
    ref_hz = np.asarray([440 * 2 ** ((note.pitch - 69) / 12) for note in reference])
    pred_hz = np.asarray([440 * 2 ** ((note.pitch - 69) / 12) for note in predicted])
    result = {'reference_notes': len(reference), 'predicted_notes': len(predicted),
              'note_count_change': len(predicted) - len(reference)}
    for name, ratio in (('onset', None), ('onset_offset', .2)):
        pairs = mt.match_notes(ref_intervals, ref_hz, pred_intervals, pred_hz,
            onset_tolerance=.05, pitch_tolerance=50., offset_ratio=ratio,
            offset_min_tolerance=.05) if predicted else []
        result[name] = {'matched_notes': len(pairs),
                        'precision': len(pairs) / len(predicted) if predicted else 0.,
                        'recall': len(pairs) / len(reference)}
    timed = mt.match_notes(ref_intervals, ref_hz, pred_intervals, pred_hz,
        onset_tolerance=.05, pitch_tolerance=np.inf, offset_ratio=.2,
        offset_min_tolerance=.05) if predicted else []
    cents = [float(abs(1200 * np.log2(pred_hz[j] / ref_hz[i]))) for i, j in timed]
    result.update(timing_only_matched_pairs=len(timed),
                  timing_only_unmatched_reference_notes=len(reference) - len(timed),
                  timing_only_unmatched_prediction_notes=len(predicted) - len(timed),
                  timing_matched_pitch_correct_pairs=sum(value <= 50. for value in cents),
                  timing_matched_pitch_wrong_pairs=sum(value > 50. for value in cents),
                  timing_matched_absolute_pitch_cents={
                      'count': len(cents), 'minimum': min(cents) if cents else None,
                      'median': float(np.median(cents)) if cents else None,
                      'maximum': max(cents) if cents else None,
                  })
    return result


def compare_case(row, baseline_arm):
    base, candidate = row['arms'][baseline_arm], row['arms'][ARM]
    result = {'baseline_arm': baseline_arm, 'candidate_arm': ARM,
              'predicted_notes_change': candidate['count'] - base['count'],
              'event_identity_unchanged': candidate['event_sha256'] == base['event_sha256'],
              'no_accepted_cuts': candidate['readout']['accepted_cut_count'] == 0,
              'onset_f1_change': None, 'onset_offset_f1_change': None,
              'baseline_perfect': None, 'candidate_perfect': None}
    if row['accuracy_eligible']:
        for metric in ('onset_f1', 'onset_offset_f1'):
            result[metric + '_change'] = candidate['metrics'][metric] - base['metrics'][metric]
        result['baseline_perfect'] = all(base['metrics'][m] == 1. for m in ('onset_f1', 'onset_offset_f1'))
        result['candidate_perfect'] = all(candidate['metrics'][m] == 1. for m in ('onset_f1', 'onset_offset_f1'))
    if baseline_arm == BASE_ARM and result['no_accepted_cuts'] and not result['event_identity_unchanged']:
        raise ValueError('no-accepted-cut prediction file identity changed')
    return result


def arm_summary(rows, arm):
    eligible = [row for row in rows if row['accuracy_eligible']]
    result = {
        'all_cases_predicted_notes': sum(row['arms'][arm]['count'] for row in rows),
        'empty_output_cases': sum(row['arms'][arm]['count'] == 0 for row in rows),
        'eligible_cases': len(eligible),
        'silence_false_positive_notes': sum(row['arms'][arm]['count'] for row in rows
                                          if row['spec']['kind'] == 'silence'),
        'too_many_note_cases': sum(row['arms'][arm]['count'] > len(row['truth']) for row in eligible),
        'too_few_note_cases': sum(row['arms'][arm]['count'] < len(row['truth']) for row in eligible),
        'equal_note_count_cases': sum(row['arms'][arm]['count'] == len(row['truth']) for row in eligible),
        'timing_only_matched_pairs': sum(row['note_evaluation'][arm]['timing_only_matched_pairs']
                                        for row in eligible),
        'timing_matched_pitch_wrong_pairs': sum(row['note_evaluation'][arm]['timing_matched_pitch_wrong_pairs']
                                               for row in eligible),
    }
    for metric in ('onset_f1', 'onset_offset_f1'):
        result[metric] = float(np.mean([row['arms'][arm]['metrics'][metric] for row in eligible]))
    return result


def summarize(rows):
    require_population(rows)
    return {name: {arm: arm_summary([row for row in rows if row['cohort'] == name], arm)
                   for arm in ARMS} for name in COHORTS}


def comparison_summary(rows):
    populations = require_population(rows)
    result = {}
    for name in COHORTS:
        selected = [row for row in rows if row['cohort'] == name]
        eligible = [row for row in selected if row['accuracy_eligible']]
        comparisons = {}
        for baseline in (BASE_ARM, SPLIT_ARM):
            changes = {}
            for metric in ('onset_f1', 'onset_offset_f1'):
                values = [row['guard_comparisons'][baseline][metric + '_change'] for row in eligible]
                changes[metric] = {
                    'macro_change': float(np.mean(values)),
                    'improved_cases': sum(value > 0 for value in values),
                    'worse_cases': sum(value < 0 for value in values),
                    'tied_cases': sum(value == 0 for value in values),
                }
            comparisons[baseline] = {
                'baseline_arm': baseline, 'candidate_arm': ARM,
                'identical_event_cases': sum(row['guard_comparisons'][baseline]['event_identity_unchanged']
                                             for row in selected),
                'eligible_metric_changes': changes,
            }
        result[name] = {**populations[name], 'baseline_comparisons': comparisons,
                        'no_accepted_cut_cases': sum(row['arms'][ARM]['readout']['accepted_cut_count'] == 0
                                                     for row in selected)}
    old = [row for row in rows if row['cohort'] == 'legacy']
    successes = [row for row in old if row['guard_comparisons'][BASE_ARM]['baseline_perfect']]
    controls = [row for row in old if row['id'] in previous.SEMITONE_CONTROL_IDS]
    if len(successes) != 221 or tuple(row['id'] for row in controls) != previous.SEMITONE_CONTROL_IDS:
        raise ValueError('frozen six controls or 221 prior successes changed')
    result['legacy'].update(
        previous_gaussian_perfect_cases=len(successes),
        previous_gaussian_perfect_case_ids=[row['id'] for row in successes],
        damaged_previous_success_case_ids=[row['id'] for row in successes
                                          if not row['guard_comparisons'][BASE_ARM]['candidate_perfect']],
        joined_semitone_controls=[{
            'id': row['id'], 'reference_notes': len(row['truth']),
            'baseline_predicted_notes': row['arms'][BASE_ARM]['count'],
            'split_predicted_notes': row['arms'][SPLIT_ARM]['count'],
            'candidate_predicted_notes': row['arms'][ARM]['count'],
            'baseline_metrics': row['arms'][BASE_ARM]['metrics'],
            'split_metrics': row['arms'][SPLIT_ARM]['metrics'],
            'candidate_metrics': row['arms'][ARM]['metrics'],
            'candidate_two_notes_pitch_onset_offset_correct': (
                len(row['truth']) == row['arms'][ARM]['count'] == 2
                and row['guard_comparisons'][BASE_ARM]['candidate_perfect']),
        } for row in controls])
    return result


def historical_parity(report, previous_path=None):
    path = ROOT / PREVIOUS if previous_path is None else previous_path
    if path.is_symlink() or not path.is_file() or dsp.digest(path) != PREVIOUS_SHA256:
        raise ValueError('wrong original #297 artifact')
    with zipfile.ZipFile(path) as archive:
        if set(archive.namelist()) != {'legacy-synthetic.json', 'synthetic.json', 'vocadito.json',
                                      'legacy-vocadito.json', 'legacy-audit.json', 'audit.json'}:
            raise ValueError('original #297 artifact inventory differs')
        baseline = json.loads(archive.read('synthetic.json'))
    legacy = legacy_projection(report)
    actual = {key: value for key, value in legacy.items() if key not in VOLATILE}
    expected = {key: value for key, value in baseline.items() if key not in VOLATILE}
    differences = previous.numeric_difference_paths(actual, expected, '/legacy')
    counts = {'compared_prediction_files': sum(len(row['arms']) for row in legacy['cases']),
              'compared_input_arrays': len(legacy['cases']),
              'compared_state_paths': sum('state_path' in arm for row in legacy['cases']
                                          for arm in row['arms'].values())}
    return {'baseline_zip_sha256': PREVIOUS_SHA256, **counts,
            'all_equal': not differences and tuple(counts.values()) == (1960, 245, 1470),
            'differences': differences}


def source_hashes():
    from scripts.run_note_boundary_parent_guard import SOURCE_PATHS

    return {path: dsp.digest(ROOT / path) for path in SOURCE_PATHS}


def run(work, report_path, legacy_report_path=None):
    started = time.monotonic()
    work.mkdir(mode=0o700)
    plan = cases()
    report = {
        'schema': 'note-boundary-parent-guard-synthetic-v1', 'status': 'started', 'cases': [],
        'source_revision': os.getenv('GITHUB_SHA'), 'protocol_head_revision': os.getenv('EXPERIMENT_HEAD_SHA'),
        'source_sha256': source_hashes(), 'numerical_environment': numerical_environment(), 'preflight': None,
        'planned_cases': len(plan), 'planned_arms': list(ARMS), 'acoustic_extraction': False,
        'quality_approved': False, 'heldout_generalization': False, 'product_changes': False,
        'stress_timing_semantics': TIMING_SEMANTICS, 'cohorts': None,
        'emission_analysis': None, 'aggregate': None, 'comparisons': None,
        'all_predictions_saved_before_scoring': False, 'historical_parity': None,
    }
    dsp.save(report_path, report)
    try:
        previous.require_numerical_runtime(report['numerical_environment'])
        prepared, analytic, report['preflight'] = prepare_inputs(plan)
        report['emission_analysis'] = analytic
        dsp.save(report_path, report)
        if not report['preflight']['all_equal']:
            raise ValueError('exact numeric input preflight failed before model inference')
        for case, hz, duration in prepared:
            arms, paths, diagnostics, split_public, split_trace, public, trace = predict(hz, duration)
            directory = work / case.id
            directory.mkdir()
            np.savez_compressed(directory / 'observations.npz', hz=hz, **paths)
            dsp.save(directory / 'readout-private.json', split_trace)
            dsp.save(directory / 'guard-private.json', trace)
            row = {'id': case.id, 'spec': asdict(case), 'cohort': cohort(case), 'duration_seconds': duration,
                   'accuracy_eligible': case.accuracy_eligible, 'observation': frozen.identity(hz),
                   'readout_private_sha256': dsp.digest(directory / 'readout-private.json'),
                   'guard_private_sha256': dsp.digest(directory / 'guard-private.json'), 'arms': {}}
            for arm in ARMS:
                path = directory / f'{arm}.json'
                dsp.save(path, [asdict(note) for note in arms[arm]])
                row['arms'][arm] = {'count': len(arms[arm]), 'event_sha256': dsp.digest(path)}
                if arm in (ARM, SPLIT_ARM):
                    row['arms'][arm].update(readout=public if arm == ARM else split_public,
                        shared_state_path=frozen.identity(paths[BASE_ARM]), shared_state_path_arm=BASE_ARM)
                else:
                    row['arms'][arm]['diagnostics'] = diagnostics[arm]
                    if arm in paths:
                        row['arms'][arm]['state_path'] = frozen.identity(paths[arm])
            report['cases'].append(row)
        report['cohorts'] = require_population(report['cases'])
        report['predictions_manifest_sha256'] = verify_prediction_files(work, report['cases'])
        report['all_predictions_saved_before_scoring'] = True
        report['truth_access_started_after_prediction_files'] = sum(len(row['arms']) for row in report['cases'])
        dsp.save(report_path, report)
        for case, row in zip(plan, report['cases'], strict=True):
            reference = truth(case)
            row['truth'] = [asdict(note) for note in reference]
            row['alternative_truth'] = [asdict(note) for note in alternative_truth(case)]
            row['note_evaluation'] = {} if case.accuracy_eligible else None
            for arm in ARMS:
                path = work / case.id / f'{arm}.json'
                if dsp.digest(path) != row['arms'][arm]['event_sha256']:
                    raise ValueError('synthetic prediction mutation')
                notes = [dsp.Note(**note) for note in json.loads(path.read_text())]
                row['arms'][arm]['events'] = [asdict(note) for note in notes]
                row['arms'][arm]['metrics'] = frozen.score(notes, reference) if case.accuracy_eligible else None
                if case.accuracy_eligible:
                    row['note_evaluation'][arm] = note_evaluation(notes, reference)
            row['comparison'] = previous.compare_case(row)
            row['guard_comparisons'] = {baseline: compare_case(row, baseline) for baseline in (BASE_ARM, SPLIT_ARM)}
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
    for name in ('work', 'report', 'legacy-report'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    paths = [args.work, args.report, args.legacy_report]
    if (len({path.resolve() for path in paths}) != len(paths)
            or any(path.exists() or path.is_symlink() or path.resolve().is_relative_to(ROOT) for path in paths)
            or os.getenv('HF_TOKEN') or os.getenv('HUGGING_FACE_HUB_TOKEN')):
        parser.error('distinct new work and reports outside checkout, no model credentials required')
    return 0 if run(args.work, args.report, args.legacy_report)['status'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())

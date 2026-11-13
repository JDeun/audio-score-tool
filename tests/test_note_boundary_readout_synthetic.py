"""Barrier and identity contracts; no new full-grid performance experiment."""
from __future__ import annotations

import copy
import inspect
import json
import zipfile
from dataclasses import asdict

import numpy as np
import pytest

from scripts import note_boundary_readout_synthetic as subject
from scripts import note_state_synthetic as frozen


@pytest.fixture
def historical_report():
    with zipfile.ZipFile(subject.ROOT / subject.PREVIOUS) as archive:
        return json.loads(archive.read('synthetic.json'))


@pytest.fixture
def unchanged_candidate(historical_report):
    """An explicitly fake candidate copies G; no proposed readout is evaluated."""
    report = copy.deepcopy(historical_report)
    report['schema'] = 'note-boundary-readout-synthetic-v1'
    report['planned_arms'] = list(subject.ARMS)
    for row in report['cases']:
        base = row['arms'][subject.BASE_ARM]
        row['readout_private_sha256'] = '0' * 64
        row['arms'][subject.ARM] = {
            'count': base['count'], 'event_sha256': base['event_sha256'],
            'events': copy.deepcopy(base['events']), 'metrics': copy.deepcopy(base['metrics']),
            'shared_state_path': copy.deepcopy(base['state_path']),
            'shared_state_path_arm': subject.BASE_ARM,
            'readout': {'applied_cut_count': 0, 'readout': {
                'raw_voiced_frames': base['diagnostics']['raw_voiced_frames'],
                'raw_voiced_decoded_silent_frames': base['diagnostics']['raw_voiced_to_silent_frames'],
            }},
        }
        row['comparison'] = subject.compare_case(row)
    report['predictions_manifest_sha256'] = subject.prediction_manifest(report['cases'])
    report['aggregate'] = subject.summarize(report['cases'])
    report['comparisons'] = subject.comparison_summary(report['cases'])
    return report


def test_original_population_and_shared_path_inventory(unchanged_candidate):
    assert subject.require_population(unchanged_candidate['cases']) == {
        'all_cases': 245, 'accuracy_eligible_cases': 227, 'ambiguous_cases': 15, 'silence_cases': 3,
    }
    assert subject.ARMS[:-1] == frozen.ARMS
    assert len(subject.ARMS) == 8
    assert subject.PATH_ARMS == frozen.ARMS[1:]
    assert list(inspect.signature(subject.predict).parameters) == ['hz', 'duration']


@pytest.mark.parametrize('sabotage', ['missing', 'duplicate', 'order', 'eligibility', 'spec', 'arm'])
def test_incomplete_population_cannot_be_summarized(unchanged_candidate, sabotage):
    rows = unchanged_candidate['cases']
    if sabotage == 'missing':
        rows.pop()
    elif sabotage == 'duplicate':
        rows[-1] = rows[0]
    elif sabotage == 'order':
        rows[0], rows[1] = rows[1], rows[0]
    elif sabotage == 'eligibility':
        rows[0]['accuracy_eligible'] = 1
    elif sabotage == 'spec':
        rows[0]['spec']['pitch'] += 1
    else:
        del rows[0]['arms'][subject.ARM]
    with pytest.raises(ValueError, match='population'):
        subject.summarize(rows)


def test_legacy_projection_retains_complete_historical_payload(unchanged_candidate, historical_report):
    projected = subject.legacy_projection(unchanged_candidate)
    assert projected == historical_report
    assert projected is not unchanged_candidate
    projected['cases'][0]['arms']['pitch_runs']['events'].clear()
    assert unchanged_candidate['cases'][0]['arms']['pitch_runs']['events']


def test_partial_report_cannot_get_legacy_projection(unchanged_candidate):
    unchanged_candidate['status'] = 'failed'
    with pytest.raises(ValueError, match='complete synthetic'):
        subject.legacy_projection(unchanged_candidate)


def test_manifest_covers_new_arm_and_preserves_seven_arm_projection(unchanged_candidate, historical_report):
    rows = unchanged_candidate['cases']
    assert subject.prediction_manifest(rows, frozen.ARMS) == historical_report['predictions_manifest_sha256']
    full = subject.prediction_manifest(rows)
    rows[0]['arms'][subject.ARM]['event_sha256'] = 'f' * 64
    assert subject.prediction_manifest(rows) != full
    assert subject.prediction_manifest(rows, frozen.ARMS) == historical_report['predictions_manifest_sha256']
    with pytest.raises(ValueError, match='inventory'):
        subject.prediction_manifest(rows, ('pitch_runs',))


def test_historical_parity_checks_all_scientific_payload(unchanged_candidate):
    result = subject.historical_parity(unchanged_candidate)
    assert result == {
        'baseline_zip_sha256': subject.PREVIOUS_SHA256,
        'compared_prediction_files': 1715, 'compared_input_arrays': 245,
        'compared_state_paths': 1470, 'all_equal': True, 'differences': [],
    }
    unchanged_candidate['cases'][0]['arms']['pitch_runs']['metrics']['onset_f1'] = .123
    assert subject.historical_parity(unchanged_candidate)['all_equal'] is False


def test_historical_parity_rejects_wrong_archive(tmp_path, unchanged_candidate):
    bad = tmp_path / 'wrong.zip'
    bad.write_bytes(b'not the immutable archive')
    with pytest.raises(ValueError, match='original #295'):
        subject.historical_parity(unchanged_candidate, bad)


def test_summary_preserves_old_arms_and_excludes_ambiguity(unchanged_candidate, historical_report):
    aggregate = subject.summarize(unchanged_candidate['cases'])
    assert {arm: aggregate[arm] for arm in frozen.ARMS} == historical_report['aggregate']
    assert aggregate[subject.ARM] == aggregate[subject.BASE_ARM]
    for row in unchanged_candidate['cases']:
        if not row['accuracy_eligible']:
            assert row['arms'][subject.ARM]['metrics'] is None
            assert row['comparison']['baseline_perfect'] is None
            assert row['comparison']['candidate_perfect'] is None
            assert row['comparison']['onset_f1_change'] is None
            assert row['comparison']['onset_offset_f1_change'] is None


def test_fixed_six_controls_and_all_221_prior_successes_are_reported(unchanged_candidate):
    result = subject.comparison_summary(unchanged_candidate['cases'])
    assert result['previous_gaussian_perfect_cases'] == 221
    assert len(result['previous_gaussian_perfect_case_ids']) == 221
    assert result['damaged_previous_success_case_ids'] == []
    assert tuple(row['id'] for row in result['joined_semitone_controls']) == subject.SEMITONE_CONTROL_IDS
    assert all(row['candidate_two_notes_pitch_onset_offset_correct'] is False
               for row in result['joined_semitone_controls'])
    assert result['no_added_cut_cases'] == result['identical_event_cases'] == 245
    assert all(value == {'macro_change': 0., 'improved_cases': 0, 'worse_cases': 0, 'tied_cases': 227}
               for value in result['eligible_metric_changes'].values())


def test_prior_success_damage_is_not_hidden_by_macro(unchanged_candidate):
    rows = unchanged_candidate['cases']
    success = next(row for row in rows if row['comparison']['baseline_perfect'])
    success['arms'][subject.ARM]['metrics']['onset_offset_f1'] = 0.
    success['comparison'] = subject.compare_case(success)
    result = subject.comparison_summary(rows)
    assert result['damaged_previous_success_case_ids'] == [success['id']]
    assert result['eligible_metric_changes']['onset_offset_f1']['worse_cases'] == 1
    assert result['eligible_metric_changes']['onset_f1']['worse_cases'] == 0


def test_no_cut_case_requires_byte_identical_prediction(unchanged_candidate):
    row = unchanged_candidate['cases'][0]
    row['arms'][subject.ARM]['event_sha256'] = 'f' * 64
    with pytest.raises(ValueError, match='no-cut'):
        subject.compare_case(row)


def tiny_frozen_prediction(hz, duration):
    note = subject.dsp.Note(69, 0., duration)
    arms = {arm: [note] for arm in frozen.ARMS}
    paths = {arm: np.full(len(hz), 325, dtype=np.int16) for arm in subject.PATH_ARMS}
    diagnostics = {arm: {} for arm in frozen.ARMS}
    return arms, paths, diagnostics


def test_predict_reuses_six_paths_and_calls_old_predictor_once(monkeypatch):
    calls = []

    def old(hz, duration):
        calls.append((hz, duration))
        return tiny_frozen_prediction(hz, duration)

    monkeypatch.setattr(frozen, 'predict', old)
    hz = np.full(21, 440.)
    arms, paths, _, diagnostics, _ = subject.predict(hz, .2)
    assert len(calls) == 1
    assert set(arms) == set(subject.ARMS)
    assert set(paths) == set(subject.PATH_ARMS)
    assert arms[subject.ARM] == arms[subject.BASE_ARM]
    assert diagnostics['applied_cut_count'] == 0


def test_predict_rejects_shared_path_mutation(monkeypatch):
    monkeypatch.setattr(frozen, 'predict', tiny_frozen_prediction)

    def mutate(path, hz, duration):
        path[0] += 1
        return [], {'applied_cut_count': 1}, {}

    monkeypatch.setattr(subject.readout, 'notes_from_state_path', mutate)
    with pytest.raises(ValueError, match='mutated shared'):
        subject.predict(np.full(21, 440.), .2)


def test_predict_rejects_no_cut_event_change(monkeypatch):
    monkeypatch.setattr(frozen, 'predict', tiny_frozen_prediction)
    monkeypatch.setattr(subject.readout, 'notes_from_state_path',
                        lambda path, hz, duration: ([], {'applied_cut_count': 0}, {}))
    with pytest.raises(ValueError, match='no-cut'):
        subject.predict(np.full(21, 440.), .2)


@pytest.fixture
def mini_run(monkeypatch, tmp_path):
    """Two mocked predictions exercise ordering, without evaluating the grid."""
    from scripts import run_note_boundary_readout as corpus

    plan = (frozen.Case('tiny_001', 'single', pitch=69, frames=12),
            frozen.Case('tiny_002', 'single', pitch=69, frames=12))
    monkeypatch.setattr(corpus, 'SOURCE_PATHS', ())
    monkeypatch.setattr(frozen, 'cases', lambda: plan)
    monkeypatch.setattr(subject, 'require_population', lambda rows: {})
    monkeypatch.setattr(subject, 'summarize', lambda rows: {'cases': len(rows)})
    monkeypatch.setattr(subject, 'comparison_summary', lambda rows: {'cases': len(rows)})
    monkeypatch.setattr(subject, 'historical_parity', lambda report: {'all_equal': True})
    environment = {
        'python': '3.11.18', 'executable': '/test/python', 'platform': 'owned-test-platform',
        'numpy_version': '1.26.4', 'numpy_file': '/test/numpy/__init__.py',
        'runtime': dict(subject.EXPECTED_RUNTIME), 'cpu_features': {'AVX512F': True},
        'cpu_baseline': ['SSE2'], 'cpu_dispatch': ['AVX512F'], 'numpy_disable_cpu_features': None,
    }
    monkeypatch.setattr(subject, 'numerical_environment', lambda: environment)
    work, report_path = tmp_path / 'private', tmp_path / 'public.json'
    predictions = []
    truths = []
    prepared = []
    preparations = []
    original_truth = frozen.truth

    def prepare(plan):
        assert predictions == [] and truths == []
        preparations.append(1)
        for case in plan:
            hz, duration = frozen.observations(case)
            prepared.append((case, hz, duration))
        return prepared, [], {
            'manifest_sha256': subject.NUMERIC_INPUTS_SHA256, 'compared_input_arrays': len(plan),
            'compared_analytic_rows': 0, 'all_equal': True, 'input_differences': [],
            'analytic_difference_paths': [], 'model_calls_before_preflight': 0,
        }

    def fake_predict(hz, duration):
        saved = json.loads(report_path.read_text())
        assert saved['preflight']['all_equal'] is True
        assert saved['preflight']['model_calls_before_preflight'] == 0
        assert hz is prepared[len(predictions)][1]
        assert duration == prepared[len(predictions)][2]
        predictions.append(1)
        note = subject.dsp.Note(69, .3, .42)
        arms = {arm: [note] for arm in subject.ARMS}
        paths = {arm: np.full(len(hz), 325, dtype=np.int16) for arm in subject.PATH_ARMS}
        return arms, paths, {arm: {} for arm in frozen.ARMS}, {'applied_cut_count': 0}, {'parents': []}

    def observed_truth(case):
        saved = json.loads(report_path.read_text())
        assert len(predictions) == 2
        assert saved['all_predictions_saved_before_scoring'] is True
        assert saved['truth_access_started_after_prediction_files'] == 16
        assert sum(len(list((work / case.id).glob('*.json'))) for case in plan) == 18
        assert all('truth' not in row for row in saved['cases'])
        truths.append(case.id)
        return original_truth(case)

    monkeypatch.setattr(subject, 'predict', fake_predict)
    monkeypatch.setattr(subject, 'prepare_inputs', prepare)
    monkeypatch.setattr(frozen, 'truth', observed_truth)
    return {'work': work, 'report': report_path, 'plan': plan, 'predictions': predictions,
            'truths': truths, 'predict': fake_predict, 'truth': observed_truth,
            'prepared': prepared, 'preparations': preparations, 'prepare': prepare,
            'environment': environment}


def test_all_predictions_and_manifest_are_persisted_before_first_truth(mini_run):
    result = subject.run(mini_run['work'], mini_run['report'])
    assert result['status'] == 'complete'
    assert mini_run['truths'] == ['tiny_001', 'tiny_002']
    assert result['predictions_manifest_sha256'] == result['post_evaluation_predictions_manifest_sha256']
    for row in result['cases']:
        assert row['arms'][subject.ARM]['shared_state_path'] == row['arms'][subject.BASE_ARM]['state_path']
        with np.load(mini_run['work'] / row['id'] / 'observations.npz') as observations:
            assert set(observations.files) == {'hz', *subject.PATH_ARMS}
        assert row['comparison']['event_identity_unchanged']


def test_failed_prediction_never_reads_truth_or_emits_aggregate(monkeypatch, mini_run):
    def fail_second(hz, duration):
        if mini_run['predictions']:
            raise ValueError('authored test failure')
        return mini_run['predict'](hz, duration)

    monkeypatch.setattr(subject, 'predict', fail_second)
    result = subject.run(mini_run['work'], mini_run['report'])
    assert result['status'] == 'failed'
    assert result['all_predictions_saved_before_scoring'] is False
    assert result['aggregate'] is result['comparisons'] is None
    assert len(result['cases']) == 1
    assert mini_run['truths'] == []
    assert (mini_run['work'] / 'error.txt').read_text() == 'authored test failure'


def test_missing_prediction_is_detected_before_truth(monkeypatch, mini_run):
    def remove_first(hz, duration):
        if mini_run['predictions']:
            (mini_run['work'] / 'tiny_001' / f'{subject.ARM}.json').unlink()
        return mini_run['predict'](hz, duration)

    monkeypatch.setattr(subject, 'predict', remove_first)
    result = subject.run(mini_run['work'], mini_run['report'])
    assert result['status'] == 'failed'
    assert result['aggregate'] is None
    assert mini_run['truths'] == []


@pytest.mark.parametrize('target', [subject.ARM + '.json', 'readout-private.json'])
def test_post_scoring_rechecks_earlier_case_prediction_and_trace(monkeypatch, mini_run, target):
    def mutate_earlier(case):
        reference = mini_run['truth'](case)
        if case.id == 'tiny_002':
            (mini_run['work'] / 'tiny_001' / target).write_text('[]\n')
        return reference

    monkeypatch.setattr(frozen, 'truth', mutate_earlier)
    result = subject.run(mini_run['work'], mini_run['report'])
    assert result['status'] == 'failed'
    assert result['aggregate'] is result['comparisons'] is None
    assert len(mini_run['truths']) == 2


def test_empty_output_is_kept_and_scored_zero(monkeypatch, mini_run):
    def empty(hz, duration):
        arms, paths, diagnostics, public, trace = mini_run['predict'](hz, duration)
        arms[subject.ARM] = []
        public['applied_cut_count'] = 1
        return arms, paths, diagnostics, public, trace

    monkeypatch.setattr(subject, 'predict', empty)
    result = subject.run(mini_run['work'], mini_run['report'])
    assert result['status'] == 'complete'
    assert len(result['cases']) == 2
    for row in result['cases']:
        assert row['arms'][subject.ARM]['count'] == 0
        assert row['arms'][subject.ARM]['metrics'] == {'onset_f1': 0., 'onset_offset_f1': 0.}


def test_failed_historical_parity_withholds_aggregate(monkeypatch, mini_run):
    monkeypatch.setattr(subject, 'historical_parity', lambda report: {'all_equal': False})
    result = subject.run(mini_run['work'], mini_run['report'])
    assert result['status'] == 'failed'
    assert result['historical_parity'] == {'all_equal': False}
    assert result['aggregate'] is result['comparisons'] is None


def test_owned_input_values_are_not_case_metadata():
    case = frozen.Case('tiny_owned', 'single', pitch=69, frames=12)
    hz, duration = frozen.observations(case)
    assert hz.ndim == 1 and duration > 0
    assert set(asdict(case)) == {'id', 'kind', 'pitch', 'frames', 'context', 'gap', 'interval'}
    assert list(inspect.signature(subject.predict).parameters) == ['hz', 'duration']


def test_numeric_manifest_contains_only_original_input_identities_and_analytic_table(historical_report):
    manifest = subject.read_numeric_manifest()
    assert set(manifest) == {'schema', 'baseline_zip_sha256', 'cases', 'emission_analysis'}
    assert len(manifest['cases']) == 245
    assert manifest['cases'] == [
        {key: row[key] for key in ('id', 'duration_seconds', 'observation')}
        for row in historical_report['cases']]
    assert manifest['emission_analysis'] == historical_report['emission_analysis']
    assert all(set(row) == {'id', 'duration_seconds', 'observation'} for row in manifest['cases'])


@pytest.mark.parametrize('location', ['top', 'case', 'analytic'])
def test_numeric_manifest_rejects_truth_or_event_fields_even_with_an_updated_hash(monkeypatch, tmp_path, location):
    manifest = subject.read_numeric_manifest()
    if location == 'top':
        manifest['truth'] = []
    elif location == 'case':
        manifest['cases'][0]['truth'] = []
    else:
        manifest['emission_analysis'][0]['events'] = []
    path = tmp_path / 'numeric.json'
    subject.dsp.save(path, manifest)
    monkeypatch.setattr(subject, 'ROOT', tmp_path)
    monkeypatch.setattr(subject, 'NUMERIC_INPUTS', path.name)
    monkeypatch.setattr(subject, 'NUMERIC_INPUTS_SHA256', subject.dsp.digest(path))
    with pytest.raises(ValueError, match='input-only'):
        subject.read_numeric_manifest()


def test_numeric_manifest_requires_original_bytes(monkeypatch, tmp_path):
    path = tmp_path / 'numeric.json'
    path.write_text('{}\n')
    monkeypatch.setattr(subject, 'ROOT', tmp_path)
    monkeypatch.setattr(subject, 'NUMERIC_INPUTS', path.name)
    with pytest.raises(ValueError, match='immutable numeric'):
        subject.read_numeric_manifest()


@pytest.fixture
def tiny_preflight():
    plan = (frozen.Case('owned_001', 'single', pitch=69, frames=8),
            frozen.Case('owned_002', 'single', pitch=57, frames=12))
    prepared = [(case, *frozen.observations(case)) for case in plan]
    analytic = [{'value': .25}, {'value': .5}]
    manifest = {
        'cases': [{'id': case.id, 'duration_seconds': duration, 'observation': frozen.identity(hz)}
                  for case, hz, duration in prepared], 'emission_analysis': copy.deepcopy(analytic),
    }
    return plan, prepared, analytic, manifest


def test_numeric_preflight_is_exact_for_arrays_and_analytic_scalars(tiny_preflight):
    _, prepared, analytic, manifest = tiny_preflight
    result = subject.compare_numeric_inputs(prepared, analytic, manifest)
    assert result == {
        'manifest_sha256': subject.NUMERIC_INPUTS_SHA256, 'compared_input_arrays': 2,
        'compared_analytic_rows': 2, 'all_equal': True, 'input_differences': [],
        'analytic_difference_paths': [], 'model_calls_before_preflight': 0,
    }
    hz = prepared[0][1]
    positive = int(np.flatnonzero(hz > 0)[0])
    hz[positive] = np.nextafter(hz[positive], np.inf)
    analytic[1]['value'] = float(np.nextafter(analytic[1]['value'], np.inf))
    failed = subject.compare_numeric_inputs(prepared, analytic, manifest)
    assert failed['all_equal'] is False
    assert failed['input_differences'] == ['owned_001']
    assert failed['analytic_difference_paths'] == ['/emission_analysis/1/value']
    assert failed['model_calls_before_preflight'] == 0


def test_numeric_preflight_rejects_reordered_population_and_numeric_type_drift(tiny_preflight):
    _, prepared, analytic, manifest = tiny_preflight
    with pytest.raises(ValueError, match='ordered input'):
        subject.compare_numeric_inputs(prepared[::-1], analytic, manifest)
    assert subject.numeric_difference_paths({'n': 1.}, {'n': 1}, '/analytic') == ['/analytic/n']
    assert subject.numeric_difference_paths([1.], [1., 2.], '/analytic') == ['/analytic']


def test_prepare_inputs_generates_once_and_never_calls_predictor_or_truth(monkeypatch, tiny_preflight):
    plan, prepared, analytic, manifest = tiny_preflight
    generated = []

    def observation(case):
        generated.append(case.id)
        row = next(item for item in prepared if item[0].id == case.id)
        return row[1], row[2]

    def forbidden(*args):
        raise AssertionError('numeric preflight cannot access predictions or truth')

    monkeypatch.setattr(subject, 'read_numeric_manifest', lambda: manifest)
    monkeypatch.setattr(frozen, 'observations', observation)
    monkeypatch.setattr(frozen, 'emission_analysis', lambda: analytic)
    monkeypatch.setattr(frozen, 'predict', forbidden)
    monkeypatch.setattr(frozen, 'truth', forbidden)
    actual, measured, receipt = subject.prepare_inputs(plan)
    assert generated == [case.id for case in plan]
    assert all(a[1] is b[1] for a, b in zip(actual, prepared, strict=True))
    assert measured is analytic
    assert receipt['all_equal'] is True


def test_failed_numeric_preflight_stops_before_every_prediction_and_truth(monkeypatch, mini_run):
    def mismatch(plan):
        prepared, analytic, receipt = mini_run['prepare'](plan)
        receipt.update(all_equal=False, input_differences=['tiny_001'])
        return prepared, analytic, receipt

    monkeypatch.setattr(subject, 'prepare_inputs', mismatch)
    result = subject.run(mini_run['work'], mini_run['report'])
    assert result['status'] == 'failed'
    assert result['cases'] == []
    assert result['aggregate'] is result['comparisons'] is None
    assert result['all_predictions_saved_before_scoring'] is False
    assert result['preflight']['input_differences'] == ['tiny_001']
    assert result['numerical_environment'] == mini_run['environment']
    assert mini_run['predictions'] == mini_run['truths'] == []


def test_wrong_actual_runtime_is_recorded_and_stops_before_input_preflight(monkeypatch, mini_run):
    environment = copy.deepcopy(mini_run['environment'])
    environment['numpy_version'] = '2.3.5'
    monkeypatch.setattr(subject, 'numerical_environment', lambda: environment)
    result = subject.run(mini_run['work'], mini_run['report'])
    assert result['status'] == 'failed'
    assert result['preflight'] is result['aggregate'] is None
    assert result['cases'] == []
    assert result['numerical_environment']['numpy_version'] == '2.3.5'
    assert mini_run['preparations'] == mini_run['predictions'] == mini_run['truths'] == []


@pytest.mark.parametrize('field,value', [
    ('python', '3.12.14'), ('numpy_version', '2.3.5'), ('runtime', {}),
])
def test_actual_runtime_requires_pinned_python_numpy_and_dependencies(field, value):
    valid = {'python': '3.11.18', 'numpy_version': '1.26.4', 'runtime': dict(subject.EXPECTED_RUNTIME)}
    subject.require_numerical_runtime(valid)
    valid[field] = value
    with pytest.raises(ValueError, match='actual pinned'):
        subject.require_numerical_runtime(valid)


def test_numerical_environment_records_dispatch_without_enabling_cpu_features(monkeypatch):
    before = dict(np.core._multiarray_umath.__cpu_features__)
    monkeypatch.setenv('NPY_DISABLE_CPU_FEATURES', 'owned-observation-only-test')
    environment = subject.numerical_environment()
    assert set(environment) == {
        'python', 'executable', 'platform', 'numpy_version', 'numpy_file', 'runtime',
        'cpu_features', 'cpu_baseline', 'cpu_dispatch', 'numpy_disable_cpu_features',
    }
    assert environment['numpy_version'] == np.__version__
    assert environment['numpy_file'] == np.__file__
    assert set(environment['runtime']) == set(subject.EXPECTED_RUNTIME)
    assert environment['cpu_features'] == before
    assert np.core._multiarray_umath.__cpu_features__ == before
    assert environment['numpy_disable_cpu_features'] == 'owned-observation-only-test'


def test_legacy_projection_strips_recovery_environment_and_preflight(unchanged_candidate, historical_report):
    unchanged_candidate['numerical_environment'] = {'owned_test': True}
    unchanged_candidate['preflight'] = {'owned_test': True}
    assert subject.legacy_projection(unchanged_candidate) == historical_report

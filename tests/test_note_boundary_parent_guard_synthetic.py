"""Small owned contracts and archived projections; never run the full grid."""
from __future__ import annotations

import copy
import inspect
import itertools
import json
import math
import zipfile
from dataclasses import asdict, replace

import numpy as np
import pytest

from scripts import note_boundary_parent_guard_synthetic as subject
from scripts import note_state_hmm as legacy


@pytest.fixture(scope='module')
def historical_report():
    with zipfile.ZipFile(subject.ROOT / subject.PREVIOUS) as archive:
        return json.loads(archive.read('synthetic.json'))


@pytest.fixture
def projected_report(historical_report):
    """Archived old results plus placeholders, not newly inferred stress results."""
    report = copy.deepcopy(historical_report)
    report.update(schema='note-boundary-parent-guard-synthetic-v1', planned_cases=461,
                  planned_arms=list(subject.ARMS),
                  preflight={'legacy': copy.deepcopy(historical_report['preflight'])})
    for row in report['cases']:
        row['cohort'] = 'legacy'
        row['arms'][subject.ARM] = {
            **copy.deepcopy(row['arms'][subject.BASE_ARM]),
            'readout': {'accepted_cut_count': 0},
        }
        row['guard_comparisons'] = {arm: subject.compare_case(row, arm)
                                    for arm in (subject.BASE_ARM, subject.SPLIT_ARM)}
    for case in subject.stress_cases():
        row = {'id': case.id, 'spec': asdict(case), 'cohort': case.kind,
               'accuracy_eligible': True, 'arms': {arm: {
                   'count': 0, 'event_sha256': 'owned-contract-placeholder',
                   'metrics': {'onset_f1': 0., 'onset_offset_f1': 0.},
               } for arm in subject.ARMS}}
        row['arms'][subject.ARM]['readout'] = {'accepted_cut_count': 0}
        row['guard_comparisons'] = {arm: subject.compare_case(row, arm)
                                    for arm in (subject.BASE_ARM, subject.SPLIT_ARM)}
        report['cases'].append(row)
    return report


def test_fixed_population_keeps_old245_and_two_separate108_grids(projected_report):
    plan = subject.cases()
    assert len(plan) == 461 and len(subject.ARMS) == 9
    assert len(plan) * len(subject.ARMS) == 4149
    assert plan[:245] == subject.frozen.cases()
    assert len({case.id for case in plan}) == 461
    assert subject.require_population(projected_report['cases']) == {
        'legacy': {'all_cases': 245, 'accuracy_eligible_cases': 227, 'ambiguous_cases': 15, 'silence_cases': 3},
        'single_expression': {'all_cases': 108, 'accuracy_eligible_cases': 108},
        'adjacent_semitone': {'all_cases': 108, 'accuracy_eligible_cases': 108},
    }
    expected = list(itertools.product((45, 57, 69), (-.4, 0., .4), (.3, .6), (3, 6), (24, 48, 96)))
    for kind in subject.COHORTS[1:]:
        selected = [case for case in plan if isinstance(case, subject.StressCase) and case.kind == kind]
        assert [(case.pitch, case.detuning, case.amplitude, case.frequency_hz, case.frames)
                for case in selected] == expected
        assert [case.id for case in selected] == [f'stress_{kind}_{index:03d}' for index in range(1, 109)]


@pytest.mark.parametrize('damage', ['missing_case', 'reorder', 'missing_arm', 'wrong_cohort', 'eligible', 'spec'])
def test_population_rejects_wrong_denominators_and_specifications(projected_report, damage):
    rows = projected_report['cases']
    if damage == 'missing_case':
        rows.pop()
    elif damage == 'reorder':
        rows[245], rows[246] = rows[246], rows[245]
    elif damage == 'missing_arm':
        rows[246]['arms'].pop(subject.ARM)
    elif damage == 'wrong_cohort':
        rows[246]['cohort'] = 'legacy'
    elif damage == 'eligible':
        rows[246]['accuracy_eligible'] = 1
    else:
        rows[246]['spec']['amplitude'] = .9
    with pytest.raises(ValueError, match='population'):
        subject.require_population(rows)


@pytest.mark.parametrize('frames', [24, 48, 96])
@pytest.mark.parametrize('kind', ['single_expression', 'adjacent_semitone'])
def test_new_frame_clock_silence_terminal_and_duration_are_explicit(frames, kind):
    case = subject.StressCase('owned_clock', kind, 57, .4, .6, 3, frames)
    hz, duration = subject.observations(case)
    assert hz.dtype == np.float64 and hz.shape == (frames + 21,)
    assert duration == (frames + 20) * .01
    assert np.flatnonzero(hz > 0).tolist() == list(range(10, 10 + frames))
    assert np.count_nonzero(hz == 0) == 21
    assert hz[-1] == 0 and (len(hz) - 1) * .01 == duration
    expected_midi = [57.4 + .6 * math.sin(2 * math.pi * 3 * frame * .01)
                     + (1. if kind == 'adjacent_semitone' and frame >= frames // 2 else 0.)
                     for frame in range(frames)]
    expected_hz = [440 * 2 ** ((midi - 69) / 12) for midi in expected_midi]
    np.testing.assert_allclose(hz[10:10 + frames], expected_hz, rtol=2e-15, atol=0)


def test_adjacent_phase_is_continuous_and_observations_do_not_access_truth(monkeypatch):
    case = subject.StressCase('owned_phase', 'single_expression', 69, -.4, .3, 6, 24)
    monkeypatch.setattr(subject, 'truth', lambda _case: pytest.fail('input generation cannot read truth'))
    single, duration = subject.observations(case)
    adjacent, other_duration = subject.observations(replace(case, kind='adjacent_semitone'))
    assert duration == other_duration
    np.testing.assert_array_equal(single[:22], adjacent[:22])
    np.testing.assert_allclose(adjacent[22:34], single[22:34] * 2 ** (1 / 12), rtol=2e-15)
    np.testing.assert_array_equal(single[34:], adjacent[34:])
    assert list(inspect.signature(subject.predict).parameters) == ['hz', 'duration']


def test_authored_centers_are_not_rounded_and_truth_is_separate(monkeypatch):
    case = subject.StressCase('owned_truth', 'adjacent_semitone', 57, .4, .6, 6, 24)
    monkeypatch.setattr(subject, 'observations', lambda _case: pytest.fail('truth cannot inspect generated input'))
    notes = subject.truth(case)
    assert [note.pitch for note in notes] == [57.4, 58.4]
    assert [(note.onset, note.offset) for note in notes] == [(.1, .22), (.22, .34)]
    assert subject.truth(replace(case, kind='single_expression')) == [subject.dsp.Note(57.4, .1, .34)]
    assert subject.alternative_truth(case) == []


def test_frozen_observation_and_truth_delegation_are_unchanged():
    case = subject.frozen.Case('owned_old', 'single', pitch=69, frames=8, context='full')
    actual, duration = subject.observations(case)
    expected, old_duration = subject.frozen.observations(case)
    np.testing.assert_array_equal(actual, expected)
    assert duration == old_duration and actual[-1] > 0
    assert subject.truth(case) == subject.frozen.truth(case)
    assert subject.alternative_truth(case) == subject.frozen.alternative_truth(case)


def test_legacy_projection_exactly_recreates_all_old_scientific_payload(projected_report, historical_report):
    assert subject.legacy_projection(projected_report) == historical_report
    result = subject.historical_parity(projected_report)
    assert result == {'baseline_zip_sha256': subject.PREVIOUS_SHA256,
        'compared_prediction_files': 1960, 'compared_input_arrays': 245,
        'compared_state_paths': 1470, 'all_equal': True, 'differences': []}


@pytest.mark.parametrize('field', ['truth', 'observation', 'diagnostics', 'events', 'metrics', 'state_path', 'readout'])
def test_historical_parity_checks_full_old_arrays_notes_scores_and_diagnostics(projected_report, field):
    row = projected_report['cases'][0]
    if field == 'truth':
        row['truth'][0]['pitch'] += 1
    elif field == 'observation':
        row[field]['sha256'] = '0' * 64
    else:
        arm = row['arms'][subject.SPLIT_ARM if field == 'readout' else subject.BASE_ARM]
        if field == 'events':
            arm[field][0]['pitch'] += 1
        elif field == 'metrics':
            arm[field]['onset_f1'] = .123
        elif field == 'state_path':
            arm[field]['sha256'] = '0' * 64
        else:
            arm[field]['contract_sabotage'] = True
    assert subject.historical_parity(projected_report)['all_equal'] is False


def test_partial_report_cannot_project_or_claim_legacy_success(projected_report):
    projected_report['status'] = 'failed'
    with pytest.raises(ValueError, match='complete'):
        subject.legacy_projection(projected_report)


def test_historical_archive_requires_original_bytes(tmp_path, projected_report):
    path = tmp_path / 'wrong.zip'
    path.write_bytes(b'wrong')
    with pytest.raises(ValueError, match='original #297'):
        subject.historical_parity(projected_report, path)


def test_stratified_comparisons_keep_six_221_227_15_3_and_new108_separate(projected_report):
    result = subject.comparison_summary(projected_report['cases'])
    assert set(result) == set(subject.COHORTS)
    old = result['legacy']
    assert old['all_cases'] == 245 and old['accuracy_eligible_cases'] == 227
    assert old['ambiguous_cases'] == 15 and old['silence_cases'] == 3
    assert old['previous_gaussian_perfect_cases'] == 221
    assert old['damaged_previous_success_case_ids'] == []
    assert tuple(row['id'] for row in old['joined_semitone_controls']) == subject.previous.SEMITONE_CONTROL_IDS
    for name in subject.COHORTS[1:]:
        assert result[name]['all_cases'] == result[name]['accuracy_eligible_cases'] == 108
    row = next(row for row in projected_report['cases'][:245]
               if row['guard_comparisons'][subject.BASE_ARM]['baseline_perfect'])
    row['arms'][subject.ARM]['metrics']['onset_offset_f1'] = 0.
    row['guard_comparisons'][subject.BASE_ARM] = subject.compare_case(row, subject.BASE_ARM)
    assert subject.comparison_summary(projected_report['cases'])['legacy']['damaged_previous_success_case_ids'] == [row['id']]


def test_timing_only_pitch_diagnostics_do_not_change_accuracy_or_hide_unmatched_notes():
    reference = [subject.dsp.Note(69.4, .1, .34), subject.dsp.Note(71.4, .5, .74)]
    predicted = [subject.dsp.Note(70, .1, .34)]
    result = subject.note_evaluation(predicted, reference)
    assert result['reference_notes'] == 2 and result['predicted_notes'] == 1
    assert result['note_count_change'] == -1
    assert result['onset'] == result['onset_offset'] == {'matched_notes': 0, 'precision': 0., 'recall': 0.}
    assert result['timing_only_matched_pairs'] == 1
    assert result['timing_only_unmatched_reference_notes'] == 1
    assert result['timing_only_unmatched_prediction_notes'] == 0
    assert result['timing_matched_pitch_correct_pairs'] == 0
    assert result['timing_matched_pitch_wrong_pairs'] == 1
    assert result['timing_matched_absolute_pitch_cents']['median'] == pytest.approx(60.)
    assert subject.frozen.score(predicted, reference) == {'onset_f1': 0., 'onset_offset_f1': 0.}


def test_empty_output_retains_denominators_and_zero_scores():
    result = subject.note_evaluation([], [subject.dsp.Note(69., .1, .34)])
    assert result['onset_offset'] == {'matched_notes': 0, 'precision': 0., 'recall': 0.}
    assert result['timing_only_unmatched_reference_notes'] == 1
    assert result['timing_only_unmatched_prediction_notes'] == 0
    assert result['timing_matched_absolute_pitch_cents'] == {
        'count': 0, 'minimum': None, 'median': None, 'maximum': None}


def tiny_previous_prediction(hz, duration):
    path = np.full(len(hz), 325, dtype=np.int16)
    notes, _ = legacy.notes_from_state_path(path, hz, duration)
    return ({arm: list(notes) for arm in subject.previous.ARMS},
            {arm: path.copy() for arm in subject.PATH_ARMS},
            {arm: {} for arm in subject.frozen.ARMS},
            {'applied_cut_count': 0}, {'parents': []})


def test_predict_calls_previous_once_shares_path_and_preserves_original_note_instances(monkeypatch):
    calls = []
    supplied = {}

    def old(hz, duration):
        calls.append((hz, duration))
        supplied['value'] = tiny_previous_prediction(hz, duration)
        return supplied['value']

    monkeypatch.setattr(subject.previous, 'predict', old)
    hz = np.full(21, 440.)
    arms, paths, _diagnostics, _split, _split_trace, public, _trace = subject.predict(hz, .2)
    assert len(calls) == 1 and set(arms) == set(subject.ARMS)
    assert set(paths) == set(subject.PATH_ARMS)
    assert arms[subject.ARM][0] is supplied['value'][0][subject.BASE_ARM][0]
    assert public['accepted_cut_count'] == 0


@pytest.mark.parametrize('mutation', ['hz', 'path', 'no_cut_event', 'union'])
def test_predict_rejects_mutation_or_guard_contract_violation(monkeypatch, mutation):
    monkeypatch.setattr(subject.previous, 'predict', tiny_previous_prediction)

    def broken(path, hz, duration, *, original_notes):
        if mutation == 'hz':
            hz[0] = 0.
        elif mutation == 'path':
            path[0] += 1
        if mutation in ('no_cut_event', 'union'):
            return [], {'accepted_cut_count': int(mutation == 'union')}, {}
        return original_notes, {'accepted_cut_count': 0}, {}

    monkeypatch.setattr(subject.guard, 'notes_from_state_path', broken)
    with pytest.raises(ValueError, match='mutated|identity|union'):
        subject.predict(np.full(21, 440.), .2)


def test_new_manifest_is_exact_input_only_and_separate_from_original245():
    manifest = subject.read_numeric_manifest()
    assert set(manifest) == {'schema', 'baseline_zip_sha256', 'legacy_numeric_manifest_sha256',
                             'timing_semantics', 'generation_environment', 'cases'}
    assert len(manifest['cases']) == 216
    assert manifest['legacy_numeric_manifest_sha256'] == subject.previous.NUMERIC_INPUTS_SHA256
    assert manifest['generation_environment']['numpy_version'] == '1.26.4'
    assert manifest['timing_semantics'] == subject.TIMING_SEMANTICS
    assert all(set(row) == {'id', 'duration_seconds', 'observation'} for row in manifest['cases'])


@pytest.mark.parametrize('location', ['top', 'case', 'observation'])
def test_manifest_rejects_truth_and_events_even_with_updated_digest(monkeypatch, tmp_path, location):
    manifest = subject.read_numeric_manifest()
    target = manifest if location == 'top' else manifest['cases'][0]
    if location == 'observation':
        target = target['observation']
    target['truth'] = []
    path = tmp_path / 'bad.json'
    subject.dsp.save(path, manifest)
    monkeypatch.setattr(subject, 'NUMERIC_INPUTS', str(path))
    monkeypatch.setattr(subject, 'NUMERIC_INPUTS_SHA256', subject.dsp.digest(path))
    with pytest.raises(ValueError, match='input-only'):
        subject.read_numeric_manifest()


def test_manifest_byte_identity_is_mandatory(monkeypatch, tmp_path):
    path = tmp_path / 'modified.json'
    path.write_text((subject.ROOT / subject.NUMERIC_INPUTS).read_text() + '\n')
    monkeypatch.setattr(subject, 'NUMERIC_INPUTS', str(path))
    with pytest.raises(ValueError, match='immutable'):
        subject.read_numeric_manifest()


def test_stress_preflight_is_exact_and_type_sensitive():
    case = subject.stress_cases()[0]
    hz, duration = subject.observations(case)
    manifest = {'cases': [subject.input_identity(case, hz, duration)]}
    assert subject.compare_stress_inputs([(case, hz, duration)], manifest)['all_equal']
    changed = hz.copy()
    changed[10] = np.nextafter(changed[10], np.inf)
    failed = subject.compare_stress_inputs([(case, changed, duration)], manifest)
    assert failed['input_differences'] == [case.id]
    assert failed['all_equal'] is False and failed['model_calls_before_preflight'] == 0
    manifest['cases'][0]['duration_seconds'] = 0
    assert not subject.compare_stress_inputs([(case, hz, duration)], manifest)['all_equal']
    manifest['cases'][0]['id'] = 'wrong'
    with pytest.raises(ValueError, match='ordered'):
        subject.compare_stress_inputs([(case, hz, duration)], manifest)


def test_prepare_input_generates_each_array_once_without_prediction_or_truth(monkeypatch):
    old = subject.frozen.Case('owned_old', 'single', pitch=69, frames=8)
    new = subject.stress_cases()[0]
    old_hz, old_duration = subject.frozen.observations(old)
    new_hz, new_duration = subject.observations(new)
    plan = (old, new)
    calls = []

    def prepare_legacy(selected):
        assert selected == (old,)
        calls.append('legacy')
        return [(old, old_hz, old_duration)], [], {'all_equal': True}

    def prepare_new(case):
        assert case is new
        calls.append('stress')
        return new_hz, new_duration

    monkeypatch.setattr(subject, 'cases', lambda: plan)
    monkeypatch.setattr(subject.previous, 'prepare_inputs', prepare_legacy)
    monkeypatch.setattr(subject, 'observations', prepare_new)
    monkeypatch.setattr(subject, 'read_numeric_manifest', lambda: {
        'cases': [subject.input_identity(new, new_hz, new_duration)]})
    monkeypatch.setattr(subject, 'predict', lambda *_: pytest.fail('no model call before preflight'))
    monkeypatch.setattr(subject, 'truth', lambda *_: pytest.fail('no truth access before prediction barrier'))
    prepared, analytic, preflight = subject.prepare_inputs(plan)
    assert calls == ['legacy', 'stress'] and analytic == []
    assert prepared[0][1] is old_hz and prepared[1][1] is new_hz
    assert preflight['all_equal'] and preflight['compared_input_arrays'] == 2
    assert preflight['model_calls_before_preflight'] == 0


def test_manifest_authoring_never_decodes_or_reads_truth(monkeypatch):
    selected = subject.stress_cases()[:2]
    monkeypatch.setattr(subject, 'stress_cases', lambda: selected)
    monkeypatch.setattr(subject.previous, 'prepare_inputs', lambda _plan: ([], [], {'all_equal': True}))
    monkeypatch.setattr(subject, 'numerical_environment', lambda: {'numpy_version': '1.26.4'})
    monkeypatch.setattr(subject, 'predict', lambda *_: pytest.fail('manifest cannot predict'))
    monkeypatch.setattr(subject.previous, 'predict', lambda *_: pytest.fail('manifest cannot infer old arms'))
    monkeypatch.setattr(subject, 'truth', lambda *_: pytest.fail('manifest cannot access truth'))
    manifest = subject.make_numeric_manifest()
    assert [row['id'] for row in manifest['cases']] == [case.id for case in selected]


@pytest.fixture
def mini_run(monkeypatch, tmp_path):
    """Three mocked cases exercise both cohorts and ordering, never the full grid."""
    plan = (subject.frozen.Case('tiny_001', 'single', pitch=69, frames=12),
            subject.frozen.Case('tiny_002', 'single', pitch=69, frames=12),
            subject.StressCase('tiny_stress', 'single_expression', 69, 0., .3, 3, 24))
    monkeypatch.setattr(subject, 'cases', lambda: plan)
    monkeypatch.setattr(subject, 'source_hashes', lambda: {})
    monkeypatch.setattr(subject, 'require_population', lambda _rows: {})
    monkeypatch.setattr(subject, 'summarize', lambda rows: {'mock_cases': len(rows)})
    monkeypatch.setattr(subject, 'comparison_summary', lambda rows: {'mock_cases': len(rows)})
    monkeypatch.setattr(subject, 'historical_parity', lambda _report: {'all_equal': True})
    environment = {
        'python': '3.11.18', 'numpy_version': '1.26.4',
        'runtime': dict(subject.previous.EXPECTED_RUNTIME),
    }
    monkeypatch.setattr(subject, 'numerical_environment', lambda: environment)
    work, path = tmp_path / 'private', tmp_path / 'public.json'
    predictions, truths, prepared = [], [], []
    original_truth = subject.truth

    def prepare(selected):
        assert selected == plan and not predictions and not truths
        prepared.extend((case, *subject.observations(case)) for case in plan)
        return prepared, [], {'all_equal': True, 'model_calls_before_preflight': 0}

    def fake_predict(hz, duration):
        public_report = json.loads(path.read_text())
        assert public_report['preflight']['all_equal']
        assert public_report['preflight']['model_calls_before_preflight'] == 0
        assert hz is prepared[len(predictions)][1]
        assert duration == prepared[len(predictions)][2]
        predictions.append(1)
        notes = [subject.dsp.Note(69, .1, .34)]
        return ({arm: list(notes) for arm in subject.ARMS},
                {arm: np.full(len(hz), 325, dtype=np.int16) for arm in subject.PATH_ARMS},
                {arm: {} for arm in subject.frozen.ARMS},
                {'applied_cut_count': 0}, {'parents': []},
                {'accepted_cut_count': 0}, {'parents': []})

    def checked_truth(case):
        public_report = json.loads(path.read_text())
        assert len(predictions) == 3
        assert public_report['all_predictions_saved_before_scoring'] is True
        assert public_report['truth_access_started_after_prediction_files'] == 27
        assert sum(len(list((work / item.id).glob('*.json'))) for item in plan) == 33
        assert all('truth' not in row for row in public_report['cases'])
        truths.append(case.id)
        return original_truth(case)

    monkeypatch.setattr(subject, 'prepare_inputs', prepare)
    monkeypatch.setattr(subject, 'predict', fake_predict)
    monkeypatch.setattr(subject, 'truth', checked_truth)
    return {'work': work, 'report': path, 'plan': plan, 'predictions': predictions,
            'truths': truths, 'predict': fake_predict, 'truth': checked_truth,
            'prepare': prepare, 'environment': environment}


def test_all_predictions_and_private_files_are_frozen_before_first_truth(mini_run):
    result = subject.run(mini_run['work'], mini_run['report'])
    assert result['status'] == 'complete'
    assert mini_run['truths'] == ['tiny_001', 'tiny_002', 'tiny_stress']
    assert result['predictions_manifest_sha256'] == result['post_evaluation_predictions_manifest_sha256']
    assert all(row['arms'][subject.ARM]['shared_state_path'] == row['arms'][subject.BASE_ARM]['state_path']
               for row in result['cases'])


def test_failed_prediction_retains_partial_rows_but_never_reads_truth(monkeypatch, mini_run):
    def fail(hz, duration):
        if mini_run['predictions']:
            raise ValueError('owned prediction failure')
        return mini_run['predict'](hz, duration)

    monkeypatch.setattr(subject, 'predict', fail)
    result = subject.run(mini_run['work'], mini_run['report'])
    assert result['status'] == 'failed' and len(result['cases']) == 1
    assert result['aggregate'] is result['comparisons'] is None
    assert result['all_predictions_saved_before_scoring'] is False
    assert mini_run['truths'] == []


@pytest.mark.parametrize('target', [subject.ARM + '.json', 'guard-private.json', 'readout-private.json', 'observations.npz'])
def test_saved_prediction_or_trace_mutation_is_detected_before_truth(monkeypatch, mini_run, target):
    def remove_first(hz, duration):
        if len(mini_run['predictions']) == 1:
            (mini_run['work'] / 'tiny_001' / target).unlink()
        return mini_run['predict'](hz, duration)

    monkeypatch.setattr(subject, 'predict', remove_first)
    result = subject.run(mini_run['work'], mini_run['report'])
    assert result['status'] == 'failed' and mini_run['truths'] == []
    assert result['aggregate'] is result['comparisons'] is None


@pytest.mark.parametrize('target', [subject.ARM + '.json', 'guard-private.json', 'readout-private.json'])
def test_post_scoring_rechecks_already_scored_files(monkeypatch, mini_run, target):
    def mutate(case):
        reference = mini_run['truth'](case)
        if case.id == 'tiny_stress':
            (mini_run['work'] / 'tiny_001' / target).write_text('[]\n')
        return reference

    monkeypatch.setattr(subject, 'truth', mutate)
    result = subject.run(mini_run['work'], mini_run['report'])
    assert result['status'] == 'failed' and len(mini_run['truths']) == 3
    assert result['aggregate'] is result['comparisons'] is None


@pytest.mark.parametrize('array', ['hz', subject.BASE_ARM])
def test_post_scoring_rechecks_input_and_path_bytes(monkeypatch, mini_run, array):
    def mutate(case):
        reference = mini_run['truth'](case)
        if case.id == 'tiny_stress':
            path = mini_run['work'] / 'tiny_001' / 'observations.npz'
            with np.load(path, allow_pickle=False) as archive:
                values = {name: archive[name] for name in archive.files}
            values[array][0] += 1
            np.savez_compressed(path, **values)
        return reference

    monkeypatch.setattr(subject, 'truth', mutate)
    result = subject.run(mini_run['work'], mini_run['report'])
    assert result['status'] == 'failed'
    assert result['aggregate'] is result['comparisons'] is None


def test_preflight_failure_publishes_diagnostics_and_stops_every_model_call(monkeypatch, mini_run):
    def fail(plan):
        prepared, analytic, preflight = mini_run['prepare'](plan)
        preflight['all_equal'] = False
        return prepared, analytic, preflight

    monkeypatch.setattr(subject, 'prepare_inputs', fail)
    result = subject.run(mini_run['work'], mini_run['report'])
    assert result['status'] == 'failed' and result['preflight']['all_equal'] is False
    assert mini_run['predictions'] == mini_run['truths'] == []
    assert result['aggregate'] is result['comparisons'] is None


def test_wrong_runtime_is_recorded_before_input_preflight(monkeypatch, mini_run):
    environment = {**mini_run['environment'], 'numpy_version': '2.4.6'}
    monkeypatch.setattr(subject, 'numerical_environment', lambda: environment)
    monkeypatch.setattr(subject, 'prepare_inputs', lambda _plan: pytest.fail('wrong runtime must stop'))
    result = subject.run(mini_run['work'], mini_run['report'])
    assert result['status'] == 'failed' and result['preflight'] is None
    assert result['numerical_environment'] == environment
    assert mini_run['predictions'] == mini_run['truths'] == []


def test_historical_parity_failure_withholds_aggregates(monkeypatch, mini_run):
    monkeypatch.setattr(subject, 'historical_parity', lambda _report: {'all_equal': False, 'differences': ['owned']})
    result = subject.run(mini_run['work'], mini_run['report'])
    assert result['status'] == 'failed' and result['historical_parity']['all_equal'] is False
    assert result['aggregate'] is result['comparisons'] is None

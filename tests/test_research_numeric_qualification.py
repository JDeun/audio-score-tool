import copy
import json
import zipfile
from types import SimpleNamespace

import pytest

from scripts import research_numeric_pytest_plugin as plugin
from scripts import research_numeric_qualification as qualification


def test_input_only_qualification_records_actual_environment_and_never_calls_models(monkeypatch):
    from scripts import audit_note_boundary_parent_guard as independent
    from scripts import note_boundary_parent_guard_synthetic as stress
    from scripts import note_boundary_readout_synthetic as prior
    from scripts import note_state_synthetic as legacy

    def forbidden(*args, **kwargs):
        raise AssertionError('input-only qualification accessed prediction or truth')

    for module in (stress, prior, legacy):
        for name in ('predict', 'truth', 'alternative_truth', 'score'):
            if hasattr(module, name):
                monkeypatch.setattr(module, name, forbidden)
    monkeypatch.setattr(legacy, 'infer_factors', forbidden)
    monkeypatch.setattr(legacy.legacy, 'infer_note_states', forbidden)
    monkeypatch.setattr(stress.guard, 'notes_from_state_path', forbidden)
    for name in ('stress_truth', 'parse_reference', 'direct_score', 'note_evaluation'):
        monkeypatch.setattr(independent, name, forbidden)
    # Source bytes may be hashed, but historical ZIP truth/score payloads must
    # never be opened by this input-only diagnostic.
    monkeypatch.setattr(zipfile, 'ZipFile', forbidden)
    report = qualification.qualify()
    assert report['scope'] == 'input_identity_only'
    assert report['scientific_trial'] is False
    assert report['frozen_sources']['source_files_compared'] == 66
    assert report['frozen_sources']['all_equal'] is True
    assert report['frozen_sources']['original_receipt_verified'] is True
    assert report['compared_input_arrays'] == 461
    assert report['independently_regenerated_stress_arrays'] == 216
    assert report['compared_analytic_rows'] == 20
    assert all(report[key] == 0 for key in (
        'predictor_calls', 'decoder_calls', 'truth_or_reference_calls', 'scorer_calls'))
    environment = report['environment']
    assert environment['numpy_version'] == '1.26.4'
    assert environment['numpy_file']
    assert environment['numpy_extension_sha256']
    assert environment['numpy_build']
    assert environment['numpy_runtime'] or environment['numpy_runtime_error']
    assert 'AVX512F' in environment['cpu_features']
    different = any(report['input_differences'].values()) or report['analytic_difference_paths']
    assert report['status'] == ('incompatible' if different else 'compatible')
    if report['first_input_difference'] is not None:
        assert set(report['first_input_difference']['expected']['observation']) == {'sha256', 'dtype', 'shape'}


def test_hash_drift_keeps_both_identities_and_rejects_population_changes():
    from scripts.note_boundary_readout_synthetic import numeric_difference_paths

    expected = [{'id': 'case1', 'duration_seconds': 1.,
                 'observation': {'dtype': '<f8', 'shape': [101], 'sha256': 'a' * 64}}]
    actual = copy.deepcopy(expected)
    actual[0]['observation']['sha256'] = 'b' * 64
    difference = qualification.compare_rows(actual, expected, numeric_difference_paths)
    assert difference == [{'id': 'case1', 'difference_paths': ['case1/observation/sha256'],
                           'expected': expected[0], 'actual': actual[0]}]
    with pytest.raises(ValueError, match='v2_exact_ordered_input_population'):
        qualification.compare_rows([], expected, numeric_difference_paths)


def test_source_drift_stops_before_generating_inputs(monkeypatch):
    monkeypatch.setattr(qualification, 'environment', lambda: {'test': 'environment'})
    monkeypatch.setattr(qualification, 'frozen_sources', lambda: {'all_equal': False})
    report = qualification.qualify()
    assert report['status'] == 'incompatible'
    assert report['reason'] == 'frozen_source_identity'
    assert 'observations' not in report


def test_incompatible_host_cannot_claim_mutation_rejections():
    with pytest.raises(ValueError, match='v2_positive_environment_qualification_required'):
        qualification.mutation_contract({'schema': qualification.SCHEMA, 'status': 'incompatible'})


def test_earlier_environment_failure_is_not_accepted_as_a_mutation_rejection(monkeypatch):
    from scripts import audit_note_boundary_parent_guard as audit
    from scripts import note_boundary_parent_guard_synthetic as stress
    from scripts import note_boundary_readout_synthetic as prior

    old = prior.read_numeric_manifest()
    report = {'schema': qualification.SCHEMA, 'status': 'compatible',
              'observations': {'legacy': old['cases'], 'stress': stress.read_numeric_manifest()['cases']},
              'analytic_actual': old['emission_analysis']}
    calls = []

    def wrong_rejection(*args):
        calls.append(None)
        if len(calls) == 1:
            return {'compared_input_arrays': 461}
        raise ValueError('independent_stress_input_regeneration: boolean mismatch')

    monkeypatch.setattr(audit, 'check_numeric_preflight', wrong_rejection)
    with pytest.raises(ValueError, match='v2_wrong_mutation_rejection/stress_input'):
        qualification.mutation_contract(report)


def fixture_session():
    return SimpleNamespace(
        config=SimpleNamespace(pluginmanager=SimpleNamespace(get_plugin=lambda name: None)),
        testscollected=3, exitstatus=0)


def test_plugin_keeps_every_test_but_forces_failure_for_incompatible_host(tmp_path, monkeypatch):
    monkeypatch.setenv('RUNNER_TEMP', str(tmp_path))
    monkeypatch.setattr(qualification, 'qualify', lambda: {'schema': qualification.SCHEMA, 'status': 'incompatible'})

    def forbidden(*args):
        raise AssertionError('mutation checks must not run before positive qualification')

    monkeypatch.setattr(qualification, 'mutation_contract', forbidden)
    session = fixture_session()
    plugin.pytest_sessionstart(session)
    plugin.pytest_sessionfinish(session, 0)
    assert session.exitstatus == 1
    report = json.loads((tmp_path / 'research-numeric-qualification-v2.json').read_text())
    assert report['mutation_contract']['status'] == 'not_run'
    assert report['test_execution'] == {
        'collected': 3, 'pytest_exitstatus': 0,
        'qualification_forced_failure': True, 'test_selection_changed': False}


def test_diagnostic_error_is_preserved_and_does_not_turn_green(tmp_path, monkeypatch):
    monkeypatch.setenv('RUNNER_TEMP', str(tmp_path))

    def broken():
        raise ValueError('v2_frozen_source_manifest_identity')

    monkeypatch.setattr(qualification, 'qualify', broken)
    monkeypatch.setattr(qualification, 'environment', lambda: {'actual_numpy_file': '/fixture/numpy'})
    session = fixture_session()
    plugin.pytest_sessionstart(session)
    plugin.pytest_sessionfinish(session, 0)
    assert session.exitstatus == 1
    report = session.config._research_numeric_report
    assert report['status'] == 'diagnostic_error'
    assert report['error'] == 'ValueError: v2_frozen_source_manifest_identity'
    assert report['environment'] == {'actual_numpy_file': '/fixture/numpy'}


def test_plugin_preserves_an_existing_pytest_error(tmp_path, monkeypatch):
    monkeypatch.setenv('RUNNER_TEMP', str(tmp_path))
    monkeypatch.setattr(qualification, 'qualify', lambda: {'schema': qualification.SCHEMA, 'status': 'incompatible'})
    session = fixture_session()
    session.exitstatus = 2
    plugin.pytest_sessionstart(session)
    plugin.pytest_sessionfinish(session, 2)
    assert session.exitstatus == 2
    assert session.config._research_numeric_report['test_execution']['qualification_forced_failure'] is False

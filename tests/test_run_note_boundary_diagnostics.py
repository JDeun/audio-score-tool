"""No boundary claims unless the entire frozen scientific payload is replayed."""
from __future__ import annotations

import copy
import json
import zipfile

import pytest

from scripts import run_note_boundary_diagnostics as study


def previous_reports():
    with zipfile.ZipFile(study.ROOT / study.PREVIOUS) as archive:
        return {name: json.loads(archive.read(name + '.json'))
                for name in ('vocadito', 'synthetic', 'audit')}


def test_exact_full_replay_allows_only_volatile_environment_fields():
    previous = previous_reports()
    corpus, synthetic = previous['vocadito'], previous['synthetic']
    corpus['cases'][0]['inference_seconds'] = 1000.
    corpus['cases'][0]['observation_sha256'] = '0' * 64
    corpus['platform'] = 'different runner host'
    corpus['source_revision'] = synthetic['source_revision'] = 'new revision'
    synthetic['elapsed_seconds'] = 42.
    result = study.replay_parity(corpus, synthetic)
    assert result['all_equal'] is True
    assert result['compared_corpus_prediction_files'] == 400
    assert result['compared_corpus_observation_arrays'] == 440
    assert result['compared_synthetic_prediction_files'] == 1715
    assert result['compared_synthetic_input_arrays'] == 245
    assert result['compared_synthetic_state_paths'] == 1470
    assert len(result['source_checks']) == 24


@pytest.mark.parametrize('damage', [
    'last_case', 'duplicate_case', 'prediction', 'array_bytes', 'array_dtype',
    'array_shape', 'new_arm', 'score', 'diagnostic', 'reference', 'source',
    'extra_source', 'aggregate', 'barrier', 'synthetic_prediction',
    'synthetic_state_path', 'synthetic_input', 'synthetic_truth',
    'synthetic_ambiguity', 'synthetic_subset', 'synthetic_emission',
    'boolean_type', 'integer_type',
])
def test_scientific_mutation_blocks_diagnostics(damage):
    previous = previous_reports()
    corpus, synthetic = previous['vocadito'], previous['synthetic']
    row = corpus['cases'][-1]
    if damage == 'last_case':
        corpus['cases'].pop()
    elif damage == 'duplicate_case':
        corpus['cases'][-1] = copy.deepcopy(corpus['cases'][0])
    elif damage == 'prediction':
        row['arms']['gaussian_exponent_1']['event_sha256'] = '0' * 64
    elif damage.startswith('array_'):
        field, value = {'array_bytes': ('sha256', '0' * 64),
                        'array_dtype': ('dtype', '<f4'), 'array_shape': ('shape', [1])}[damage]
        row['observations']['gaussian_exponent_1_path'][field] = value
    elif damage == 'new_arm':
        row['arms']['unplanned'] = copy.deepcopy(row['arms']['pitch_runs'])
    elif damage == 'score':
        row['arms']['pitch_runs']['annotators']['A2']['onset_offset_f1'] += .01
    elif damage == 'diagnostic':
        row['diagnostics']['factors']['gaussian_exponent_1']['emitted_notes'] += 1
    elif damage == 'reference':
        row['reference_sha256']['A2'] = '0' * 64
    elif damage == 'source':
        corpus['source_sha256']['scripts/note_state_factors.py'] = '0' * 64
    elif damage == 'extra_source':
        corpus['source_sha256']['unknown.py'] = '0' * 64
    elif damage == 'aggregate':
        corpus['aggregate']['pitch_runs']['onset_offset_f1']['macro'] += .01
    elif damage == 'barrier':
        corpus['all_predictions_frozen_before_references'] = False
    elif damage == 'boolean_type':
        corpus['product_changes'] = 0
    elif damage == 'integer_type':
        row['arms']['pitch_runs']['count'] = float(row['arms']['pitch_runs']['count'])
    elif damage == 'synthetic_prediction':
        synthetic['cases'][-1]['arms']['gaussian_exponent_1']['event_sha256'] = '0' * 64
    elif damage == 'synthetic_state_path':
        synthetic['cases'][-1]['arms']['gaussian_exponent_1']['state_path']['sha256'] = '0' * 64
    elif damage == 'synthetic_input':
        synthetic['cases'][-1]['observation']['sha256'] = '0' * 64
    elif damage == 'synthetic_truth':
        synthetic['cases'][0]['truth'][0]['offset'] += .01
    elif damage == 'synthetic_ambiguity':
        synthetic['cases'][-1]['alternative_truth'] = []
    elif damage == 'synthetic_subset':
        synthetic['cases'].pop()
    else:
        synthetic['emission_analysis'][0]['attack_mass'] += .01
    result = study.replay_parity(corpus, synthetic)
    assert result['all_equal'] is False


def test_wrong_artifact_fails_before_any_replay_comparison(tmp_path):
    path = tmp_path / 'wrong.zip'
    path.write_bytes(b'not the preserved artifact')
    with pytest.raises(ValueError, match='original #292'):
        study.replay_parity({}, {}, path)


@pytest.mark.parametrize('raw', ['{"same": 1, "same": 2}', '{"x": NaN}', '{"x": Infinity}'])
def test_noncanonical_input_json_is_rejected(tmp_path, raw):
    path = tmp_path / 'input.json'
    path.write_text(raw)
    with pytest.raises(ValueError):
        study.read_json(path)


def prepare_inputs(tmp_path):
    paths = {}
    with zipfile.ZipFile(study.ROOT / study.PREVIOUS) as archive:
        for name in ('vocadito', 'synthetic', 'audit'):
            paths[name] = tmp_path / (name + '.json')
            paths[name].write_bytes(archive.read(name + '.json'))
    work, synthetic_work = tmp_path / 'private', tmp_path / 'synthetic-private'
    work.mkdir()
    synthetic_work.mkdir()
    return paths, work, synthetic_work


@pytest.mark.parametrize('damage', ['failed_audit', 'unbound_audit', 'replay_mismatch'])
def test_gate_prevents_even_the_first_diagnostic_call(tmp_path, monkeypatch, damage):
    paths, work, synth_work = prepare_inputs(tmp_path)
    if damage == 'replay_mismatch':
        content = json.loads(paths['synthetic'].read_text())
        content['cases'][-1]['arms']['gaussian_exponent_1']['count'] += 1
        study.dsp.save(paths['synthetic'], content)
    else:
        content = json.loads(paths['audit'].read_text())
        if damage == 'failed_audit':
            content['status'] = 'failed'
        else:
            content['report_sha256'] = '0' * 64
        study.dsp.save(paths['audit'], content)
    called = []
    monkeypatch.setattr(study, 'diagnose', lambda *_: called.append(True))
    report = study.run(work, paths['vocadito'], synth_work, paths['synthetic'],
                       paths['audit'], tmp_path / 'diagnostics.json')
    assert called == []
    assert report['status'] in ('failed', 'replay_parity_failed')
    assert report['all_cases_complete'] is False
    assert report['corpus'] is None and report['synthetic'] is None
    assert report['quality_approved'] is False


def test_diagnostic_failure_cannot_publish_partial_complete_summary(tmp_path, monkeypatch):
    paths, work, synth_work = prepare_inputs(tmp_path)

    def failure(*_):
        raise ValueError('private evidence differs')

    monkeypatch.setattr(study, 'diagnose', failure)
    report = study.run(work, paths['vocadito'], synth_work, paths['synthetic'],
                       paths['audit'], tmp_path / 'diagnostics.json')
    assert report['status'] == 'failed'
    assert report['corpus'] is None and report['synthetic'] is None
    assert report['all_cases_complete'] is False
    assert (work / 'boundary-error.txt').read_text() == 'private evidence differs'


def test_returning_partial_diagnostic_payload_does_not_mean_completion(tmp_path, monkeypatch):
    paths, work, synth_work = prepare_inputs(tmp_path)
    monkeypatch.setattr(study, 'diagnose', lambda *_: (
        {'cases': [], 'aggregate': None}, {'status': 'complete', 'cases': [], 'aggregate': None}))
    report = study.run(work, paths['vocadito'], synth_work, paths['synthetic'],
                       paths['audit'], tmp_path / 'diagnostics.json')
    assert report['status'] == 'failed'
    assert report['all_cases_complete'] is False
    assert report['corpus'] is None and report['synthetic'] is None

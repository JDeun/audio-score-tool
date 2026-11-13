"""Failure, provenance, and prediction-before-reference contracts for the study."""
from __future__ import annotations

import copy
import json

import numpy as np
import pytest

from scripts import run_note_state_factors as study
from scripts.dsp_note_probe import save


def ready_rows(tmp_path):
    rows = []
    for case in study.CASES:
        arms = {}
        for arm in study.ARMS:
            path = tmp_path / case / f'{arm}.json'
            save(path, [])
            arms[arm] = {'event_sha256': study.dsp.digest(path), 'count': 0, 'annotators': {}}
        rows.append({'id': case, 'status': 'predicted', 'arms': arms})
    return rows


def scored_rows():
    metrics = {'onset_f1': .2, 'onset_offset_f1': .1, 'onset_precision': .2,
               'onset_recall': .2, 'offset_precision': .1, 'offset_recall': .1,
               'onset_gained_reference_ids': [], 'onset_lost_reference_ids': [],
               'onset_offset_gained_reference_ids': [], 'onset_offset_lost_reference_ids': []}
    return [{'id': case, 'status': 'scored', 'arms': {
        arm: {'count': 3, 'annotators': {a: copy.deepcopy(metrics) for a in study.ANNOTATORS}}
        for arm in study.ARMS}} for case in study.CASES]


def test_array_hash_includes_dtype_shape_and_exact_bytes():
    a = np.arange(6, dtype=np.float64).reshape(2, 3)
    identity = study.array_identity(a)
    assert identity == study.array_identity(np.asfortranarray(a))
    assert identity != study.array_identity(a.reshape(-1))
    assert identity != study.array_identity(a.astype(np.float32))
    with pytest.raises(ValueError):
        study.array_identity(np.array([np.nan]))
    with pytest.raises(ValueError):
        study.array_identity(np.array([object()], dtype=object))


def test_prediction_barrier_rejects_tampering_and_duplicate_cases(tmp_path):
    rows = ready_rows(tmp_path)
    assert len(study.prediction_manifest(rows, tmp_path)) == 64
    duplicate = copy.deepcopy(rows)
    duplicate[-1] = duplicate[0]
    with pytest.raises(ValueError, match='all planned'):
        study.prediction_manifest(duplicate, tmp_path)
    save(tmp_path / study.CASES[0] / f'{study.ARMS[0]}.json', [{'changed': True}])
    with pytest.raises(ValueError, match='prediction changed'):
        study.prediction_manifest(rows, tmp_path)


def test_missing_last_prediction_prevents_even_first_reference_read(tmp_path, monkeypatch):
    rows = ready_rows(tmp_path)
    report = {'cases': rows, 'all_predictions_frozen_before_references': True,
              'predictions_manifest_sha256': study.prediction_manifest(rows, tmp_path)}
    rows[-1]['status'] = 'prediction_failed'
    calls = []
    monkeypatch.setattr(study, 'score_case', lambda *args: calls.append('reference'))
    with pytest.raises(ValueError, match='all planned'):
        study.evaluate_all(None, tmp_path, report, tmp_path / 'report.json')
    assert calls == []


def test_complete_barrier_then_read_all_refs_keeps_manifest(tmp_path, monkeypatch):
    rows = ready_rows(tmp_path)
    manifest = study.prediction_manifest(rows, tmp_path)
    report = {'cases': rows, 'all_predictions_frozen_before_references': True,
              'predictions_manifest_sha256': manifest}
    calls = []

    def score(_package, row, work):
        assert len(list(work.glob('vocadito_*/*.json'))) == len(study.CASES) * len(study.ARMS)
        calls.append(row['id'])
        row['status'] = 'scored'

    monkeypatch.setattr(study, 'score_case', score)
    study.evaluate_all(None, tmp_path, report, tmp_path / 'report.json')
    assert calls == list(study.CASES)
    assert report['post_evaluation_predictions_manifest_sha256'] == manifest
    assert report['reference_access_started_after_predicted_cases'] == 40


def test_predict_pass_opens_only_audio_even_before_last_case(tmp_path, monkeypatch):
    opened = []

    class AudioOnlyArchive:
        def read(self, member):
            assert member.startswith('Audio/') and member.endswith('.wav')
            opened.append(member)
            return b'owned-test-audio-placeholder'

    def fake_infer(_audio):
        arrays = {k: np.zeros(1) for k in ('hz', 'probability', 'attacks', 'rms', 'phase_path', 'rms_phase_path')}
        return arrays, dict.fromkeys(study.ARMS, []), {}, 0.

    monkeypatch.setattr(study, 'infer_recording', fake_infer)
    report = {'cases': []}
    study.predict_all(AudioOnlyArchive(), tmp_path, report, tmp_path / 'report.json')
    assert opened == [f'Audio/{c}.wav' for c in study.CASES]
    assert report['all_predictions_frozen_before_references'] is True
    assert len(report['cases']) == 40
    assert all(not a['annotators'] for r in report['cases'] for a in r['arms'].values())


@pytest.mark.parametrize('damage', ['missing_case', 'duplicate_case', 'failed_case', 'missing_arm', 'missing_annotator'])
def test_incomplete_cohort_cannot_have_a_mean(damage):
    rows = scored_rows()
    if damage == 'missing_case':
        rows.pop()
    elif damage == 'duplicate_case':
        rows[-1] = rows[0]
    elif damage == 'failed_case':
        rows[-1]['status'] = 'evaluation_failed'
    elif damage == 'missing_arm':
        rows[-1]['arms'].pop(study.ARMS[-1])
    else:
        rows[-1]['arms'][study.ARMS[-1]]['annotators'].pop('A2')
    assert study.aggregate(rows) is None


def test_macro_retains_all_files_both_annotators_and_zero_predictions():
    rows = scored_rows()
    arm = study.ARMS[-1]
    rows[0]['arms'][arm]['count'] = 0
    for a in study.ANNOTATORS:
        rows[0]['arms'][arm]['annotators'][a]['onset_f1'] = 0.
    rows[1]['arms'][arm]['annotators']['A2']['onset_f1'] = .6
    result = study.aggregate(rows)[arm]
    assert result['predicted_notes'] == 117
    assert result['onset_f1']['macro'] == pytest.approx(.2)
    assert result['onset_f1']['recordings_improved'] == 1
    assert result['onset_f1']['recordings_worse'] == 1
    assert result['onset_f1']['recordings_tied'] == 38
    assert result['onset_f1']['A1_macro'] == pytest.approx(.195)
    assert result['onset_f1']['A2_macro'] == pytest.approx(.205)


def test_public_diagnostics_do_not_export_full_segment_lists():
    result = study.scalar_diagnostics({'frames': 12, 'segments': [{'pitch': 60}],
                                       'child': {'count': 3, 'path': [1, 2, 3]}})
    assert json.loads(json.dumps(result)) == {'frames': 12, 'child': {'count': 3}}


def test_historical_mismatch_is_a_failed_gate_even_with_all_scores(monkeypatch):
    report = {'cases': scored_rows()}
    mismatch = {'all_equal': False, 'differences': [{'field': 'event_sha256'}]}
    monkeypatch.setattr(study, 'baseline_parity', lambda *_: mismatch)
    monkeypatch.setattr(study, 'historical_parity', lambda *_: {'all_equal': True})
    study.finalize_results(report, None, None)
    assert report['status'] == 'baseline_parity_failed'
    assert report['all_cases_complete'] is True
    assert report['aggregate'] is not None
    assert report['historical_baseline_parity'] == mismatch


def prior_report():
    import zipfile
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    path = root / study.HMM_RECEIPT
    with zipfile.ZipFile(path) as archive:
        old = json.loads(archive.read('vocadito.json'))
    report = copy.deepcopy(old)
    for row in report['cases']:
        row['diagnostics'] = {'legacy': row['diagnostics']}
    return report, path


@pytest.mark.parametrize('damage', [None, 'observation', 'prediction', 'score', 'source', 'diagnostic'])
def test_all_old_array_prediction_score_and_source_identities_are_required(damage):
    report, path = prior_report()
    row = report['cases'][-1]
    if damage == 'observation':
        row['observations']['hz']['sha256'] = '0' * 64
    elif damage == 'prediction':
        row['arms']['note_state_hmm']['event_sha256'] = '0' * 64
    elif damage == 'score':
        row['arms']['note_state_hmm']['annotators']['A2']['onset_offset_f1'] += .01
    elif damage == 'source':
        report['source_sha256']['scripts/note_state_hmm.py'] = '0' * 64
    elif damage == 'diagnostic':
        row['diagnostics']['legacy']['arms']['note_state_hmm']['decoded_voiced_frames'] += 1
    result = study.historical_parity(report, path)
    assert result['all_equal'] is (damage is None)
    assert result['compared_observation_arrays'] == 240
    assert result['compared_prediction_files'] == 200
    assert result['array_identity_available'] is True
    assert result['raw_historical_arrays_available'] is False


def test_primary_bootstrap_resamples_paired_recordings_not_annotators():
    rows = scored_rows()
    for row in rows:
        row['arms']['gaussian_exponent_1']['annotators']['A1']['onset_offset_f1'] = .2
        row['arms']['gaussian_exponent_1']['annotators']['A2']['onset_offset_f1'] = 0.
    result = study.primary_summary(rows)
    assert result['mean_delta'] == 0.
    assert result['recordings_tied'] == 40
    assert result['bootstrap']['low'] == result['bootstrap']['high'] == 0.
    assert result == study.primary_summary(list(reversed(rows)))
    rows.pop()
    with pytest.raises(ValueError, match='complete cohort'):
        study.primary_summary(rows)


def test_hmm_identity_mismatch_also_fails_after_complete_scoring(monkeypatch):
    report = {'cases': scored_rows()}
    monkeypatch.setattr(study, 'baseline_parity', lambda *_: {'all_equal': True})
    monkeypatch.setattr(study, 'historical_parity', lambda *_: {'all_equal': False})
    study.finalize_results(report, None, None)
    assert report['status'] == 'baseline_parity_failed'
    assert report['aggregate'] is not None and report['primary_result'] is not None

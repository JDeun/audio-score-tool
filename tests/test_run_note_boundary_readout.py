"""Prediction barriers, frozen replay and private diagnostics for the #296 runner."""
from __future__ import annotations

import copy
import json
import zipfile
from dataclasses import asdict

import numpy as np
import pytest

from scripts import note_boundary_readout as readout
from scripts import note_state_hmm
from scripts import run_note_boundary_readout as study
from scripts.dsp_note_probe import Note, digest, fingerprint, save


def ready_rows(tmp_path):
    rows = []
    for case in study.CASES:
        arms = {}
        for arm in study.ARMS:
            path = tmp_path / case / f'{arm}.json'
            save(path, [])
            arms[arm] = {'event_sha256': digest(path), 'count': 0, 'annotators': {}}
        rows.append({'id': case, 'status': 'predicted', 'arms': arms})
    return rows


def scored_rows():
    metrics = {'onset_f1': .2, 'onset_offset_f1': .1,
               'onset_precision': .2, 'onset_recall': .2,
               'offset_precision': .1, 'offset_recall': .1,
               'onset_gained_reference_ids': [], 'onset_lost_reference_ids': [],
               'onset_offset_gained_reference_ids': [], 'onset_offset_lost_reference_ids': []}
    return [{'id': case, 'status': 'scored', 'arms': {
        arm: {'count': 3, 'annotators': {a: copy.deepcopy(metrics) for a in study.ANNOTATORS}}
        for arm in study.ARMS}} for case in study.CASES]


def archived_reports():
    with zipfile.ZipFile(study.ROOT / study.PREVIOUS) as archive:
        corpus = json.loads(archive.read('vocadito.json'))
        sources = json.loads(archive.read('diagnostics.json'))['source_sha256']
    report = copy.deepcopy(corpus)
    report.update(schema='note-boundary-readout-v1', planned_arms=list(study.ARMS),
                  source_sha256=sources, primary_comparison=study.SETTINGS)
    for row in report['cases']:
        row['arms'][study.ARM] = copy.deepcopy(row['arms'][study.BASE_ARM])
        row.update(readout={'owned_fixture': True}, readout_private_sha256='1' * 64,
                   annotation_diagnostics={'owned_fixture': True}, annotation_private_sha256='2' * 64)
    return report, corpus


def test_arm_source_and_denominator_inventories_are_frozen():
    assert len(study.CASES) == 40
    assert len(study.ARMS) == 11
    assert study.ARMS[:-1] == study.frozen.ARMS
    assert study.ARMS[-1] == study.ARM
    assert len(study.SOURCE_PATHS) == len(set(study.SOURCE_PATHS)) == 47
    assert study.SOURCE_PATHS[:35] == study.prior.SOURCE_PATHS
    assert study.SETTINGS['bootstrap_seed'] == 296
    assert study.SETTINGS['bootstrap_resamples'] == 10000
    assert study.SETTINGS['shared_G_path'] is True


@pytest.mark.parametrize('damage', ['missing_file', 'mutated_file', 'missing_arm',
                                  'failed_last', 'duplicate_case', 'wrong_manifest',
                                  'missing_barrier'])
def test_last_of_440_predictions_blocks_even_the_first_reference(tmp_path, monkeypatch, damage):
    rows = ready_rows(tmp_path)
    report = {'cases': rows, 'all_predictions_frozen_before_references': True,
              'predictions_manifest_sha256': study.prediction_manifest(rows, tmp_path)}
    final = tmp_path / study.CASES[-1] / f'{study.ARM}.json'
    if damage == 'missing_file':
        final.unlink()
    elif damage == 'mutated_file':
        save(final, [{'changed': True}])
    elif damage == 'missing_arm':
        rows[-1]['arms'].pop(study.ARM)
    elif damage == 'failed_last':
        rows[-1]['status'] = 'prediction_failed'
    elif damage == 'duplicate_case':
        rows[-1] = copy.deepcopy(rows[0])
    elif damage == 'wrong_manifest':
        report['predictions_manifest_sha256'] = '0' * 64
    else:
        report['all_predictions_frozen_before_references'] = False
    calls = []
    monkeypatch.setattr(study, 'score_case', lambda *_: calls.append('reference'))
    with pytest.raises((ValueError, FileNotFoundError)):
        study.evaluate_all(None, tmp_path, report, tmp_path / 'report.json')
    assert calls == []
    assert 'reference_access_started_after_predicted_cases' not in report


def test_complete_prediction_barrier_precedes_all_40_scoring_calls(tmp_path, monkeypatch):
    rows = ready_rows(tmp_path)
    manifest = study.prediction_manifest(rows, tmp_path)
    report = {'cases': rows, 'all_predictions_frozen_before_references': True,
              'predictions_manifest_sha256': manifest}
    calls = []

    def score(_package, row, work):
        assert len(list(work.glob('vocadito_*/*.json'))) == 440
        calls.append(row['id'])
        row['status'] = 'scored'

    monkeypatch.setattr(study, 'score_case', score)
    study.evaluate_all(None, tmp_path, report, tmp_path / 'report.json')
    assert calls == list(study.CASES)
    assert report['reference_access_started_after_predicted_cases'] == 40
    assert report['post_evaluation_predictions_manifest_sha256'] == manifest
    assert study.prediction_manifest(list(reversed(rows)), tmp_path) == manifest


def test_scoring_failure_is_retained_without_a_partial_complete_manifest(tmp_path, monkeypatch):
    rows = ready_rows(tmp_path)
    report = {'cases': rows, 'all_predictions_frozen_before_references': True,
              'predictions_manifest_sha256': study.prediction_manifest(rows, tmp_path)}
    calls = []

    def score(_package, row, _work):
        calls.append(row['id'])
        if row['id'] == study.CASES[-1]:
            raise ValueError('owned missing reference fixture')
        row['status'] = 'scored'

    monkeypatch.setattr(study, 'score_case', score)
    study.evaluate_all(None, tmp_path, report, tmp_path / 'report.json')
    assert calls == list(study.CASES)
    assert len(report['cases']) == 40
    assert report['cases'][-1]['status'] == 'evaluation_failed'
    assert report['cases'][-1]['error_type'] == 'ValueError'
    assert 'post_evaluation_predictions_manifest_sha256' not in report
    assert (tmp_path / study.CASES[-1] / 'error.txt').read_text() == 'owned missing reference fixture'


def test_prediction_pass_reads_only_wav_and_saves_all_new_traces_before_references(tmp_path, monkeypatch):
    opened = []

    class AudioOnlyArchive:
        def read(self, member):
            assert member.startswith('Audio/') and member.endswith('.wav')
            opened.append(member)
            return b'owned-test-placeholder'

    def fake_infer(_audio):
        return ({'hz': np.zeros(1)}, {arm: [] for arm in study.ARMS}, {}, 0.,
                {'candidate_cut_count': 0}, {'schema_version': 1, 'parents': []})

    monkeypatch.setattr(study, 'infer_recording', fake_infer)
    report = {'cases': []}
    study.predict_all(AudioOnlyArchive(), tmp_path, report, tmp_path / 'report.json')
    assert opened == [f'Audio/{case}.wav' for case in study.CASES]
    assert report['all_predictions_frozen_before_references'] is True
    assert len(report['cases']) == 40
    assert all(not arm['annotators'] for row in report['cases'] for arm in row['arms'].values())
    assert len(list(tmp_path.glob('vocadito_*/readout-private.json'))) == 40
    assert not list(tmp_path.glob('vocadito_*/*.csv'))


def test_inference_reuses_exact_existing_G_arrays_once_without_decoding(monkeypatch):
    hz = 440. * 2 ** ((np.array([60.] * 10 + [61.] * 10) - 69) / 12)
    path = np.full(20, 244, dtype=np.int16)
    arrays = {'hz': hz, 'gaussian_exponent_1_path': path,
              'probability': np.ones(20), 'old_private_array': np.arange(5, dtype=np.int16)}
    old_notes, _ = note_state_hmm.notes_from_state_path(path, hz, .2)
    old_arms = {arm: copy.deepcopy(old_notes) for arm in study.frozen.ARMS}
    old_snapshot, array_snapshot = copy.deepcopy(old_arms), {k: v.copy() for k, v in arrays.items()}
    calls = []

    def original_infer(audio):
        calls.append(('frozen', audio))
        return arrays, old_arms, {'legacy': {}, 'factors': {}}, .2

    def child_readout(actual_path, actual_hz, duration):
        assert actual_path is path and actual_hz is hz and duration == .2
        calls.append(('readout', None))
        return readout.notes_from_state_path(actual_path, actual_hz, duration)

    monkeypatch.setattr(study.frozen, 'infer_recording', original_infer)
    monkeypatch.setattr(study, 'notes_from_state_path', child_readout)
    result = study.infer_recording('owned-audio')
    assert calls == [('frozen', 'owned-audio'), ('readout', None)]
    assert result[0] is arrays
    assert set(arrays) == set(array_snapshot)
    assert all(np.array_equal(value, array_snapshot[key]) for key, value in arrays.items())
    assert {arm: result[1][arm] for arm in study.frozen.ARMS} == old_snapshot
    assert result[1][study.ARM] == [Note(60, 0., .1), Note(61, .1, .2)]


def test_inference_rejects_original_G_parent_reconstruction_mismatch(monkeypatch):
    arrays = {'hz': np.full(10, 440.), 'gaussian_exponent_1_path': np.full(10, 325, dtype=np.int16)}
    arms = {arm: [Note(68, 0., .1)] for arm in study.frozen.ARMS}
    monkeypatch.setattr(study.frozen, 'infer_recording', lambda _: (arrays, arms, {}, .1))
    with pytest.raises(ValueError, match='original G parent'):
        study.infer_recording('owned-placeholder')


@pytest.mark.parametrize('damage', ['empty_cohort', 'missing_case', 'duplicate_case',
                                  'failed_case', 'missing_arm', 'extra_arm',
                                  'missing_annotator', 'extra_annotator'])
def test_incomplete_cohort_cannot_have_an_aggregate_or_primary_interval(damage):
    rows = scored_rows()
    if damage == 'empty_cohort':
        rows = []
    elif damage == 'missing_case':
        rows.pop()
    elif damage == 'duplicate_case':
        rows[-1] = copy.deepcopy(rows[0])
    elif damage == 'failed_case':
        rows[-1]['status'] = 'evaluation_failed'
    elif damage == 'missing_arm':
        rows[-1]['arms'].pop(study.ARM)
    elif damage == 'extra_arm':
        rows[-1]['arms']['unplanned'] = copy.deepcopy(rows[-1]['arms'][study.ARM])
    elif damage == 'missing_annotator':
        rows[-1]['arms'][study.ARM]['annotators'].pop('A2')
    else:
        rows[-1]['arms'][study.ARM]['annotators']['A3'] = {}
    assert study.aggregate(rows) is None
    with pytest.raises(ValueError, match='complete cohort'):
        study.primary_summary(rows)


def test_empty_prediction_remains_a_scored_zero_in_both_annotator_macro():
    rows = scored_rows()
    empty = rows[0]['arms'][study.ARM]
    empty['count'] = 0
    for annotator in study.ANNOTATORS:
        for metric in ('onset_f1', 'onset_offset_f1', 'onset_precision',
                       'onset_recall', 'offset_precision', 'offset_recall'):
            empty['annotators'][annotator][metric] = 0.
    rows[1]['arms'][study.ARM]['annotators']['A2']['onset_f1'] = .6
    result = study.aggregate(rows)[study.ARM]
    assert result['predicted_notes'] == 117
    assert result['onset_f1']['macro'] == pytest.approx(.2)
    assert result['onset_f1']['A1_macro'] == pytest.approx(.195)
    assert result['onset_f1']['A2_macro'] == pytest.approx(.205)
    assert result['onset_f1']['recordings_improved'] == 1
    assert result['onset_f1']['recordings_worse'] == 1
    assert result['onset_f1']['recordings_tied'] == 38
    assert result['onset_offset_f1']['macro'] == pytest.approx(.0975)


@pytest.mark.parametrize('score', [-.01, 1.01, float('nan'), float('inf')])
def test_invalid_new_arm_F1_is_rejected(score):
    rows = scored_rows()
    rows[-1]['arms'][study.ARM]['annotators']['A2']['onset_offset_f1'] = score
    with pytest.raises(ValueError, match='invalid score'):
        study.aggregate(rows)


def test_legacy_projection_reproduces_entire_archived_old_ten_arm_scientific_payload():
    report, old = archived_reports()
    result = study.legacy_projection(
        report, study.ROOT / 'docs/research/receipts/dsp-note-baseline-42989661618.zip',
        study.ROOT / study.frozen.HMM_RECEIPT)
    assert all(study.prior.exact_equal(result[key], old[key]) for key in study.prior.CORPUS_FIELDS)
    assert study.prior.exact_equal(result['cases'], old['cases'])
    assert result['source_sha256'] == old['source_sha256']
    assert len(result['cases']) == 40
    assert sum(len(row['arms']) for row in result['cases']) == 400
    assert sum(len(row['observations']) for row in result['cases']) == 440
    assert all(not (set(row) & study.ROW_ADDITIONS) for row in result['cases'])
    assert all(set(row['arms']) == set(study.frozen.ARMS) for row in result['cases'])
    # The projection is a copy: later receipt annotation must not modify source evidence.
    result['cases'][0]['observations']['hz']['sha256'] = '0' * 64
    assert report['cases'][0]['observations']['hz']['sha256'] != '0' * 64


@pytest.mark.parametrize('damage', [None, 'event', 'array', 'array_dtype', 'score',
                                  'reference', 'diagnostic', 'source', 'barrier',
                                  'integer_type', 'new_row_field'])
def test_archived_all_400_predictions_440_arrays_and_35_sources_remain_a_gate(damage):
    report, legacy = archived_reports()
    row = legacy['cases'][-1]
    if damage == 'event':
        row['arms'][study.BASE_ARM]['event_sha256'] = '0' * 64
    elif damage == 'array':
        row['observations'][study.BASE_ARM + '_path']['sha256'] = '0' * 64
    elif damage == 'array_dtype':
        row['observations']['hz']['dtype'] = '<f4'
    elif damage == 'score':
        row['arms'][study.BASE_ARM]['annotators']['A2']['onset_offset_f1'] += .001
    elif damage == 'reference':
        row['reference_sha256']['A2'] = '0' * 64
    elif damage == 'diagnostic':
        row['diagnostics']['factors'][study.BASE_ARM]['emitted_notes'] += 1
    elif damage == 'source':
        report['source_sha256']['scripts/note_state_hmm.py'] = '0' * 64
    elif damage == 'barrier':
        legacy['all_predictions_frozen_before_references'] = False
    elif damage == 'integer_type':
        row['arms'][study.BASE_ARM]['count'] = float(row['arms'][study.BASE_ARM]['count'])
    elif damage == 'new_row_field':
        row['unplanned_scientific_field'] = True
    result = study.historical_parity(report, legacy)
    assert result['all_equal'] is (damage is None)
    assert result['compared_prediction_files'] == 400
    assert result['compared_observation_arrays'] == 440
    assert len(result['source_checks']) == 35
    assert result['raw_historical_arrays_available'] is False
    assert result['array_identity_available'] is True


def test_primary_interval_pairs_A1_A2_within_recording_and_is_order_invariant():
    rows = scored_rows()
    for row in rows:
        row['arms'][study.ARM]['annotators']['A1']['onset_offset_f1'] = .2
        row['arms'][study.ARM]['annotators']['A2']['onset_offset_f1'] = 0.
    result = study.primary_summary(rows)
    assert result['mean_delta'] == 0.
    assert result['recordings_tied'] == 40
    assert result['bootstrap'] == {
        'resampling_unit': 'recording_mean_of_A1_A2', 'seed': 296,
        'resamples': 10000, 'confidence_level': .95, 'method': 'paired_percentile_linear',
        'low': 0., 'high': 0.}
    assert result == study.primary_summary(list(reversed(rows)))
    for row in rows:
        row['arms'][study.ARM]['annotators']['A1'], row['arms'][study.ARM]['annotators']['A2'] = (
            row['arms'][study.ARM]['annotators']['A2'], row['arms'][study.ARM]['annotators']['A1'])
    assert result == study.primary_summary(rows)


def test_seed_296_and_linear_percentiles_have_fixed_owned_fixture_result():
    rows = scored_rows()
    for i, row in enumerate(rows):
        row['arms'][study.ARM]['annotators']['A1']['onset_offset_f1'] = .1 + i * i / 10000
        row['arms'][study.ARM]['annotators']['A2']['onset_offset_f1'] = .1 + i / 1000
    result = study.primary_summary(rows)
    assert result['mean_delta'] == pytest.approx(.035425, abs=1e-14)
    assert result['bootstrap']['low'] == pytest.approx(.02662584375, abs=1e-14)
    assert result['bootstrap']['high'] == pytest.approx(.04462778125, abs=1e-14)
    assert result['recordings_improved'] == 39
    assert result['recordings_worse'] == 0
    assert result['recordings_tied'] == 1
    assert result == study.primary_summary(list(reversed(rows)))


def matching_details(onset_ids, offset_ids):
    return {'onset_pairs': [{'reference_id': ref, 'prediction_id': i}
                            for i, ref in enumerate(onset_ids)],
            'offset_pairs': [[ref, i] for i, ref in enumerate(offset_ids)]}


def test_matched_reference_partitions_preserve_all_ids_for_both_baselines():
    details = {'pitch_runs': matching_details([0, 1], [0, 2]),
               study.BASE_ARM: matching_details([1, 2], [1, 2]),
               study.ARM: matching_details([2, 3], [2, 3])}
    result = study.comparison_sets(details, 5)
    assert result[study.BASE_ARM]['onset'] == {
        'retained': [2], 'gained': [3], 'lost': [1], 'neither': [0, 4]}
    assert result['pitch_runs']['onset'] == {
        'retained': [], 'gained': [2, 3], 'lost': [0, 1], 'neither': [4]}
    assert result['pitch_runs']['onset_offset'] == {
        'retained': [2], 'gained': [3], 'lost': [0], 'neither': [1, 4]}
    for baseline in result.values():
        for criterion in baseline.values():
            assert sorted(i for ids in criterion.values() for i in ids) == list(range(5))


def test_pruning_harm_descriptors_overlap_and_count_only_lost_G_matches():
    details = {study.BASE_ARM: matching_details([0, 1, 2], [0, 1, 2])}
    comparisons = {study.BASE_ARM: {'onset': {'lost': [0, 1, 2]},
                                  'onset_offset': {'lost': [0, 2]}}}
    trace = {'parents': [
        {'original': {'emitted': True, 'prediction_index': 0}, 'applied_cut_frames': [5],
         'children': [{'emitted': False, 'discard_reason': 'short'},
                      {'emitted': False, 'discard_reason': 'short'}]},
        {'original': {'emitted': True, 'prediction_index': 1}, 'applied_cut_frames': [30],
         'children': [{'emitted': False, 'discard_reason': 'short'},
                      {'emitted': True, 'discard_reason': None}]},
        {'original': {'emitted': True, 'prediction_index': 2}, 'applied_cut_frames': [],
         'children': [{'emitted': True, 'discard_reason': None}]},
        {'original': {'emitted': False, 'prediction_index': None}, 'applied_cut_frames': [70],
         'children': [{'emitted': False, 'discard_reason': 'short'}]},
    ]}
    result = study.pruning_harm(details, comparisons, trace)
    assert result['onset'] == {'lost_references': 3, 'lost_matched_parent_cut': 2,
        'lost_matched_parent_with_short_children': 2, 'lost_matched_parent_all_children_pruned': 1}
    assert result['onset_offset'] == {'lost_references': 2, 'lost_matched_parent_cut': 1,
        'lost_matched_parent_with_short_children': 1, 'lost_matched_parent_all_children_pruned': 1}


def annotation_fixture(tmp_path):
    case = 'owned_tiny'
    directory = tmp_path / case
    directory.mkdir()
    hz = 440. * 2 ** ((np.array([60.] * 5 + [61.] * 5) - 69) / 12)
    path = np.full(10, 244, dtype=np.int16)
    notes, diagnostics, trace = readout.notes_from_state_path(path, hz, .1)
    old, _ = note_state_hmm.notes_from_state_path(path, hz, .1)
    row = {'id': case, 'duration_seconds': .1, 'arms': {}, 'readout': diagnostics,
           'reference_sha256': {}}
    for arm in study.DIAGNOSTIC_ARMS:
        events = notes if arm == study.ARM else old
        target = directory / f'{arm}.json'
        save(target, [asdict(note) for note in events])
        row['arms'][arm] = {'count': len(events), 'event_sha256': digest(target), 'annotators': {}}
    for annotator, onset in (('A1', 0.), ('A2', .01)):
        target = directory / f'{annotator}.csv'
        target.write_text(f'{onset},{440. * 2 ** ((60 - 69) / 12)},{.1 - onset}\n')
        row['reference_sha256'][annotator] = digest(target)
    save(directory / 'readout-private.json', trace)
    row['readout_private_sha256'] = digest(directory / 'readout-private.json')
    return row, directory


def test_annotation_pair_ids_and_parent_details_stay_private(tmp_path):
    row, directory = annotation_fixture(tmp_path)
    study.analyze_annotations(row, tmp_path)
    private_path = directory / 'annotation-private.json'
    private = json.loads(private_path.read_text())
    assert row['annotation_private_sha256'] == digest(private_path)
    for annotator in study.ANNOTATORS:
        detail = private[annotator]
        assert detail['arms'][study.BASE_ARM]['onset_pairs'][0]['reference_id'] == 0
        assert detail['comparisons'][study.BASE_ARM]['onset_offset']['lost'] == [0]
        public = row['annotation_diagnostics'][annotator]
        assert public['comparisons'][study.BASE_ARM]['onset_offset']['lost'] == 1
        assert public['pruning_harm']['onset_offset']['lost_matched_parent_all_children_pruned'] == 1
        assert public['arms'][study.ARM]['fixed_onset_pairs']['matched'] == 0
        assert public['arms'][study.ARM]['fixed_onset_pairs']['signed_offset_seconds']['median'] is None
    rendered = json.dumps(row['annotation_diagnostics'])
    assert all(word not in rendered for word in ('reference_id', 'prediction_id',
        'onset_pairs": [', 'offset_pairs', 'onset_seconds', 'raw_positive_midi_median'))
    assert row['readout']['trace_sha256'] == fingerprint(json.loads((directory / 'readout-private.json').read_text()))


@pytest.mark.parametrize('filename', ['readout-private.json', 'A2.csv', study.ARM + '.json'])
def test_annotation_analysis_rechecks_private_trace_references_and_predictions(tmp_path, filename):
    row, directory = annotation_fixture(tmp_path)
    target = directory / filename
    target.write_bytes(target.read_bytes() + b'\n')
    with pytest.raises(ValueError, match='changed'):
        study.analyze_annotations(row, tmp_path)
    assert not (directory / 'annotation-private.json').exists()
    assert 'annotation_diagnostics' not in row


def test_empty_new_prediction_scores_zero_and_preserves_lost_reference_ids(tmp_path, monkeypatch):
    row, _ = annotation_fixture(tmp_path)

    def old_score(_package, current, _work):
        current['status'] = 'scored'

    monkeypatch.setattr(study.frozen, 'score_case', old_score)
    study.score_case(None, row, tmp_path)
    for annotator in study.ANNOTATORS:
        result = row['arms'][study.ARM]['annotators'][annotator]
        assert result['onset_f1'] == result['onset_offset_f1'] == 0.
        assert result['onset_matched'] == result['onset_offset_matched'] == 0
        assert result['onset_offset_lost_reference_ids'] == [0]
        assert result['onset_offset_gained_reference_ids'] == []
        assert result['reference_note_count'] == 1
    assert row['status'] == 'scored'


def test_finalization_does_not_open_diagnostics_for_an_incomplete_cohort(tmp_path, monkeypatch):
    report = {'cases': scored_rows()[:-1]}
    calls = []
    monkeypatch.setattr(study, 'legacy_projection', lambda *_: calls.append('legacy'))
    monkeypatch.setattr(study.prior, 'read_json', lambda *_: calls.append('annotation'))
    study.finalize_results(report, tmp_path, None, None, tmp_path / 'legacy.json')
    assert report['status'] == 'incomplete'
    assert report['all_cases_complete'] is False
    assert report['aggregate'] is None
    assert calls == []


@pytest.mark.parametrize('gate', ['legacy_failure', 'historical_mismatch'])
def test_replay_gate_failure_erases_new_aggregates_and_never_computes_primary(tmp_path, monkeypatch, gate):
    report = {'cases': scored_rows()}
    legacy = {'status': 'baseline_parity_failed' if gate == 'legacy_failure' else 'complete'}
    historical = {'all_equal': gate != 'historical_mismatch'}
    calls = []
    monkeypatch.setattr(study, 'legacy_projection', lambda *_: legacy)
    monkeypatch.setattr(study, 'historical_parity', lambda *_: historical)
    monkeypatch.setattr(study, 'primary_summary', lambda *_: calls.append('primary'))
    monkeypatch.setattr(study.prior, 'read_json', lambda *_: calls.append('annotation'))
    legacy_path = tmp_path / 'legacy.json'
    study.finalize_results(report, tmp_path, None, None, legacy_path)
    assert report['status'] == 'baseline_parity_failed'
    assert report['all_cases_complete'] is False
    assert report['aggregate'] is report['primary_result'] is report['boundary_summary'] is None
    assert report['historical_parity'] == historical
    assert report['legacy_report_sha256'] == digest(legacy_path)
    assert len(report['cases']) == 40
    assert calls == []


def test_run_failure_clears_previously_staged_complete_results_and_preserves_error(tmp_path, monkeypatch):
    archive = tmp_path / 'owned.zip'
    with zipfile.ZipFile(archive, 'w'):
        pass
    monkeypatch.setattr(study, 'SOURCE_PATHS', ())
    monkeypatch.setattr(study, 'distributions', lambda: [])
    monkeypatch.setattr(study, 'version', lambda name: study.frozen.EXPECTED_RUNTIME[name])
    monkeypatch.setattr(study.dsp, 'ARCHIVE_BYTES', archive.stat().st_size)
    monkeypatch.setattr(study.dsp, 'ARCHIVE_MD5', study.hashlib.md5(archive.read_bytes()).hexdigest())
    monkeypatch.setattr(study, 'predict_all', lambda *_: None)
    monkeypatch.setattr(study, 'evaluate_all', lambda *_: None)

    def failure(report, *_):
        report.update(status='complete', all_cases_complete=True, aggregate={'staged': True},
                      primary_result={'staged': True}, boundary_summary={'staged': True})
        raise ValueError('owned failure after staging')

    monkeypatch.setattr(study, 'finalize_results', failure)
    work, report_path = tmp_path / 'private', tmp_path / 'report.json'
    report = study.run(archive, work, report_path, None, None, tmp_path / 'legacy.json')
    assert report['status'] == 'failed'
    assert report['error_type'] == 'ValueError'
    assert report['all_cases_complete'] is False
    assert report['aggregate'] is report['primary_result'] is report['boundary_summary'] is None
    assert report['quality_approved'] is report['product_changes'] is False
    assert (work / 'error.txt').read_text() == 'owned failure after staging'
    assert study.prior.exact_equal(json.loads(report_path.read_text()), report)

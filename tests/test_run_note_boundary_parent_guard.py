"""Small contracts and archived metadata checks; no corpus inference or grid run."""
from __future__ import annotations

import json
import zipfile
from dataclasses import asdict

import numpy as np
import pytest

from scripts import note_boundary_parent_guard as guard
from scripts import note_boundary_readout as split
from scripts import note_state_hmm
from scripts import run_note_boundary_parent_guard as study
from scripts.dsp_note_probe import digest, fingerprint, save


def ready_rows(tmp_path):
    rows = []
    for case in study.CASES:
        arms = {}
        for arm in study.ARMS:
            path = tmp_path / case / f'{arm}.json'
            save(path, [])
            arms[arm] = {'count': 0, 'event_sha256': digest(path), 'annotators': {}}
        rows.append({'id': case, 'status': 'predicted', 'arms': arms})
    return rows


def scored_rows():
    metrics = {'onset_f1': .2, 'onset_offset_f1': .1,
               'onset_precision': .2, 'onset_recall': .2,
               'offset_precision': .1, 'offset_recall': .1,
               'onset_gained_reference_ids': [], 'onset_lost_reference_ids': [],
               'onset_offset_gained_reference_ids': [], 'onset_offset_lost_reference_ids': []}
    return [{'id': case, 'status': 'scored', 'arms': {
        arm: {'count': 3, 'annotators': {a: study.json_projection(metrics) for a in study.ANNOTATORS}}
        for arm in study.ARMS}} for case in study.CASES]


def archived_reports():
    with zipfile.ZipFile(study.ROOT / study.PREVIOUS) as archive:
        old = json.loads(archive.read('vocadito.json'))
    report = study.json_projection(old)
    report.update(schema='note-boundary-parent-guard-v1', planned_arms=list(study.ARMS),
                  guard_settings=study.SETTINGS,
                  primary_comparison={'candidate': study.ARM, 'baseline': study.BASE_ARM, 'metric': 'onset_offset_f1'},
                  secondary_comparison={'candidate': study.ARM, 'baseline': study.SPLIT_ARM, 'metric': 'onset_offset_f1'})
    for row in report['cases']:
        row['arms'][study.ARM] = study.json_projection(row['arms'][study.BASE_ARM])
        row.update(guard={'owned_metadata_fixture': True}, guard_private_sha256='1' * 64,
                   guard_annotation_diagnostics={'owned_metadata_fixture': True},
                   guard_annotation_private_sha256='2' * 64)
    return report, old


def test_inventory_is_480_predictions_and_unchanged_53_plus_13_sources():
    assert len(study.CASES) == 40 and len(study.ARMS) == 12
    assert study.ARMS[:-1] == study.previous_study.ARMS
    assert study.ARMS[-1] == study.ARM
    assert len(study.SOURCE_PATHS) == len(set(study.SOURCE_PATHS)) == 66
    assert study.SOURCE_PATHS[:53] == study.previous_study.SOURCE_PATHS
    assert study.SETTINGS['bootstrap_seed'] == 298
    assert study.SETTINGS['bootstrap_resamples'] == 10000


@pytest.mark.parametrize('damage', ['missing_file', 'mutated_file', 'missing_arm',
                                  'failed_last', 'duplicate_case', 'wrong_manifest', 'missing_barrier'])
def test_last_of_480_predictions_blocks_first_reference(tmp_path, monkeypatch, damage):
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
        rows[-1] = study.json_projection(rows[0])
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


def test_complete_prediction_barrier_precedes_all_scoring_calls(tmp_path, monkeypatch):
    rows = ready_rows(tmp_path)
    manifest = study.prediction_manifest(rows, tmp_path)
    report = {'cases': rows, 'all_predictions_frozen_before_references': True,
              'predictions_manifest_sha256': manifest}
    calls = []

    def score(_package, row, work):
        assert len(list(work.glob('vocadito_*/*.json'))) == 480
        calls.append(row['id'])
        row['status'] = 'scored'

    monkeypatch.setattr(study, 'score_case', score)
    study.evaluate_all(None, tmp_path, report, tmp_path / 'report.json')
    assert calls == list(study.CASES)
    assert report['reference_access_started_after_predicted_cases'] == 40
    assert report['post_evaluation_predictions_manifest_sha256'] == manifest
    assert study.prediction_manifest(list(reversed(rows)), tmp_path) == manifest


def test_prediction_opens_only_wav_and_saves_old_and_new_private_traces(tmp_path, monkeypatch):
    opened = []

    class AudioOnlyArchive:
        def read(self, member):
            assert member.startswith('Audio/') and member.endswith('.wav')
            opened.append(member)
            return b'owned-placeholder'

    monkeypatch.setattr(study, 'infer_recording', lambda _: (
        {'hz': np.zeros(1)}, {arm: [] for arm in study.ARMS}, {}, 0.,
        {'old': True}, {'parents': []}, {'new': True}, {'parents': []}))
    report = {'cases': []}
    study.predict_all(AudioOnlyArchive(), tmp_path, report, tmp_path / 'report.json')
    assert opened == [f'Audio/{case}.wav' for case in study.CASES]
    assert report['all_predictions_frozen_before_references'] is True
    for filename in ('readout-private.json', 'guard-private.json'):
        assert len(list(tmp_path.glob('vocadito_*/' + filename))) == 40
    assert not list(tmp_path.glob('vocadito_*/*.csv'))
    assert all(not arm['annotators'] for row in report['cases'] for arm in row['arms'].values())


def test_shared_G_path_readout_once_preserves_old_arrays_and_note_object(monkeypatch):
    hz = 440. * 2 ** ((np.array([60.] * 5 + [61.] * 5) - 69) / 12)
    path = np.full(10, 244, dtype=np.int16)
    arrays = {'hz': hz, study.BASE_ARM + '_path': path, 'owned_old_array': np.arange(4)}
    original, _ = note_state_hmm.notes_from_state_path(path, hz, .1)
    arms = {arm: list(original) for arm in study.previous_study.ARMS}
    old_snapshot = {arm: [asdict(note) for note in notes] for arm, notes in arms.items()}
    array_snapshot = {key: value.copy() for key, value in arrays.items()}
    calls = []

    def old_infer(audio):
        calls.append(('old', audio))
        return arrays, arms, {'old': True}, .1, {'old_diag': True}, {'old_trace': True}

    def new_readout(actual_path, actual_hz, duration, *, original_notes):
        assert actual_path is path and actual_hz is hz and duration == .1
        assert original_notes is arms[study.BASE_ARM]
        calls.append(('guard', None))
        return guard.notes_from_state_path(actual_path, actual_hz, duration, original_notes=original_notes)

    monkeypatch.setattr(study.previous_study, 'infer_recording', old_infer)
    monkeypatch.setattr(study, 'notes_from_state_path', new_readout)
    result = study.infer_recording('owned-audio')
    assert calls == [('old', 'owned-audio'), ('guard', None)]
    assert result[0] is arrays
    assert set(arrays) == set(array_snapshot)
    assert all(np.array_equal(value, array_snapshot[key]) for key, value in arrays.items())
    assert {arm: [asdict(note) for note in result[1][arm]] for arm in study.previous_study.ARMS} == old_snapshot
    assert result[1][study.ARM][0] is original[0]
    assert result[4:6] == ({'old_diag': True}, {'old_trace': True})


@pytest.mark.parametrize('damage', ['empty', 'missing_case', 'duplicate_case', 'failed_case',
                                  'missing_arm', 'extra_arm', 'missing_annotator', 'extra_annotator'])
def test_partial_cohort_has_no_aggregate_or_either_contrast(damage):
    rows = scored_rows()
    if damage == 'empty':
        rows = []
    elif damage == 'missing_case':
        rows.pop()
    elif damage == 'duplicate_case':
        rows[-1] = study.json_projection(rows[0])
    elif damage == 'failed_case':
        rows[-1]['status'] = 'evaluation_failed'
    elif damage == 'missing_arm':
        rows[-1]['arms'].pop(study.ARM)
    elif damage == 'extra_arm':
        rows[-1]['arms']['unplanned'] = {}
    elif damage == 'missing_annotator':
        rows[-1]['arms'][study.ARM]['annotators'].pop('A2')
    else:
        rows[-1]['arms'][study.ARM]['annotators']['A3'] = {}
    assert study.aggregate(rows) is None
    for baseline in study.BASELINES:
        with pytest.raises(ValueError, match='complete cohort'):
            study.contrast_summary(rows, baseline)


def test_empty_prediction_is_zero_with_both_annotators_in_macro_denominator():
    rows = scored_rows()
    rows[0]['arms'][study.ARM]['count'] = 0
    for annotator in study.ANNOTATORS:
        for metric in ('onset_f1', 'onset_offset_f1', 'onset_precision', 'onset_recall',
                       'offset_precision', 'offset_recall'):
            rows[0]['arms'][study.ARM]['annotators'][annotator][metric] = 0.
    result = study.aggregate(rows)[study.ARM]
    assert result['predicted_notes'] == 117
    assert result['onset_offset_f1']['macro'] == pytest.approx(.0975)
    assert result['onset_offset_f1']['recordings_worse'] == 1
    assert result['onset_offset_f1']['recordings_tied'] == 39


@pytest.mark.parametrize('score', [-.01, 1.01, float('nan'), float('inf')])
def test_invalid_new_F1_rejected(score):
    rows = scored_rows()
    rows[-1]['arms'][study.ARM]['annotators']['A2']['onset_offset_f1'] = score
    with pytest.raises(ValueError, match='invalid score'):
        study.aggregate(rows)


def test_projection_preserves_exact_archived_11_arm_payload_and_live_immutable_settings(tmp_path, monkeypatch):
    report, old = archived_reports()
    live = study.frozen.FACTOR_SETTINGS
    report['factor_settings'] = live
    original_settings = fingerprint(live)
    # The old private pair rows are intentionally not in the public ZIP. Only
    # that unchanged pooling dependency is supplied from its archived metadata;
    # real old aggregation, primary bootstrap and both older parity gates run.
    monkeypatch.setattr(study.previous_study.prior, 'read_json',
                        lambda _: {a: {'annotator': a} for a in study.ANNOTATORS})

    def archived_pool(rows):
        if len(rows) == 80:
            return study.json_projection(old['boundary_summary']['pooled_annotation_judgments'])
        assert len(rows) == 40 and len({row['annotator'] for row in rows}) == 1
        return study.json_projection(old['boundary_summary']['by_annotator'][rows[0]['annotator']])

    monkeypatch.setattr(study.previous_study, 'summarize_annotations', archived_pool)
    factor_path = tmp_path / 'factor.json'
    result = study.legacy_projection(
        report, tmp_path, study.ROOT / 'docs/research/receipts/dsp-note-baseline-42989661618.zip',
        study.ROOT / study.frozen.HMM_RECEIPT, factor_path)
    assert result['status'] == 'complete'
    assert study.parity.exact_equal(result['cases'], old['cases'])
    assert set(result) == set(old)
    assert all(study.parity.exact_equal(result[key], old[key])
               for key in old.keys() - study.LEGACY_VOLATILE - {'cases'})
    assert type(result['factor_settings']) is dict
    assert type(result['factor_settings']['factor_configs'][study.BASE_ARM]) is dict
    assert report['factor_settings'] is live and fingerprint(live) == original_settings
    assert result['legacy_report_sha256'] == digest(factor_path)
    assert study.historical_parity(report, result)['all_equal'] is True
    result['cases'][0]['readout']['owned_change'] = True
    assert 'owned_change' not in report['cases'][0]['readout']


@pytest.mark.parametrize('damage', [None, 'event', 'array', 'array_dtype', 'score', 'reference',
                                  'readout', 'annotation', 'source', 'barrier', 'integer_type', 'extra_field'])
def test_archived_440_events_440_arrays_53_sources_and_metrics_are_an_exact_gate(damage):
    report, legacy = archived_reports()
    row = legacy['cases'][-1]
    if damage == 'event':
        row['arms'][study.SPLIT_ARM]['event_sha256'] = '0' * 64
    elif damage == 'array':
        row['observations'][study.BASE_ARM + '_path']['sha256'] = '0' * 64
    elif damage == 'array_dtype':
        row['observations']['hz']['dtype'] = '<f4'
    elif damage == 'score':
        row['arms'][study.SPLIT_ARM]['annotators']['A2']['onset_offset_f1'] += .001
    elif damage == 'reference':
        row['reference_sha256']['A2'] = '0' * 64
    elif damage == 'readout':
        row['readout']['applied_cut_count'] += 1
    elif damage == 'annotation':
        row['annotation_private_sha256'] = '0' * 64
    elif damage == 'source':
        report['source_sha256']['scripts/note_boundary_readout.py'] = '0' * 64
    elif damage == 'barrier':
        legacy['all_predictions_frozen_before_references'] = False
    elif damage == 'integer_type':
        row['arms'][study.SPLIT_ARM]['count'] = float(row['arms'][study.SPLIT_ARM]['count'])
    elif damage == 'extra_field':
        row['undeclared'] = True
    result = study.historical_parity(report, legacy)
    assert result['all_equal'] is (damage is None)
    assert result['compared_prediction_files'] == result['compared_observation_arrays'] == 440
    assert len(result['source_checks']) == 53


def test_new_aggregate_preserves_every_old_arm_metric():
    report, old = archived_reports()
    actual = study.aggregate(report['cases'])
    assert study.parity.exact_equal({arm: actual[arm] for arm in study.previous_study.ARMS}, old['aggregate'])


def test_two_seed_298_contrasts_pair_annotations_within_recording_and_ignore_row_order():
    rows = scored_rows()
    for row in rows:
        row['arms'][study.ARM]['annotators']['A1']['onset_offset_f1'] = .2
        row['arms'][study.ARM]['annotators']['A2']['onset_offset_f1'] = 0.
        for annotator in study.ANNOTATORS:
            row['arms'][study.SPLIT_ARM]['annotators'][annotator]['onset_offset_f1'] = .05
    primary = study.contrast_summary(rows, study.BASE_ARM)
    assert primary['mean_delta'] == primary['bootstrap']['low'] == primary['bootstrap']['high'] == 0.
    assert primary['recordings_tied'] == 40
    secondary = study.contrast_summary(rows, study.SPLIT_ARM)
    assert secondary['mean_delta'] == pytest.approx(.05)
    for baseline, result in zip(study.BASELINES, (primary, secondary), strict=True):
        assert result['bootstrap']['seed'] == 298
        assert result['bootstrap']['resampling_unit'] == 'recording_mean_of_A1_A2'
        assert result == study.contrast_summary(list(reversed(rows)), baseline)
    for row in rows:
        annotations = row['arms'][study.ARM]['annotators']
        annotations['A1'], annotations['A2'] = annotations['A2'], annotations['A1']
    assert primary == study.contrast_summary(rows, study.BASE_ARM)


def test_seed_298_linear_quantiles_have_fixed_owned_fixture_values():
    rows = scored_rows()
    for index, row in enumerate(rows):
        row['arms'][study.ARM]['annotators']['A1']['onset_offset_f1'] = .1 + index * index / 10000
        row['arms'][study.ARM]['annotators']['A2']['onset_offset_f1'] = .1 + index / 1000
    result = study.contrast_summary(rows, study.BASE_ARM)
    assert result['mean_delta'] == pytest.approx(.035425, abs=1e-14)
    assert result['bootstrap']['low'] == pytest.approx(.0266635, abs=1e-14)
    assert result['bootstrap']['high'] == pytest.approx(.04451903125, abs=1e-14)
    assert result['recordings_improved'] == 39 and result['recordings_tied'] == 1


def matching_details(pairs):
    return {'onset_pairs': [{'reference_id': reference, 'prediction_id': prediction}
                            for reference, prediction in pairs], 'offset_pairs': [list(pair) for pair in pairs]}


def test_reference_partitions_for_G_and_split_preserve_denominator():
    details = {study.BASE_ARM: matching_details([(0, 0), (1, 1)]),
               study.SPLIT_ARM: matching_details([(1, 0), (2, 1)]),
               study.ARM: matching_details([(2, 0), (3, 1)])}
    result = study.comparison_sets(details, 5)
    assert result[study.BASE_ARM]['onset'] == {
        'retained': [], 'gained': [2, 3], 'lost': [0, 1], 'neither': [4]}
    assert result[study.SPLIT_ARM]['onset_offset'] == {
        'retained': [2], 'gained': [3], 'lost': [1], 'neither': [0, 4]}
    for baseline in result.values():
        for criterion in baseline.values():
            assert sorted(index for indices in criterion.values() for index in indices) == list(range(5))


def test_private_harm_links_use_original_or_split_child_indices_and_overlap():
    pitches = [60] * 5 + [61] * 5 + [None] + [60] * 10 + [61] * 5 + [62] * 10 + [None] + [60] * 10 + [61] * 10
    hz = np.array([0. if pitch is None else 440. * 2 ** ((pitch - 69) / 12) for pitch in pitches])
    path = np.array([245 if pitch is None else 244 for pitch in pitches], dtype=np.int16)
    _, _, trace = guard.notes_from_state_path(path, hz, len(hz) * .01)
    _, _, split_trace = split.notes_from_state_path(path, hz, len(hz) * .01)
    assert [parent['decision'] for parent in trace['parents']] == ['rejected', 'rejected', 'accepted']
    details = {study.BASE_ARM: matching_details([(0, 0), (1, 1), (2, 2)]),
               study.SPLIT_ARM: matching_details([(1, 0), (3, 2)]), study.ARM: matching_details([])}
    comparisons = study.comparison_sets(details, 5)
    result = study.parental_harm(details, comparisons, trace, split_trace)
    primary = result[study.BASE_ARM]['onset_offset']
    assert {key: primary[key] for key in study.HARM_KEYS} == {
        'lost_references': 3, 'lost_matched_parent_proposed_cut': 3,
        'lost_matched_parent_accepted': 1, 'lost_matched_parent_rejected': 2,
        'lost_matched_parent_with_proposed_short_children': 2,
        'lost_matched_parent_all_proposed_children_fail': 1, 'lost_matched_parent_final_empty': 0}
    secondary = result[study.SPLIT_ARM]['onset_offset']
    assert secondary['lost_matched_parent_accepted'] == secondary['lost_matched_parent_rejected'] == 1
    assert [item['parent_id'] for item in secondary['lost_reference_parents']] == [1, 2]
    assert secondary['lost_matched_parent_all_proposed_children_fail'] == 0


def annotation_fixture(tmp_path):
    directory = tmp_path / 'owned_tiny'
    directory.mkdir()
    hz = 440. * 2 ** ((np.array([60.] * 5 + [61.] * 5) - 69) / 12)
    path = np.full(10, 244, dtype=np.int16)
    original, _ = note_state_hmm.notes_from_state_path(path, hz, .1)
    split_notes, split_diag, split_trace = split.notes_from_state_path(path, hz, .1)
    guard_notes, guard_diag, guard_trace = guard.notes_from_state_path(path, hz, .1, original_notes=original)
    row = {'id': 'owned_tiny', 'duration_seconds': .1, 'arms': {},
           'readout': split_diag, 'guard': guard_diag, 'reference_sha256': {}}
    for arm in study.DIAGNOSTIC_ARMS:
        events = split_notes if arm == study.SPLIT_ARM else guard_notes if arm == study.ARM else original
        target = directory / f'{arm}.json'
        save(target, [asdict(note) for note in events])
        row['arms'][arm] = {'count': len(events), 'event_sha256': digest(target), 'annotators': {}}
    for annotator, onset in (('A1', 0.), ('A2', .01)):
        target = directory / f'{annotator}.csv'
        target.write_text(f'{onset},{440. * 2 ** ((60 - 69) / 12)},{.1 - onset}\n')
        row['reference_sha256'][annotator] = digest(target)
    for filename, key, trace in (('readout-private.json', 'readout_private_sha256', split_trace),
                                 ('guard-private.json', 'guard_private_sha256', guard_trace)):
        save(directory / filename, trace)
        row[key] = digest(directory / filename)
    study.previous_study.analyze_annotations(row, tmp_path)
    return row, directory


def test_guard_annotation_details_stay_private_and_old_annotation_bytes_unchanged(tmp_path):
    row, directory = annotation_fixture(tmp_path)
    original_fields = study.json_projection(row)
    old_bytes = (directory / 'annotation-private.json').read_bytes()
    study.analyze_annotations(row, tmp_path)
    assert all(study.parity.exact_equal(row[key], value) for key, value in original_fields.items())
    assert (directory / 'annotation-private.json').read_bytes() == old_bytes
    private = json.loads((directory / 'guard-annotation-private.json').read_text())
    assert row['guard_annotation_private_sha256'] == digest(directory / 'guard-annotation-private.json')
    for annotator in study.ANNOTATORS:
        detail, public = private[annotator], row['guard_annotation_diagnostics'][annotator]
        assert detail['comparisons'][study.BASE_ARM]['onset_offset']['retained'] == [0]
        assert detail['comparisons'][study.SPLIT_ARM]['onset_offset']['gained'] == [0]
        assert public['comparisons'][study.BASE_ARM]['onset_offset']['retained'] == 1
        assert public['comparisons'][study.SPLIT_ARM]['onset_offset']['gained'] == 1
        assert public['arms'][study.ARM]['fixed_onset_pairs']['matched'] == 1
    public_text = json.dumps(row['guard_annotation_diagnostics'])
    assert all(f'"{key}"' not in public_text for key in (
        'reference_id', 'prediction_id', 'parent_id', 'lost_reference_parents',
        'onset_seconds', 'offset_seconds', 'proposed_cut_frames'))


@pytest.mark.parametrize('filename', ['guard-private.json', 'readout-private.json', 'annotation-private.json',
                                    'A2.csv', study.ARM + '.json', study.SPLIT_ARM + '.json'])
def test_guard_annotation_rechecks_all_private_dependencies(tmp_path, filename):
    row, directory = annotation_fixture(tmp_path)
    target = directory / filename
    target.write_bytes(target.read_bytes() + b'\n')
    with pytest.raises(ValueError, match='changed'):
        study.analyze_annotations(row, tmp_path)
    assert not (directory / 'guard-annotation-private.json').exists()


def test_new_scoring_keeps_old_metrics_and_uses_the_frozen_matching_rules(tmp_path, monkeypatch):
    row, _ = annotation_fixture(tmp_path)
    old_arms = study.json_projection({arm: data for arm, data in row['arms'].items() if arm != study.ARM})
    monkeypatch.setattr(study.previous_study, 'score_case', lambda *_: None)
    study.score_case(None, row, tmp_path)
    assert {arm: row['arms'][arm] for arm in old_arms} == old_arms
    assert row['status'] == 'scored'
    for annotator in study.ANNOTATORS:
        metrics = row['arms'][study.ARM]['annotators'][annotator]
        assert metrics['onset_f1'] == metrics['onset_offset_f1'] == 1.
        assert metrics['onset_offset_matched'] == metrics['reference_note_count'] == 1
        assert metrics['onset_offset_gained_reference_ids'] == metrics['onset_offset_lost_reference_ids'] == []


def test_incomplete_finalization_never_reads_diagnostics_or_produces_partial_results(tmp_path, monkeypatch):
    report = {'cases': scored_rows()[:-1], 'primary_result': {'stale': True}, 'secondary_result': {'stale': True}}
    monkeypatch.setattr(study, 'legacy_projection', lambda *_: pytest.fail('must not project incomplete cohort'))
    study.finalize_results(report, tmp_path, None, None, tmp_path / 'old.json', tmp_path / 'factor.json')
    assert report['status'] == 'incomplete' and report['all_cases_complete'] is False
    assert all(report[key] is None for key in ('aggregate', 'primary_result', 'secondary_result', 'boundary_summary'))


@pytest.mark.parametrize('gate', ['legacy_failure', 'historical_mismatch'])
def test_legacy_failure_clears_both_contrasts_and_new_metrics(tmp_path, monkeypatch, gate):
    report = {'cases': scored_rows()}
    factor_path = tmp_path / 'factor.json'

    def legacy(*_):
        save(factor_path, {'status': 'owned_factor_fixture'})
        return {'status': 'baseline_parity_failed' if gate == 'legacy_failure' else 'complete'}

    monkeypatch.setattr(study, 'legacy_projection', legacy)
    monkeypatch.setattr(study, 'historical_parity', lambda *_: {'all_equal': gate != 'historical_mismatch'})
    monkeypatch.setattr(study, 'contrast_summary', lambda *_: pytest.fail('must not accept failed parity'))
    legacy_path = tmp_path / 'old.json'
    study.finalize_results(report, tmp_path, None, None, legacy_path, factor_path)
    assert report['status'] == 'baseline_parity_failed' and report['all_cases_complete'] is False
    assert all(report[key] is None for key in ('aggregate', 'primary_result', 'secondary_result', 'boundary_summary'))
    assert report['legacy_report_sha256'] == digest(legacy_path)
    assert report['legacy_factor_report_sha256'] == digest(factor_path)


def test_run_failure_preserves_error_and_clears_staged_results(tmp_path, monkeypatch):
    archive = tmp_path / 'owned.zip'
    with zipfile.ZipFile(archive, 'w'):
        pass
    monkeypatch.setattr(study, 'SOURCE_PATHS', ())
    monkeypatch.setattr(study, 'distributions', lambda: [])
    monkeypatch.setattr(study, 'version', lambda key: study.frozen.EXPECTED_RUNTIME[key])
    monkeypatch.setattr(study.dsp, 'ARCHIVE_BYTES', archive.stat().st_size)
    monkeypatch.setattr(study.dsp, 'ARCHIVE_MD5', study.hashlib.md5(archive.read_bytes()).hexdigest())
    monkeypatch.setattr(study, 'predict_all', lambda *_: None)
    monkeypatch.setattr(study, 'evaluate_all', lambda *_: None)

    def failure(report, *_):
        assert report['elapsed_seconds'] >= 0 and report['peak_rss_kib'] > 0
        report.update(status='complete', all_cases_complete=True, aggregate={'staged': True},
                      primary_result={'staged': True}, secondary_result={'staged': True}, boundary_summary={'staged': True})
        raise ValueError('owned finalization failure')

    monkeypatch.setattr(study, 'finalize_results', failure)
    work, report_path = tmp_path / 'private', tmp_path / 'report.json'
    report = study.run(archive, work, report_path, None, None, tmp_path / 'old.json', tmp_path / 'factor.json')
    assert report['status'] == 'failed' and report['error_type'] == 'ValueError'
    assert report['all_cases_complete'] is False
    assert all(report[key] is None for key in ('aggregate', 'primary_result', 'secondary_result', 'boundary_summary'))
    assert (work / 'error.txt').read_text() == 'owned finalization failure'
    assert study.parity.exact_equal(json.loads(report_path.read_text()), report)

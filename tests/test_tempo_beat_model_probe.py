"""Leakage, provenance and tempo-conversion contracts, not musical accuracy."""
from __future__ import annotations

import inspect

import numpy as np
import pytest

from scripts.tempo_beat_model_probe import (
    PRIMARY_METHODS,
    admitted_fold,
    annotation_key,
    bounded_download,
    bpm_from_beats,
    git_blob_hash,
    parse_folds,
    summarize,
    verify_checkpoint_metadata,
)


def test_split_is_content_verified():
    raw = b'drummer1_session1_1_test_4-4\t3\n'
    mapping = parse_folds(raw, git_blob_hash(raw))
    assert admitted_fold('drummer1/session1/1_test_4-4.wav', mapping) == 3
    with pytest.raises(ValueError):
        parse_folds(raw, 'wrong')


def test_unmapped_is_not_automatically_assumed_unseen():
    assert admitted_fold('drummer1/session1/99_other.wav', {}) is None


@pytest.mark.parametrize('bad', [b'a\t8\n', b'a\t3\na\t4\n', b'a\tb\n', b''])
def test_invalid_fold_file_rejected(bad):
    with pytest.raises(ValueError):
        parse_folds(bad, expected_blob=None)


@pytest.mark.parametrize('path', ['../recording.wav', '/file.wav', 'a\\b.wav', 'a.mid'])
def test_reference_name_is_exact_and_safe(path):
    with pytest.raises(ValueError):
        annotation_key(path)


def test_checkpoint_requires_matching_excluded_fold():
    checkpoint = {'state_dict': {'x': 1}, 'datamodule_hyper_parameters': {'fold': 3, 'no_val': False}}
    assert verify_checkpoint_metadata(checkpoint, 3)['file_excluded_from_training_by_published_split']
    with pytest.raises(ValueError):
        verify_checkpoint_metadata(checkpoint, 4)
    checkpoint['datamodule_hyper_parameters']['no_val'] = True
    with pytest.raises(ValueError):
        verify_checkpoint_metadata(checkpoint, 3)
    del checkpoint['datamodule_hyper_parameters']['no_val']
    with pytest.raises(ValueError):
        verify_checkpoint_metadata(checkpoint, 3)


def test_no_bpm_truth_meter_or_downbeat_interface():
    assert set(inspect.signature(bpm_from_beats).parameters) == {'beats', 'duration'}


def test_beats_convert_to_bpm_without_octave_folding():
    original = np.arange(.2, 8, .5)
    before = original.copy()
    result = bpm_from_beats(original, 8)
    assert result['bpm'] == pytest.approx(120)
    assert result['automatic_half_double_folding'] is False
    assert np.array_equal(original, before)
    assert bpm_from_beats(np.arange(.2, 8, 1.), 8)['bpm'] == pytest.approx(60)
    assert bpm_from_beats(np.arange(.2, 8, .25), 8)['bpm'] == pytest.approx(240)


def test_shift_does_not_affect_tempo():
    a = bpm_from_beats([.1, .6, 1.1, 1.6, 2.1, 2.6, 3.1, 3.6], 4)
    b = bpm_from_beats([.3, .8, 1.3, 1.8, 2.3, 2.8, 3.3, 3.8], 4)
    assert a['bpm'] == pytest.approx(b['bpm'])


@pytest.mark.parametrize('values', [[0, 0, 1, 2], [0, 2, 1, 3], [-1, 0, 1, 2], [0, 1, 2, 5], [0, 1, 2, float('nan')]])
def test_bad_model_output_is_not_silently_repaired(values):
    with pytest.raises(ValueError):
        bpm_from_beats(values, 4)


def test_sparse_outputs_abstain_not_default120():
    assert bpm_from_beats([], 12)['bpm'] is None
    assert bpm_from_beats([.1, .6, 1.1], 12)['status'] == 'insufficient_predicted_beats'


def test_unapproved_downloads_never_touch_network(tmp_path):
    with pytest.raises(ValueError):
        bounded_download('https://elsewhere.example/model.ckpt', tmp_path / 'm', 10)


def test_summary_keeps_nonadmitted_in_denominator():
    row = {'id': 'a', 'cohort': 'previous', 'fold_verified': False, 'methods': {
        name: {'evaluation': {'alias': 'unavailable' if name == 'beat_this_cv' else 'nominal'}}
        for name in PRIMARY_METHODS}}
    result = summarize([row], ['a'])
    assert result['all_planned']['methods']['beat_this_cv']['unavailable'] == 1
    assert result['all_planned']['methods']['beat_this_cv']['correct_all_planned'] == 0
    assert result['fold_verified']['methods']['beat_this_cv']['correct_all_planned'] is None
    assert result['all_planned']['paired_model_vs_baseline']['hit_mean8']['paired_available'] == 0
    with pytest.raises(ValueError):
        summarize([row], ['a', 'b'])

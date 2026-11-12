"""Boundary and intervention contracts; no source-recording accuracy claims."""
from __future__ import annotations

import copy
from dataclasses import replace

import numpy as np
import pytest

from scripts.audio_gate_attribution import (
    ARMS,
    OPERATIONS,
    classify_edit,
    make_attribution_arms,
    rms_envelope,
)
from scripts.audio_gate_rest import apply_gate, gate_levels
from scripts.audio_gate_rest import rms_envelope as archived_rms_envelope
from scripts.vocal_recovery import Event, event_digest


@pytest.mark.parametrize('sr', [8000, 16000, 22050, 44100])
@pytest.mark.parametrize('centiseconds', [7, 14, 28, 56, 112, 224])
def test_hop_boundary_never_creates_zero_width_cell(sr, centiseconds):
    samples = np.full(round(sr * centiseconds / 100), .1)
    edges, levels = rms_envelope(samples, sr)
    expected_count = (len(samples) * 100 + sr - 1) // sr
    assert len(levels) == expected_count
    assert edges[0] == 0 and edges[-1] == len(samples) / sr
    assert np.all(np.diff(edges) > 0)
    assert np.isfinite(levels).all()
    quiet, _ = gate_levels(levels, 'relative')
    note = Event(60, 0., len(samples) / sr)
    arms = make_attribution_arms([note], edges, quiet)
    assert all(output == [note] for output, _ in arms.values())


def test_seventy_millisecond_regression_reproduces_old_failure():
    samples = np.full(1120, .1)
    old_edges, old_levels = archived_rms_envelope(samples, 16000)
    quiet, _ = gate_levels(old_levels, 'relative')
    assert old_edges[-2] == old_edges[-1]
    with pytest.raises(ValueError, match='invalid frame timeline'):
        apply_gate([Event(60, 0., .07)], old_edges, quiet, 'soft')
    new_edges, new_levels = rms_envelope(samples, 16000)
    assert len(new_levels) == 7
    assert len(new_edges) == 8


@pytest.mark.parametrize('sr', [8000, 16000, 22050, 44100])
@pytest.mark.parametrize('delta,expected', [(-1, 14), (0, 14), (1, 15)])
def test_single_sample_either_side_of_exact_hop(sr, delta, expected):
    samples = np.full(sr * 14 // 100 + delta, .1)
    edges, levels = rms_envelope(samples, sr)
    assert len(levels) == expected
    assert edges[-1] == len(samples) / sr
    assert np.all(np.diff(edges) > 0)


@pytest.mark.parametrize('sr', [8000, 22050, 44100])
def test_one_sample_audio_has_one_positive_cell(sr):
    edges, levels = rms_envelope([.1], sr)
    assert np.array_equal(edges, [0., 1 / sr])
    assert len(levels) == 1
    assert levels[0] == pytest.approx(-20.)


@pytest.mark.parametrize('sr', [8000, 16000, 22050, 44100])
@pytest.mark.parametrize('channels', [1, 2])
def test_nondegenerate_historical_rms_is_bit_identical(sr, channels):
    rng = np.random.default_rng(36)
    for length in (sr, sr + 11, 2 * sr - 17):
        shape = (length,) if channels == 1 else (length, channels)
        samples = rng.normal(0., .04, size=shape)
        old_edges, old_levels = archived_rms_envelope(samples, sr)
        assert np.all(np.diff(old_edges) > 0)
        edges, levels = rms_envelope(samples, sr)
        assert np.array_equal(edges, old_edges)
        assert np.array_equal(levels, old_levels)
        for mode in ('absolute', 'relative'):
            assert np.array_equal(gate_levels(levels, mode)[0],
                                  gate_levels(old_levels, mode)[0])


@pytest.mark.parametrize('gain', [-12, 12])
def test_fixed_relative_gate_retains_gain_invariance_at_repaired_length(gain):
    samples = np.zeros(4480)
    samples[800:2400] = .1 * np.sin(np.arange(1600) * .1)
    edges, levels = rms_envelope(samples, 16000)
    scaled_edges, scaled_levels = rms_envelope(samples * 10 ** (gain / 20), 16000)
    assert np.array_equal(edges, scaled_edges)
    assert np.array_equal(gate_levels(levels, 'relative')[0],
                          gate_levels(scaled_levels, 'relative')[0])


def test_stereo_opposite_polarity_uses_power_average():
    samples = np.full((1120, 2), .1)
    samples[:, 1] *= -1
    _, levels = rms_envelope(samples, 16000)
    assert np.allclose(levels, -20., atol=1e-8)


@pytest.mark.parametrize('samples,sr', [
    ([], 16000), ([np.nan], 16000), ([np.inf], 16000),
    (np.ones((10, 0)), 16000), (np.ones((10, 9)), 16000),
    (np.ones((10, 2, 2)), 16000), (1., 16000),
    (np.ones(100), 0), (np.ones(100), 7999), (np.ones(100), 16000.),
])
def test_waveform_validation_matches_archive(samples, sr):
    for function in (archived_rms_envelope, rms_envelope):
        with pytest.raises(ValueError):
            function(samples, sr)


@pytest.mark.parametrize('edges,quiet', [
    ([0., 0., 1.], [True, True]), ([0., 1.], []),
    ([0., np.nan], [True]), ([1., 0.], [True]),
    ([0., 1.], [[True]]), ([0.], np.array([], dtype=bool)),
    ([[0., 1.]], [True]), ([0., 1.], [np.nan]),
    ([0., 1.], [2]), ([0., 1.], ['false']),
])
def test_invalid_frame_timeline_rejected_even_with_no_notes(edges, quiet):
    with pytest.raises(ValueError):
        make_attribution_arms([], edges, quiet)


def _mixed_example():
    edges = np.arange(501) / 100
    quiet = np.zeros(500, dtype=bool)
    quiet[70:100] = True
    quiet[100:130] = True
    quiet[200:300] = True
    quiet[340:370] = True
    notes = [Event(60, 0., 1., channel=1, program=40),
             Event(61, 1., 2., channel=2, program=41),
             Event(62, 2., 3.), Event(63, 3., 4.), Event(64, 4., 5.)]
    return notes, edges, quiet


def test_partition_tail_start_delete_split_and_unchanged():
    notes, edges, quiet = _mixed_example()
    arms = make_attribution_arms(notes, edges, quiet)
    assert tuple(arms) == ARMS
    full, diagnostic = arms['relative_soft']
    assert [(n.pitch, n.onset, n.offset) for n in full] == [
        (60, 0., .7), (61, 1.3, 2.), (63, 3., 3.4),
        (63, 3.7, 4.), (64, 4., 5.),
    ]
    assert diagnostic['operation_counts'] == dict.fromkeys(OPERATIONS, 1)
    assert diagnostic['selected_parent_indices'] == [0, 1, 2, 3]
    assert diagnostic['changed_parents'] == 4
    assert diagnostic['deleted'] == 1
    assert diagnostic['split_parents'] == 1
    assert diagnostic['extra_fragments'] == 1
    assert diagnostic['removed_seconds'] == pytest.approx(1.9)
    assert arms['tail_only'][0] == [replace(notes[0], offset=.7), *notes[1:]]
    assert arms['tail_only'][1]['selected_parent_indices'] == [0]
    assert arms['non_tail_only'][0] == [notes[0], *full[1:]]
    assert arms['non_tail_only'][1]['selected_parent_indices'] == [1, 2, 3]
    assert arms['raw'][0] == notes
    assert arms['raw'][1]['selected_parent_indices'] == []


def test_full_arm_is_exact_archived_soft_output_with_identical_counters():
    notes, edges, quiet = _mixed_example()
    expected, archived_diagnostic = apply_gate(notes, edges, quiet, 'soft')
    actual, diagnostic = make_attribution_arms(notes, edges, quiet)['relative_soft']
    assert actual == expected
    assert event_digest(actual) == event_digest(expected)
    assert {key: diagnostic[key] for key in archived_diagnostic} == archived_diagnostic


def test_complementary_interventions_are_disjoint_and_recombine_exactly():
    notes, edges, quiet = _mixed_example()
    arms = make_attribution_arms(notes, edges, quiet)
    tail = set(arms['tail_only'][1]['selected_parent_indices'])
    other = set(arms['non_tail_only'][1]['selected_parent_indices'])
    assert not tail & other
    assert tail | other == set(arms['relative_soft'][1]['selected_parent_indices'])
    recombined = []
    for i, parent in enumerate(notes):
        individual = make_attribution_arms([parent], edges, quiet)
        chosen = 'tail_only' if i in tail else 'non_tail_only'
        recombined.extend(individual[chosen][0])
    assert recombined == arms['relative_soft'][0]


def test_tail_arm_preserves_parent_count_order_onsets_and_identity():
    notes, edges, quiet = _mixed_example()
    notes = [notes[3], notes[0], notes[4], notes[1], notes[2]]
    before = copy.deepcopy(notes)
    original_hash = event_digest(notes)
    tail, _ = make_attribution_arms(notes, edges, quiet)['tail_only']
    assert len(tail) == len(notes)
    assert all(replace(child, offset=parent.offset) == parent
               for parent, child in zip(notes, tail))
    assert all(child.offset <= parent.offset for parent, child in zip(notes, tail))
    assert notes == before and event_digest(notes) == original_hash


def test_absent_evidence_is_identity_for_every_arm():
    notes = [Event(62, .4, .8), Event(60, .1, .2)]
    arms = make_attribution_arms(notes, np.arange(101) / 100, np.zeros(100, bool))
    for output, diagnostic in arms.values():
        assert output == notes
        assert diagnostic['operation_counts']['unchanged'] == len(notes)
        assert diagnostic['changed_parents'] == 0
        assert diagnostic['removed_seconds'] == 0.
        assert diagnostic['selected_parent_indices'] == []


def test_drums_and_notes_beyond_observed_audio_remain_unchanged():
    notes = [Event(60, .1, .9, is_drum=True), Event(62, .5, 1.2)]
    arms = make_attribution_arms(notes, np.arange(101) / 100, np.ones(100, bool))
    for output, diagnostic in arms.values():
        assert output == notes
        assert diagnostic['out_of_audio_unchanged'] == 2
        assert diagnostic['changed_parents'] == 0


def test_soft_rejection_is_not_reoptimized_for_tail_arm():
    note = Event(60, 0., 1.)
    quiet = np.zeros(100, bool)
    quiet[94:] = True
    edges = np.arange(101) / 100
    assert apply_gate([note], edges, quiet, 'hard')[0] != [note]
    for output, diagnostic in make_attribution_arms([note], edges, quiet).values():
        assert output == [note]
        assert diagnostic['changed_parents'] == 0


def test_single_fragment_with_both_boundaries_changed_is_not_tail_only():
    note = Event(60, 0., 1.)
    quiet = np.zeros(100, bool)
    quiet[:20] = True
    quiet[80:] = True
    arms = make_attribution_arms([note], np.arange(101) / 100, quiet)
    assert arms['relative_soft'][0] == [replace(note, onset=.2, offset=.8)]
    assert arms['relative_soft'][1]['operation_counts']['onset_trim'] == 1
    assert arms['tail_only'][0] == [note]
    assert arms['non_tail_only'][0] == arms['relative_soft'][0]


@pytest.mark.parametrize('children', [
    [Event(61, 0., .5)], [Event(60, 0., .5, channel=1)],
    [Event(60, -.1, .5)], [Event(60, 0., 1.1)],
    [Event(60, 0., .7), Event(60, .6, .9)],
])
def test_classification_rejects_changed_identity_extension_or_overlap(children):
    with pytest.raises(ValueError):
        classify_edit(Event(60, 0., 1.), children)


def test_empty_predictions_are_complete_zero_count_arms():
    arms = make_attribution_arms([], [0., 1.], [True])
    assert set(arms) == set(ARMS)
    for output, diagnostic in arms.values():
        assert output == []
        assert diagnostic['output_count'] == 0
        assert all(value == 0 for value in diagnostic['operation_counts'].values())

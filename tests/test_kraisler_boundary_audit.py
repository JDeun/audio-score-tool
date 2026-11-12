"""Constructed waveform, annotation-context and cohort-conservation contracts."""
from __future__ import annotations

import copy
import hashlib
import json
from fractions import Fraction
from types import SimpleNamespace

import numpy as np
import pytest

from scripts import kraisler_boundary_audit as subject
from scripts.audio_gate_attribution import rms_envelope
from scripts.audio_gate_rest import gate_levels
from scripts.kraisler_correspondence import Reference
from scripts.kraisler_rest_acoustics import RegionIntervals
from scripts.kraisler_score import parse_score
from scripts.kraisler_waveform_features import extract_features
from scripts.run_kraisler_alignment import _encoded


def source_signal(*, end=.6, tail=0., duration=.8):
    time = np.arange(round(duration * 44100)) / 44100
    signal = .2 * np.sin(2 * np.pi * 440 * time)
    signal[time < .2] = 0.
    signal[time >= end] *= tail
    return signal


def probe(signal, refs, index, kind):
    bank = extract_features(signal, 44100)
    edges, levels = rms_envelope(signal, 44100)
    quiet, _ = gate_levels(levels, 'relative')
    return subject.probe_boundary(bank, edges, quiet, refs, index, kind)


def test_zero_after_release_is_counted_without_fabricated_log_delta():
    row = probe(source_signal(), [Reference(.2, .6, 69)], 0, 'offset')
    assert row['spectral_availability'] == 'both'
    assert row['before']['spectrum']['mean_target_band_power'] > 0
    assert row['after']['spectrum']['mean_total_band_power'] == 0
    assert row['metrics']['target_change_db'] is None
    summary = subject.summarize_probes([row])
    for band in ('target', 'total'):
        assert summary['energy_transition_counts'][band]['before_positive_after_zero'] == 1
    assert summary['statistics']['target_change_db']['count'] == 0
    assert summary['statistics']['target_change_db']['undefined'] == 1


def test_nonzero_tail_and_midpoint_have_different_fixed_descriptors():
    signal = source_signal(tail=.01)
    refs = [Reference(.2, .6, 69)]
    end = probe(signal, refs, 0, 'offset')
    middle = probe(signal, refs, 0, 'midpoint')
    assert end['metrics']['target_change_db'] == pytest.approx(-40., abs=.01)
    assert middle['metrics']['target_change_db'] == pytest.approx(0., abs=.01)
    assert end['after']['spectrum']['mean_target_band_power'] > 0
    assert end['after']['gate']['quiet_fraction'] == pytest.approx(1.)
    assert end['context']['category'] == 'isolated_annotation_context'
    assert middle['context']['own_note_covers_expected_sides']


def test_same_pitch_reattack_annotation_does_not_invent_an_acoustic_release():
    signal = source_signal(tail=1.)
    refs = [Reference(.2, .4, 69), Reference(.4, .7, 69)]
    row = probe(signal, refs, 0, 'offset')
    assert row['context']['category'] == 'same_pitch_neighbor'
    assert row['context']['window_annotation_coverage']['after']['other_same_pitch_s'] == pytest.approx(.08)
    assert row['metrics']['target_change_db'] == pytest.approx(0., abs=.01)
    assert not row['context']['independent_acoustic_isolation_verified']


def test_context_priority_and_overlapping_annotations_are_union_counted():
    refs = [Reference(.2, .6, 69), Reference(.6, .8, 69),
            Reference(.55, .8, 70), Reference(.58, .9, 70)]
    _, _, context = subject.annotation_context(refs, 0, 'offset')
    assert context['category'] == 'same_pitch_neighbor'
    assert context['same_pitch_neighbor'] and context['other_pitch_neighbor']
    after = context['window_annotation_coverage']['after']
    assert after['other_pitch_s'] == pytest.approx(.08)
    assert after['other_notes_union_s'] == pytest.approx(.08)
    assert after['uncovered_by_annotations_s'] == pytest.approx(0.)


@pytest.mark.parametrize('kind', subject.KINDS)
def test_short_notes_remain_in_the_context_denominator(kind):
    refs = [Reference(.2, .25, 69)]
    row = probe(source_signal(end=.25), refs, 0, kind)
    assert row['context']['category'] == 'own_note_short_window'
    summary = subject.summarize_probes([row])
    assert summary['reference_count'] == 1
    assert sum(v['reference_count'] for v in summary['by_context'].values()) == 1


def test_audio_edge_is_unavailable_without_partial_window_clipping():
    row = probe(source_signal(), [Reference(.03, .6, 69)], 0, 'onset')
    assert row['spectral_availability'] == 'after_only'
    assert row['before']['spectrum']['reason'] == 'window_outside_audio'
    assert row['before']['gate']['quiet_s'] is None
    summary = subject.summarize_probes([row])
    assert summary['energy_transition_counts']['target']['unavailable'] == 1
    assert summary['statistics']['target_change_db']['undefined'] == 1


def test_gate_seconds_use_partial_cell_intersections():
    row = subject._quiet_window(np.array([0., .1, .2, .3]),
                                np.array([True, False, True]), .05, .25)
    assert row['quiet_s'] == pytest.approx(.1)
    assert row['active_s'] == pytest.approx(.1)
    assert row['quiet_fraction'] == pytest.approx(.5)


def test_frozen_rms_path_has_no_zero_width_seventy_ms_cell():
    assert subject.rms_envelope is rms_envelope
    edges, levels = subject.rms_envelope(np.zeros((3087, 1)), 44100)
    assert len(levels) == 7
    assert np.all(np.diff(edges) > 0)


def test_spectral_rest_boundary_crossing_is_explicit_not_forced_additivity():
    bank = extract_features(np.full(44100, .1), 44100)
    regions = {
        'envelope': RegionIntervals(((.2, .6),), (), ((.2, .6),)),
        'core': RegionIntervals(((.3, .5),), (), ((.3, .5),)),
        'boundary_uncertain': RegionIntervals(((.2, .3), (.5, .6)), (), ((.2, .3), (.5, .6))),
    }
    report = subject.rest_spectral_context(bank, regions)
    counts = {key: value['full_frame_count'] for key, value in report['regions'].items()}
    missing = report['envelope_frames_crossing_core_uncertain_boundary']
    assert missing > 0
    assert counts['envelope'] == counts['core'] + counts['boundary_uncertain'] + missing


def test_spectral_rest_rejects_outside_interval_even_if_some_frames_fit():
    bank = extract_features(np.zeros(44100), 44100)
    with pytest.raises(ValueError, match='outside original audio'):
        subject._spectral_region(bank, [(-.1, .4)])


def test_short_supported_rest_has_time_but_no_invented_fft_frame():
    bank = extract_features(np.zeros(44100), 44100)
    row, mask = subject._spectral_region(bank, [(.2, .21)])
    assert row['interval_count'] == row['intervals_without_full_spectral_frame'] == 1
    assert row['full_frame_count'] == 0 and not mask.any()
    assert row['total_band_dbfs'] is None


@pytest.fixture
def integrated_case():
    note = '<note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>'
    attributes = '<attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>'
    xml = ('<score-partwise><part id="P1"><measure number="1">' + attributes + note * 4
           + '</measure><measure number="2">' + note * 4 + '</measure></part></score-partwise>').encode()
    score = parse_score(xml)
    match = SimpleNamespace(strict_score_consistency=True,
                            anchors=tuple(SimpleNamespace(q=Fraction(i), time=i / 2) for i in range(8)),
                            diagnostics={})
    rows = ['beat_time,beat_type,time_signature,piano,violin']
    rows += [f'{i / 2},{"db" if i % 4 == 0 else "b"},{"4/4" if i == 0 else ""},True,True'
             for i in range(8)]
    beats = ('\n'.join(rows) + '\n').encode()
    notes = b'onset,offset,midi,velocity\n1,1.25,60,127\n1.5,2,60,127\n2,2.7,60,127\n'
    time = np.arange(4 * 44100) / 44100
    signal = .2 * np.sin(2 * np.pi * (440 * 2 ** (-9 / 12)) * time)
    active = ((1 <= time) & (time < 1.25)) | ((1.5 <= time) & (time < 2.7))
    signal[~active] = 0.
    return subject.analyze_boundaries('08', signal, 44100, score, score, match,
                                      beats, notes, raw_score=xml)


def test_full_synthetic_parser_waveform_ranges_integration(integrated_case):
    result = integrated_case
    public = result.public
    assert public['reference_count'] == 3
    for kind in subject.KINDS:
        assert public['boundaries'][kind]['reference_count'] == 3
    assert public['expressive_analysis_sha256'] == hashlib.sha256(_encoded(result.expressive_analysis)).hexdigest()
    assert public['rest_acoustics']['source_projection'] == result.expressive_analysis['rest_ranges']
    assert public['watchlist'] == {}
    assert public['policy']['new_model_inferences'] == 0
    encoded = json.dumps(public, allow_nan=False)
    assert 'raw_notes' not in encoded and 'spectrogram' not in encoded


def test_complete_cohort_aggregate_preserves_every_kind(integrated_case):
    cases = [{'id': ident, 'status': 'complete', 'analysis': copy.deepcopy(integrated_case.public)}
             for ident in subject.PLANNED_IDS]
    summary = subject.summarize_boundaries(cases)
    assert summary['reference_count'] == 18
    for kind in subject.KINDS:
        row = summary['boundaries'][kind]
        assert row['reference_count'] == 18
        assert sum(row['spectral_availability'].values()) == 18
        assert sum(row['energy_transition_counts']['target'].values()) == 18
        assert all(s['count'] + s['undefined'] == 18 for s in row['statistics'].values())
    corrupted = copy.deepcopy(cases)
    corrupted[0]['analysis']['reference_count'] += 1
    with pytest.raises(ValueError, match='every reference'):
        subject.summarize_boundaries(corrupted)
    cases[-1]['status'] = 'failed'
    with pytest.raises(ValueError, match='complete'):
        subject.summarize_boundaries(cases)


def test_count_sum_pooling_never_averages_recording_means_or_quantiles():
    rows = [dict(count=1, undefined=1, sum=-10., min=-10., max=-10., median=-10.),
            dict(count=3, undefined=0, sum=6., min=1., max=3., median=2.)]
    result = subject._pool_statistics(rows)
    assert result['count'] == 4 and result['undefined'] == 1
    assert result['mean'] == -1.
    assert 'median' not in result and not result['cohort_quantiles_computed']


@pytest.mark.parametrize('cases', [[], [{'id': '02', 'status': 'complete'}],
                                  [{'id': '02', 'status': 'failed'}] * 6])
def test_incomplete_or_duplicate_cohort_cannot_publish_summary(cases):
    with pytest.raises(ValueError, match='planned unique complete'):
        subject.summarize_boundaries(cases)

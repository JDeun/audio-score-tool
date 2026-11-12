"""Constructed rest geometry and continuous waveform-cell contracts only."""
import hashlib
import json
import math
from dataclasses import dataclass, replace
from fractions import Fraction as F

import numpy as np
import pytest

from scripts import kraisler_rest_acoustics as module
from scripts.kraisler_correspondence import Reference
from scripts.kraisler_rest_acoustics import rest_acoustic_context
from scripts.kraisler_rhythm_ranges import rest_range_context
from scripts.kraisler_score import parse_score


def note(duration=1, *, rest=False):
    ticks = F(duration) * 120
    assert ticks.denominator == 1
    content = '<rest/>' if rest else '<pitch><step>C</step><octave>4</octave></pitch>'
    return f'<note>{content}<duration>{ticks.numerator}</duration></note>'


def score(content, beats=4):
    raw = ('<score-partwise><part id="P1"><measure number="1"><attributes>'
           f'<divisions>120</divisions><time><beats>{beats}</beats><beat-type>4</beat-type></time>'
           '</attributes>' + content + '</measure></part></score-partwise>').encode()
    return parse_score(raw)


@dataclass
class Clock:
    shift: float = 0.
    scale: float = 1.
    spans: tuple = ((F(0), F(4)),)
    period: float | None = 1.

    def time_at(self, q):
        return float(q) * self.scale + self.shift if any(a <= q <= b for a, b in self.spans) else None

    def supports_interval(self, start, end):
        return any(a <= start < end <= b for a, b in self.spans)

    def supports_time_band(self, q, width):
        return any(a <= q <= b and float(a) * self.scale + self.shift <= self.time_at(q) - width
                   and self.time_at(q) + width <= float(b) * self.scale + self.shift
                   for a, b in self.spans)

    def period_at(self, q):
        return self.period


def ordinary_score():
    return score(note() + note(rest=True) + note(2))


def test_partial_gate_cells_and_annotation_subsets_conserve_seconds():
    symbolic = ordinary_score()
    refs = (Reference(.9, 1.1, 60), Reference(1.6, 1.9, 62), Reference(2., 2.1, 64))
    edges = [0., .95, 1.4, 1.6, 2.05, 4.]
    quiet = [False, True, False, True, False]
    out = rest_acoustic_context(symbolic, refs, Clock(), Clock(shift=.1), edges, quiet)
    assert out.public['source_projection'] == rest_range_context(symbolic, refs, Clock(), Clock(shift=.1))
    expected = {
        'envelope': (1.5, .9, .6, .6, .5, .1),
        'core': (.5, .3, .2, .2, .2, 0.),
        'boundary_uncertain': (1., .6, .4, .4, .3, .1),
    }
    for name, values in expected.items():
        row = out.public['regions'][name]
        whole = tuple(row[key] for key in ('duration_s', 'quiet_s', 'active_s'))
        annotated = tuple(row['annotated_note_overlap'][key]
                          for key in ('duration_s', 'quiet_s', 'active_s'))
        assert whole + annotated == pytest.approx(values)
        for key in ('duration_s', 'quiet_s', 'active_s'):
            assert row[key] == pytest.approx(row['annotated_note_overlap'][key]
                                            + row['uncovered_by_note_annotations'][key])
    assert out.regions['envelope'].whole == ((.8, 2.3000000000000003),)
    assert out.public['gate_trace']['mask_sha256'] == hashlib.sha256(bytes([0, 1, 0, 1, 0])).hexdigest()
    assert out.public['gate_trace']['quiet_frame_count'] == 2
    assert out.public['conservation_checked']


def test_overlapping_annotations_are_unioned_before_gate_overlap():
    refs = (Reference(.9, 1.6, 60), Reference(1.4, 2.1, 62))
    out = rest_acoustic_context(ordinary_score(), refs, Clock(), Clock(shift=.1),
                                [0., .95, 1.4, 1.6, 2.05, 4.],
                                [False, True, False, True, False])
    row = out.public['regions']['envelope']['annotated_note_overlap']
    assert row['duration_s'] == pytest.approx(1.2)
    assert row['quiet_s'] == pytest.approx(.9)
    assert row['active_s'] == pytest.approx(.3)
    assert out.regions['envelope'].annotated_note_overlap == ((.9, 2.1),)


@pytest.mark.parametrize('quiet', [False, True])
def test_all_active_or_all_quiet_is_context_not_an_acoustic_truth_label(quiet):
    out = rest_acoustic_context(ordinary_score(), (), Clock(), Clock(), [0., 4.], [quiet])
    for row in out.public['regions'].values():
        assert row['quiet_fraction'] == float(quiet)
        assert row['quiet_s' if quiet else 'active_s'] == row['duration_s']
        assert row['active_s' if quiet else 'quiet_s'] == 0
    assert not out.public['acoustic_silence_verified']
    assert not out.public['annotation_uncovered_is_silence']
    assert not out.public['written_rest_accuracy_measured']


def test_collapsed_cores_and_overlapping_envelopes_keep_each_source_rest():
    symbolic = score(note() + note(F(1, 5), rest=True) + note(F(1, 10))
                     + note(F(1, 5), rest=True) + note(F(5, 2)))
    out = rest_acoustic_context(symbolic, (), Clock(), Clock(), [0., 1.2, 4.], [True, False])
    projection = out.public['source_projection']
    assert projection['instrument_wide_rest_intervals'] == projection['projected_rest_intervals'] == 2
    assert projection['collapsed_core_intervals'] == 2
    assert out.regions['core'].whole == ()
    assert out.public['regions']['core']['quiet_fraction'] is None
    assert out.public['regions']['envelope']['interval_count'] == 1
    assert out.public['regions']['envelope']['duration_s'] == pytest.approx(.9)
    assert out.public['regions']['envelope'] == out.public['regions']['boundary_uncertain']


def test_unprojectable_interval_is_counted_without_clipping_to_a_component():
    symbolic = score(note(F(1, 5), rest=True) + note(F(4, 5)) + note(rest=True) + note(2))
    out = rest_acoustic_context(symbolic, (), Clock(), Clock(), [0., 4.], [True])
    source = out.public['source_projection']
    assert source['instrument_wide_rest_intervals'] == 2
    assert source['projected_rest_intervals'] == source['unprojectable_rest_intervals'] == 1
    assert source['unprojectable_reasons'] == {'expanded_boundary_band_not_supported_by_both_clocks': 1}
    assert not out.public['clipping_performed']


def test_disconnected_support_is_not_bridged_even_with_valid_endpoints():
    broken = Clock(spans=((F(0), F(7, 5)), (F(8, 5), F(4))))
    assert broken.time_at(F(1)) is not None and broken.time_at(F(2)) is not None
    out = rest_acoustic_context(ordinary_score(), (), Clock(), broken, [0., 4.], [False])
    assert out.public['source_projection']['unprojectable_reasons'] == {
        'interval_not_supported_by_both_clocks': 1}
    assert all(region.whole == () for region in out.regions.values())


def test_expanded_guard_includes_clock_disagreement_before_admission():
    spans = ((F(3, 4), F(9, 4)),)
    bclock, pclock = Clock(spans=spans), Clock(shift=.2, spans=spans)
    assert bclock.supports_time_band(F(1), .2)
    assert pclock.supports_time_band(F(1), .2)
    out = rest_acoustic_context(ordinary_score(), (), bclock, pclock, [0., 4.], [False])
    assert out.public['source_projection']['unprojectable_reasons'] == {
        'expanded_boundary_band_not_supported_by_both_clocks': 1}
    assert out.public['source_projection']['projected_rest_intervals'] == 0


def test_overlapping_performed_components_do_not_double_count_union_seconds():
    class RepeatedClock(Clock):
        spans = ((F(0), F(4)), (F(4), F(8)))

        def time_at(self, q):
            return float(q if q <= 4 else q - 4)

        def supports_interval(self, start, end):
            return 0 <= start < end <= 4 or 4 <= start < end <= 8

        def supports_time_band(self, q, width):
            return 0 <= self.time_at(q) - width <= self.time_at(q) + width <= 4

    symbolic = score(note() + note(rest=True) + note(3) + note(rest=True) + note(2), 8)
    out = rest_acoustic_context(symbolic, (), RepeatedClock(), RepeatedClock(), [0., 4.], [True])
    assert out.public['source_projection']['projected_rest_intervals'] == 2
    assert out.public['source_projection']['nonempty_core_source_intervals'] == 2
    assert out.public['regions']['envelope']['interval_count'] == 1
    assert out.public['regions']['envelope']['duration_s'] == pytest.approx(1.4)
    assert out.public['regions']['core']['duration_s'] == pytest.approx(.6)


@pytest.mark.parametrize('mode', ['clock', 'score'])
def test_unavailable_source_still_preserves_rest_denominator(mode):
    symbolic = ordinary_score()
    if mode == 'score':
        symbolic = replace(symbolic, unsupported=('synthetic source representation limit',))
    out = rest_acoustic_context(symbolic, (), None if mode == 'clock' else Clock(), Clock(),
                                [0., 4.], [False])
    source = out.public['source_projection']
    assert source['instrument_wide_rest_intervals'] == source['unprojectable_rest_intervals'] == 1
    assert source['projected_rest_intervals'] == 0


def test_unannotated_score_time_is_not_promoted_to_written_rest():
    symbolic = score('<forward><duration>120</duration></forward>' + note(3))
    out = rest_acoustic_context(symbolic, (), Clock(), Clock(), [0., 4.], [True])
    assert out.public['source_projection']['unknown_score_intervals'] == 1
    assert out.public['source_projection']['instrument_wide_rest_intervals'] == 0
    assert out.public['regions']['envelope']['duration_s'] == 0


@pytest.mark.parametrize('edges,quiet', [
    ([0., 1., 1., 4.], [False, False, False]),
    ([0., 2., 1., 4.], [False, False, False]),
    (np.array([0, 4, 2], dtype=np.uint64), [False, False]),
    ([.1, 4.], [False]),
    ([0., math.inf], [False]),
    ([0., math.nan], [False]),
    ([0., 4.], [0]),
    ([0., 4.], [False, True]),
    ([[0., 4.]], [False]),
    ([], []),
])
def test_invalid_or_nonboolean_gate_timeline_cannot_be_used_as_evidence(edges, quiet):
    with pytest.raises(ValueError):
        rest_acoustic_context(ordinary_score(), (), Clock(), Clock(), edges, quiet)


@pytest.mark.parametrize('reason,refs,edges', [
    ('projected rest', (), [0., 2.1]),
    ('reference', (Reference(3.9, 4.1, 60),), [0., 4.]),
])
def test_out_of_audio_context_fails_closed_instead_of_clipping(reason, refs, edges):
    with pytest.raises(ValueError, match=reason + ' outside original audio coverage; clipping forbidden'):
        rest_acoustic_context(ordinary_score(), refs, Clock(), Clock(), edges, [False])


def test_frozen_source_summary_disagreement_is_a_failure(monkeypatch):
    original = module.rest_range_context

    def changed(*args):
        value = original(*args)
        value['projections']['core']['duration_s'] += .001
        return value

    monkeypatch.setattr(module, 'rest_range_context', changed)
    with pytest.raises(ValueError, match='frozen rest projection summary changed'):
        rest_acoustic_context(ordinary_score(), (), Clock(), Clock(), [0., 4.], [True])


def test_public_payload_contains_no_interval_or_media_arrays_and_hashes_are_replayable():
    out = rest_acoustic_context(ordinary_score(), (), Clock(), Clock(), np.array([0., 4.]),
                                np.array([True], dtype=bool))

    def inspect(value):
        assert not isinstance(value, (list, tuple, np.ndarray))
        if isinstance(value, dict):
            for child in value.values():
                inspect(child)

    inspect(out.public)
    json.dumps(out.public, allow_nan=False)
    for name, region in out.regions.items():
        raw = json.dumps(region.whole, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=True, allow_nan=False).encode('utf-8')
        assert out.public['regions'][name]['interval_sha256'] == hashlib.sha256(raw).hexdigest()
    with pytest.raises(TypeError):
        out.regions['core'] = out.regions['envelope']

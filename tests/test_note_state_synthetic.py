"""Population, ambiguity and scoring contracts; no experimental model evaluation."""
from dataclasses import replace

import numpy as np
import pytest

from scripts import note_state_synthetic as synthetic


def test_fixed_population_includes_all_difficult_and_ambiguous_controls():
    plan = synthetic.cases()
    assert len(plan) == len({c.id for c in plan}) == 245
    assert sum(c.accuracy_eligible for c in plan) == 227
    counts = {kind: sum(c.kind == kind for c in plan)
              for kind in ('single', 'repeat', 'change', 'silence', 'vibrato', 'drift', 'dropout')}
    assert counts == dict(single=140, repeat=54, change=36, silence=3, vibrato=3, drift=3, dropout=6)
    assert len(synthetic.ARMS) == 7
    for case in plan:
        hz, duration = synthetic.observations(case)
        assert len(hz) == round(duration / .01) + 1
        if case.context in ('end', 'full') and case.kind != 'silence':
            assert hz[-1] == hz[-2] and hz[-1] > 0
        else:
            assert hz[-1] == 0
        assert np.isfinite(hz).all() and (hz >= 0).all()
        for note in synthetic.truth(case):
            assert 0 <= note.onset < note.offset <= duration + 1e-10
            assert note.offset - note.onset >= .08 - 1e-10


def test_identical_contour_cannot_distinguish_two_same_pitch_notes():
    for pair in (c for c in synthetic.cases() if c.kind == 'repeat' and c.gap == 0):
        single = replace(pair, kind='single', frames=2 * pair.frames)
        hz, duration = synthetic.observations(pair)
        other, other_duration = synthetic.observations(single)
        np.testing.assert_array_equal(hz, other)
        assert duration == other_duration
        assert not pair.accuracy_eligible
        assert len(synthetic.truth(pair)) == 2
        assert synthetic.alternative_truth(pair) == synthetic.truth(single)


def test_dropout_has_distinct_continuous_and_rest_interpretations():
    for case in (c for c in synthetic.cases() if c.kind == 'dropout'):
        hz, _ = synthetic.observations(case)
        left, end, _ = synthetic.layout(case)
        assert (hz[left:end] == 0).sum() == case.gap
        assert len(synthetic.truth(case)) == 1
        alternate = synthetic.alternative_truth(case)
        assert len(alternate) == 2
        assert alternate[1].onset - alternate[0].offset == pytest.approx(case.gap * .01)
        assert not case.accuracy_eligible


def test_onset_offset_metric_counts_empty_and_octave_errors():
    note = synthetic.dsp.Note(57, .3, .6)
    assert synthetic.score([note], [note]) == {'onset_f1': 1., 'onset_offset_f1': 1.}
    assert synthetic.score([], [note]) == {'onset_f1': 0., 'onset_offset_f1': 0.}
    assert synthetic.score([replace(note, pitch=69)], [note])['onset_f1'] == 0
    assert synthetic.score([replace(note, offset=.9)], [note]) == {'onset_f1': 1., 'onset_offset_f1': 0.}
    with pytest.raises(ValueError, match='separate silence'):
        synthetic.score([], [])


def test_known_truth_never_enters_predictor_signature():
    import inspect

    assert list(inspect.signature(synthetic.predict).parameters) == ['hz', 'duration']
    with pytest.raises(ValueError, match='incomplete'):
        synthetic.summarize([])

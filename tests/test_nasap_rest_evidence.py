"""Frozen development controls for evidence-based silence preservation."""
import inspect
import itertools
import math

import pytest

from scripts import nasap_joint_rhythm as joint
from scripts.nasap_rest_evidence import decode, overlap, silence_evidence, solve_path


def groups():
    return [joint.Group(('a',), (0.,), (.5,)), joint.Group(('b',), (1.,), (.5,))]


def test_evidence_requires_both_inputs_and_not_score_labels():
    x = {'csv_sustain': groups(), 'key_release': groups()}
    assert silence_evidence(x, 2.) == [(0.5625, .9375)]
    x['csv_sustain'] = [joint.Group(('a',), (0.,), (1.1,)), groups()[1]]
    assert silence_evidence(x, 2.) == []


def test_boundaries_are_not_treated_as_rest_evidence():
    g = [joint.Group(('a',), (.5,), (.5,))]
    assert silence_evidence(dict(csv_sustain=g, key_release=g), 2.) == []


@pytest.mark.parametrize('change', ('identity', 'onset', 'nan', 'negative'))
def test_invalid_evidence_fails(change):
    g = groups()
    first = {'identity': joint.Group(('x',), (0.,), (.5,)),
             'onset': joint.Group(('a',), (.01,), (.5,)),
             'nan': joint.Group(('a',), (float('nan'),), (.5,)),
             'negative': joint.Group(('a',), (0.,), (-1.,))}[change]
    with pytest.raises(ValueError):
        silence_evidence(dict(csv_sustain=g, key_release=[first, g[1]]), 2.)


@pytest.mark.parametrize('method', ('silence_soft', 'silence_hard'))
def test_zero_evidence_exactly_reproduces_previous_rest_objective(method):
    g = groups()
    a = joint.decode(g, 2., 2., 'joint_rest_cost')
    b = decode(g, 2., 2., [], method)
    assert a == b


def test_hard_guard_cannot_fill_evidence_core():
    x = decode(groups(), 2., 2., [(.5625, .9375)], 'silence_hard')
    assert all(overlap(a, a+d, [(.5625, .9375)]) == 0 for a, d in x['predictions'].values())
    assert set(x['predictions']) == {'a', 'b'}


def test_impossible_guard_reports_failure_not_unprotected_fallback():
    with pytest.raises(ValueError):
        decode(groups(), 2., 2., [(0., 2.)], 'silence_hard')


def test_dp_matches_exhaustive_search():
    lattices = [[(0, 12, .1), (0, 24, .2)], [(24, 36, .1), (24, 48, .3)]]
    costs = []
    for sequence in itertools.product(*lattices):
        a, b = sequence
        if a[1] <= b[0]:
            cost = sum(c[2] for c in sequence)+joint.REST_WEIGHT*sum((
                joint.gap_cost(0, a[0], 48), joint.gap_cost(a[1], b[0], 48),
                joint.gap_cost(b[1], 48, 48)))
            if math.isfinite(cost):
                costs.append((cost, tuple(c[:2] for c in sequence)))
    assert solve_path(lattices, 48, 48) == min(costs)


def test_no_target_arguments():
    assert list(inspect.signature(silence_evidence).parameters) == ['by_rep', 'length_q']
    assert list(inspect.signature(decode).parameters) == ['groups', 'bar_q', 'length_q', 'evidence', 'method']

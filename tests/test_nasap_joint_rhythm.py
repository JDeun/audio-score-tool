"""Offline parser and exact joint-search controls, before real-source evaluation."""
from __future__ import annotations

import itertools
import math
from fractions import Fraction

import pytest

from scripts.nasap_joint_rhythm import (
    GRID,
    METHODS,
    Group,
    aggregate,
    base_id,
    candidate_lattice,
    complement,
    decode,
    gap_cost,
    make_blocks,
    merged_intervals,
    parse_score,
    rest_matches,
    run_block,
    spell_cost,
)
from scripts.nasap_duration_probe import Observation


def note(nid, duration, *, voice='1', pitch='C', chord=False, rest=False, ties=()):
    body = '<rest/>' if rest else f'<pitch><step>{pitch}</step><octave>4</octave></pitch>'
    return (f'<note id="{nid}">' + ('<chord/>' if chord else '') + body
            + f'<duration>{duration}</duration><voice>{voice}</voice>'
            + ''.join(f'<tie type="{t}"/>' for t in ties) + '</note>')


def document(content, meter=4):
    return ('<score-partwise><part id="P1"><measure number="1">'
            '<attributes><divisions>48</divisions><time>'
            f'<beats>{meter}</beats><beat-type>4</beat-type></time></attributes>'
            + content + '</measure></part></score-partwise>').encode()


def two_bar_score():
    first = note('a', 48) + note('r', 48, rest=True)
    second = note('b', 48) + note('s', 48, rest=True)
    return document(first + '</measure><measure number="2">' + second, 2)


def test_explicit_rests_are_not_manufactured_from_gaps():
    parsed = parse_score(document(note('a', 48) + note('r', 144, rest=True)))
    assert parsed['rests'] == [(('P1', '1'), Fraction(1), Fraction(4))]
    assert len(parsed['notes']) == 1
    gap_only = parse_score(document(note('a', 48)))
    assert gap_only['rests'] == []


def test_chord_does_not_advance_time_twice():
    parsed = parse_score(document(note('a', 48) + note('b', 48, pitch='E', chord=True)
                                  + note('c', 144, pitch='G')))
    assert parsed['notes']['b']['start'] == 0
    assert parsed['notes']['c']['start'] == 1


def test_backup_and_forward_change_position_not_voice_identity():
    parsed = parse_score(document(note('a', 192) + '<backup><duration>192</duration></backup>'
                                  + '<forward><duration>48</duration></forward>'
                                  + note('b', 144, voice='2')))
    assert parsed['notes']['b']['start'] == 1
    assert parsed['notes']['b']['voice'] == ('P1', '2')


def test_cross_measure_tie_preserves_one_attack():
    raw = document(note('a', 192, ties=('start',)) + '</measure><measure number="2">'
                   + note('b', 48, ties=('stop',)) + note('r', 144, rest=True))
    parsed = parse_score(raw)
    assert len(parsed['notes']) == 1
    assert parsed['notes']['a']['end'] == 5
    assert parsed['notes']['a']['segments'] == 2


def test_repeated_pitch_without_tie_keeps_two_attacks():
    parsed = parse_score(document(note('a', 96) + note('b', 96)))
    assert set(parsed['notes']) == {'a', 'b'}


@pytest.mark.parametrize('body', ('<!ENTITY bad SYSTEM "file:///tmp/x">',
                                  '<score-timewise/>', '<score-partwise/>'))
def test_invalid_or_empty_score_is_rejected_or_contains_no_notes(body):
    try:
        parsed = parse_score(body.encode())
    except ValueError:
        return
    assert not parsed['notes']


def test_noncontiguous_tie_rejected():
    with pytest.raises(ValueError):
        parse_score(document(note('a', 48, ties=('start',)) + note('r', 48, rest=True)
                             + note('b', 96, ties=('stop',))))


def test_unfolded_suffix_does_not_overwrite_note_identity():
    assert base_id('n4-2', {'n4': {}}) == 'n4'
    assert base_id('n4', {'n4': {}}) == 'n4'
    assert base_id('missing-2', {'n4': {}}) is None


def test_explicit_context_separates_predictor_groups_and_targets():
    parsed = parse_score(two_bar_score())
    score_rows = [{'id': 'a-1', 'onset_quarter': '0', 'duration_quarter': '1', 'pitch': '60'},
                  {'id': 'b-1', 'onset_quarter': '2', 'duration_quarter': '1', 'pitch': '60'}]
    alignment = [{'matchtype': '0', 'partid': 'a-1', 'ppartid': 'p1'},
                 {'matchtype': '0', 'partid': 'b-1', 'ppartid': 'p2'}]
    observations = [Observation('p1', 60, .02, .6), Observation('p2', 60, 2.02, .6)]
    blocks, attempts = make_blocks(parsed, score_rows, alignment,
                                   {'csv_sustain': observations, 'key_release': observations}, 0)
    assert len(blocks) == 1
    assert attempts[0]['status'] == 'admitted'
    assert blocks[0]['rests'] == [(1., 2.), (3., 4.)]
    assert blocks[0]['groups']['csv_sustain'][0].durations == (.6,)
    assert blocks[0]['targets']['p1'] == (0., 1.)
    assert 'rests' not in blocks[0]['groups']['csv_sustain'][0].__dict__


def test_incomplete_note_inventory_is_not_silently_replaced():
    parsed = parse_score(two_bar_score())
    rows = [{'id': 'a-1', 'onset_quarter': '0', 'duration_quarter': '1', 'pitch': '60'},
            {'id': 'b-1', 'onset_quarter': '2', 'duration_quarter': '1', 'pitch': '60'}]
    observations = [Observation('p1', 60, .02, .6)]
    align = [{'matchtype': '0', 'partid': 'a-1', 'ppartid': 'p1'}]
    blocks, attempted = make_blocks(parsed, rows, align,
                                    {'csv_sustain': observations, 'key_release': observations}, 0)
    assert not blocks
    assert attempted[0]['reason'] == 'missing_unique_performance_alignment'


def test_gap_segmentation_and_notation_constraints():
    assert spell_cost(0) == 0
    assert math.isinf(spell_cost(1))
    assert spell_cost(48) > 0
    assert gap_cost(24, 120, 96) > 0
    assert math.isinf(gap_cost(95, 97, 96))


@pytest.mark.parametrize('method', METHODS)
def test_clean_rhythm_counts_and_real_reattacks_remain(method):
    groups = [Group(('a',), (0.,), (1.,)), Group(('b',), (1.,), (1.,))]
    result = decode(groups, 2., 2., method)
    assert result['predictions'] == {'a': (0., 1.), 'b': (1., 1.)}
    assert result['note_count_preserved']
    assert result['structural_valid']
    assert result['rests'] == []


@pytest.mark.parametrize('method', ('joint_structure', 'joint_rest_cost'))
def test_joint_path_agrees_with_exhaustive_search(method):
    groups = [Group(('a',), (.02,), (.50,)), Group(('b',), (.75,), (.24,))]
    size, bar = 48, 48
    lattice = [candidate_lattice(g, size, bar) for g in groups]
    weight = .2 if method == 'joint_rest_cost' else 0
    solutions = []
    for first, second in itertools.product(*lattice):
        a, b, c = first
        x, y, z = second
        if b > x:
            continue
        bridge = gap_cost(0, a, bar) + gap_cost(b, x, bar) + gap_cost(y, size, bar)
        if math.isfinite(bridge):
            solutions.append(c+z+weight*bridge)
    result = decode(groups, 1, 1, method)
    assert result['cost'] == pytest.approx(min(solutions), abs=1e-9)


def test_independent_can_overlap_but_joint_cannot():
    groups = [Group(('a',), (0.,), (2.,)), Group(('b',), (1.,), (1.,))]
    original = decode(groups, 2, 2, 'independent')
    joint = decode(groups, 2, 2, 'joint_structure')
    assert not original['structural_valid']
    assert joint['structural_valid']
    assert set(joint['predictions']) == {'a', 'b'}


def test_rests_are_scored_against_explicit_reference_not_assumed_correct():
    assert rest_matches([(1, 2), (3, 4)], [(1, 2)]) == {'predicted': 2, 'reference': 1, 'matched': 1}
    assert rest_matches([], []) == {'predicted': 0, 'reference': 0, 'matched': 0}
    assert merged_intervals([(0, 1), (1, 2)]) == [(0, 2)]
    assert complement([(0, 1), (2, 3)], 4) == [(1, 2), (3, 4)]


def test_chord_identity_preserved_with_single_shared_duration():
    groups = [Group(('a', 'b'), (.01, .03), (.5, .6)), Group(('c',), (1.,), (1.,))]
    result = decode(groups, 2, 2, 'joint_rest_cost')
    assert result['predictions']['a'] == result['predictions']['b']
    assert len(result['predictions']) == 3


def test_targets_do_not_influence_predictions():
    groups = [Group(('a',), (0.,), (1.,)), Group(('b',), (1.,), (1.,))]
    inputs = {'csv_sustain': groups, 'key_release': groups}
    good = {'id': 'test', 'groups': inputs, 'targets': {'a': (0., 1.), 'b': (1., 1.)},
            'rests': [], 'bar_q': 2, 'length_q': 2}
    bad = {**good, 'targets': {'a': (0., .5), 'b': (1., .5)}, 'rests': [(0.5, 1)]}
    a, b = run_block(good), run_block(bad)
    for key in a['arms']:
        assert a['arms'][key]['cost'] == b['arms'][key]['cost']
        assert a['arms'][key]['duration_exact'] == 2
        assert b['arms'][key]['duration_exact'] == 0


@pytest.mark.parametrize('group', (Group(('x',), (0.,), (0.,)),
                                   Group(('x',), (float('nan'),), (1.,)),
                                   Group(('x','x'), (0.,0.), (1.,1.))))
def test_invalid_observations_rejected(group):
    with pytest.raises(ValueError):
        decode([group], 2, 2, 'joint_structure')


def test_missing_passages_stay_in_coverage():
    result = aggregate([{'status': 'prior_not_evaluated'}, {'status': 'no_supported_blocks'}])
    assert result['sources_planned'] == 2
    assert result['blocks_admitted'] == 0
    assert result['note_evaluations'] == 0


def test_candidate_positions_are_not_inserted_from_hidden_truth():
    group = Group(('a',), (1.,), (.6,))
    candidates = candidate_lattice(group, 4*GRID, 4*GRID)
    assert all(abs(a/GRID-1.) <= .25+1e-8 for a, _, _ in candidates)
    assert not any(a == 0 for a, _, _ in candidates)

"""Offline held-out selection and diagnostic checks; no real outcome tuning."""
from __future__ import annotations

from copy import deepcopy

import pytest

from scripts import nasap_joint_rhythm as joint
from scripts.nasap_joint_holdout import (
    MAX_PER_COMPOSER,
    canonical,
    choose_new_sources,
    crosses_inner_bar,
    extend_summary,
    f1_counts,
    piece_key,
    rest_occupancy,
    run_frozen_block,
)


def row(composer, title, performance):
    folder = f'{composer}/{title}'
    return {'composer': composer, 'title': title, 'midi_performance': f'{folder}/{performance}.mid',
            'robust_note_alignment': '1.0', 'parangonada_data_folder': f'{folder}/{performance}/data',
            'performance_annotations': f'{folder}/{performance}_annotations.txt',
            'folder': folder, 'xml_score': f'{folder}/score.xml', 'midi_score': f'{folder}/score.mid'}


def pool():
    return [row(str(c), str(t), str(p)) for c in range(10) for t in range(6) for p in range(2)]


def block():
    groups = [joint.Group(('a',), (.01,), (.8,)), joint.Group(('b',), (2.02,), (.9,))]
    return {'id': 'fixture', 'groups': {'csv_sustain': groups, 'key_release': groups},
            'targets': {'a': (0., 1.), 'b': (2., 1.)}, 'rests': [(1., 2.), (3., 4.)],
            'bar_q': 2., 'length_q': 4.}


def test_selection_is_reproducible_piece_disjoint_not_just_file_disjoint():
    data = pool()
    old_ids = [data[0]['midi_performance']]
    a, audit = choose_new_sources(data, old_ids)
    b, _ = choose_new_sources(list(reversed(data)), old_ids)
    assert a == b
    assert len(a) == 24
    assert len({piece_key(r) for r in a}) == 24
    assert piece_key(data[0]) not in {piece_key(r) for r in a}
    assert max(audit['selected_composers'].values()) <= MAX_PER_COMPOSER


def test_score_aliases_and_schema_inspection_pieces_are_excluded():
    data = pool()
    alias = row('alias', 'different title', 'one')
    alias['xml_score'] = data[0]['xml_score']
    inspected = row('Bach', 'Fugue_bwv_846', 'not-evaluated-but-inspected')
    chosen, _ = choose_new_sources(data+[alias, inspected], [data[0]['midi_performance']])
    assert alias not in chosen and inspected not in chosen


def test_normalization_preserves_work_identity_across_case_whitespace():
    assert canonical('  BACH  ') == 'bach'
    a = row('Bach', 'Fugue X', 'a')
    b = row(' BACH ', ' Fugue   X ', 'b')
    chosen, _ = choose_new_sources([a, b]+pool(), [a['midi_performance']])
    assert a not in chosen and b not in chosen


def test_selection_never_replaces_unavailable_sources_based_on_outcomes():
    data = pool()
    a, _ = choose_new_sources(data, [])
    for r in data:
        r['later_status'] = 'failed' if r in a else 'complete'
        r['later_accuracy'] = 0 if r in a else 1
    b, _ = choose_new_sources(data, [])
    assert [r['midi_performance'] for r in a] == [r['midi_performance'] for r in b]


@pytest.mark.parametrize('kind', ('duplicate', 'missing'))
def test_ambiguous_metadata_fails_closed(kind):
    data = pool()
    if kind == 'duplicate':
        data.append(data[0])
        ids = []
    else:
        ids = ['no/such/performance.mid']
    with pytest.raises(ValueError):
        choose_new_sources(data, ids)


@pytest.mark.parametrize('pred,ref,overlap,false,miss', (
    ([], [], 0., 0., 0.),
    ([(0., 1.)], [(0., 1.)], 1., 0., 0.),
    ([(0., 1.)], [(1., 2.)], 0., 1., 1.),
    ([(0., 2.)], [(1., 3.)], 1., 1., 1.),
    ([(0., 1.), (1., 2.)], [(0., 2.)], 2., 0., 0.),
))
def test_rest_occupancy_tracks_false_and_erased_silence(pred, ref, overlap, false, miss):
    result = rest_occupancy(pred, ref)
    assert result['overlap_q'] == overlap
    assert result['false_rest_q'] == false
    assert result['missed_rest_q'] == miss


def test_strict_rest_metrics_do_not_mistake_empty_reference_for_success():
    assert f1_counts({'predicted': 0, 'reference': 0, 'matched': 0})['f1'] is None
    assert f1_counts({'predicted': 2, 'reference': 2, 'matched': 1})['f1'] == .5
    assert f1_counts({'predicted': 3, 'reference': 0, 'matched': 0})['f1'] == 0


@pytest.mark.parametrize('value,expected', (((0., 1.), False), ((1., 1.), False),
                                           ((1., 2.), True), ((2., 1.), False)))
def test_tie_diagnostic_distinguishes_positive_crossing(value, expected):
    assert crosses_inner_bar(value, 2.) is expected


def test_secondary_diagnostics_leave_every_primary_outcome_unchanged():
    case = block()
    original = deepcopy(case)
    before = joint.run_block(case)
    after = run_frozen_block(case)
    assert case == original
    for name, values in before['arms'].items():
        assert all(after['arms'][name][key] == value for key, value in values.items())
        assert sum(after['arms'][name]['inner_bar_crossing'].values()) == 2


def test_target_swap_changes_evaluation_not_the_decoder_cost():
    case = block()
    a = run_frozen_block(case)
    case['targets'] = {'a': (.5, .5), 'b': (2.5, .5)}
    case['rests'] = [(0., .5), (1., 2.5), (3., 4.)]
    b = run_frozen_block(case)
    for name in a['arms']:
        assert a['arms'][name]['cost'] == b['arms'][name]['cost']


def test_full_coverage_and_paired_denominators_remain_distinct():
    b = run_frozen_block(block())
    case = {'status': 'complete', 'blocks': [b]}
    stats = extend_summary([case, {'status': 'not_evaluated'}])
    assert stats['sources_planned'] == 2
    assert stats['blocks_admitted'] == stats['all_six_arms_complete_blocks'] == 1
    assert stats['all_six_arms_complete_notes'] == 2
    changed = deepcopy(b)
    changed['arms']['key_release/joint_rest_cost'] = {'status': 'unavailable', 'n': 2}
    changed['paired'].pop('key_release/joint_rest_cost')
    stats = extend_summary([{'status': 'complete', 'blocks': [changed]}])
    assert stats['blocks_admitted'] == 1
    assert stats['all_six_arms_complete_blocks'] == 0
    assert stats['paired_scope']['csv_sustain/independent']['n'] == 0


def test_empty_coverage_is_not_zero_accuracy_evidence():
    stats = extend_summary([{'status': 'not_evaluated'}])
    assert stats['blocks_admitted'] == 0
    assert stats['arms']['csv_sustain/independent']['composition_equal_pair_accuracy'] is None

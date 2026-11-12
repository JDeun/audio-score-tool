import json

import pytest

from scripts.qwen_constraint_ablation import (
    FIXTURES,
    ORDERS,
    body_for,
    parse,
    payload,
    plan,
    summarize,
)


def test_schema_is_only_different_field_in_pair():
    data = payload(0, 0)
    enforced = body_for(data, True, 'greedy', 0)
    plain = body_for(data, False, 'greedy', 0)
    del enforced['response_format']
    assert enforced == plain


def test_predeclared_plan_has_no_best_seed_and_no_duplicate():
    assert len(plan()) == len(set(plan())) == 144
    assert {seed for _, recipe, seed, _, _ in plan() if recipe == 'sampled'} == {0, 1}


def test_target_never_in_payload_and_all_mappings_correct():
    for c, (a, b, d) in enumerate(FIXTURES):
        for p, (_, labels) in enumerate(ORDERS):
            data = payload(c, p)
            assert set(data) == {'desired_marker', 'candidates'}
            matches = [x['id'] for x in data['candidates'] if x['marker'] == d]
            text = json.dumps({'choice': matches[0] if matches else 'abstain'})
            expected = 0 if d == a else 1 if d == b else None
            assert parse(text, labels) == expected


@pytest.mark.parametrize('text', ['A', '{"choice":"C"}', '{"choice":"A","why":1}',
                                 'prefix {"choice":"A"}', '{"choice":null}'])
def test_malformed_is_not_repaired(text):
    with pytest.raises((ValueError, TypeError)):
        parse(text, ('A', 'B'))


def test_incomplete_results_do_not_emit_complete_summary():
    assert summarize([]) is None
    rows = [{'key': list(k), 'status': 'scored', 'correct': True} for k in plan()]
    assert all(r['gate_passed'] for r in summarize(rows))
    rows[0]['status'] = 'failed'
    rows[0]['correct'] = False
    assert sum(r['invalid_or_failed'] for r in summarize(rows)) == 1
    rows[-1] = rows[0]
    assert summarize(rows) is None

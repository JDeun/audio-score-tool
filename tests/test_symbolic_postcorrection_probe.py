from __future__ import annotations

import copy
import json
from fractions import Fraction

import pytest

from scripts.symbolic_postcorrection_probe import (
    baseline,
    cases,
    fingerprint,
    model_input,
    note,
    parse_choice,
    step_decode,
    step_encode,
    summarize,
    validate_notes,
)


def test_targets_and_categories_never_enter_model_input():
    for case in cases():
        changed = copy.deepcopy(case)
        changed.update(target="poison", category="secret", id="answer")
        assert model_input(case, (0, 1)) == model_input(changed, (0, 1))
        assert "poison" not in json.dumps(model_input(changed, (0, 1)))


@pytest.mark.parametrize("case", cases(), ids=lambda c: c["id"])
def test_fixture_schema_and_roundtrip(case):
    for events in [case["raw"], case["alternate"]]:
        validate_notes(events)
        assert json.loads(json.dumps(events)) == events
        supported = all((Fraction(e[k])*4).denominator == 1 for e in events for k in ("start", "duration"))
        if supported:
            assert step_decode(step_encode(events)) == events
        else:
            with pytest.raises(ValueError, match="unsupported_resolution"):
                step_encode(events)


@pytest.mark.parametrize("markov", [False, True])
def test_explicit_synthetic_baseline_is_reference_independent(markov):
    for case in cases():
        before = fingerprint(case)
        choice = baseline(case, markov)
        altered = copy.deepcopy(case)
        altered["target"] = "must_not_be_read"
        assert baseline(altered, markov) == choice
        assert fingerprint(case) == before
        assert choice == case["target"]


@pytest.mark.parametrize("text", ['{"choice":"C"}', '{"choice":"A","other":1}', '[]', 'oops'])
def test_response_fail_closed(text):
    with pytest.raises((ValueError, TypeError)):
        parse_choice(text, (0, 1))


def test_candidate_permutation_maps_back_to_same_interpretation():
    assert parse_choice('{"choice":"A"}', (0, 1)) == parse_choice('{"choice":"B"}', (1, 0))
    assert parse_choice('{"choice":"abstain"}', (0, 1)) is None


def test_incomplete_and_duplicates_never_get_summary():
    row = {"id": "a", "status": "scored", "correct": True, "choice": 0,
           "category": "clean", "order_consistent": True}
    assert summarize([row], ["a", "b"]) is None
    assert summarize([row, row], ["a", "b"]) is None
    assert summarize([{**row, "status": "failed"}], ["a"]) is None
    assert summarize([row], ["a"])["choice_correct"] == 1


@pytest.mark.parametrize("events", [[note(0, -1)], [note(0, 2)], [note(0, 1, 128)], []])
def test_invalid_candidates_rejected(events):
    with pytest.raises(ValueError):
        validate_notes(events)

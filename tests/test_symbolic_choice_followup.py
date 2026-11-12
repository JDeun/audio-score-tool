import copy
import json

import pytest

from scripts.symbolic_choice_followup import (
    PRESENTATIONS,
    acoustic_costs,
    control_data,
    group_summary,
    music_data,
    parse_answer,
    select_with_prior,
    ticks,
)


def fixture():
    return {"id": "private-id", "target": "NEVER-PROMPT", "category": "private-category",
            "raw": [{"start": "0", "duration": "1/2", "pitch": 60},
                    {"start": "1/2", "duration": "1/2", "pitch": 60}],
            "alternate": [{"start": "0", "duration": "1", "pitch": 60}],
            "attacks": [0], "evidence_complete": True,
            "context_durations": ["1/2"] * 4}


@pytest.mark.parametrize("order,labels", PRESENTATIONS)
def test_order_and_labels_are_independent_and_targets_do_not_enter_model_input(order, labels):
    c = fixture()
    before = copy.deepcopy(c)
    data = music_data(c, order, labels)
    assert data["candidates"][0]["id"] == labels[order[0]]
    assert data["candidates"][1]["id"] == labels[order[1]]
    assert parse_answer(json.dumps({"choice": labels[1]}), labels) == 1
    text = json.dumps(data)
    assert not any(s in text for s in ("NEVER-PROMPT", "private-id", "private-category", "is_original"))
    assert c == before
    assert data["observed_attack_ticks"] == [0]


@pytest.mark.parametrize("order,labels", PRESENTATIONS)
def test_lookup_control_not_solved_by_first_position(order, labels):
    data = control_data(29, order, labels)
    correct = next(c["id"] for c in data["candidates"] if c["marker"] == data["desired_marker"])
    assert parse_answer(json.dumps({"choice": correct}), labels) == 1
    assert parse_answer('{"choice":"abstain"}', labels) is None


@pytest.mark.parametrize("text", ['{"choice":"C"}', '{"choice":true}', '{"choice":"A","reason":"x"}',
                                  '[]', 'A', '```json\n{"choice":"A"}\n```'])
def test_malformed_response_not_silently_repaired(text):
    with pytest.raises((ValueError, TypeError)):
        parse_answer(text, ("A", "B"))


@pytest.mark.parametrize("value,expected", [("1/3", 8), ("2/3", 16), (".125", 3), (".5", 12)])
def test_exact_time_codec(value, expected):
    assert ticks(value) == expected


def test_unrepresentable_time_rejected():
    with pytest.raises(ValueError):
        ticks("1/7")


def rows():
    return [{"id": "case", "presentation": i, "status": "scored", "category": "clean",
             "choice": 0 if i == 0 else 1, "correct": i == 0} for i in range(4)]


def test_summary_reports_damage_in_reverse_presentations():
    result = group_summary(rows(), ["case"])
    assert result["correct_presentations"] == 1
    assert result["all_presentations_correct_cases"] == 0
    assert result["content_choice_disagreement_cases"] == 1
    assert result["clean_cases_damaged_any_presentation"] == 1


@pytest.mark.parametrize("kind", ["missing", "duplicate", "failed"])
def test_incomplete_summary_is_not_subset_average(kind):
    data = rows()
    if kind == "missing":
        data.pop()
    elif kind == "duplicate":
        data[-1] = data[0]
    else:
        data[-1]["status"] = "failed"
    assert group_summary(data, ["case"]) is None


def test_no_evidence_abstains_despite_prior():
    c = fixture()
    c.update(evidence_complete=False, attacks=[])
    assert acoustic_costs(c) is None
    assert select_with_prior(None, [-100, -1], .1) is None


def test_zero_weight_reproduces_acoustic_rule_and_real_repeat_preserved():
    c = fixture()
    assert select_with_prior(acoustic_costs(c), [-1, -100], 0) == 1
    c["attacks"] = [0, .5]
    assert select_with_prior(acoustic_costs(c), [-100, -1], 0) == 0


@pytest.mark.parametrize("scores,weight", [([float('nan'), 0], .1), ([0, float('inf')], .1),
                                           ([0, 0], -1), ([0, 0], float('nan'))])
def test_invalid_scoring_not_used(scores, weight):
    with pytest.raises(ValueError):
        select_with_prior([0, 1], scores, weight)

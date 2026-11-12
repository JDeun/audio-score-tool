"""Bounded articulation/accent research regression tests, not product QA."""
from __future__ import annotations

import itertools

import numpy as np
import pytest

from scripts.bar_sum_articulation import (
    GATE_HYPOTHESES,
    extract_audio_accents,
    gate_cost,
    search_articulation_phases,
    sha256_audio,
    solve_articulation,
    synthetic_beat_audio,
)
from scripts.bar_sum_rhythm import (
    Clock,
    Observation,
    candidates,
    notation_cost,
    structural_check,
)
from scripts.run_bar_sum_articulation import (
    ALL_PROFILES,
    ARMS,
    aggregate,
    assess,
    new_performance,
)
from scripts.run_bar_sum_rhythm import authored_scores


@pytest.fixture
def phrase():
    return authored_scores()[0]


def test_hypotheses_are_fixed_and_have_unity():
    assert GATE_HYPOTHESES[0] == (1.0, 0.0)
    assert all(0 < g <= 1 and p >= 0 for g, p in GATE_HYPOTHESES)


@pytest.mark.parametrize("profile", ("mixed_gate", "variable_short_gate"))
def test_generated_new_profiles_use_immutable_note_identity(phrase, profile):
    obs, seed = new_performance(phrase, profile)
    obs2, seed2 = new_performance(phrase, profile)
    assert seed == seed2 and obs == obs2
    assert [(x.id, x.pitch) for x in obs] == [
        (x.id, x.pitch) for x in phrase["notes"]
    ]
    assert all(x.offset > x.onset for x in obs)


def test_staccato_gate_cost_is_lower_for_plausible_longer_duration():
    from scripts.bar_sum_rhythm import WrittenNote

    clock = Clock(4, 4, 120)
    obs = Observation("n", 60, 0.0, 7.0 * clock.tick_seconds)
    long_note = WrittenNote("n", 60, 0, 12)
    naive = 0.35 * ((long_note.end - 7.0) / 2.0) ** 2
    score, gate = gate_cost(long_note, obs, clock)
    assert score < naive
    assert gate in (0.5, 0.75)


def test_gate_model_does_not_change_a_clean_long_sustain():
    from scripts.bar_sum_rhythm import WrittenNote

    clock = Clock(4, 4, 120)
    note = WrittenNote("n", 60, 0, 12)
    score, gate = gate_cost(
        note, Observation("n", 60, 0, 12 * clock.tick_seconds), clock
    )
    assert score == pytest.approx(0)
    assert gate == 1.0


def test_exact_shortest_path_matches_exhaustive_two_note_costs():
    clock = Clock(4, 4, 120)
    obs = (
        Observation("a", 60, .01, .38),
        Observation("b", 62, .48, .82),
    )
    phase = 0
    brute = []
    for (n1, _), (n2, _) in itertools.product(
        candidates(obs[0], clock), candidates(obs[1], clock)
    ):
        if n1.end > n2.start:
            continue
        cost = (
            gate_cost(n1, obs[0], clock)[0]
            + gate_cost(n2, obs[1], clock)[0]
            + notation_cost(0, n1.start, phase, clock.bar, False)
            + notation_cost(n1.start, n1.end, phase, clock.bar, True)
            + notation_cost(n1.end, n2.start, phase, clock.bar, False)
            + notation_cost(n2.start, n2.end, phase, clock.bar, True)
        )
        brute.append(cost)
    inferred = solve_articulation(obs, clock, phase)
    assert inferred.solution.cost == pytest.approx(min(brute), abs=1e-9)
    assert structural_check(inferred.solution, clock, obs)["bar_sums_exact"]


@pytest.mark.parametrize("num,den,bpm,unit", (
    (4, 4, 120, 1), (3, 4, 120, 1), (6, 8, 60, 1.5)
))
def test_explicit_meter_and_beat_unit(num, den, bpm, unit):
    clock = Clock(num, den, bpm, unit)
    assert clock.bar == 12 * 4 * num // den
    assert clock.tick_seconds > 0


def test_ambiguous_phase_stays_unselected():
    clock = Clock(4, 4, 120)
    obs = tuple(Observation(str(i), 60, i * .5, (i + 1) * .5)
                for i in range(6))
    inferred = search_articulation_phases(obs, clock)
    assert len(inferred["candidate_phases"]) >= 2
    assert inferred["selected_phase"] is None


@pytest.mark.parametrize("phase", (0, 6, 12))
def test_waveform_audio_features_are_deterministic_and_phase_blind(phase):
    clock = Clock(4, 4, 120)
    samples = synthetic_beat_audio(clock, phase, 192, 12)
    first, energy = extract_audio_accents(samples, clock, 192)
    second, energy2 = extract_audio_accents(samples, clock, 192)
    assert np.array_equal(energy, energy2)
    assert first == second
    assert sha256_audio(samples) == sha256_audio(samples.copy())
    assert len(first) > 0
    assert all(0 <= time <= 192 and 0 <= amp <= 1 for time, amp in first)


def test_silence_yields_no_audio_accent():
    clock = Clock(4, 4, 120)
    accents, _ = extract_audio_accents(np.zeros(120000), clock, 100)
    assert accents == ()


def test_corrupt_waveforms_are_rejected():
    clock = Clock(4, 4, 120)
    with pytest.raises(ValueError):
        extract_audio_accents(np.array([float("nan")] * 200), clock, 48)
    with pytest.raises(ValueError):
        synthetic_beat_audio(clock, -1, 100, 0)


def test_sampled_known_phase_is_only_diagnostic(phrase):
    row = assess(phrase, "clean")
    assert row["status"] == "scored"
    assert set(row["arms"]) == set(ARMS)
    assert row["arms"]["old_joint_notation"]["truth_phase_provided"] is True
    assert row["arms"]["articulation_joint"]["truth_phase_provided"] is True
    for name in ARMS[2:]:
        assert row["arms"][name]["truth_phase_provided"] is False
    assert row["arms"]["old_joint_notation"]["metrics"]["note_pair_exact"] == 1.0
    assert row["arms"]["articulation_joint"]["metrics"]["note_pair_exact"] == 1.0


def test_new_profile_pairing_and_repeatability(phrase):
    first = assess(phrase, "mixed_gate")
    second = assess(phrase, "mixed_gate")
    assert first["observation_sha256"] == second["observation_sha256"]
    assert first["audio_sha256"] == second["audio_sha256"]
    assert first["arms"]["articulation_joint"] == second["arms"]["articulation_joint"]


def test_aggregate_refuses_partial_completions(phrase):
    case = assess(phrase, "clean")
    assert aggregate([case], ["other"]) is None
    assert aggregate([case, case], [case["id"], "other"]) is None


def test_aggregate_is_finite_for_complete_single_case(phrase):
    case = assess(phrase, "clean")
    # This is a unit test of arithmetic only; real study predeclares all cases.
    full = aggregate([case], [case["id"]])
    assert full is not None
    assert full["case_count"] == 1
    assert full["old_joint_notation"]["note_pair_exact"] == 1.0
    assert full["paired_changes"]["better_cases"] == 0
    assert all(v["decided"] + v["abstained"] == 1
               for v in (full[name] for name in ARMS[2:]))


def test_trial_profiles_cover_repeated_and_new_conditions():
    assert "staccato" in ALL_PROFILES
    assert "variable_short_gate" in ALL_PROFILES


def test_known_phase_invariants_for_compound_meter():
    phrase = next(x for x in authored_scores() if x["name"] == "compound_68")
    row = assess(phrase, "mixed_gate")
    a = row["arms"]["articulation_joint"]
    assert a["structure"]["invariant"]
    assert a["structure"]["nonoverlap"]
    assert a["structure"]["bar_sums_exact"]
    assert [(n["id"], n["pitch"]) for n in a["notes"]] == [
        (n.id, n.pitch) for n in phrase["notes"]
    ]


def test_written_truth_never_enters_articulation_solver(phrase):
    rows = assess(phrase, "weak_accent")
    obs_digest = rows["observation_sha256"]
    assert obs_digest != rows["reference_sha256"]
    assert rows["note_count"] == len(phrase["notes"])
    assert rows["arms"]["articulation_joint"]["search_cost"] >= 0
    assert all("reference" not in k for k in rows["arms"]["articulation_joint"])

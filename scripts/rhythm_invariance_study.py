"""Same-score multi-take controls and separate real same-groove evaluation.

Only authored controls have canonical onset truth. GMD supplies same-beat task
labels, not canonical written scores. Neither scope measures audio transcription,
written sounding durations, complete engraving or perceived naturalness.
"""

from __future__ import annotations

import math
import random
from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import asdict
from fractions import Fraction
from itertools import combinations
from statistics import mean

from scripts.performed_rhythm_invariance import (
    KIT_PITCHES,
    METHODS,
    Event,
    Q,
    canonical_fingerprint,
    fingerprint,
)

FAMILIES = (
    "four_on_floor_eighth", "offbeat_kick", "anticipated_snare",
    "sixteenth_hats", "literal_triplet_long", "literal_dotted_hats",
    "mixed_thirds_sparse", "syncopated_holes",
)
PROFILES = ("straight", "light_swing", "triplet_swing", "strong_swing", "changing_swing")
TEMPOS = (80, 120, 160)
TAKES = (0, 1, 2, 3)
MASTER_SEED = "performed-rhythm-invariance-v1-20261112"
SYNTHETIC_METHODS = METHODS + ("always_four_on_floor",)
REAL_METHODS = METHODS + ("phase_best_single", "instrument_inventory",
                          "velocity_weighted_straight", "constant_profile")
PAIR_EPSILON = 1e-12
STUDY_SETTINGS = {
    "authored_families": list(FAMILIES), "expression_profiles": list(PROFILES),
    "nominal_tempos": list(TEMPOS), "takes": list(TAKES), "master_seed": MASTER_SEED,
    "synthetic_main_cases": 480, "synthetic_counterfactual_cases": 4,
    "synthetic_stationary_in_vocabulary_cases": 384,
    "synthetic_nonstationary_out_of_vocabulary_cases": 96,
    "real_cases": 40, "synthetic_length_q": 8, "real_length_q": 60,
    "all_authored_family_inventories": {"kick": 8, "snare": 4, "closed_hihat": 16},
    "real_distance": "minimum total variation across diagnostic global-phase bar profiles",
    "real_profile_normalization": "unit total mass, no BPM or absolute duration",
    "real_gallery": "all other drummers; no training; nearest-example retrieval",
    "nearest_tie_epsilon": PAIR_EPSILON,
    "synthetic_tempo_variants_independent": False,
    "real_pair_samples_independent": False,
    "velocity_used_for_rhythm_selection": False,
    "real_profile_can_include_invalid_full_score_fit": True,
    "real_single_phase_control": "one minimum-MSE phase per take; ties follow declared phase order",
    "real_candidate_min_can_choose_different_phase_per_pair": True,
    "straight_narrow_wide_profiles_identical_by_design": True,
    "observational_counterfactuals_scored_separately": True,
}


def _written(family: str) -> tuple[tuple[int, int], ...]:
    """Two authored 4/4 bars, all with exactly the same instrument inventory."""
    if family not in FAMILIES:
        raise ValueError("unknown authored family")
    kick = [12 * b for b in range(8)]
    snare = [12 * b for b in (1, 3, 5, 7)]
    hats = [12 * b + p for b in range(8) for p in (0, 6)]
    if family == "offbeat_kick":
        kick = [12 * b + 6 for b in range(8)]
    elif family == "anticipated_snare":
        snare = [12 * b - 3 for b in (1, 3, 5, 7)]
    elif family == "sixteenth_hats":
        hats = [12 * b + p for b in range(8) for p in (0, 3)]
    elif family == "literal_triplet_long":
        hats = [12 * b + p for b in range(8) for p in (0, 8)]
    elif family == "literal_dotted_hats":
        hats = [12 * b + p for b in range(8) for p in (0, 9)]
    elif family == "mixed_thirds_sparse":
        hats = [24 * b + p for b in range(4) for p in (0, 4, 8, 18)]
    elif family == "syncopated_holes":
        hats = [tick + 3 if tick in (30, 78) else tick for tick in hats]
        kick = [48 * bar + p for bar in range(2) for p in (0, 18, 24, 42)]
    return tuple(sorted([(0, t) for t in kick] + [(1, t) for t in snare]
                        + [(2, t) for t in hats]))


def _phase(profile: str, beat: int) -> Fraction:
    if profile == "changing_swing":
        return Fraction(14, 25) if beat < 4 else Fraction(7, 10)
    return {"straight": Fraction(1, 2), "light_swing": Fraction(3, 5),
            "triplet_swing": Fraction(2, 3), "strong_swing": Fraction(3, 4)}[profile]


def _warp(tick: int, profile: str) -> Fraction:
    beat, remainder = divmod(tick, Q)
    phase, fraction = _phase(profile, beat), Fraction(remainder, Q)
    return beat + (2 * fraction * phase if remainder <= 6
                   else phase + 2 * (fraction - Fraction(1, 2)) * (1 - phase))


def _clock(bpm: int, take: int) -> list[float]:
    boundaries = [0.5]  # supplied preroll permits a slightly early first attack
    for beat in range(8):
        variation = 0 if take == 0 else 0.08 * math.sin(2 * math.pi * beat / 8)
        boundaries.append(boundaries[-1] + 60 / bpm * (1 + variation))
    return boundaries


def _to_seconds(q: float, boundaries: list[float]) -> float:
    index = min(max(math.floor(q), 0), len(boundaries) - 2)
    return boundaries[index] + (q - index) * (boundaries[index + 1] - boundaries[index])


def _to_beats(seconds: float, boundaries: list[float]) -> float:
    index = min(max(bisect_right(boundaries, seconds) - 1, 0), len(boundaries) - 2)
    return index + (seconds - boundaries[index]) / (boundaries[index + 1] - boundaries[index])


def _seed(profile: str, take: int) -> int:
    # Common random numbers across score families and tempos: expression does not
    # encode the hidden family, and tempo replicas are explicitly not independent.
    return int(fingerprint([MASTER_SEED, profile, take])[:16], 16)


def _make_case(family: str, profile: str, take: int, bpm: int,
               case_id: str | None = None, counterfactual: str | None = None) -> dict:
    written = _written(family)
    rng, clock = random.Random(_seed(profile, take)), _clock(bpm, take)
    intermediate = []
    raw_performance = []
    for ordinal, (instrument, tick) in enumerate(written):
        q = float(_warp(tick, profile))
        if take:
            offsets = ((-0.006, 0.012, 0.003) if take == 1
                       else (0.008, 0.018, -0.004) if take == 2
                       else (-0.005, 0.015, 0.005))
            amplitude = (0, 0.008, 0.012, 0.020)[take]
            q += offsets[instrument] + rng.uniform(-amplitude, amplitude)
            if take == 3:
                q += 0.012 * math.sin(math.pi * tick / 48)
        if take == 0:
            velocity = 100
        elif take == 1:
            velocity = (102 if tick % 12 == 0 else 72) + rng.randint(-6, 6)
        elif take == 2:
            velocity = (72 if tick % 12 == 0 else 104) + rng.randint(-6, 6)
        else:
            velocity = rng.randint(45, 118)
        onset_s = _to_seconds(q, clock)
        offset_s = _to_seconds(q + 0.08 + 0.01 * (ordinal % 3), clock)
        observed_q = _to_beats(onset_s, clock)
        intermediate.append((observed_q, instrument, velocity, tick, ordinal))
        raw_performance.append([instrument, onset_s, offset_s, velocity])
    intermediate.sort(key=lambda x: (x[0], x[1], x[4]))
    events, truth = [], []
    for i, (q, instrument, velocity, tick, _) in enumerate(intermediate):
        event_id = f"e{i:06d}"
        events.append(Event(event_id, instrument, q, velocity))
        truth.append({"event_id": event_id, "instrument": instrument, "tick": tick})
    identity = case_id or f"syn/{family}/{profile}/take{take}/bpm{bpm}"
    return {
        "id": identity, "scope": "synthetic_exact_onsets", "events": tuple(events),
        "length_q": 8.0,
        "evaluation": {"family": family, "profile": profile, "take": take,
                       "nominal_bpm": bpm, "truth": truth,
                       "truth_fingerprint": canonical_fingerprint(written),
                       "counterfactual_pair": counterfactual},
        "receipt": {"status": "complete", "seed": _seed(profile, take),
                    "input_events_sha256": fingerprint([asdict(e) for e in events]),
                    "performed_seconds_sha256": fingerprint(raw_performance),
                    "supplied_clock_sha256": fingerprint(clock), "event_count": len(events),
                    "clock_condition": "supplied exact generated beat boundaries; not inferred",
                    "velocity_histogram": dict(sorted(Counter(e.velocity for e in events).items())),
                    "source_is_human_performance": False},
    }


def synthetic_plan() -> list[str]:
    result = [f"syn/{family}/{profile}/take{take}/bpm{bpm}"
              for family in FAMILIES for profile in PROFILES for take in TAKES for bpm in TEMPOS]
    return result + [f"counterfactual/{kind}/{target}" for kind in ("two_to_one", "three_to_one")
                     for target in ("swung_eighth", "literal_written")]


def prepare_synthetic() -> list[dict]:
    result = [_make_case(family, profile, take, bpm)
              for family in FAMILIES for profile in PROFILES for take in TAKES for bpm in TEMPOS]
    for pair, profile, literal in (("two_to_one", "triplet_swing", "literal_triplet_long"),
                                   ("three_to_one", "strong_swing", "literal_dotted_hats")):
        result.append(_make_case("four_on_floor_eighth", profile, 0, 120,
                                 f"counterfactual/{pair}/swung_eighth", pair))
        result.append(_make_case(literal, "straight", 0, 120,
                                 f"counterfactual/{pair}/literal_written", pair))
    if [c["id"] for c in result] != synthetic_plan():
        raise ValueError("synthetic plan changed")
    return result


def _fit_receipt(fit: dict) -> dict:
    return {key: fit[key] for key in ("phase", "canonical_fingerprint", "mse_q2",
                                     "max_abs_residual_q", "tie_count", "collision_count")}


def _contains_truth(fit: dict, truth: list[dict]) -> bool:
    expected = {t["event_id"]: t for t in truth}
    if (len(expected) != len(truth) or len(fit["assignments"]) != len(truth)
            or len({a["event_id"] for a in fit["assignments"]}) != len(truth)):
        return False
    return all(a["event_id"] in expected
               and a["instrument"] == expected[a["event_id"]]["instrument"]
               and expected[a["event_id"]]["tick"] in a["alternatives"]
               for a in fit["assignments"])


def _best_exact(fit: dict, truth: list[dict]) -> int:
    expected = {t["event_id"]: (t["instrument"], t["tick"]) for t in truth}
    return sum(expected.get(a["event_id"]) == (a["instrument"], a["tick"])
               for a in fit["assignments"])


def _constant_assignments(events: tuple[Event, ...]) -> list[dict]:
    by_instrument = defaultdict(list)
    for instrument, tick in _written("four_on_floor_eighth"):
        by_instrument[instrument].append(tick)
    ordered = defaultdict(list)
    for event in events:
        ordered[event.instrument].append(event)
    if {k: len(v) for k, v in ordered.items()} != {k: len(v) for k, v in by_instrument.items()}:
        raise ValueError("constant-score control requires declared identical inventory")
    return [{"event_id": e.event_id, "instrument": instrument, "tick": tick,
             "alternatives": [tick]}
            for instrument, group in sorted(ordered.items())
            for e, tick in zip(sorted(group, key=lambda e: (e.onset_q, e.event_id)),
                               by_instrument[instrument])]


def evaluate_synthetic(cases: list[dict], predictions: dict[str, dict]) -> dict:
    rows = []
    constant = canonical_fingerprint(_written("four_on_floor_eighth"))
    for case in cases:
        prediction, evaluation = predictions[case["id"]], case["evaluation"]
        truth, target = evaluation["truth"], evaluation["truth_fingerprint"]
        arms = {}
        for method in METHODS:
            arm = prediction["arms"][method]
            diagnostic = min(arm["diagnostic_fit_indices"],
                             key=lambda i: (prediction["fits"][i]["mse_q2"], i))
            selected = arm["selected_fingerprint"]
            selected_exact_hits = (min(_best_exact(prediction["fits"][i], truth)
                                       for i in arm["retained_fit_indices"]
                                       if prediction["fits"][i]["canonical_fingerprint"] == selected)
                                   if selected is not None else None)
            arms[method] = {
                "status": arm["status"], "selected_fingerprint": selected,
                "selected_correct": (selected == target and selected_exact_hits == len(truth))
                if selected is not None else None,
                "selected_multiset_correct": selected == target if selected is not None else None,
                "selected_exact_hits": selected_exact_hits,
                "truth_in_retained_candidates": any(_contains_truth(prediction["fits"][i], truth)
                                                     for i in arm["retained_fit_indices"]),
                "candidate_fingerprints": arm["candidate_fingerprints"],
                "candidate_fingerprints_exhaustive": arm["candidate_fingerprints_exhaustive"],
                "diagnostic_exact_hits": _best_exact(prediction["fits"][diagnostic], truth),
                "diagnostic_fit_index": diagnostic,
            }
        constant_fit = {"assignments": _constant_assignments(case["events"])}
        arms["always_four_on_floor"] = {
            "status": "decided", "selected_fingerprint": constant,
            "selected_correct": constant == target and _best_exact(constant_fit, truth) == len(truth),
            "selected_multiset_correct": constant == target,
            "selected_exact_hits": _best_exact(constant_fit, truth),
            "truth_in_retained_candidates": constant == target,
            "candidate_fingerprints": [constant], "candidate_fingerprints_exhaustive": True,
            "diagnostic_exact_hits": _best_exact(constant_fit, truth),
            "diagnostic_fit_index": None,
        }
        rows.append({"id": case["id"], "family": evaluation["family"],
                     "profile": evaluation["profile"], "take": evaluation["take"],
                     "nominal_bpm": evaluation["nominal_bpm"],
                     "counterfactual_pair": evaluation["counterfactual_pair"],
                     "event_count": len(truth), "truth_fingerprint": target,
                     "event_content_fingerprint": case["receipt"]["input_events_sha256"],
                     "prediction_content_fingerprint": fingerprint(prediction),
                     "fits": [_fit_receipt(fit) for fit in prediction["fits"]], "arms": arms})
    main = [r for r in rows if r["counterfactual_pair"] is None]
    family_rows, summaries = [], {}
    for method in SYNTHETIC_METHODS:
        entries = [r["arms"][method] for r in main]
        same_pairs = different_pairs = same_decided_equal = different_decided_equal = 0
        different_both_decided = 0
        for left, right in combinations(main, 2):
            a, b = left["arms"][method]["selected_fingerprint"], right["arms"][method]["selected_fingerprint"]
            if left["family"] == right["family"]:
                same_pairs += 1
                same_decided_equal += a is not None and b is not None and a == b
            else:
                different_pairs += 1
                different_both_decided += a is not None and b is not None
                different_decided_equal += a is not None and b is not None and a == b
        method_families = []
        for family in FAMILIES:
            group = [r for r in main if r["family"] == family]
            if not group:
                continue
            outcomes = [r["arms"][method] for r in group]
            selected = [a["selected_fingerprint"] for a in outcomes]
            all_decided = all(value is not None for value in selected)
            stable = all_decided and len(set(selected)) == 1
            correct = stable and all(a["selected_correct"] is True for a in outcomes)
            common = set(outcomes[0]["candidate_fingerprints"])
            for arm in outcomes[1:]:
                common.intersection_update(arm["candidate_fingerprints"])
            item = {"method": method, "family": family, "cases": len(group),
                    "all_takes_same_decision": stable, "all_takes_same_correct_score": correct,
                    "all_takes_same_wrong_score": stable and not correct,
                    "truth_in_every_retained_candidate_set": all(a["truth_in_retained_candidates"] for a in outcomes),
                    "common_representative_candidates": sorted(common),
                    "common_candidates_exhaustive": all(a["candidate_fingerprints_exhaustive"] for a in outcomes),
                    "grouping_used_for_inference": False}
            family_rows.append(item)
            method_families.append(item)
        strata = []
        for profile in PROFILES:
            subset = [r for r in main if r["profile"] == profile]
            if subset:
                strata.append({"profile": profile, "cases": len(subset),
                               "correct": sum(r["arms"][method]["selected_correct"] is True for r in subset),
                               "wrong": sum(r["arms"][method]["selected_correct"] is False for r in subset),
                               "abstained": sum(r["arms"][method]["selected_fingerprint"] is None for r in subset),
                               "truth_in_candidates": sum(r["arms"][method]["truth_in_retained_candidates"] for r in subset)})
        summaries[method] = {
            "cases": len(main), "correct": sum(a["selected_correct"] is True for a in entries),
            "wrong": sum(a["selected_correct"] is False for a in entries),
            "abstained": sum(a["selected_fingerprint"] is None for a in entries),
            "truth_in_candidates": sum(a["truth_in_retained_candidates"] for a in entries),
            "diagnostic_exact_hits": sum(a["diagnostic_exact_hits"] for a in entries),
            "total_hits": sum(r["event_count"] for r in main),
            "selected_exact_hits": sum(a["selected_exact_hits"] for a in entries
                                       if a["selected_exact_hits"] is not None),
            "selected_total_hits": sum(r["event_count"] for r in main
                                       if r["arms"][method]["selected_fingerprint"] is not None),
            "selected_multiset_correct_cases": sum(a["selected_multiset_correct"] is True for a in entries),
            "all_takes_correct_families": sum(r["all_takes_same_correct_score"] for r in method_families),
            "stable_wrong_families": sum(r["all_takes_same_wrong_score"] for r in method_families),
            "same_family_pairs": same_pairs, "same_family_decided_equal_pairs": same_decided_equal,
            "different_family_pairs": different_pairs, "different_family_both_decided_pairs": different_both_decided,
            "different_family_decided_collision_pairs": different_decided_equal,
            "correct_cases_gained_vs_straight": sum(
                r["arms"][method]["selected_correct"] is True
                and r["arms"]["straight_narrow"]["selected_correct"] is not True for r in main),
            "correct_cases_lost_vs_straight": sum(
                r["arms"][method]["selected_correct"] is not True
                and r["arms"]["straight_narrow"]["selected_correct"] is True for r in main),
            "by_regime": [{"regime": regime, "cases": len(group),
                           "correct": sum(r["arms"][method]["selected_correct"] is True for r in group),
                           "wrong": sum(r["arms"][method]["selected_correct"] is False for r in group),
                           "abstained": sum(r["arms"][method]["selected_fingerprint"] is None for r in group),
                           "truth_in_candidates": sum(r["arms"][method]["truth_in_retained_candidates"] for r in group)}
                          for regime, group in (
                              ("stationary_in_vocabulary", [r for r in main if r["profile"] != "changing_swing"]),
                              ("nonstationary_out_of_vocabulary", [r for r in main if r["profile"] == "changing_swing"]))],
            "by_profile": strata,
        }
    controls = []
    for pair in sorted({r["counterfactual_pair"] for r in rows if r["counterfactual_pair"]}):
        group = [r for r in rows if r["counterfactual_pair"] == pair]
        if len(group) != 2:
            raise ValueError("counterfactual pair incomplete")
        if (group[0]["event_content_fingerprint"] != group[1]["event_content_fingerprint"]
                or group[0]["prediction_content_fingerprint"] != group[1]["prediction_content_fingerprint"]
                or group[0]["truth_fingerprint"] == group[1]["truth_fingerprint"]):
            raise ValueError("identical-observation counterfactual contract failed")
        controls.append({"pair": pair, "ids": [r["id"] for r in group],
                         "inputs_identical": group[0]["event_content_fingerprint"] == group[1]["event_content_fingerprint"],
                         "predictions_identical": group[0]["prediction_content_fingerprint"] == group[1]["prediction_content_fingerprint"],
                         "targets_differ": group[0]["truth_fingerprint"] != group[1]["truth_fingerprint"],
                         "arms": {method: {
                             "decisions": [r["arms"][method]["selected_fingerprint"] for r in group],
                             "correct": sum(r["arms"][method]["selected_correct"] is True for r in group),
                             "wrong": sum(r["arms"][method]["selected_correct"] is False for r in group),
                             "truth_in_candidates": sum(r["arms"][method]["truth_in_retained_candidates"] for r in group),
                         } for method in SYNTHETIC_METHODS}})
    return {"case_rows": rows, "families": family_rows, "identifiability_controls": controls,
            "summary": {"main_cases": len(main), "counterfactual_cases": len(rows) - len(main),
                        "methods": summaries, "canonical_target": "instrument and exact onset tick multiset only"}}


def _normalize(values: list[float]) -> list[float]:
    if any(not math.isfinite(v) or v < 0 for v in values) or sum(values) <= 0:
        raise ValueError("nonnegative nonempty profile required")
    total = math.fsum(values)
    return [v / total for v in values]


def _features(case: dict, prediction: dict) -> dict[str, list[list[float]]]:
    out = {}
    for method in METHODS:
        out[method] = [_normalize([v for kit in prediction["fits"][i]["profile"] for v in kit])
                       for i in prediction["arms"][method]["diagnostic_fit_indices"]]
    best = min(range(len(prediction["fits"])), key=lambda i: (prediction["fits"][i]["mse_q2"], i))
    out["phase_best_single"] = [_normalize([v for kit in prediction["fits"][best]["profile"] for v in kit])]
    inventory = Counter(e.instrument for e in case["events"])
    out["instrument_inventory"] = [_normalize([inventory[i] for i in range(len(KIT_PITCHES))])]
    weighted = [0.0] * (len(KIT_PITCHES) * 48)
    velocities = {e.event_id: e.velocity for e in case["events"]}
    for assignment in prediction["fits"][0]["assignments"]:
        weighted[assignment["instrument"] * 48 + assignment["tick"] % 48] += velocities[assignment["event_id"]]
    out["velocity_weighted_straight"] = [_normalize(weighted)]
    out["constant_profile"] = [[1.0]]
    return out


def profile_distance(left: list[list[float]], right: list[list[float]]) -> float:
    if not left or not right or any(len(a) != len(b) for a in left for b in right):
        raise ValueError("incompatible profile candidates")
    return min(math.fsum(abs(x - y) for x, y in zip(a, b)) / 2 for a in left for b in right)


def _distance_summary(positive: list[float], negative: list[float]) -> dict:
    pairs = len(positive) * len(negative)
    auc = (sum(1.0 if p < n - PAIR_EPSILON else 0.5 if abs(p - n) <= PAIR_EPSILON else 0.0
               for p in positive for n in negative) / pairs) if pairs else None
    return {"same_groove_pairs": len(positive), "different_groove_pairs": len(negative),
            "same_mean_distance": mean(positive) if positive else None,
            "different_mean_distance": mean(negative) if negative else None,
            "pair_separation_auc": auc,
            "same_zero_distance_pairs": sum(d <= PAIR_EPSILON for d in positive),
            "different_zero_distance_pairs": sum(d <= PAIR_EPSILON for d in negative)}


def evaluate_real(cases: list[dict], predictions: dict[str, dict]) -> dict:
    features = {c["id"]: _features(c, predictions[c["id"]]) for c in cases}
    case_by_id = {c["id"]: c for c in cases}
    pair_rows, distances = [], {}
    for left, right in combinations(cases, 2):
        le, re = left["evaluation"], right["evaluation"]
        if le["drummer"] == re["drummer"]:
            continue
        values = {method: profile_distance(features[left["id"]][method], features[right["id"]][method])
                  for method in REAL_METHODS}
        distances[left["id"], right["id"]] = values
        distances[right["id"], left["id"]] = values
        equality = {}
        for method in METHODS:
            a = predictions[left["id"]]["arms"][method]["selected_fingerprint"]
            b = predictions[right["id"]]["arms"][method]["selected_fingerprint"]
            equality[method] = {"both_decided": a is not None and b is not None,
                                "same_decided_score": a is not None and b is not None and a == b}
        pair_rows.append({"left": left["id"], "right": right["id"],
                          "same_groove": le["groove"] == re["groove"],
                          "distances": values, "strict_canonical": equality})
    retrievals = []
    for query in cases:
        qe = query["evaluation"]
        gallery = [c for c in cases if c["evaluation"]["drummer"] != qe["drummer"]]
        for method in REAL_METHODS:
            if not gallery:
                continue
            best = min(distances[query["id"], c["id"]][method] for c in gallery)
            nearest = [c["id"] for c in gallery
                       if distances[query["id"], c["id"]][method] <= best + PAIR_EPSILON]
            labels = {case_by_id[i]["evaluation"]["groove"] for i in nearest}
            status = "ambiguous" if len(labels) != 1 else "correct" if qe["groove"] in labels else "wrong"
            retrievals.append({"query": query["id"], "drummer": qe["drummer"],
                               "groove": qe["groove"], "method": method,
                               "gallery_size": len(gallery), "minimum_distance": best,
                               "nearest_ids": nearest, "status": status,
                               "correct_groove_in_nearest_set": qe["groove"] in labels})
    method_summaries = {}
    for method in REAL_METHODS:
        positive = [p["distances"][method] for p in pair_rows if p["same_groove"]]
        negative = [p["distances"][method] for p in pair_rows if not p["same_groove"]]
        rows = [r for r in retrievals if r["method"] == method]
        summary = _distance_summary(positive, negative)
        summary.update({"queries": len(rows), "correct": sum(r["status"] == "correct" for r in rows),
                        "wrong": sum(r["status"] == "wrong" for r in rows),
                        "ambiguous": sum(r["status"] == "ambiguous" for r in rows),
                        "correct_in_nearest_set": sum(r["correct_groove_in_nearest_set"] for r in rows),
                        "by_held_out_drummer": []})
        baseline = {r["query"]: r["status"] for r in retrievals if r["method"] == "straight_narrow"}
        summary["correct_queries_gained_vs_straight"] = sum(
            r["status"] == "correct" and baseline[r["query"]] != "correct" for r in rows)
        summary["correct_queries_lost_vs_straight"] = sum(
            r["status"] != "correct" and baseline[r["query"]] == "correct" for r in rows)
        for drummer in sorted({r["drummer"] for r in rows}):
            group = [r for r in rows if r["drummer"] == drummer]
            summary["by_held_out_drummer"].append({"drummer": drummer, "queries": len(group),
                                                  **{status: sum(r["status"] == status for r in group)
                                                     for status in ("correct", "wrong", "ambiguous")}})
        if method in METHODS:
            summary["strict_canonical"] = {
                "decided_takes": sum(predictions[c["id"]]["arms"][method]["selected_fingerprint"] is not None for c in cases),
                "same_groove_decided_equal_pairs": sum(p["same_groove"] and p["strict_canonical"][method]["same_decided_score"] for p in pair_rows),
                "different_groove_decided_collision_pairs": sum(not p["same_groove"] and p["strict_canonical"][method]["same_decided_score"] for p in pair_rows),
            }
        method_summaries[method] = summary
    equal_tempo_controls = []
    for labels in (("groove1", "groove7"), ("groove2", "groove9")):
        subset = {c["id"] for c in cases if c["evaluation"]["groove"] in labels}
        pairs = [p for p in pair_rows if p["left"] in subset and p["right"] in subset]
        equal_tempo_controls.append({"grooves": list(labels), "cases": len(subset),
                                    "methods": {method: _distance_summary(
                                        [p["distances"][method] for p in pairs if p["same_groove"]],
                                        [p["distances"][method] for p in pairs if not p["same_groove"]])
                                        for method in REAL_METHODS}})
    case_rows = [{"id": c["id"], "evaluation": c["evaluation"],
                  "event_count": len(c["events"]),
                  "event_content_fingerprint": fingerprint([asdict(e) for e in c["events"]]),
                  "prediction_content_fingerprint": fingerprint(predictions[c["id"]]),
                  "fits": [_fit_receipt(f) for f in predictions[c["id"]]["fits"]],
                  "arms": predictions[c["id"]]["arms"],
                  "feature_sha256": {method: fingerprint(features[c["id"]][method]) for method in REAL_METHODS}}
                 for c in cases]
    return {"case_rows": case_rows, "pair_rows": pair_rows, "retrieval_rows": retrievals,
            "same_bpm_controls": equal_tempo_controls,
            "summary": {"cases": len(cases), "cross_drummer_pairs": len(pair_rows),
                        "methods": method_summaries, "canonical_notation_truth_available": False,
                        "retrieval_is_closed_ten_groove_example_comparison": True}}


def evaluate_study(prepared_cases: list[dict], predictions: dict[str, dict]) -> dict:
    """Evaluation-only labels are first consulted after every prediction is saved."""
    ids = [c["id"] for c in prepared_cases]
    if len(ids) != len(set(ids)) or set(ids) != set(predictions):
        raise ValueError("complete one-to-one prediction population required")
    if any(c["receipt"].get("status") != "complete" for c in prepared_cases):
        raise ValueError("source failure cannot be silently excluded")
    if (len(prepared_cases) != 524 or {c["scope"] for c in prepared_cases}
            != {"synthetic_exact_onsets", "real_same_groove"}):
        raise ValueError("unknown scope or full planned denominator changed")
    synthetic = [c for c in prepared_cases if c["scope"] == "synthetic_exact_onsets"]
    real = [c for c in prepared_cases if c["scope"] == "real_same_groove"]
    if [c["id"] for c in synthetic] != synthetic_plan() or len(real) != 40:
        raise ValueError("frozen population incomplete")
    expected_groups = {(f"groove{g}", d) for g in range(1, 11)
                       for d in ("drummer1", "drummer5", "drummer7", "drummer8")}
    if {(c["evaluation"]["groove"], c["evaluation"]["drummer"]) for c in real} != expected_groups:
        raise ValueError("real paired-group population changed")
    for case in prepared_cases:
        validate_prediction(case, predictions[case["id"]])
    return {
        "synthetic": evaluate_synthetic(synthetic, predictions),
        "real": evaluate_real(real, predictions),
        "limitations": [
            "Synthetic canonical truth covers only instrument and onset positions, not full note/rest spelling.",
            "Expression profiles are authored mathematical transformations, not measured human performers.",
            "Synthetic clock boundaries and real MIDI pulse/bar origin are supplied, not inferred from audio.",
            "Independent takes do not receive grouping, labels, BPM, filenames or ground-truth scores.",
            "The bounded global phase warp also transforms thirds; it is not a universal swing convention.",
            "The changing-swing stress changes both stationarity and phase-vocabulary support (0.56/0.70).",
            "GMD same-beat instructions are not canonical written-score or every-hit equivalence labels.",
            "Real bar-profile distances fold bar order and may use fits rejected as complete scores.",
            "Phase-candidate minimum distance can choose a different phase for each pair; single-phase control fixes one per take.",
            "Straight narrow/wide profile retrieval is identical by construction; only full-score acceptance differs.",
            "Nearest-example retrieval is restricted to ten known grooves and three other drummers.",
            "Tempos, synthetic takes and real pairs are dependent; no independent-sample interval is claimed.",
            "Input mutation checks are not MIDI export, perceptual naturalness or audio-transcription validation.",
        ],
    }


def validate_prediction(case: dict, prediction: dict) -> None:
    """Check identity/mass/canonical consistency before counting any outcome."""
    from scripts.performed_rhythm_invariance import PHASES, POSITION_TICKS

    if [f["phase"] for f in prediction["fits"]] != [list(p) for p in PHASES]:
        raise ValueError("phase population changed")
    if set(prediction["arms"]) != set(METHODS):
        raise ValueError("method population changed")
    observed = [(e.event_id, e.instrument) for e in case["events"]]
    for fit in prediction["fits"]:
        assignments = fit["assignments"]
        if [(a["event_id"], a["instrument"]) for a in assignments] != observed:
            raise ValueError("prediction attack identity changed")
        profile = [[0] * 48 for _ in KIT_PITCHES]
        counts = Counter()
        for assignment in assignments:
            alternatives = assignment["alternatives"]
            if (not alternatives or alternatives != sorted(set(alternatives))
                    or assignment["tick"] != alternatives[0]
                    or any(type(t) is not int or not 0 <= t < Q * case["length_q"]
                           or t % Q not in POSITION_TICKS for t in alternatives)):
                raise ValueError("invalid canonical alternatives")
            profile[assignment["instrument"]][assignment["tick"] % 48] += 1
            counts[assignment["instrument"], assignment["tick"]] += 1
        if profile != fit["profile"] or sum(map(sum, profile)) != len(observed):
            raise ValueError("profile mass or positions changed")
        if canonical_fingerprint(counts.elements()) != fit["canonical_fingerprint"]:
            raise ValueError("canonical fingerprint mismatch")
        if (fit["tie_count"] != sum(len(a["alternatives"]) > 1 for a in assignments)
                or fit["collision_count"] != sum(n - 1 for n in counts.values())):
            raise ValueError("ambiguity or collision count mismatch")
        if any(not math.isfinite(fit[k]) or fit[k] < 0 for k in ("mse_q2", "max_abs_residual_q")):
            raise ValueError("invalid residual statistics")
        if fit["mse_q2"] > fit["max_abs_residual_q"] ** 2 + 1e-12:
            raise ValueError("residual moments inconsistent")
    for arm in prediction["arms"].values():
        diagnostic, retained = arm["diagnostic_fit_indices"], arm["retained_fit_indices"]
        if (not diagnostic or any(type(i) is not int or not 0 <= i < len(prediction["fits"]) for i in diagnostic)
                or not set(retained) <= set(diagnostic)):
            raise ValueError("invalid fit index population")
        fingerprints = sorted({prediction["fits"][i]["canonical_fingerprint"] for i in retained})
        if arm["candidate_fingerprints"] != fingerprints:
            raise ValueError("retained candidate hash mismatch")
        selected = arm["selected_fingerprint"]
        if selected is not None and (arm["status"] != "decided" or fingerprints != [selected]
                                     or any(prediction["fits"][i]["tie_count"]
                                            or prediction["fits"][i]["collision_count"] for i in retained)):
            raise ValueError("unsupported decisive score")

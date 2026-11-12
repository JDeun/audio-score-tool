"""Evaluation-only repeated-rhythm study and balanced authored controls.

Every selector input is limited to immutable attacks and the supplied span.
Written identities, context labels and source alignments enter only after all
predictions are frozen. Repeated input skeletons are hypotheses, not score truth.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import zipfile
from collections import Counter, defaultdict
from dataclasses import asdict
from fractions import Fraction
from itertools import combinations, product
from pathlib import Path

from scripts import rhythm_invariance_study as legacy
from scripts import same_score_expression_study as previous
from scripts.repeat_context_phase import METHODS, OnsetEvent, path_from_index
from scripts.same_score_expression_study import (
    _count_outcomes,
    _fit_summary,
    _outcome,
    fingerprint,
    signature,
    target_tick,
)

SYNTHETIC_METHODS = METHODS + ("always_four_on_floor",)
SCOPES = ("reused_authored", "factorial_authored", "reused_real", "additional_real")
REAL_IDS = tuple(f"nasap{i:03d}" for i in range(1, 9))
STYLES = ("AAAA", "ABAB", "AAAB", "ABCD")
STATIONARITY = ("stationary", "changing")
SUPPORT = ("supported", "outside")
PHASE_PAIRS = {"supported": (Fraction(1, 2), Fraction(2, 3)),
               "outside": (Fraction(11, 20), Fraction(43, 60))}
MASTER_SEED = "repeat-context-factorial-v1-20261113"
PITCHES = previous.PITCHES
Q = 12
EPS = 1e-9
BASELINE_ZIP = "docs/research/receipts/same-score-expression-43247249315.zip"
BASELINE_BYTES = 319774
BASELINE_SHA256 = "38107d18e89058ef4e870214e0ba5af0bb7b97eb92d1b7ef056e9096c30c7f17"
BASELINE_REPORT_SHA256 = "0b5b2d14c7f49c75a18413d9876dd8960e224c06131b8e5c47e4f47657860a1a"
STUDY_SETTINGS = {
    "cohort_order": list(SCOPES), "cohort_case_counts": [484, 1028, 4, 4],
    "planned_cases": 1520, "factorial_main_cases": 1024,
    "factorial_counterfactual_cases": 4, "factorial_length_q": 16,
    "factorial_base_patterns": list(legacy.FAMILIES), "written_context_styles": list(STYLES),
    "phase_stationarity": list(STATIONARITY), "phase_support": list(SUPPORT),
    "phase_pairs": {k: [[p.numerator, p.denominator] for p in v] for k, v in PHASE_PAIRS.items()},
    "phase_pair_separation_q": [1, 6], "trajectory_variants": [0, 1], "takes": [0, 1, 2, 3],
    "factorial_nominal_bpm": 120, "master_seed": MASTER_SEED,
    "nonzero_tick_rotation_cycle": [3, 4, 6, 8, 9],
    "written_rotation_steps": {"A": 0, "B": 1, "C": 2, "D": 3},
    "factorial_attack_inventory": {"kick": 16, "snare": 8, "closed_hihat": 32},
    "phase_and_expression_labels_reach_selector": False,
    "factorial_cases_independent": False, "reused_controls_are_holdout": False,
    "primary_method": "repeat_soft010", "primary_comparator": "local_switch005",
    "velocity_used_for_selection": False,
}


def reused_plan():
    return previous.synthetic_plan()


def factorial_plan():
    return [f"fac{i:04d}" for i in range(1, 1029)]


def prepare_reused_inputs():
    return [{**case, "scope": "reused_authored"} for case in previous.prepare_synthetic_inputs()]


def load_reused_evaluation():
    return previous.load_synthetic_evaluation()


def _written_context(family, style):
    if family not in legacy.FAMILIES or style not in STYLES:
        raise ValueError("unknown authored pattern or context")
    base = [(instrument, tick) for instrument, tick in legacy._written(family) if tick < 48]
    cycle = (3, 4, 6, 8, 9)
    result = []
    for block, letter in enumerate(style):
        rotation = "ABCD".index(letter)
        for instrument, tick in base:
            quarter, position = divmod(tick, 12)
            if position:
                position = cycle[(cycle.index(position) + rotation) % len(cycle)]
            result.append((instrument, block * 48 + quarter * 12 + position))
    return tuple(sorted(result))


def _trajectory(stationarity, support, variant):
    if stationarity not in STATIONARITY or support not in SUPPORT or variant not in (0, 1):
        raise ValueError("unknown expression condition")
    pair = PHASE_PAIRS[support]
    return tuple(pair[variant if stationarity == "stationary" else (block + variant) % 2]
                 for block in range(4))


def _warp(tick, phases):
    quarter, position = divmod(tick, 12)
    phase, fraction = phases[quarter // 4], Fraction(position, 12)
    return quarter + (2 * fraction * phase if position <= 6
                      else phase + 2 * (fraction - Fraction(1, 2)) * (1 - phase))


def _make_case(cid, family, style, stationarity, support, variant, take, *, written=None,
               phases=None, counterfactual=None):
    written = _written_context(family, style) if written is None else written
    phases = _trajectory(stationarity, support, variant) if phases is None else phases
    # The two factorial axes share exactly the same random stream for a given
    # trajectory variant/take. Noise must not be a second changed factor.
    seed = int(fingerprint([MASTER_SEED, variant, take])[:16], 16)
    rng = random.Random(seed)
    clock = [0.5]
    for quarter in range(16):
        variation = 0 if take == 0 else .08 * math.sin(2 * math.pi * quarter / 16)
        clock.append(clock[-1] + .5 * (1 + variation))
    intermediate, raw_performance = [], []
    for ordinal, (instrument, tick) in enumerate(written):
        q = float(_warp(tick, phases))
        if take:
            offsets = ((-.006, .012, .003) if take == 1
                       else (.008, .018, -.004) if take == 2 else (-.005, .015, .005))
            q += offsets[instrument] + rng.uniform(-(0, .008, .012, .020)[take], (0, .008, .012, .020)[take])
            if take == 3:
                q += .012 * math.sin(math.pi * tick / 96)
        velocity = (100 if take == 0 else (102 if tick % 12 == 0 else 72) + rng.randint(-6, 6)
                    if take == 1 else (72 if tick % 12 == 0 else 104) + rng.randint(-6, 6)
                    if take == 2 else rng.randint(45, 118))
        onset = legacy._to_seconds(q, clock)
        offset = legacy._to_seconds(q + .08 + .01 * (ordinal % 3), clock)
        observed = legacy._to_beats(onset, clock)
        intermediate.append((observed, instrument, velocity, tick, ordinal))
        raw_performance.append([instrument, onset, offset, velocity])
    intermediate.sort(key=lambda row: (row[0], row[1], row[4]))
    events, truth = [], []
    for i, (q, instrument, velocity, tick, _) in enumerate(intermediate):
        eid = f"e{i:06d}"
        events.append(OnsetEvent(eid, PITCHES[instrument], q, velocity))
        truth.append({"event_id": eid, "pitch": PITCHES[instrument], "tick": tick})
    return {"id": cid, "scope": "factorial_authored", "length_q": 16., "events": tuple(events),
            "receipt": {"status": "complete", "seed": seed,
                        "input_events_sha256": fingerprint([asdict(e) for e in events]),
                        "performed_seconds_sha256": fingerprint(raw_performance),
                        "supplied_clock_sha256": fingerprint(clock), "event_count": len(events),
                        "clock_condition": "supplied exact generated beat boundaries; not inferred",
                        "velocity_histogram": dict(sorted(Counter(e.velocity for e in events).items())),
                        "source_is_human_performance": False, "reused_development_control": False},
            "evaluation": {"status": "complete", "family": family + "/" + style,
                           "base_pattern": family, "written_context": style,
                           "profile": stationarity + "/" + support, "stationarity": stationarity,
                           "vocabulary_support": support, "trajectory_variant": variant,
                           "phase_trajectory": [[p.numerator, p.denominator] for p in phases],
                           "take": take, "nominal_bpm": 120, "truth": truth,
                           "truth_fingerprint": signature((t["pitch"], t["tick"]) for t in truth),
                           "counterfactual_pair": counterfactual}}


def _factorial_cases():
    result = []
    for family, style, stationary, support, variant, take in product(
            legacy.FAMILIES, STYLES, STATIONARITY, SUPPORT, (0, 1), (0, 1, 2, 3)):
        result.append(_make_case(f"fac{len(result) + 1:04d}", family, style, stationary, support, variant, take))
    for pair, phase, literal in (("changing_two_to_one", Fraction(2, 3), "literal_triplet_long"),
                                 ("changing_three_to_one", Fraction(3, 4), "literal_dotted_hats")):
        phases = (Fraction(1, 2), phase, Fraction(1, 2), phase)
        performed = _make_case(f"fac{len(result) + 1:04d}", "four_on_floor_eighth", "AAAA",
                               "changing", "supported", 0, 0, phases=phases, counterfactual=pair)
        a = [(i, t) for i, t in legacy._written("four_on_floor_eighth") if t < 48]
        b = [(i, t) for i, t in legacy._written(literal) if t < 48]
        written = tuple(sorted((i, block * 48 + t) for block in range(4) for i, t in (a if block % 2 == 0 else b)))
        alternate = _make_case(f"fac{len(result) + 2:04d}", "four_on_floor_eighth", "ABAB",
                               "stationary", "supported", 0, 0, written=written,
                               phases=(Fraction(1, 2),) * 4, counterfactual=pair)
        alternate["evaluation"]["family"] = "counterfactual_alternating/" + literal
        if performed["events"] != alternate["events"]:
            raise ValueError("new counterfactuals must have byte-identical observed attacks")
        if performed["evaluation"]["truth_fingerprint"] == alternate["evaluation"]["truth_fingerprint"]:
            raise ValueError("counterfactual truths must differ")
        result.extend((performed, alternate))
    if [c["id"] for c in result] != factorial_plan():
        raise ValueError("fixed factorial population changed")
    return result


def prepare_factorial_inputs():
    return [{k: v for k, v in case.items() if k != "evaluation"} for case in _factorial_cases()]


def load_factorial_evaluation():
    return {case["id"]: case["evaluation"] for case in _factorial_cases()}


def _mask_indices(encoded, block_count):
    if not isinstance(encoded, str) or not encoded or any(c not in "0123456789abcdef" for c in encoded):
        raise ValueError("invalid joint candidate mask")
    bits = int(encoded, 16)
    if format(bits, "x") != encoded or bits.bit_length() > 4 ** block_count:
        raise ValueError("noncanonical or oversized joint candidate mask")
    while bits:
        lowest = bits & -bits
        yield lowest.bit_length() - 1
        bits ^= lowest


def validate_prediction(case, prediction):
    """Check identities and the actual joint path sets before public evaluation."""
    events = case["events"]
    identities = [(e.event_id, e.pitch) for e in events]
    if not identities or len({eid for eid, _ in identities}) != len(identities):
        raise ValueError("nonempty unique attack identities required")
    if set(prediction["arms"]) != set(METHODS) or set(prediction["path_sets"]) != set(METHODS):
        raise ValueError("fixed method population changed")
    if [f["phase"] for f in prediction["fits"]] != [list(p) for p in previous.PHASES]:
        raise ValueError("fixed phase vocabulary changed")
    size = math.ceil(case["length_q"] / 4)
    membership = [min(size - 1, max(0, math.floor(e.onset_q / 4))) for e in events]
    if prediction["event_block_indices"] != membership or len(prediction["blocks"]) != size:
        raise ValueError("fixed block partition changed")
    for fit in prediction["fits"]:
        assignments = fit["assignments"]
        if [(a["event_id"], a["pitch"]) for a in assignments] != identities:
            raise ValueError("phase fit changed attack identity")
        for a in assignments:
            ticks = a["alternatives"]
            if (not ticks or ticks != sorted(set(ticks)) or a["tick"] != ticks[0]
                    or any(type(t) is not int or target_tick(t / 12, case["length_q"]) != t for t in ticks)
                    or not math.isfinite(a["abs_residual_q"]) or a["abs_residual_q"] < 0):
                raise ValueError("invalid phase candidate")
        if fit["canonical_fingerprint"] != signature((a["pitch"], a["tick"]) for a in assignments):
            raise ValueError("phase fingerprint changed")
    for method in METHODS:
        arm, paths = prediction["arms"][method], prediction["path_sets"][method]
        decoded = {}
        for prefix in ("diagnostic", "full"):
            indices = list(_mask_indices(paths[prefix + "_mask_hex"], size))
            decoded[prefix] = {i: path_from_index(i, size) for i in indices}
            if len(indices) != paths[prefix + "_path_count"]:
                raise ValueError("joint candidate count changed")
            states = [sorted({p[b] for p in decoded[prefix].values()}) for b in range(size)]
            if states != paths[prefix + "_retained_states"]:
                raise ValueError("joint candidate state projection changed")
            assignments = arm["diagnostic_assignments" if prefix == "diagnostic" else "full_candidate_assignments"]
            if [(a["event_id"], a["pitch"]) for a in assignments] != identities:
                raise ValueError("arm changed attack identity")
            for i, a in enumerate(assignments):
                ticks = sorted({t for s in states[membership[i]]
                                if prefix == "full" or prediction["fits"][s]["assignments"][i]["abs_residual_q"] <= .08 + 1e-12
                                for t in prediction["fits"][s]["assignments"][i]["alternatives"]})
                if a["candidate_ticks"] != ticks:
                    raise ValueError("candidate union differs from joint masks")
                if prefix == "diagnostic" and a["selected_tick"] != (ticks[0] if len(ticks) == 1 else None):
                    raise ValueError("unsupported event decision")
        if not decoded["diagnostic"] or not decoded["full"].keys() <= decoded["diagnostic"].keys():
            raise ValueError("invalid full candidate subset")
        for p in decoded["full"].values():
            if any(prediction["blocks"][b]["max_abs_residual_q"][s] > .08 + 1e-12 for b, s in enumerate(p)):
                raise ValueError("full candidate bypassed residual gate")
        chosen = arm["full_selected_assignments"]
        if chosen is None:
            if arm["full_selected_fingerprint"] is not None or arm["full_status"] == "decided":
                raise ValueError("full decision missing assignments")
        elif ([(a["event_id"], a["pitch"]) for a in chosen] != identities
              or any(a["candidate_ticks"] != [b["tick"]] for a, b in zip(arm["full_candidate_assignments"], chosen, strict=True))
              or len({(a["pitch"], a["tick"]) for a in chosen}) != len(chosen)
              or arm["full_selected_fingerprint"] != signature((a["pitch"], a["tick"]) for a in chosen)):
            raise ValueError("invalid strict full decision")
    for method in ("straight_narrow", "global_phase", "local_switch005"):
        if prediction["baseline_arm_content_fingerprints"][method] != fingerprint(prediction["arms"][method]):
            raise ValueError("baseline arm changed")


def joint_truth_available(case, prediction, method, truth, *, full):
    if not truth:
        return None
    indices = {e.event_id: i for i, e in enumerate(case["events"])}
    allowed = [set(range(4)) for _ in prediction["blocks"]]
    for eid, (pitch, tick) in truth.items():
        if eid not in indices or tick is None:
            return False
        i = indices[eid]
        if case["events"][i].pitch != pitch:
            return False
        block = prediction["event_block_indices"][i]
        allowed[block] &= {s for s in range(4)
                           if tick in prediction["fits"][s]["assignments"][i]["alternatives"]
                           and prediction["fits"][s]["assignments"][i]["abs_residual_q"] <= .08 + 1e-12}
    if any(not states for states in allowed):
        return False
    mask = int(prediction["path_sets"][method]["full_mask_hex" if full else "diagnostic_mask_hex"], 16)
    for phases in product(*[sorted(states) for states in allowed]):
        index = 0
        for state in phases:
            index = 4 * index + state
        if mask & (1 << index):
            return True
    return False


def _arm_summary(prediction, method):
    arm, paths = prediction["arms"][method], prediction["path_sets"][method]
    return {"full_status": arm["full_status"], "full_selected_fingerprint": arm["full_selected_fingerprint"],
            "diagnostic_status_counts": dict(Counter(a["status"] for a in arm["diagnostic_assignments"])),
            "diagnostic_collision_count": arm["diagnostic_collision_count"],
            "path_set_fingerprint": fingerprint(paths),
            **{k: v for k, v in paths.items() if k not in ("diagnostic_mask_hex", "full_mask_hex")}}


def _context_summary(case, prediction, truth):
    context = prediction["repeat_context"]
    counts = Counter()
    for link in context["links"]:
        pair_status = []
        for i, j in link["event_index_pairs"]:
            left, right = (truth.get(case["events"][k].event_id) for k in (i, j))
            if left is None or right is None or left[1] is None or right[1] is None:
                status = "unscorable"
            else:
                status = "same_canonical" if (left[0], left[1] - 48 * link["left_block"]) == (right[0], right[1] - 48 * link["right_block"]) else "different_canonical"
            counts["event_pairs_" + status] += 1
            pair_status.append(status)
        # Partial ordinary truth never certifies an entire real-input repeat.
        state = "different_canonical" if "different_canonical" in pair_status else "unscorable" if "unscorable" in pair_status else "same_canonical"
        counts["links_" + state] += 1
    return {**{k: v for k, v in context.items() if k not in ("links", "eligibility")},
            "evaluation_only_link_truth": {key: counts[key] for key in (
                "links_same_canonical", "links_different_canonical", "links_unscorable",
                "event_pairs_same_canonical", "event_pairs_different_canonical", "event_pairs_unscorable")}}


def _constant_synthetic(events, length_q):
    template, inputs = defaultdict(list), defaultdict(list)
    for instrument, tick in legacy._written("four_on_floor_eighth"):
        if tick < 48:
            for block in range(int(length_q / 4)):
                template[PITCHES[instrument]].append(48 * block + tick)
    for pitch in template:
        template[pitch].sort()
    for event in events:
        inputs[event.pitch].append(event)
    if {p: len(v) for p, v in template.items()} != {p: len(v) for p, v in inputs.items()}:
        raise ValueError("constant control inventory changed")
    return {e.event_id: tick for pitch, group in inputs.items()
            for e, tick in zip(group, template[pitch], strict=True)}


def _group_summary(group, method, outcomes):
    arms = [r["arms"][method] for r in group]
    return {"cases": len(group), "full_correct": sum(a["full_correct"] is True for a in arms),
            "full_wrong": sum(a["full_correct"] is False for a in arms),
            "full_abstained": sum(a["full_correct"] is None for a in arms),
            "diagnostic_joint_truth_available": sum(a["diagnostic_joint_truth_available"] is True for a in arms),
            "retained_joint_truth_available": sum(a["retained_joint_truth_available"] is True for a in arms),
            "per_hit": _count_outcomes([v for r in group for v in outcomes[r["id"], method]])}


def _context_totals(rows):
    counts = Counter()
    reasons, truth = Counter(), Counter()
    for row in rows:
        context = row["repeat_context"]
        for key in ("block_count", "eligible_block_count", "link_count", "linked_event_pair_count", "distinct_linked_event_count", "unlinked_event_count"):
            counts[key] += context[key]
        counts["cases_with_links"] += context["link_count"] > 0
        reasons.update(context["eligibility_reason_counts"])
        truth.update(context["evaluation_only_link_truth"])
    return {"cases": len(rows), **counts, "eligibility_reason_counts": dict(reasons), "evaluation_only_link_truth": dict(truth)}


def evaluate_synthetic(cases, predictions, evaluations):
    rows, outcomes_by_case = [], {}
    for case in cases:
        evaluation, prediction = evaluations[case["id"]], predictions[case["id"]]
        truth = {t["event_id"]: (t["pitch"], t["tick"]) for t in evaluation["truth"]}
        events = {e.event_id: e for e in case["events"]}
        if len(truth) != len(evaluation["truth"]) or set(truth) != set(events):
            raise ValueError("authored truth identity changed")
        arms = {}
        for method in METHODS:
            arm = prediction["arms"][method]
            outcomes = [_outcome(events[a["event_id"]], a, *truth[a["event_id"]]) for a in arm["diagnostic_assignments"]]
            outcomes_by_case[case["id"], method] = outcomes
            full = arm["full_selected_assignments"]
            correct = (arm["full_selected_fingerprint"] == evaluation["truth_fingerprint"]
                       and all(truth[a["event_id"]] == (a["pitch"], a["tick"]) for a in full)) if full is not None else None
            arms[method] = {**_arm_summary(prediction, method), "full_correct": correct,
                            "per_hit": _count_outcomes(outcomes),
                            "diagnostic_joint_truth_available": joint_truth_available(case, prediction, method, truth, full=False),
                            "retained_joint_truth_available": joint_truth_available(case, prediction, method, truth, full=True)}
        constant = _constant_synthetic(case["events"], case["length_q"])
        constant_fp = signature((events[eid].pitch, t) for eid, t in constant.items())
        constant_outcomes = [_outcome(event, {"selected_tick": constant[eid], "candidate_ticks": [constant[eid]], "collision": False}, *truth[eid])
                             for eid, event in events.items()]
        outcomes_by_case[case["id"], "always_four_on_floor"] = constant_outcomes
        correct = constant_fp == evaluation["truth_fingerprint"] and all(v["status"] == "correct" for v in constant_outcomes)
        arms["always_four_on_floor"] = {"full_status": "decided", "full_selected_fingerprint": constant_fp,
                                        "full_correct": correct, "per_hit": _count_outcomes(constant_outcomes),
                                        "diagnostic_joint_truth_available": correct, "retained_joint_truth_available": correct}
        metadata = {k: evaluation[k] for k in ("family", "profile", "take", "nominal_bpm", "counterfactual_pair",
                    "base_pattern", "written_context", "stationarity", "vocabulary_support", "trajectory_variant", "phase_trajectory") if k in evaluation}
        rows.append({"id": case["id"], **metadata, "event_count": len(events),
                     "truth_fingerprint": evaluation["truth_fingerprint"],
                     "input_content_fingerprint": fingerprint([asdict(e) for e in case["events"]]),
                     "prediction_content_fingerprint": fingerprint(prediction),
                     "baseline_prediction_content_fingerprint": prediction["baseline_prediction_content_fingerprint"],
                     "repeat_context": _context_summary(case, prediction, truth),
                     "fits": [_fit_summary(f) for f in prediction["fits"]], "arms": arms})
    main = [r for r in rows if r["counterfactual_pair"] is None]
    summaries, families = {}, []
    for method in SYNTHETIC_METHODS:
        def group_summary(group):
            return _group_summary(group, method, outcomes_by_case)
        summary = group_summary(main)
        summary["by_profile"] = [{"profile": name, **group_summary([r for r in main if r["profile"] == name])}
                                 for name in sorted({r["profile"] for r in main})]
        summary["by_link_presence"] = [{"has_links": value, **group_summary([r for r in main if bool(r["repeat_context"]["link_count"]) == value])}
                                       for value in (False, True)]
        if main and "written_context" in main[0]:
            summary["factorial_cells"] = [{"written_context": style, "stationarity": stationary, "vocabulary_support": support,
                                            **group_summary([r for r in main if (r["written_context"], r["stationarity"], r["vocabulary_support"]) == (style, stationary, support)])}
                                           for style, stationary, support in product(STYLES, STATIONARITY, SUPPORT)]
            summary["by_trajectory_variant"] = [{"variant": v, **group_summary([r for r in main if r["trajectory_variant"] == v])} for v in (0, 1)]
            summary["by_take"] = [{"take": t, **group_summary([r for r in main if r["take"] == t])} for t in range(4)]
        for baseline in ("straight_narrow", "global_phase", "local_switch005"):
            summary[f"full_correct_gained_vs_{baseline}"] = sum(r["arms"][method]["full_correct"] is True and r["arms"][baseline]["full_correct"] is not True for r in main)
            summary[f"full_correct_lost_vs_{baseline}"] = sum(r["arms"][method]["full_correct"] is not True and r["arms"][baseline]["full_correct"] is True for r in main)
            summary[f"joint_truth_lost_vs_{baseline}"] = sum(r["arms"][method]["diagnostic_joint_truth_available"] is not True and r["arms"][baseline]["diagnostic_joint_truth_available"] is True for r in main)
        summary["full_outcomes_vs_local"] = dict(Counter(
            ("abstained" if r["arms"]["local_switch005"]["full_correct"] is None else "correct" if r["arms"]["local_switch005"]["full_correct"] else "wrong") + "_to_" +
            ("abstained" if r["arms"][method]["full_correct"] is None else "correct" if r["arms"][method]["full_correct"] else "wrong") for r in main))
        for family in sorted({r["family"] for r in main}):
            group = [r for r in main if r["family"] == family]
            if len({r["truth_fingerprint"] for r in group}) != 1:
                raise ValueError("same-family canonical truth differs")
            selected = [r["arms"][method]["full_selected_fingerprint"] for r in group]
            stable = all(s is not None for s in selected) and len(set(selected)) == 1
            correct = stable and all(r["arms"][method]["full_correct"] is True for r in group)
            families.append({"method": method, "family": family, **group_summary(group),
                             "all_cases_same_correct": correct, "all_cases_same_wrong": stable and not correct})
        pair_counts = Counter()
        # Count by histograms rather than materializing O(N^2) dependent pairs.
        by_family = defaultdict(list)
        for row in main:
            by_family[row["family"]].append(row["arms"][method]["full_selected_fingerprint"])
        all_selected = [s for group in by_family.values() for s in group if s is not None]
        same_total = same_decided = same_equal = 0
        for group in by_family.values():
            selected = [s for s in group if s is not None]
            same_total += math.comb(len(group), 2)
            same_decided += math.comb(len(selected), 2)
            same_equal += sum(math.comb(n, 2) for n in Counter(selected).values())
        pair_counts.update(same_family_pairs=same_total, same_family_both_decided=same_decided, same_family_decided_equal=same_equal,
                           different_family_pairs=math.comb(len(main), 2) - same_total,
                           different_family_both_decided=math.comb(len(all_selected), 2) - same_decided,
                           different_family_decided_equal=sum(math.comb(n, 2) for n in Counter(all_selected).values()) - same_equal)
        summary.update(pair_counts)
        summary["all_cases_correct_families"] = sum(f["all_cases_same_correct"] for f in families if f["method"] == method)
        summary["stable_wrong_families"] = sum(f["all_cases_same_wrong"] for f in families if f["method"] == method)
        summaries[method] = summary
    counterfactuals = []
    for pair in sorted({r["counterfactual_pair"] for r in rows if r["counterfactual_pair"]}):
        group = [r for r in rows if r["counterfactual_pair"] == pair]
        if (len(group) != 2 or group[0]["input_content_fingerprint"] != group[1]["input_content_fingerprint"]
                or group[0]["prediction_content_fingerprint"] != group[1]["prediction_content_fingerprint"]
                or group[0]["truth_fingerprint"] == group[1]["truth_fingerprint"]):
            raise ValueError("identical-observation control changed")
        counterfactuals.append({"pair": pair, "ids": [r["id"] for r in group], "inputs_and_predictions_identical": True,
                               "targets_differ": True, "methods": {m: group_summary_for_counterfactual(group, m) for m in SYNTHETIC_METHODS}})
    return {"case_rows": rows, "family_rows": families, "counterfactuals": counterfactuals,
            "summary": {"main_cases": len(main), "counterfactual_cases": len(rows) - len(main), "methods": summaries,
                        "context": _context_totals(main), "reused_development_controls": cases[0]["scope"] == "reused_authored"}}


def group_summary_for_counterfactual(group, method):
    return {"full_correct": sum(r["arms"][method]["full_correct"] is True for r in group),
            "full_wrong": sum(r["arms"][method]["full_correct"] is False for r in group),
            "full_abstained": sum(r["arms"][method]["full_correct"] is None for r in group),
            "diagnostic_joint_truth_available": sum(r["arms"][method]["diagnostic_joint_truth_available"] is True for r in group),
            "retained_joint_truth_available": sum(r["arms"][method]["retained_joint_truth_available"] is True for r in group)}


def evaluate_real(cases, predictions, evaluations):
    public_rows, private_outcomes, lookup = [], {}, {}
    for case in cases:
        evaluation, prediction = evaluations[case["id"]], predictions[case["id"]]
        events = {e.event_id: e for e in case["events"]}
        links = evaluation["input_links"]
        if len(links) != len(events) or {x["event_id"] for x in links} != set(events):
            raise ValueError("input classification must cover every original selected attack")
        target_notes = evaluation["target_notes"]
        if len({t["score_id"] for t in target_notes}) != len(target_notes):
            raise ValueError("unique score occurrence identities required")
        ordinary = sorted((t for t in target_notes if not t["grace"]),
                          key=lambda t: (t["onset_q"], t["pitch"], t["score_id"]))
        lookup[case["id"]] = {t["score_id"]: t for t in ordinary}
        arms = {}
        for method in METHODS:
            arm = prediction["arms"][method]
            assignments = {a["event_id"]: a for a in arm["diagnostic_assignments"]}
            outcomes, conditional_truth = {}, {}
            for target in ordinary:
                tick = target_tick(target["onset_q"], case["length_q"])
                event_id = target["event_id"]
                if target["coverage"] == "observed":
                    if event_id not in events:
                        raise ValueError("observed target lacks an input attack")
                    outcome = _outcome(events[event_id], assignments[event_id], target["pitch"], tick)
                    conditional_truth[event_id] = (target["pitch"], tick)
                else:
                    if event_id is not None:
                        raise ValueError("unobserved target has a selected input identity")
                    outcome = {"status": "unobserved", "onset_correct": None, "pitch_match": None,
                               "truth_in_diagnostic_candidates": False, "diagnostic_collision": False,
                               "lattice_supported": tick is not None}
                outcomes[target["score_id"]] = outcome
            private_outcomes[case["id"], method] = outcomes
            arms[method] = {**_arm_summary(prediction, method), **_count_outcomes(list(outcomes.values())),
                            "conditional_observed_diagnostic_truth_available": joint_truth_available(case, prediction, method, conditional_truth, full=False),
                            "conditional_observed_retained_truth_available": joint_truth_available(case, prediction, method, conditional_truth, full=True),
                            "reference_masks": {
                                "status": "".join({"correct": "C", "wrong": "W", "abstained": "A", "unobserved": "U"}[v["status"]]
                                                  for v in outcomes.values()),
                                **{key: "".join("?" if v[key] is None else "1" if v[key] else "0" for v in outcomes.values())
                                   for key in ("onset_correct", "pitch_match", "truth_in_diagnostic_candidates", "diagnostic_collision")}}}
        ordinary_fp = signature((t["pitch"], t["onset_q"]) for t in ordinary)
        public_rows.append({"id": case["id"], "score_id": evaluation["score_id"],
                            "score_sha256": evaluation["score_sha256"], "ordinary_truth_content_fingerprint": ordinary_fp,
                            "input_event_count": len(events), "ordinary_targets": len(ordinary),
                            "grace_targets": len(target_notes) - len(ordinary),
                            "reference_keys": [fingerprint([evaluation["score_sha256"], t["score_id"]]) for t in ordinary],
                            "reference_coverage": [t["coverage"] for t in ordinary],
                            "lattice_support_mask": "".join("1" if target_tick(t["onset_q"], case["length_q"]) is not None else "0" for t in ordinary),
                            "target_coverage": dict(Counter(t["coverage"] for t in target_notes)),
                            "ordinary_target_coverage": dict(Counter(t["coverage"] for t in ordinary)),
                            "input_classifications": dict(Counter(t["classification"] for t in links)),
                            "evaluation_receipt": evaluation["receipt"],
                            "input_content_fingerprint": fingerprint([asdict(e) for e in case["events"]]),
                            "prediction_content_fingerprint": fingerprint(prediction),
                            "baseline_prediction_content_fingerprint": prediction["baseline_prediction_content_fingerprint"],
                            "repeat_context": _context_summary(case, prediction, {
                                t["event_id"]: (t["pitch"], target_tick(t["onset_q"], case["length_q"]))
                                for t in ordinary if t["coverage"] == "observed"}),
                            "fits": [_fit_summary(f) for f in prediction["fits"]], "arms": arms})
    pairs, paired_reference_counts = [], {method: Counter() for method in METHODS}
    row_by_id = {r["id"]: r for r in public_rows}
    for left, right in combinations(cases, 2):
        le, re = evaluations[left["id"]], evaluations[right["id"]]
        same = le["score_id"] == re["score_id"]
        lp, rp = row_by_id[left["id"]], row_by_id[right["id"]]
        if same and (le["score_sha256"] != re["score_sha256"] or lookup[left["id"]].keys() != lookup[right["id"]].keys()
                     or lp["ordinary_truth_content_fingerprint"] != rp["ordinary_truth_content_fingerprint"]):
            raise ValueError("same-score canonical targets differ")
        if not same and (le["score_sha256"] == re["score_sha256"] or lp["ordinary_truth_content_fingerprint"] == rp["ordinary_truth_content_fingerprint"]):
            raise ValueError("different-score control is not distinct")
        methods = {}
        for method in METHODS:
            a, b = (predictions[c["id"]]["arms"][method]["full_selected_fingerprint"] for c in (left, right))
            methods[method] = {"both_strict_decided": a is not None and b is not None,
                               "strict_observed_signatures_equal": a is not None and b is not None and a == b}
            if same:
                counts, mask = Counter(), []
                left_assign = {a["event_id"]: a for a in predictions[left["id"]]["arms"][method]["diagnostic_assignments"]}
                right_assign = {a["event_id"]: a for a in predictions[right["id"]]["arms"][method]["diagnostic_assignments"]}
                left_events = {e.event_id: e for e in left["events"]}
                right_events = {e.event_id: e for e in right["events"]}
                for ref, lt in lookup[left["id"]].items():
                    rt = lookup[right["id"]][ref]
                    if (lt["pitch"], lt["onset_q"], lt["duration_q"]) != (rt["pitch"], rt["onset_q"], rt["duration_q"]):
                        raise ValueError("canonical occurrence map changed")
                    lo, ro = private_outcomes[left["id"], method][ref], private_outcomes[right["id"], method][ref]
                    if "unobserved" in (lo["status"], ro["status"]):
                        outcome = "unobserved"
                    elif "abstained" in (lo["status"], ro["status"]):
                        outcome = "abstention"
                    elif lo["status"] == ro["status"] == "correct":
                        outcome = "same_correct"
                    else:
                        ls = (left_events[lt["event_id"]].pitch, left_assign[lt["event_id"]]["selected_tick"])
                        rs = (right_events[rt["event_id"]].pitch, right_assign[rt["event_id"]]["selected_tick"])
                        outcome = "same_wrong" if ls == rs else "disagreement"
                    counts[outcome] += 1
                    mask.append({"same_correct": "C", "same_wrong": "W", "disagreement": "D", "abstention": "A", "unobserved": "U"}[outcome])
                paired_reference_counts[method].update(counts)
                methods[method]["ordinary_reference_pairs"] = {"targets": len(lookup[left["id"]]),
                    **{k: counts[k] for k in ("same_correct", "same_wrong", "disagreement", "abstention", "unobserved")}}
                methods[method]["reference_status_mask"] = "".join(mask)
        pairs.append({"left": left["id"], "right": right["id"], "same_score": same, "methods": methods})
    summaries = {}
    for method in METHODS:
        values = [v for case in cases for v in private_outcomes[case["id"], method].values()]
        summary = _count_outcomes(values)
        for baseline in ("straight_narrow", "global_phase", "local_switch005"):
            gained = lost = 0
            for case in cases:
                current, previous = private_outcomes[case["id"], method], private_outcomes[case["id"], baseline]
                for ref, outcome in current.items():
                    gained += outcome["status"] == "correct" and previous[ref]["status"] != "correct"
                    lost += outcome["status"] != "correct" and previous[ref]["status"] == "correct"
            summary[f"correct_gained_vs_{baseline}"], summary[f"correct_lost_vs_{baseline}"] = gained, lost
        summary["strict_decided_cases"] = sum(predictions[c["id"]]["arms"][method]["full_selected_fingerprint"] is not None for c in cases)
        summary["same_score_strict_equal_pairs"] = sum(p["same_score"] and p["methods"][method]["strict_observed_signatures_equal"] for p in pairs)
        summary["different_score_strict_equal_pairs"] = sum(not p["same_score"] and p["methods"][method]["strict_observed_signatures_equal"] for p in pairs)
        summary["paired_references"] = {k: paired_reference_counts[method][k]
                                        for k in ("same_correct", "same_wrong", "disagreement", "abstention", "unobserved")}
        summary["outcomes_vs_local"] = dict(Counter(
            private_outcomes[case["id"], "local_switch005"][ref]["status"] + "_to_" + outcome["status"]
            for case in cases for ref, outcome in private_outcomes[case["id"], method].items()))
        summary["by_score"] = []
        for score in sorted({r["score_id"] for r in public_rows}):
            ids = [r["id"] for r in public_rows if r["score_id"] == score]
            score_values = [v for cid in ids for v in private_outcomes[cid, method].values()]
            summary["by_score"].append({"score_id": score, "performances": len(ids), **_count_outcomes(score_values)})
        summary["equal_score_correct_rate"] = math.fsum(s["correct"] / s["targets"] for s in summary["by_score"]) / len(summary["by_score"])
        summaries[method] = summary
    constant_signature = signature((60, beat * Q) for beat in range(32))
    return {"case_rows": public_rows, "pair_rows": pairs,
            "mask_legend": {"alignment": "case masks follow reference_keys; same-score pair masks follow the left case reference_keys",
                            "case_status": {"C": "correct", "W": "wrong", "A": "abstained", "U": "unobserved"},
                            "pair_status": {"C": "same_correct", "W": "same_wrong", "D": "disagreement", "A": "abstention", "U": "unobserved"},
                            "boolean": {"1": True, "0": False, "?": None}},
            "constant_score_control": {"construction": "always 32 C4 quarter-note attacks, independent of input",
                                       "signature": constant_signature, "same_score_equal_pairs": sum(p["same_score"] for p in pairs),
                                       "different_score_equal_pairs": sum(not p["same_score"] for p in pairs),
                                       "per_hit_alignment_not_defined": True},
            "summary": {"cases": len(cases), "score_families": len({r["score_id"] for r in public_rows}),
                        "same_score_pairs": sum(p["same_score"] for p in pairs),
                        "different_score_pairs": sum(not p["same_score"] for p in pairs),
                        "input_attacks": sum(len(c["events"]) for c in cases),
                        "ordinary_targets": sum(r["ordinary_targets"] for r in public_rows),
                        "grace_targets": sum(r["grace_targets"] for r in public_rows),
                        "methods": summaries, "context": _context_totals(public_rows)}}


def _check_baseline_rows(cases, predictions, old_rows):
    lookup = {row["id"]: row for row in old_rows}
    if len(lookup) != len(old_rows) or set(lookup) != {c["id"] for c in cases}:
        raise ValueError("baseline receipt population changed")
    for case in cases:
        row, prediction = lookup[case["id"]], predictions[case["id"]]
        if row["input_content_fingerprint"] != fingerprint([asdict(e) for e in case["events"]]):
            raise ValueError("reused input differs from original receipt")
        if row["prediction_content_fingerprint"] != prediction["baseline_prediction_content_fingerprint"]:
            raise ValueError("reused baseline differs from original receipt")
    return {"cases": len(cases), "input_content_fingerprints_equal": len(cases),
            "full_original_prediction_fingerprints_equal": len(cases),
            "original_six_arm_baseline_included": True}


def baseline_parity(cases, predictions):
    """Only called by post-prediction evaluation; the old evidence is immutable."""
    source = Path(__file__).resolve().parents[1] / BASELINE_ZIP
    if source.is_symlink() or source.stat().st_size != BASELINE_BYTES:
        raise ValueError("original evidence archive size or path changed")
    raw = source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != BASELINE_SHA256:
        raise ValueError("original evidence archive digest changed")
    with zipfile.ZipFile(source) as archive:
        if archive.namelist() != ["report.json"] or archive.getinfo("report.json").file_size != 7260857:
            raise ValueError("original evidence archive members changed")
        report_bytes = archive.read("report.json")
    if hashlib.sha256(report_bytes).hexdigest() != BASELINE_REPORT_SHA256:
        raise ValueError("original evidence report digest changed")
    report = json.loads(report_bytes)
    if report["status"] != "complete" or report["source_head"] != "ce59cd16fe53072c5967cd8c1c555f8eb30ece79":
        raise ValueError("original completed baseline provenance changed")
    rows = report["evaluation"]["synthetic"]["case_rows"] + report["evaluation"]["real"]["case_rows"]
    return {**_check_baseline_rows(cases, predictions, rows),
            "original_run_id": "43247249315", "archive_sha256": BASELINE_SHA256,
            "report_sha256": BASELINE_REPORT_SHA256}


def evaluate_study(cases, predictions, evaluations):
    plans = (reused_plan(), factorial_plan(), list(REAL_IDS[:4]), list(REAL_IDS[4:]))
    expected = [cid for group in plans for cid in group]
    ids = [c["id"] for c in cases]
    if ids != expected or set(ids) != set(predictions) or set(ids) != set(evaluations):
        raise ValueError("complete ordered 1520-case population required")
    cohorts, offset = {}, 0
    for scope, planned in zip(SCOPES, plans, strict=True):
        group = cases[offset:offset + len(planned)]
        for case in group:
            if (case["scope"] != scope or case["receipt"].get("status") != "complete"
                    or evaluations[case["id"]].get("status") != "complete"):
                raise ValueError("scope or source admission incomplete")
            validate_prediction(case, predictions[case["id"]])
        if scope.endswith("real"):
            sizes = Counter(evaluations[c["id"]]["score_id"] for c in group)
            if sorted(sizes.values()) != [2, 2]:
                raise ValueError("two actual same-score pairs required in each real cohort")
            cohorts[scope] = evaluate_real(group, predictions, evaluations)
        else:
            cohorts[scope] = evaluate_synthetic(group, predictions, evaluations)
        offset += len(planned)
    parity = baseline_parity([c for c in cases if c["scope"] in ("reused_authored", "reused_real")], predictions)
    return {"cohorts": cohorts, "baseline_parity": parity, "limitations": [
        "Primary target is canonical pitch/onset attacks, with onset-only correctness separated from pitch errors.",
        "Written durations, rests, voices, notation export, acoustic beat inference and perceived naturalness are not evaluated.",
        "Velocity is preserved but does not enter the selector; this is not evidence for an accent model.",
        "All four cohorts retain their own denominators; new authored controls are development evidence, not human validation.",
        "The new factorial separates phase stationarity and vocabulary support with equal-separation balanced trajectories, but no population inference is claimed.",
        "Seeds share common random numbers across score families and written context; cases and paired references are dependent.",
        "Repeat links are input-only coarse skeleton hypotheses and can join different canonical written rhythms.",
        "An all-phase nearest tie excludes a block from repeat links; even clean .5 or 2/3 observations can therefore have no repeat evidence.",
        "No-link cases remain in every denominator and fall back to the unchanged local baseline.",
        "Soft and hard priors restrict the original near-optimal local candidate pool; they cannot create a correct candidate absent from that pool.",
        "Identical observations with different written truths remain fundamentally unidentifiable without extra context.",
        "Per-hit diagnostic decisions can coexist with collisions or invalid full sequences; joint membership is not unique score recovery.",
        "Marginal candidate unions are not Cartesian joint scores; joint truth is checked against private complete-path masks.",
        "Real MIDI beat/downbeat annotations, quarter unit and published score correspondence are supplied; robustness metadata is not independent alignment truth.",
        "Unobserved, unsupported and boundary targets remain; input grace, insertion and outside-target attacks remain preserved and classified.",
        "Alignment insertions can include ornaments and are not automatically performance errors.",
        "Ordinary-reference correctness is conditional on source correspondence and does not count every nonordinary attack as a false positive.",
        "Full real signatures compare different observed inventories and cannot establish independent rhythm discrimination.",
        "Additional BWV857/858 were selected by metadata before musical source inspection; only two new works are included, with no strong unseen-population claim.",
        "XML fractions remain canonical; new binary32 CSV admission is a serialization check, not a musical timing tolerance.",
        "Original input and prediction fingerprints verify preservation and baseline replay, not MIDI export or audio quality.",
    ]}

"""Evaluation-only same-written-score comparison and reused authored controls.

The selector receives only label-free performed events and the supplied span.
Reference identity, pitch, timing and grouping are used here after prediction
files are frozen. This measures canonical onset attacks, not full notation.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import asdict
from itertools import combinations

from scripts import rhythm_invariance_study as legacy
from scripts.same_score_phase import OnsetEvent

METHODS = (
    "straight_narrow", "straight_wide", "global_phase", "local_raw",
    "local_switch005", "local_switch010",
)
SYNTHETIC_METHODS = METHODS + ("always_four_on_floor",)
REAL_IDS = ("nasap001", "nasap002", "nasap003", "nasap004")
PITCHES = (36, 38, 42)
Q = 12
POSITIONS = (0, 3, 4, 6, 8, 9)
PHASES = ((1, 2), (3, 5), (2, 3), (3, 4))
EPS = 1e-9


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def signature(pairs):
    return fingerprint(sorted([list(pair) for pair in pairs]))


def synthetic_plan():
    if len(legacy.synthetic_plan()) != 484:
        raise ValueError("reused authored population changed")
    return [f"syn{i:03d}" for i in range(1, 485)]


def prepare_synthetic_inputs():
    """Reuse the frozen generator; do not read its constructed truth here."""
    cases = []
    for new_id, old in zip(synthetic_plan(), legacy.prepare_synthetic(), strict=True):
        events = tuple(OnsetEvent(e.event_id, PITCHES[e.instrument], e.onset_q, e.velocity)
                       for e in old["events"])
        receipt = dict(old["receipt"])
        receipt["input_events_sha256"] = fingerprint([asdict(e) for e in events])
        receipt["reused_development_control"] = True
        receipt["pitch_relabeling"] = "kick36/snare38/closed-hat42; timing and velocity unchanged"
        cases.append({"id": new_id, "scope": "synthetic_exact_onsets", "events": events,
                      "length_q": old["length_q"], "receipt": receipt})
    return cases


def load_synthetic_evaluation():
    """Called only after all synthetic and real prediction files are saved."""
    result = {}
    for new_id, old in zip(synthetic_plan(), legacy.prepare_synthetic(), strict=True):
        evaluation = dict(old["evaluation"])
        evaluation["truth"] = [{"event_id": t["event_id"], "pitch": PITCHES[t["instrument"]],
                                "tick": t["tick"]} for t in evaluation["truth"]]
        evaluation["truth_fingerprint"] = signature((t["pitch"], t["tick"])
                                                     for t in evaluation["truth"])
        evaluation["status"] = "complete"
        result[new_id] = evaluation
    return result


def target_tick(onset_q, length_q):
    """Representation epsilon only; no widened performance-time scoring gate."""
    if type(onset_q) not in (int, float) or not math.isfinite(onset_q):
        raise ValueError("finite target position required")
    raw = onset_q * Q
    tick = round(raw)
    if abs(raw - tick) > 1e-7 or not 0 <= tick < Q * length_q or tick % Q not in POSITIONS:
        return None
    return tick


def _close(a, b):
    return math.isclose(a, b, abs_tol=EPS, rel_tol=1e-12)


def validate_prediction(case, prediction):
    events = case["events"]
    observed = [(e.event_id, e.pitch) for e in events]
    if len(observed) != len(set(k for k, _ in observed)) or not observed:
        raise ValueError("nonempty unique input identities required")
    if [f["phase"] for f in prediction["fits"]] != [list(p) for p in PHASES]:
        raise ValueError("phase population changed")
    if set(prediction["arms"]) != set(METHODS):
        raise ValueError("method population changed")
    block_count = math.ceil(case["length_q"] / 4)
    expected_blocks = [min(block_count - 1, max(0, math.floor(e.onset_q / 4))) for e in events]
    if prediction["event_block_indices"] != expected_blocks or len(prediction["blocks"]) != block_count:
        raise ValueError("fixed block population changed")
    for fit in prediction["fits"]:
        assigned = fit["assignments"]
        if [(a["event_id"], a["pitch"]) for a in assigned] != observed:
            raise ValueError("phase assignment attack identity changed")
        for a in assigned:
            ticks = a["alternatives"]
            if (not ticks or ticks != sorted(set(ticks)) or a["tick"] != ticks[0]
                    or any(type(t) is not int or not 0 <= t < Q * case["length_q"]
                           or t % Q not in POSITIONS for t in ticks)
                    or not math.isfinite(a["abs_residual_q"]) or a["abs_residual_q"] < 0):
                raise ValueError("invalid canonical assignment")
        counts = Counter((a["pitch"], a["tick"]) for a in assigned)
        if fit["canonical_fingerprint"] != signature(counts.elements()):
            raise ValueError("phase fingerprint mismatch")
        if (fit["collision_count"] != sum(n - 1 for n in counts.values())
                or fit["tie_count"] != sum(len(a["alternatives"]) > 1 for a in assigned)):
            raise ValueError("phase collision or tie count changed")
        sse = math.fsum(a["abs_residual_q"] ** 2 for a in assigned)
        if (not _close(fit["sse_q2"], sse) or not _close(fit["mse_q2"], sse / len(events))
                or not _close(fit["max_abs_residual_q"], max(a["abs_residual_q"] for a in assigned))):
            raise ValueError("phase residual moments inconsistent")
    for index, block in enumerate(prediction["blocks"]):
        indices = [i for i, b in enumerate(expected_blocks) if b == index]
        if block["index"] != index or block["event_indices"] != indices:
            raise ValueError("block attack partition changed")
        for state, fit in enumerate(prediction["fits"]):
            residuals = [fit["assignments"][i]["abs_residual_q"] for i in indices]
            if (not _close(block["sse_q2"][state], math.fsum(v * v for v in residuals))
                    or not _close(block["max_abs_residual_q"][state], max(residuals, default=0))):
                raise ValueError("block costs inconsistent")
    for method, arm in prediction["arms"].items():
        diagnostic = arm["diagnostic_assignments"]
        full = arm["full_candidate_assignments"]
        if ([(a["event_id"], a["pitch"]) for a in diagnostic] != observed
                or [(a["event_id"], a["pitch"]) for a in full] != observed):
            raise ValueError("arm assignment identity changed")
        for key, assignments in (("diagnostic_graph", diagnostic), ("full_graph", full)):
            graph = arm[key]
            if (len(graph["retained_states"]) != block_count
                    or len(graph["allowed_states"]) != block_count):
                raise ValueError("graph block population changed")
            for i, a in enumerate(assignments):
                states = graph["retained_states"][expected_blocks[i]]
                if any(type(s) is not int or not 0 <= s < 4 for s in states):
                    raise ValueError("invalid retained phase state")
                ticks = sorted({t for s in states
                                if key == "full_graph" or prediction["fits"][s]["assignments"][i]["abs_residual_q"]
                                <= arm["residual_gate_q"] + 1e-12
                                for t in prediction["fits"][s]["assignments"][i]["alternatives"]})
                if a["candidate_ticks"] != ticks:
                    raise ValueError("candidate union differs from retained paths")
        for i, a in enumerate(diagnostic):
            ticks, selected = a["candidate_ticks"], a["selected_tick"]
            if selected is not None and (ticks != [selected] or a["status"] != "decided"):
                raise ValueError("unsupported per-hit decision")
            if selected is None and a["status"] == "decided":
                raise ValueError("missing per-hit decision")
        selected = arm["full_selected_assignments"]
        if selected is None:
            if arm["full_selected_fingerprint"] is not None:
                raise ValueError("fingerprint without full decision")
        else:
            if ([(a["event_id"], a["pitch"]) for a in selected] != observed
                    or any(a["candidate_ticks"] != [b["tick"]] for a, b in zip(full, selected, strict=True))
                    or len({(a["pitch"], a["tick"]) for a in selected}) != len(selected)
                    or arm["full_selected_fingerprint"] != signature((a["pitch"], a["tick"]) for a in selected)):
                raise ValueError("unsupported strict full decision")
        if method not in METHODS:
            raise ValueError("unknown method")


def _minimum_path(blocks, allowed, mode, switch):
    costs = {s: blocks[0]["sse_q2"][s] for s in allowed[0]}
    for block, states in zip(blocks[1:], allowed[1:], strict=True):
        next_costs = {}
        for state in states:
            choices = [cost + (switch if previous != state else 0)
                       for previous, cost in costs.items()
                       if mode == "local" or previous == state]
            if choices:
                next_costs[state] = min(choices) + block["sse_q2"][state]
        costs = next_costs
    return min(costs.values(), default=math.inf)


def joint_truth_available(case, prediction, method, truth, *, full):
    """Evaluation-only constrained path; do not multiply marginal alternatives."""
    if not truth:
        return None
    arm = prediction["arms"][method]
    graph = arm["full_graph" if full else "diagnostic_graph"]
    allowed = [list(states) for states in graph["allowed_states"]]
    indices = {e.event_id: i for i, e in enumerate(case["events"])}
    for event_id, (pitch, tick) in truth.items():
        if event_id not in indices or tick is None:
            return False
        index = indices[event_id]
        if case["events"][index].pitch != pitch:
            return False
        block = prediction["event_block_indices"][index]
        allowed[block] = [s for s in allowed[block]
                          if tick in prediction["fits"][s]["assignments"][index]["alternatives"]
                          and prediction["fits"][s]["assignments"][index]["abs_residual_q"]
                          <= arm["residual_gate_q"] + 1e-12]
    cost = _minimum_path(prediction["blocks"], allowed, arm["mode"], arm["switch_cost_q2"] or 0.)
    return cost <= graph["budget_sse_q2"] + EPS


def _fit_summary(fit):
    return {key: fit[key] for key in ("phase", "canonical_fingerprint", "sse_q2", "mse_q2",
                                     "max_abs_residual_q", "tie_count", "collision_count")}


def _arm_summary(arm):
    return {"full_status": arm["full_status"],
            "full_selected_fingerprint": arm["full_selected_fingerprint"],
            "diagnostic_status_counts": dict(Counter(a["status"] for a in arm["diagnostic_assignments"])),
            "diagnostic_collision_count": arm["diagnostic_collision_count"],
            "diagnostic_best_objective_q2": arm["diagnostic_graph"]["best_objective_q2"],
            "diagnostic_best_phase_indices": arm["diagnostic_graph"]["best_path"],
            "diagnostic_retained_states": arm["diagnostic_graph"]["retained_states"],
            "full_best_objective_q2": arm["full_graph"]["best_objective_q2"],
            "full_retained_states": arm["full_graph"]["retained_states"]}


def _outcome(event, assignment, pitch, tick):
    selected = assignment["selected_tick"]
    pitch_match = event.pitch == pitch
    onset_correct = tick is not None and selected == tick if selected is not None else None
    correct = onset_correct is True and pitch_match
    return {"status": "abstained" if selected is None else "correct" if correct else "wrong",
            "onset_correct": onset_correct, "pitch_match": pitch_match,
            "truth_in_diagnostic_candidates": tick is not None and tick in assignment["candidate_ticks"] and pitch_match,
            "diagnostic_collision": assignment["collision"], "lattice_supported": tick is not None}


def _count_outcomes(values):
    return {"targets": len(values),
            **{status: sum(v["status"] == status for v in values)
               for status in ("correct", "wrong", "abstained", "unobserved")},
            "observed": sum(v["status"] != "unobserved" for v in values),
            "onset_correct": sum(v["onset_correct"] is True for v in values),
            "pitch_mismatched_observations": sum(v["pitch_match"] is False for v in values),
            "lattice_supported_targets": sum(v["lattice_supported"] for v in values),
            "truth_in_diagnostic_candidates": sum(v["truth_in_diagnostic_candidates"] for v in values),
            "diagnostic_collision_observations": sum(v["diagnostic_collision"] for v in values)}


def _constant_synthetic(events):
    template = defaultdict(list)
    for instrument, tick in legacy._written("four_on_floor_eighth"):
        template[PITCHES[instrument]].append(tick)
    inputs = defaultdict(list)
    for event in events:
        inputs[event.pitch].append(event)
    if {p: len(v) for p, v in template.items()} != {p: len(v) for p, v in inputs.items()}:
        raise ValueError("constant control inventory changed")
    return {e.event_id: tick for pitch, group in inputs.items()
            for e, tick in zip(group, template[pitch], strict=True)}


def evaluate_synthetic(cases, predictions, evaluations):
    rows, private_outcomes = [], {}
    for case in cases:
        evaluation, prediction = evaluations[case["id"]], predictions[case["id"]]
        truth = {t["event_id"]: (t["pitch"], t["tick"]) for t in evaluation["truth"]}
        events = {e.event_id: e for e in case["events"]}
        if len(truth) != len(evaluation["truth"]) or set(truth) != set(events):
            raise ValueError("synthetic truth identity changed")
        arms = {}
        for method in METHODS:
            arm = prediction["arms"][method]
            outcomes = [_outcome(events[a["event_id"]], a, *truth[a["event_id"]])
                        for a in arm["diagnostic_assignments"]]
            private_outcomes[case["id"], method] = outcomes
            full = arm["full_selected_assignments"]
            correct = (arm["full_selected_fingerprint"] == evaluation["truth_fingerprint"]
                       and all(truth[a["event_id"]] == (a["pitch"], a["tick"]) for a in full)) if full is not None else None
            arms[method] = {**_arm_summary(arm), "full_correct": correct,
                            "per_hit": _count_outcomes(outcomes),
                            "diagnostic_joint_truth_available": joint_truth_available(case, prediction, method, truth, full=False),
                            "retained_joint_truth_available": joint_truth_available(case, prediction, method, truth, full=True)}
        constant = _constant_synthetic(case["events"])
        constant_fp = signature((events[eid].pitch, t) for eid, t in constant.items())
        constant_outcomes = [_outcome(event, {"selected_tick": constant[eid], "candidate_ticks": [constant[eid]],
                                             "collision": False}, *truth[eid]) for eid, event in events.items()]
        private_outcomes[case["id"], "always_four_on_floor"] = constant_outcomes
        correct = constant_fp == evaluation["truth_fingerprint"] and all(v["status"] == "correct" for v in constant_outcomes)
        arms["always_four_on_floor"] = {"full_status": "decided", "full_selected_fingerprint": constant_fp,
                                        "full_correct": correct, "per_hit": _count_outcomes(constant_outcomes),
                                        "diagnostic_joint_truth_available": correct, "retained_joint_truth_available": correct}
        rows.append({"id": case["id"], **{k: evaluation[k] for k in ("family", "profile", "take", "nominal_bpm", "counterfactual_pair")},
                     "event_count": len(events), "truth_fingerprint": evaluation["truth_fingerprint"],
                     "input_content_fingerprint": fingerprint([asdict(e) for e in case["events"]]),
                     "prediction_content_fingerprint": fingerprint(prediction),
                     "fits": [_fit_summary(f) for f in prediction["fits"]], "arms": arms})
    main = [r for r in rows if r["counterfactual_pair"] is None]
    summaries, families = {}, []
    for method in SYNTHETIC_METHODS:
        def group_summary(group):
            arms = [r["arms"][method] for r in group]
            outcomes = [v for r in group for v in private_outcomes[r["id"], method]]
            return {"cases": len(group), "full_correct": sum(a["full_correct"] is True for a in arms),
                    "full_wrong": sum(a["full_correct"] is False for a in arms),
                    "full_abstained": sum(a["full_correct"] is None for a in arms),
                    "diagnostic_joint_truth_available": sum(a["diagnostic_joint_truth_available"] is True for a in arms),
                    "retained_joint_truth_available": sum(a["retained_joint_truth_available"] is True for a in arms),
                    "per_hit": _count_outcomes(outcomes)}
        summary = group_summary(main)
        summary["by_profile"] = [{"profile": name, **group_summary([r for r in main if r["profile"] == name])}
                                 for name in legacy.PROFILES]
        summary["by_regime"] = [{"regime": name, **group_summary(group)} for name, group in (
            ("stationary_in_vocabulary", [r for r in main if r["profile"] != "changing_swing"]),
            ("changing_out_of_vocabulary", [r for r in main if r["profile"] == "changing_swing"]))]
        for baseline in ("straight_narrow", "global_phase"):
            summary[f"full_correct_gained_vs_{baseline}"] = sum(r["arms"][method]["full_correct"] is True and r["arms"][baseline]["full_correct"] is not True for r in main)
            summary[f"full_correct_lost_vs_{baseline}"] = sum(r["arms"][method]["full_correct"] is not True and r["arms"][baseline]["full_correct"] is True for r in main)
        for family in legacy.FAMILIES:
            group = [r for r in main if r["family"] == family]
            if not group:
                continue
            selected = [r["arms"][method]["full_selected_fingerprint"] for r in group]
            stable = all(s is not None for s in selected) and len(set(selected)) == 1
            correct = stable and all(r["arms"][method]["full_correct"] is True for r in group)
            families.append({"method": method, "family": family, **group_summary(group),
                             "all_cases_same_correct": correct, "all_cases_same_wrong": stable and not correct})
        pairs = Counter()
        for left, right in combinations(main, 2):
            kind = "same_family" if left["family"] == right["family"] else "different_family"
            a, b = (r["arms"][method]["full_selected_fingerprint"] for r in (left, right))
            pairs[kind + "_pairs"] += 1
            pairs[kind + "_both_decided"] += a is not None and b is not None
            pairs[kind + "_decided_equal"] += a is not None and b is not None and a == b
        summary.update(pairs)
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
                               "targets_differ": True, "methods": {m: {
                                   "full_correct": sum(r["arms"][m]["full_correct"] is True for r in group),
                                   "full_wrong": sum(r["arms"][m]["full_correct"] is False for r in group),
                                   "full_abstained": sum(r["arms"][m]["full_correct"] is None for r in group),
                                   "retained_joint_truth_available": sum(r["arms"][m]["retained_joint_truth_available"] is True for r in group)} for m in SYNTHETIC_METHODS}})
    return {"case_rows": rows, "family_rows": families, "counterfactuals": counterfactuals,
            "summary": {"main_cases": len(main), "counterfactual_cases": len(rows) - len(main),
                        "methods": summaries, "reused_development_controls": True}}


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
            arms[method] = {**_arm_summary(arm), **_count_outcomes(list(outcomes.values())),
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
        for baseline in ("straight_narrow", "global_phase"):
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
                        "methods": summaries}}


def evaluate_study(cases, predictions, evaluations):
    expected = synthetic_plan() + list(REAL_IDS)
    ids = [c["id"] for c in cases]
    if ids != expected or set(ids) != set(predictions) or set(ids) != set(evaluations):
        raise ValueError("complete ordered 488-case population required")
    for index, case in enumerate(cases):
        scope = "synthetic_exact_onsets" if index < 484 else "real_same_score"
        if case["scope"] != scope or case["receipt"].get("status") != "complete" or evaluations[case["id"]].get("status") != "complete":
            raise ValueError("scope or source admission incomplete")
        validate_prediction(case, predictions[case["id"]])
    real = cases[484:]
    group_sizes = Counter(evaluations[c["id"]]["score_id"] for c in real)
    if sorted(group_sizes.values()) != [2, 2]:
        raise ValueError("two actual same-score pairs required")
    return {"synthetic": evaluate_synthetic(cases[:484], predictions, evaluations),
            "real": evaluate_real(real, predictions, evaluations),
            "limitations": [
                "Primary target is canonical pitch/onset attacks; onset-only accuracy is also separated from pitch errors.",
                "Written duration, rests, voice, engraving and acoustic beat inference are not evaluated.",
                "Performance beat/downbeat annotations and 4/4 quarter unit are explicitly supplied.",
                "Score IDs, canonical targets, voice, grouping and filenames are evaluation-only.",
                "All original selected attacks are preserved; grace, insertions, deletions and boundary coverage are explicit.",
                "Ordinary-reference accuracy is conditioned on published source correspondence; insertions, grace and outside-target attacks are not counted as ordinary false positives.",
                "Strict full hashes compare observed inventories: the BWV848 pair has different attack counts, and cross-score inventories already differ; these are auxiliary checks, not independent rhythm discrimination.",
                "Per-hit diagnostic decisions can coexist with invalid whole-input sequences or collisions.",
                "Diagnostic best paths are before event gates; compatible truth-path existence is neither unique score recovery nor missing-note recovery.",
                "Marginal tick unions are not Cartesian joint scores; truth-path membership is evaluation-only constrained DP.",
                "Local phase is piecewise constant per four quarters and uses the same four non-early phase hypotheses.",
                "The inherited Q12 lattice may not support finer written onsets; unsupported targets remain in denominators.",
                "Two score families and reused synthetic controls are development evidence, not an independent holdout.",
                "Cases, source notes, aligned pairs and tempo replicas are dependent; no population confidence interval is claimed.",
                "Source hashes and mutation checks are not MIDI export or perceived-naturalness validation.",
            ]}

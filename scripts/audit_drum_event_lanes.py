"""Independent event-receipt audit for the frozen drum-lane experiment.

This module never imports the predictor, the experiment scorer, or the source
reference parser.  Its assignment oracle is a residual-network optimizer rather
than the scorer's chronological dynamic program / SciPy assignment routine.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

ARMS = ("global85", "global10", "independent85", "independent10")
SUPPORTED_ROLES = frozenset({"kick", "backbeat"})
COUNT_KEYS = ("reference", "predicted", "matched", "false_positives", "false_negatives")
RATE_KEYS = ("precision", "recall", "f1")
SCHEMA = "drum-event-lanes-v1"
COHORT_COUNTS = {"new_waveform": 6, "development_replay": 4, "authored_controls": 100}
STRATA = {"supported_50ms": (.05, True), "all_kit_50ms": (.05, False),
          "supported_10ms": (.01, True), "all_kit_10ms": (.01, False)}
BASE_REVISION = "b60545fb2024cd37cf74a78fe68700daa8dde622"
EXCLUSION_PATH = "docs/research/TEMPO_BEAT_MODEL_INPUTS_2026-11-12.json"
EXCLUSION_SHA256 = "6f78287bf8ab42a6df61fd8e251d154af61b2121283acd2fabbd7d9fb8764957"
NUMERIC_INVENTORY = "docs/research/RESEARCH_NUMERIC_CI_V2_FROZEN_SOURCES_2026-11-14.json"
NUMERIC_INVENTORY_SHA256 = "f2a02900899ce62d10a010104e28948c5afb75478ba310636c241000b77f2ee2"
SOURCE_FREEZE = "docs/research/DRUM_EVENT_LANES_FROZEN_SOURCES_2026-11-14.json"
CONTROL_INPUTS = "docs/research/DRUM_EVENT_LANES_CONTROL_INPUTS_2026-11-14.json"
CONTROL_INPUTS_SHA256 = "907de3e22a4ca928334bd1bae1c0a08e52b09cbfec61763000f12b566d20f731"
ENDPOINT_ALLOWANCE = 1e-12
MIDI_SHA256 = "651cbc524ffb891be1a3e46d89dc82a1cecb09a57c748c7b45b844c4841dcc1e"
METADATA_SHA256 = "3e17eef2f18012c0160c183ad5b106964eb429876cceb1eee1b746def4e6b11b"
OLD_IDS = ("drummer7/session2/93", "drummer7/session2/2",
           "drummer7/session3/87", "drummer1/session2/1")


class AuditError(ValueError):
    """The preserved evidence fails a named independent check."""


def require(condition, label):
    if not condition:
        raise AuditError(label)


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def finite_number(value):
    return type(value) in (int, float) and math.isfinite(value)


def same_number(actual, expected, label, *, tolerance=1e-12):
    require(finite_number(actual) and math.isclose(
        actual, expected, rel_tol=tolerance, abs_tol=tolerance,
    ), label)


@dataclass
class _Edge:
    target: int
    reverse: int
    capacity: int
    cost: float


def maximum_weight_assignment(reference_count, prediction_count, weighted_edges):
    """Return the maximum-weight optional one-to-one bipartite assignment.

    Successive shortest augmenting paths optimize a residual network.  Stopping
    at a nonnegative path is essential: forcing maximum cardinality can reduce
    an edit-cost objective.  Positive integer secondary rewards can express a
    maximum-association tie-break without changing the primary objective.
    """
    require(type(reference_count) is int and reference_count >= 0, "assignment reference size")
    require(type(prediction_count) is int and prediction_count >= 0, "assignment prediction size")
    size = reference_count + prediction_count + 2
    source, sink = size - 2, size - 1
    graph = [[] for _ in range(size)]

    def add(start, end, cost):
        forward = _Edge(end, len(graph[end]), 1, cost)
        graph[start].append(forward)
        graph[end].append(_Edge(start, len(graph[start]) - 1, 0, -cost))
        return forward

    for index in range(reference_count):
        add(source, index, 0.0)
    for index in range(prediction_count):
        add(reference_count + index, sink, 0.0)
    records, identities = [], set()
    for ri, pi, reward in weighted_edges:
        require(type(ri) is int and 0 <= ri < reference_count, "assignment reference index")
        require(type(pi) is int and 0 <= pi < prediction_count, "assignment prediction index")
        require((ri, pi) not in identities, "duplicate assignment edge")
        require(finite_number(reward), "nonfinite assignment reward")
        identities.add((ri, pi))
        edge = add(ri, reference_count + pi, -float(reward))
        records.append((ri, pi, edge))

    while True:
        distances = [math.inf] * size
        parents = [None] * size
        queued = [False] * size
        distances[source] = 0.0
        queue = deque([source])
        queued[source] = True
        while queue:
            start = queue.popleft()
            queued[start] = False
            for index, edge in enumerate(graph[start]):
                if not edge.capacity:
                    continue
                candidate = distances[start] + edge.cost
                if candidate < distances[edge.target] - 1e-12:
                    distances[edge.target] = candidate
                    parents[edge.target] = (start, index)
                    if not queued[edge.target]:
                        queue.append(edge.target)
                        queued[edge.target] = True
        if parents[sink] is None or distances[sink] >= -1e-12:
            break
        current = sink
        while current != source:
            prior, edge_index = parents[current]
            edge = graph[prior][edge_index]
            edge.capacity = 0
            graph[current][edge.reverse].capacity = 1
            current = prior
    return [(ri, pi) for ri, pi, edge in records if not edge.capacity]


def onset_assignment(reference, predicted, tolerance, *, class_aware=True):
    """Independently maximize matches, then minimize total absolute timing error."""
    require(finite_number(tolerance) and tolerance >= 0, "invalid matching tolerance")
    maximum = min(len(reference), len(predicted))
    cardinality_reward = 1.0 + (maximum + 1) * tolerance
    edges = []
    for ri, ref in enumerate(reference):
        for pi, pred in enumerate(predicted):
            error = abs(pred["time"] - ref["time"])
            if error <= tolerance + ENDPOINT_ALLOWANCE and (
                not class_aware or ref["role"] == pred["role"]
            ):
                edges.append((ri, pi, cardinality_reward - error))
    return maximum_weight_assignment(len(reference), len(predicted), edges)


def count_metrics(reference_count, prediction_count, matched):
    require(all(type(value) is int and value >= 0 for value in
                (reference_count, prediction_count, matched)), "noninteger metric count")
    require(matched <= min(reference_count, prediction_count), "impossible matched count")
    return {
        "reference": reference_count,
        "predicted": prediction_count,
        "matched": matched,
        "false_positives": prediction_count - matched,
        "false_negatives": reference_count - matched,
        "precision": matched / prediction_count if prediction_count else 0.0,
        "recall": matched / reference_count if reference_count else 0.0,
        "f1": 2 * matched / (reference_count + prediction_count)
        if reference_count + prediction_count else 0.0,
    }


def audit_counts(actual, expected, label):
    require(isinstance(actual, dict), label + ": missing counts")
    for name in COUNT_KEYS:
        require(type(actual.get(name)) is int and actual[name] == expected[name],
                label + ": " + name)
    for name in RATE_KEYS:
        same_number(actual.get(name), expected[name], label + ": " + name)


def validate_events(events, *, duration, prediction, label):
    require(finite_number(duration) and 0 < duration <= 24, label + ": duration")
    require(isinstance(events, list) and len(events) <= 10000, label + ": event list")
    ids = set()
    previous = -math.inf
    for event in events:
        require(isinstance(event, dict), label + ": event object")
        identity = event.get("event_id")
        require(isinstance(identity, str) and 0 < len(identity) <= 128 and identity not in ids,
                label + ": unique event id")
        ids.add(identity)
        time = event.get("time")
        require(finite_number(time) and 0 <= time < duration, label + ": event time")
        require(time >= previous, label + ": event ordering")
        previous = time
        role = event.get("role")
        require(isinstance(role, str) and bool(role), label + ": role")
        require("velocity" in event, label + ": explicit velocity availability")
        velocity = event["velocity"]
        require(velocity is None or (type(velocity) is int and 1 <= velocity <= 127),
                label + ": reference velocity")
        if prediction:
            require(role in SUPPORTED_ROLES, label + ": unsupported prediction role")
            require(velocity is None, label + ": invented predicted velocity")
            strength = event.get("strength")
            require(finite_number(strength) and 0 <= strength <= 1,
                    label + ": prediction strength")


def audit_pairs(pairs, reference, predicted, tolerance, *, class_aware, label):
    """Validate stored associations and both independent optimality objectives."""
    refs = {event["event_id"]: event for event in reference}
    preds = {event["event_id"]: event for event in predicted}
    require(isinstance(pairs, list), label + ": matched pair list")
    seen_refs, seen_preds, errors = set(), set(), []
    for pair in pairs:
        require(isinstance(pair, dict), label + ": pair object")
        ri, pi = pair.get("reference_id"), pair.get("predicted_id")
        require(ri in refs and pi in preds, label + ": pair event identity")
        require(ri not in seen_refs and pi not in seen_preds, label + ": one-to-one pairs")
        seen_refs.add(ri)
        seen_preds.add(pi)
        ref, pred = refs[ri], preds[pi]
        require(not class_aware or ref["role"] == pred["role"], label + ": pair class")
        for side, event in (("reference", ref), ("predicted", pred)):
            require(pair.get(side + "_role") == event["role"], label + ": pair role identity")
            same_number(pair.get(side + "_time"), event["time"], label + ": pair time identity")
        delta = pred["time"] - ref["time"]
        require(abs(delta) <= tolerance + ENDPOINT_ALLOWANCE, label + ": pair outside tolerance")
        same_number(pair.get("error_seconds"), delta, label + ": signed pair error")
        same_number(pair.get("absolute_error_seconds"), abs(delta), label + ": absolute pair error")
        errors.append(abs(delta))
    optimum = onset_assignment(reference, predicted, tolerance, class_aware=class_aware)
    require(len(pairs) == len(optimum), label + ": maximum match cardinality")
    optimal_error = sum(abs(reference[ri]["time"] - predicted[pi]["time"])
                        for ri, pi in optimum)
    same_number(sum(errors), optimal_error, label + ": minimum total onset error", tolerance=1e-10)
    return count_metrics(len(reference), len(predicted), len(optimum))


def audit_edit_proxy(actual, reference, predicted, label):
    """Reconstruct unit operations and independently optimize their integer cost."""
    require(isinstance(actual, dict), label + ": edit proxy")
    same_number(actual.get("association_tolerance_seconds"), .05, label + ": edit association window")
    same_number(actual.get("move_tolerance_seconds"), .005, label + ": edit movement window")
    same_number(actual.get("temporal_endpoint_allowance_seconds"), ENDPOINT_ALLOWANCE,
                label + ": edit endpoint allowance", tolerance=1e-15)
    require(actual.get("velocity_evaluated") is False, label + ": velocity unavailable")
    refs = {event["event_id"]: event for event in reference}
    preds = {event["event_id"]: event for event in predicted}
    used_refs, used_preds, reclassified, moved = set(), set(), 0, 0
    pairs = actual.get("matched_pairs")
    require(isinstance(pairs, list), label + ": edit pairs")
    for pair in pairs:
        require(isinstance(pair, dict), label + ": edit pair object")
        ri, pi = pair.get("reference_id"), pair.get("predicted_id")
        require(ri in refs and pi in preds, label + ": edit pair identity")
        require(ri not in used_refs and pi not in used_preds, label + ": one-to-one edit pairs")
        used_refs.add(ri)
        used_preds.add(pi)
        ref, pred = refs[ri], preds[pi]
        delta = pred["time"] - ref["time"]
        require(abs(delta) <= .05 + ENDPOINT_ALLOWANCE, label + ": edit pair window")
        for side, event in (("reference", ref), ("predicted", pred)):
            require(pair.get(side + "_role") == event["role"], label + ": edit role identity")
            same_number(pair.get(side + "_time"), event["time"], label + ": edit time identity")
        same_number(pair.get("error_seconds"), delta, label + ": edit signed error")
        same_number(pair.get("absolute_error_seconds"), abs(delta), label + ": edit absolute error")
        reclassified += ref["role"] != pred["role"]
        moved += abs(delta) > .005 + ENDPOINT_ALLOWANCE
    def order(event):
        return event["time"], event["event_id"]

    inserted = [event["event_id"] for event in sorted(reference, key=order)
                if event["event_id"] not in used_refs]
    deleted = [event["event_id"] for event in sorted(predicted, key=order)
               if event["event_id"] not in used_preds]
    require(actual.get("inserted_reference_ids") == inserted, label + ": edit insertion identities")
    require(actual.get("deleted_predicted_ids") == deleted, label + ": edit deletion identities")
    cost = len(inserted) + len(deleted) + reclassified + moved
    operations = {"cost": cost, "insertions": len(inserted), "deletions": len(deleted),
                  "reclassifications": reclassified, "time_moves": moved}
    for name, value in operations.items():
        require(type(actual.get(name)) is int and actual[name] == value, label + ": edit " + name)
    same_number(actual.get("normalized_cost"), cost / max(1, len(reference)), label + ": normalized edit cost")
    scale = min(len(reference), len(predicted)) + 1
    edges = []
    for ri, ref in enumerate(reference):
        for pi, pred in enumerate(predicted):
            distance = abs(ref["time"] - pred["time"])
            if distance <= .05 + ENDPOINT_ALLOWANCE:
                association_cost = int(ref["role"] != pred["role"]) + int(distance > .005 + ENDPOINT_ALLOWANCE)
                edges.append((ri, pi, (2 - association_cost) * scale + 1))
    optimum = maximum_weight_assignment(len(reference), len(predicted), edges)
    optimum_cost = len(reference) + len(predicted) - 2 * len(optimum)
    optimum_cost += sum(int(reference[ri]["role"] != predicted[pi]["role"]) +
                        int(abs(reference[ri]["time"] - predicted[pi]["time"]) > .005 + ENDPOINT_ALLOWANCE)
                        for ri, pi in optimum)
    require(cost == optimum_cost and len(pairs) == len(optimum), label + ": optimal edit objective")
    return cost


def audit_metric(actual, reference, predicted, tolerance, label):
    require(isinstance(actual, dict), label + ": metric object")
    same_number(actual.get("tolerance_seconds"), tolerance, label + ": fixed tolerance")
    same_number(actual.get("temporal_endpoint_allowance_seconds"), ENDPOINT_ALLOWANCE,
                label + ": fixed endpoint allowance", tolerance=1e-15)
    expected = audit_pairs(actual.get("matched_pairs"), reference, predicted, tolerance,
                           class_aware=True, label=label)
    audit_counts(actual, expected, label)
    roles = {event["role"] for event in reference + predicted}
    require(isinstance(actual.get("per_role"), dict) and set(actual["per_role"]) == roles,
            label + ": complete per-role inventory")
    matches = Counter(pair["reference_role"] for pair in actual["matched_pairs"])
    per_role = {}
    for role in roles:
        per_role[role] = count_metrics(sum(event["role"] == role for event in reference),
                                       sum(event["role"] == role for event in predicted), matches[role])
        audit_counts(actual["per_role"][role], per_role[role], label + "/" + role)
    for name, field in (("onset_mae_seconds", "absolute_error_seconds"),
                        ("onset_signed_mean_seconds", "error_seconds")):
        pairs = actual["matched_pairs"]
        if pairs:
            same_number(actual.get(name), sum(pair[field] for pair in pairs) / len(pairs), label + ": " + name)
        else:
            require(actual.get(name) is None, label + ": unavailable " + name)
    agnostic = actual.get("class_agnostic")
    require(isinstance(agnostic, dict), label + ": class-agnostic metric")
    agnostic_expected = audit_pairs(agnostic.get("matched_pairs"), reference, predicted, tolerance,
                                    class_aware=False, label=label + "/agnostic")
    audit_counts(agnostic, agnostic_expected, label + "/agnostic")
    confusion, tied = defaultdict(Counter), 0
    for pair in agnostic["matched_pairs"]:
        confusion[pair["reference_role"]][pair["predicted_role"]] += 1
        tied += sum(abs(event["time"] - pair["reference_time"]) == pair["absolute_error_seconds"]
                    for event in predicted) > 1
    require(agnostic.get("confusion") == {key: dict(value) for key, value in confusion.items()},
            label + ": class confusion counts")
    require(type(agnostic.get("timing_tied_pairs")) is int and agnostic["timing_tied_pairs"] == tied,
            label + ": ambiguous timing count")
    edit_cost = audit_edit_proxy(actual.get("edit_proxy"), reference, predicted, label)
    return {**expected, "per_role": per_role, "edit_cost": edit_cost}


def compare_tree(actual, expected, label):
    """Strict structure and integer/boolean checks; finite float comparisons."""
    if isinstance(expected, dict):
        require(isinstance(actual, dict) and set(actual) == set(expected), label + ": fields")
        for key in expected:
            compare_tree(actual[key], expected[key], label + "/" + key)
    elif isinstance(expected, list):
        require(isinstance(actual, list) and len(actual) == len(expected), label + ": length")
        for index, (left, right) in enumerate(zip(actual, expected, strict=True)):
            compare_tree(left, right, f"{label}/{index}")
    elif type(expected) is float:
        same_number(actual, expected, label)
    else:
        require(type(actual) is type(expected) and actual == expected, label)


def audit_recovery(actual, reference, strict_pairs, label):
    """Rebuild strict pair recovery from independently checked 10 ms matches."""
    require(isinstance(actual, dict), label + ": recovery object")
    same_number(actual.get("temporal_endpoint_allowance_seconds"), ENDPOINT_ALLOWANCE,
                label + ": recovery endpoint allowance", tolerance=1e-15)
    reference = sorted(reference, key=lambda row: (row["time"], row["event_id"]))
    matches = {pair["reference_id"]: pair for pair in strict_pairs}
    clusters = []
    for ref in reference:
        if not clusters or ref["time"] - clusters[-1][0]["time"] > .005 + ENDPOINT_ALLOWANCE:
            clusters.append([ref])
        else:
            clusters[-1].append(ref)
    simultaneous = []
    for cluster in clusters:
        if len({ref["role"] for ref in cluster}) < 2:
            continue
        pairs = [matches.get(ref["event_id"]) for ref in cluster]
        complete = all(pair is not None for pair in pairs)
        preserved = complete and all(abs(
            (pairs[j]["predicted_time"] - pairs[i]["predicted_time"]) -
            (cluster[j]["time"] - cluster[i]["time"])
        ) <= .01 + ENDPOINT_ALLOWANCE for i in range(len(cluster)) for j in range(i + 1, len(cluster)))
        simultaneous.append({"reference_ids": [ref["event_id"] for ref in cluster],
                             "predicted_ids": [pair["predicted_id"] if pair else None for pair in pairs],
                             "all_matched": complete, "gaps_preserved": preserved})
    flams = []
    for role in sorted({ref["role"] for ref in reference}):
        lane = [ref for ref in reference if ref["role"] == role]
        for left, right in zip(lane, lane[1:]):
            gap = right["time"] - left["time"]
            if not 0 < gap <= .09 + ENDPOINT_ALLOWANCE:
                continue
            first, second = matches.get(left["event_id"]), matches.get(right["event_id"])
            complete = first is not None and second is not None
            actual_gap = second["predicted_time"] - first["predicted_time"] if complete else None
            flams.append({"reference_ids": [left["event_id"], right["event_id"]],
                          "predicted_ids": [first["predicted_id"] if first else None,
                                            second["predicted_id"] if second else None],
                          "role": role, "reference_gap_seconds": gap,
                          "predicted_gap_seconds": actual_gap, "both_matched": complete,
                          "recovered": complete and actual_gap > 0 and
                          abs(actual_gap - gap) <= .01 + ENDPOINT_ALLOWANCE})
    expected = {"onset_tolerance_seconds": .01, "simultaneous_tolerance_seconds": .005,
                "gap_tolerance_seconds": .01, "flam_max_gap_seconds": .09,
                "temporal_endpoint_allowance_seconds": ENDPOINT_ALLOWANCE,
                "simultaneous": {"groups": len(simultaneous),
                                 "matched_groups": sum(row["all_matched"] for row in simultaneous),
                                 "timing_preserved_groups": sum(row["gaps_preserved"] for row in simultaneous),
                                 "details": simultaneous},
                "flam": {"pairs": len(flams), "recovered_pairs": sum(row["recovered"] for row in flams),
                         "details": flams}}
    compare_tree(actual, expected, label)
    return expected


def _safe_file(root, name):
    require(isinstance(name, str) and name and not Path(name).is_absolute()
            and ".." not in Path(name).parts, "unsafe evidence path")
    path = root / name
    require(path.resolve().is_relative_to(root.resolve()) and path.is_file() and not path.is_symlink(),
            "missing or unsafe evidence file: " + name)
    return path


def _read_json(path):
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 64 * 1024 * 1024,
            "invalid or oversized JSON evidence: " + path.name)
    raw = path.read_bytes()

    def reject_constant(value):
        raise AuditError("nonfinite JSON value: " + value)

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate JSON field: " + key)
            result[key] = value
        return result

    return json.loads(raw, parse_constant=reject_constant, object_pairs_hook=unique_object), sha256(raw)


def _hash(value, label):
    require(isinstance(value, str) and len(value) == 64 and
            all(character in "0123456789abcdef" for character in value), label)


def audit_sources(preflight, qualification, root):
    freeze, freeze_sha = _read_json(_safe_file(root, SOURCE_FREEZE))
    require(freeze.get("schema") == SCHEMA and freeze.get("base_revision") == BASE_REVISION,
            "source freeze identity")
    contract = preflight.get("source_contract")
    require(isinstance(contract, dict) and contract.get("all_equal") is True,
            "source contract availability")
    require(contract.get("base_revision") == BASE_REVISION and
            contract.get("manifest_sha256") == freeze_sha and
            contract.get("source_sha256") == freeze.get("source_sha256"),
            "source contract byte binding")
    sources = freeze.get("source_sha256")
    require(isinstance(sources, dict) and bool(sources), "empty frozen source inventory")
    for name, expected in sources.items():
        _hash(expected, "invalid frozen source hash")
        require(sha256(_safe_file(root, name).read_bytes()) == expected, "frozen source changed: " + name)
    required = {"scripts/audit_drum_event_lanes.py", "scripts/run_drum_event_lanes.py",
                "scripts/drum_event_lanes.py", "scripts/drum_event_metrics.py",
                "scripts/drum_lane_source.py", "scripts/drum_lane_controls.py", EXCLUSION_PATH, CONTROL_INPUTS,
                "scripts/gmd_audio_range_probe.py", "scripts/research_numeric_qualification.py"}
    require(required <= set(sources), "incomplete experiment source freeze")
    exclusions, exclusion_sha = _read_json(_safe_file(root, EXCLUSION_PATH))
    require(exclusion_sha == EXCLUSION_SHA256, "historical waveform inventory hash")
    prior = exclusions["inputs"]
    require(len(prior) == 16 and len({row["id"] for row in prior}) == 16,
            "historical waveform population")
    require(preflight.get("prior_waveform_inventory_sha256") == EXCLUSION_SHA256 and
            preflight.get("prior_waveform_ids") == [row["id"] for row in prior],
            "prior waveform exclusion binding")
    numeric, numeric_sha = _read_json(_safe_file(root, NUMERIC_INVENTORY))
    require(numeric_sha == NUMERIC_INVENTORY_SHA256 and numeric.get("source_count") == 66 and
            len(numeric.get("source_sha256", {})) == 66, "original 66-source inventory")
    for name, expected in numeric["source_sha256"].items():
        require(sha256(_safe_file(root, name).read_bytes()) == expected, "original frozen source changed: " + name)
    require(sha256(_safe_file(root, numeric["source_receipt"]).read_bytes()) ==
            numeric["source_receipt_sha256"], "original scientific receipt changed")
    require(qualification.get("status") == "compatible" and
            qualification.get("compared_input_arrays") == 461 and
            qualification.get("independently_regenerated_stress_arrays") == 216 and
            qualification.get("compared_analytic_rows") == 20,
            "successful numeric qualification required")
    require(qualification.get("input_differences") ==
            {"legacy": [], "stress": [], "independent_stress": []} and
            qualification.get("analytic_difference_paths") == [], "numeric qualification mismatch")
    frozen = qualification.get("frozen_sources", {})
    require(frozen.get("manifest_sha256") == NUMERIC_INVENTORY_SHA256 and
            frozen.get("source_files_compared") == 66 and frozen.get("all_equal") is True and
            frozen.get("original_receipt_verified") is True and frozen.get("differences") == [],
            "numeric qualification frozen-source receipt")
    require(not qualification.get("environment", {}).get("numpy_disable_cpu_features"),
            "native CPU dispatch qualification")
    require(all(type(qualification.get(key)) is int and qualification[key] == 0 for key in
                ("predictor_calls", "decoder_calls", "truth_or_reference_calls", "scorer_calls")),
            "qualification performed no inference")
    control_inputs, control_sha = _read_json(_safe_file(root, CONTROL_INPUTS))
    require(control_sha == CONTROL_INPUTS_SHA256 and
            control_inputs.get("schema") == "authored-drum-lane-inputs-v1" and
            control_inputs.get("input_generation_only") is True,
            "pre-inference authored input manifest")
    control_rows = control_inputs.get("cases")
    require(isinstance(control_rows, list) and len(control_rows) == 100 and
            [row["id"] for row in control_rows] == [f"ctl{index:03d}" for index in range(1, 101)],
            "authored frozen input population")
    return prior, len(sources), {row["id"]: row for row in control_rows}


def _record_index(rows, label):
    require(isinstance(rows, list), label + ": case list")
    index = {}
    for row in rows:
        require(isinstance(row, dict) and isinstance(row.get("id"), str) and row["id"] and
                row["id"] not in index, label + ": unique case identity")
        index[row["id"]] = row
    return index


def audit_population(preflight, prior, control_inputs, *, work=None):
    rows = preflight.get("planned_cases")
    _record_index(rows, "preflight")
    require(Counter(row.get("cohort") for row in rows) == COHORT_COUNTS, "fixed 6+4+100 population")
    require(preflight.get("original_midi_zip_sha256") == MIDI_SHA256 and
            preflight.get("metadata_sha256") == METADATA_SHA256, "publisher MIDI and metadata identities")
    for key in ("predictor_calls_before_preflight", "reference_calls_before_preflight"):
        require(type(preflight.get(key)) is int and preflight[key] == 0, "all-input preflight barrier")
    source = preflight.get("source_access", {})
    require(source.get("full_source_zip_sha256_verified") is False,
            "ranged reads cannot verify full archive hash")
    require(type(source.get("range_bytes_fetched")) is int and
            0 <= source["range_bytes_fetched"] <= 140 * 1024 * 1024,
            "source acquisition byte budget")
    new = [row for row in rows if row["cohort"] == "new_waveform"]
    require(not ({row["id"] for row in new} & {row["id"] for row in prior}), "new waveform overlap")
    require(Counter(row.get("beat_type") for row in new) == {"beat": 4, "fill": 2},
            "new waveform beat/fill allocation")
    for row in new:
        upper = 28 if row["beat_type"] == "beat" else 15
        require(row.get("split") == "test" and row.get("time_signature") == "4-4" and
                4 <= float(row.get("duration", -1)) <= upper, "metadata-only new waveform bounds")
    replay = [row for row in rows if row["cohort"] == "development_replay"]
    require([row["id"] for row in replay] == list(OLD_IDS), "original four replay identity")
    controls = [row for row in rows if row["cohort"] == "authored_controls"]
    require([row["id"] for row in controls] == [f"ctl{index:03d}" for index in range(1, 101)],
            "authored control identities")
    categories = (["supported_singleton"] * 12 + ["same_class_pair"] * 48 +
                  ["simultaneous_supported"] * 6 + ["simultaneous_with_unsupported"] * 18 +
                  ["unsupported_singleton"] * 12 + ["silence"] * 4)
    require([row.get("category") for row in controls] == categories, "authored control strata")
    verified = 0
    old_hashes = {row["id"]: row["source_sha256"] for row in prior}
    for index, row in enumerate(rows):
        require(row.get("status") in {"ready", "unavailable"}, "input admission status")
        if row["status"] != "ready":
            require("input_path" not in row and "input_sha256" not in row and bool(row.get("reason")),
                    "unavailable input remains explicit")
            continue
        _hash(row.get("input_sha256"), "canonical input hash")
        shape = row.get("input_shape")
        require(row.get("input_path") == f"inputs/{index:03d}.npy" and row.get("input_dtype") == "<f4" and
                row.get("sample_rate") == 16000 and isinstance(shape, list) and len(shape) == 1 and
                type(shape[0]) is int and 1140 < shape[0] <= 24 * 16000,
                "canonical waveform dimensions")
        duration = row.get("duration_seconds")
        require(finite_number(duration) and 0 < duration <= 12 and
                abs(shape[0] - duration * 16000) <= 1.0000001, "waveform sample-time binding")
        if row["cohort"] != "authored_controls":
            _hash(row.get("source_audio_sha256"), "source WAV member hash")
            require(type(row.get("source_audio_crc32")) is int and 0 <= row["source_audio_crc32"] < 2**32 and
                    type(row.get("source_audio_bytes")) is int and 0 < row["source_audio_bytes"] <= 55 * 1024**2,
                    "bounded source WAV member")
            if row["id"] in old_hashes:
                require(row["source_audio_sha256"] == old_hashes[row["id"]], "historical waveform byte identity")
        else:
            require(row.get("sample_count") == shape[0], "authored input sample count")
            frozen = control_inputs[row["id"]]
            require(row["input_sha256"] == frozen["sha256"] and row["input_shape"] == frozen["shape"] and
                    row["input_dtype"] == frozen["dtype"], "pre-inference authored input byte binding")
        if work is not None:
            import numpy as np

            values = np.load(_safe_file(work, row["input_path"]), allow_pickle=False)
            require(values.dtype.str == "<f4" and list(values.shape) == shape and np.isfinite(values).all(),
                    "saved input numeric contract")
            require(sha256(values.tobytes(order="C")) == row["input_sha256"], "saved input byte identity")
            verified += 1
    return rows, verified


def _control_reference_contract(row, events):
    """A dropped unsupported/simultaneous authored event cannot hide in metrics."""
    category = row.get("category")
    roles = [event["role"] for event in events]
    if category == "supported_singleton":
        valid = len(roles) == 1 and roles[0] in SUPPORTED_ROLES
    elif category == "same_class_pair":
        valid = len(roles) == 2 and roles[0] == roles[1] and roles[0] in SUPPORTED_ROLES
    elif category == "simultaneous_supported":
        valid = Counter(roles) == {"kick": 1, "backbeat": 1}
    elif category == "simultaneous_with_unsupported":
        valid = roles.count("hat") == 1 and len(roles) in (2, 3) and all(
            role in SUPPORTED_ROLES or role == "hat" for role in roles
        )
    elif category == "unsupported_singleton":
        valid = len(roles) == 1 and roles[0] in {"hat", "tom"}
    else:
        valid = category == "silence" and not roles
    require(valid, "authored reference event inventory: " + row["id"])
    require(all(event["velocity"] is None for event in events), "authored controls have no MIDI velocity truth")


def audit_case_metrics(planned, predictions, references, reported):
    _record_index(reported, "metrics")
    identities = [row["id"] for row in planned]
    for name, rows in (("predictions", predictions.get("cases")), ("references", references.get("cases")),
                       ("metrics", reported)):
        _record_index(rows, name)
        require([row["id"] for row in rows] == identities, name + ": full ordered planned population")
    derived = []
    for source, prediction, reference, metric in zip(planned, predictions["cases"], references["cases"],
                                                     reported, strict=True):
        identity = source["id"]
        require(all(row.get("cohort") == source["cohort"] for row in (prediction, reference, metric)),
                identity + ": cohort identity")
        require(metric.get("category") == source.get("category"), identity + ": category identity")
        require(prediction.get("status") in {"predicted", "unavailable", "prediction_failed"} and
                reference.get("status") in {"ready", "unavailable", "reference_failed"},
                identity + ": stage statuses")
        if source["status"] == "unavailable":
            require(prediction["status"] == reference["status"] == "unavailable",
                    identity + ": unavailable input propagation")
        else:
            require(prediction["status"] != "unavailable" and reference["status"] != "unavailable",
                    identity + ": admitted stage coverage")
        if prediction["status"] == "predicted":
            require(prediction.get("input_sha256") == source.get("input_sha256"), identity + ": prediction input binding")
            require(isinstance(prediction.get("arms"), dict) and list(prediction["arms"]) == list(ARMS),
                    identity + ": four prediction arms")
            for arm in ARMS:
                validate_events(prediction["arms"][arm], duration=source["duration_seconds"],
                                prediction=True, label=identity + "/" + arm)
        else:
            require("arms" not in prediction and bool(prediction.get("reason")), identity + ": failed prediction retained")
        if reference["status"] == "ready":
            validate_events(reference.get("events"), duration=source["duration_seconds"],
                            prediction=False, label=identity + "/reference")
            if source["cohort"] == "authored_controls":
                _control_reference_contract(source, reference["events"])
            else:
                _hash(reference.get("source_midi_sha256"), identity + ": source MIDI hash")
                require(all(type(event["velocity"]) is int for event in reference["events"]),
                        identity + ": observed source MIDI velocity")
        else:
            require("events" not in reference and bool(reference.get("reason")), identity + ": failed reference retained")
        row = {"id": identity, "cohort": source["cohort"], "category": source.get("category"),
               "status": "not_scored"}
        if prediction["status"] != "predicted" or reference["status"] != "ready":
            require(metric.get("status") == "not_scored" and "arms" not in metric and
                    metric.get("prediction_status") == prediction["status"] and
                    metric.get("reference_status") == reference["status"], identity + ": incomplete scoring coverage")
            derived.append(row)
            continue
        require(metric.get("status") == "scored" and isinstance(metric.get("arms"), dict) and
                list(metric["arms"]) == list(ARMS), identity + ": complete score inventory")
        row.update(status="scored", arms={})
        truth = reference["events"]
        supported = [event for event in truth if event["role"] in SUPPORTED_ROLES]
        for arm in ARMS:
            output, predictions_for_arm = {}, prediction["arms"][arm]
            require(set(metric["arms"][arm]) == set(STRATA) | {"recovery"}, identity + ": complete strata")
            for stratum, (tolerance, target_only) in STRATA.items():
                output[stratum] = audit_metric(metric["arms"][arm][stratum],
                                               supported if target_only else truth,
                                               predictions_for_arm, tolerance,
                                               identity + "/" + arm + "/" + stratum)
            output["recovery"] = audit_recovery(metric["arms"][arm]["recovery"], supported,
                                                  metric["arms"][arm]["supported_10ms"]["matched_pairs"],
                                                  identity + "/" + arm + "/recovery")
            row["arms"][arm] = output
        derived.append(row)
    return derived


def _sum_metrics(rows):
    return count_metrics(sum(row["reference"] for row in rows), sum(row["predicted"] for row in rows),
                         sum(row["matched"] for row in rows))


def reconstructed_aggregates(cases):
    output = {}
    for cohort, count in COHORT_COUNTS.items():
        population = [row for row in cases if row["cohort"] == cohort]
        complete = [row for row in population if row["status"] == "scored"]
        require(len(population) == count, "aggregate planned population")
        strata = {}
        for stratum in STRATA:
            strata[stratum] = {}
            for arm in ARMS:
                entries = [row["arms"][arm][stratum] for row in complete]
                counts = _sum_metrics(entries)
                roles = {role for row in entries for role in row["per_role"]}
                counts["per_role"] = {role: _sum_metrics([row["per_role"][role] for row in entries
                                                          if role in row["per_role"]]) for role in sorted(roles)}
                edits = sum(row["edit_cost"] for row in entries)
                counts.update(edit_operations=edits, normalized_edit_operations=edits / max(1, counts["reference"]))
                strata[stratum][arm] = counts
        recovery = {}
        for arm in ARMS:
            entries = [row["arms"][arm]["recovery"] for row in complete]
            recovery[arm] = {
                "flam_pairs": sum(row["flam"]["pairs"] for row in entries),
                "flam_recovered": sum(row["flam"]["recovered_pairs"] for row in entries),
                "simultaneous_groups": sum(row["simultaneous"]["groups"] for row in entries),
                "simultaneous_recovered": sum(row["simultaneous"]["timing_preserved_groups"] for row in entries),
            }
        summary = {"planned": count, "scored": len(complete),
                   "conditional_on_admitted_cases": len(complete) != count,
                   "strata": strata, "recovery": recovery}
        if cohort == "authored_controls":
            summary["pair_gap_bins_ms"] = {}
            for arm in ARMS:
                bins = {str(gap): {"pairs": 0, "recovered_pairs": 0} for gap in (15, 30, 60, 90)}
                for row in complete:
                    if row["category"] != "same_class_pair":
                        continue
                    pairs = row["arms"][arm]["recovery"]["flam"]["details"]
                    require(len(pairs) == 1, "authored pair remains in exactly one gap bin")
                    gap_ms = pairs[0]["reference_gap_seconds"] * 1000
                    targets = [gap for gap in (15, 30, 60, 90) if abs(gap - gap_ms) <= 1e-8]
                    require(len(targets) == 1, "authored pair gap identity")
                    bin_row = bins[str(targets[0])]
                    bin_row["pairs"] += 1
                    bin_row["recovered_pairs"] += int(pairs[0]["recovered"])
                summary["pair_gap_bins_ms"][arm] = bins
        output[cohort] = summary
    return output


def reconstructed_decision(cases, aggregates):
    baseline, candidate = "global85", "independent10"
    complete = len(cases) == 110 and all(case["status"] == "scored" for case in cases)
    support = aggregates["new_waveform"]["strata"]["supported_50ms"]
    all_kit = aggregates["new_waveform"]["strata"]["all_kit_50ms"]
    a, b = support[baseline], support[candidate]
    new_cases = [case for case in cases if case["cohort"] == "new_waveform" and case["status"] == "scored"]
    nonworse = sum(case["arms"][candidate]["supported_50ms"]["f1"] + 1e-12 >=
                   case["arms"][baseline]["supported_50ms"]["f1"] for case in new_cases)
    singletons = [case for case in cases if case["category"] == "supported_singleton" and case["status"] == "scored"]
    false_positives = {arm: sum(case["arms"][arm]["supported_50ms"]["false_positives"] for case in singletons)
                       for arm in (baseline, candidate)}
    controls = aggregates["authored_controls"]["recovery"]
    conditions = {
        "all_110_cases_complete": complete,
        "primary_improves_at_least_3pp": b["f1"] + 1e-12 >= a["f1"] + .03,
        "no_supported_class_loses_more_than_2pp": all(
            b["per_role"].get(role, {"f1": 0.0})["f1"] + 1e-12 >=
            a["per_role"].get(role, {"f1": 0.0})["f1"] - .02 for role in SUPPORTED_ROLES),
        "all_kit_f1_not_lower": all_kit[candidate]["f1"] + 1e-12 >= all_kit[baseline]["f1"],
        "at_least_four_of_six_new_clips_nonworse": nonworse >= 4,
        "all_kit_edit_proxy_not_higher": all_kit[candidate]["normalized_edit_operations"] <=
        all_kit[baseline]["normalized_edit_operations"] + 1e-12,
        "supported_singleton_extra_events_not_higher": false_positives[candidate] <= false_positives[baseline],
        "strict_authored_flam_recovery_not_lower": controls[candidate]["flam_recovered"] >= controls[baseline]["flam_recovered"],
        "strict_authored_simultaneous_recovery_not_lower": controls[candidate]["simultaneous_recovered"] >=
        controls[baseline]["simultaneous_recovered"],
    }
    return {
        "candidate": candidate, "baseline": baseline, "conditions": conditions,
        "outcome": ("inconclusive_incomplete" if not complete else
                    "advance_to_broader_research" if all(conditions.values()) else "reject_candidate"),
        "primary_f1_delta": b["f1"] - a["f1"], "new_clips_nonworse": nonworse,
        "supported_singleton_false_positives": false_positives,
        "product_default_changed": False, "release_quality_approved": False,
    }


def audit_directory(reports, *, work=None, root=None):
    """Audit preserved evidence; optionally reopen the private exact input arrays."""
    reports = Path(reports)
    root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    work = Path(work) if work is not None else None
    payloads, hashes = {}, {}
    for name in ("preflight.json", "predictions.json", "references.json", "report.json", "qualification.json"):
        payloads[name], hashes[name] = _read_json(_safe_file(reports, name))
        require(isinstance(payloads[name], dict), "evidence JSON object: " + name)
        if name != "qualification.json":
            require(payloads[name].get("schema") == SCHEMA, "evidence schema: " + name)
    preflight, prediction, reference, report, qualification = (
        payloads[name] for name in ("preflight.json", "predictions.json", "references.json", "report.json", "qualification.json")
    )
    require(report.get("hashes") == {name: digest for name, digest in hashes.items() if name != "report.json"},
            "report evidence byte bindings")
    require(preflight.get("qualification_sha256") == hashes["qualification.json"] and
            prediction.get("preflight_sha256") == hashes["preflight.json"] and
            reference.get("predictions_sha256") == hashes["predictions.json"], "preflight/prediction/reference hash chain")
    require(prediction.get("reference_calls_before_freeze") == 0 and
            type(prediction["reference_calls_before_freeze"]) is int and
            reference.get("all_predictions_frozen_before_reference_access") is True,
            "prediction-before-reference barrier receipt")
    require(prediction.get("arms") == list(ARMS) and report.get("arms") == list(ARMS) and
            report.get("candidate") == "independent10", "frozen four arms and candidate")
    require(all(report.get(key) == preflight.get(key) for key in ("source_revision", "protocol_head_revision")),
            "execution revision binding")
    for key, expected in (("training", False), ("product_default_changed", False), ("quality_approved", False),
                          ("new_waveforms_are_not_unseen_dataset_or_composition_holdout", True),
                          ("unsupported_classes_retained_in_all_kit_denominator", True)):
        require(report.get(key) is expected, "research scope: " + key)
    prior, source_count, control_inputs = audit_sources(preflight, qualification, root)
    planned, verified_arrays = audit_population(preflight, prior, control_inputs, work=work)
    derived = audit_case_metrics(planned, prediction, reference, report.get("case_metrics"))
    aggregates = reconstructed_aggregates(derived)
    compare_tree(report.get("aggregates"), aggregates, "aggregates")
    decision = reconstructed_decision(derived, aggregates)
    compare_tree(report.get("decision"), decision, "fixed candidate decision")
    complete = all(row["status"] == "scored" for row in derived)
    require(report.get("status") == ("complete" if complete else "incomplete"), "report completion status")
    return {
        "schema": "drum-event-lanes-independent-audit-v1", "status": "audited",
        "report_status": report["status"], "report_sha256": hashes["report.json"], "evidence_sha256": hashes,
        "planned_cases": len(planned), "scored_cases": sum(row["status"] == "scored" for row in derived),
        "frozen_source_files_verified": source_count, "original_scientific_sources_verified": 66,
        "input_arrays_reopened": work is not None, "input_arrays_verified": verified_arrays,
        "cohorts": {key: {"planned": row["planned"], "scored": row["scored"],
                          "conditional_on_admitted_cases": row["conditional_on_admitted_cases"]}
                    for key, row in aggregates.items()},
        "independent_matching": "residual-network maximum reward; no experiment scorer imports",
        "candidate_decision": decision, "quality_approved": False,
        "limitation": "Verifies receipt bindings and event-derived calculations; does not re-infer audio or independently annotate source MIDI.",
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports", type=Path, required=True)
    parser.add_argument("--work", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit_directory(args.reports, work=args.work)
    output = args.output if args.output is not None else args.reports / "audit.json"
    with output.open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(result, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

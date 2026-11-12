"""Audit real repeat-context evaluation from an exact frozen prediction replay.

Download only the 49 hash-pinned nASAP source members into a private cache.
Use the unchanged source adapters and selector to reconstruct all eight real
inputs, predictions and target maps. Verify their hashes against the original
execution and prior independent source audit before independently scoring below.
No repository study evaluator or scoring helper is imported or called. This is
an independent evaluator of a verified replay, not a new independent model or
new independently annotated truth. Requires Python 3.12 and mido 1.3.3.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

REPORT_SHA256 = "b64985586ec5f0340a61b45bce99107bccfd60d50bd3d19491e0f524c699bf93"
SOURCE_AUDIT_SHA256 = "b21728b8bd92d4e9525c79a72d8314a8ed5424ce9b85375192d95a2b81c7bca2"
METHODS = (
    "straight_narrow", "global_phase", "local_switch005",
    "repeat_soft0025", "repeat_soft010", "repeat_hard",
)
POSITIONS = (0, 3, 4, 6, 8, 9)
STATUS_NAMES = {"C": "correct", "W": "wrong", "A": "abstained", "U": "unobserved"}
PAIR_NAMES = {"C": "same_correct", "W": "same_wrong", "D": "disagreement", "A": "abstention", "U": "unobserved"}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def pretty(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def fingerprint(value):
    return sha(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())


class Audit:
    def __init__(self):
        self.checks = Counter()

    def equal(self, kind, observed, expected):
        if observed != expected:
            raise ValueError(f"{kind}: {observed!r} != {expected!r}")
        self.checks[kind] += 1


def source_download(cache, base, path, identity):
    destination = cache / path
    if destination.is_symlink() or cache not in destination.resolve().parents:
        raise ValueError("unsafe source cache path")
    downloaded = not destination.exists()
    if downloaded:
        url = base + urllib.parse.quote(path, safe="/")
        request = urllib.request.Request(url, headers={"Accept-Encoding": "identity"})
        with urllib.request.urlopen(request, timeout=45) as response:
            if response.status != 200 or response.url != url:
                raise ValueError("unexpected source redirect or response")
            data = response.read(identity["bytes"] + 1)
    else:
        data = destination.read_bytes()
    if len(data) != identity["bytes"] or sha(data) != identity["sha256"]:
        raise ValueError("source identity mismatch: " + path)
    if downloaded:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as handle:
            handle.write(data)
    return {"path": path, "bytes": len(data), "sha256": sha(data), "downloaded": downloaded}


def canonical_tick(onset, span):
    """Select only an exactly supported Q12 target, with representation epsilon."""
    base = math.floor(onset)
    candidates = [12 * quarter + position
                  for quarter in range(max(0, base - 1), min(math.ceil(span), base + 2))
                  for position in POSITIONS if 12 * quarter + position < 12 * span]
    if not candidates:
        return None
    closest = min(candidates, key=lambda candidate: abs(candidate - 12 * onset))
    return closest if abs(closest - 12 * onset) <= 1e-7 else None


def individual_outcome(target, events, decisions, span):
    tick = canonical_tick(target["onset_q"], span)
    if target["coverage"] != "observed":
        return {"code": "U", "tick": tick, "selection": None, "onset_correct": None,
                "pitch_match": None, "truth_in_diagnostic_candidates": False,
                "diagnostic_collision": False}
    event = events[target["event_id"]]
    selected = decisions[target["event_id"]]
    chosen = selected["selected_tick"]
    pitch_match = event.pitch == target["pitch"]
    onset_correct = None if chosen is None else tick is not None and chosen == tick
    outcome = "A" if chosen is None else "C" if pitch_match and onset_correct else "W"
    return {"code": outcome, "tick": tick,
            "selection": None if chosen is None else (event.pitch, chosen),
            "onset_correct": onset_correct, "pitch_match": pitch_match,
            "truth_in_diagnostic_candidates": pitch_match and tick is not None and tick in selected["candidate_ticks"],
            "diagnostic_collision": selected["collision"]}


def outcomes_count(outcomes):
    codes = Counter(value["code"] for value in outcomes)
    return {"targets": len(outcomes), "observed": len(outcomes) - codes["U"],
            **{name: codes[code] for code, name in STATUS_NAMES.items()},
            "onset_correct": sum(value["onset_correct"] is True for value in outcomes),
            "pitch_mismatched_observations": sum(value["pitch_match"] is False for value in outcomes),
            "truth_in_diagnostic_candidates": sum(value["truth_in_diagnostic_candidates"] for value in outcomes),
            "diagnostic_collision_observations": sum(value["diagnostic_collision"] for value in outcomes),
            "lattice_supported_targets": sum(value["tick"] is not None for value in outcomes)}


def boolean_code(value):
    return "?" if value is None else "1" if value else "0"


def joint_available(case, prediction, method, targets, full):
    observed = [target for target in targets if target["coverage"] == "observed"]
    if not observed:
        return None
    event_indices = {event.event_id: index for index, event in enumerate(case["events"])}
    requirements = []
    for target in observed:
        tick = canonical_tick(target["onset_q"], case["length_q"])
        index = event_indices[target["event_id"]]
        if tick is None or case["events"][index].pitch != target["pitch"]:
            return False
        acceptable = []
        for phase in range(4):
            assignment = prediction["fits"][phase]["assignments"][index]
            if tick in assignment["alternatives"] and assignment["abs_residual_q"] <= .08 + 1e-12:
                acceptable.append(phase)
        if not acceptable:
            return False
        requirements.append((prediction["event_block_indices"][index], acceptable))
    bits = int(prediction["path_sets"][method]["full_mask_hex" if full else "diagnostic_mask_hex"], 16)
    size = len(prediction["blocks"])
    while bits:
        bit = bits & -bits
        ordinal = bit.bit_length() - 1
        states = []
        for _ in range(size):
            states.append(ordinal % 4)
            ordinal //= 4
        states.reverse()
        if all(states[block] in allowed for block, allowed in requirements):
            return True
        bits ^= bit
    return False


def audit_real(repo, report_path, source_path, cache, output):
    audit = Audit()
    repo, cache = repo.resolve(), cache.resolve()
    if repo == cache or repo in cache.parents:
        raise ValueError("source and replay cache must be outside the repository")
    cache.mkdir(parents=True, exist_ok=True)
    report_raw, source_raw = report_path.read_bytes(), source_path.read_bytes()
    audit.equal("official_report_sha256", sha(report_raw), REPORT_SHA256)
    audit.equal("prior_source_audit_sha256", sha(source_raw), SOURCE_AUDIT_SHA256)
    report, historical = json.loads(report_raw), json.loads(source_raw)
    for path, expected in report["source_sha256"].items():
        audit.equal("frozen_scientific_file", sha((repo / path).read_bytes()), expected)
    sys.path.insert(0, str(repo))
    from scripts import nasap_repeat_context_source as additional
    from scripts import nasap_same_score_source as reused
    from scripts.repeat_context_phase import infer_repeated_performance

    modules = {"reused_real": reused, "additional_real": additional}
    manifests = {scope: module.load_manifest() for scope, module in modules.items()}
    members, input_paths = {}, set()
    for manifest in manifests.values():
        for path, identity in manifest["members"].items():
            if path in members:
                audit.equal("shared_source_identity", identity, members[path])
            members[path] = identity
        for case in manifest["cases"]:
            input_paths.update((case["midi"], case["performance_annotations"]))
    audit.equal("unique_source_members", len(members), 49)
    audit.equal("unique_source_bytes", sum(v["bytes"] for v in members.values()), 3985273)
    transfers = []

    def acquire(paths):
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(source_download, cache / "sources", reused.SOURCE_BASE, path, members[path])
                       for path in sorted(paths)]
            for future in futures:
                transfers.append(future.result())

    (cache / "sources").mkdir(exist_ok=True)
    acquire(input_paths)
    print("Verified 16 pinned input members; reconstructing 8 predictions.", flush=True)
    ledger = {row["id"]: row for row in report["cases"]}
    cohorts, predictions = {}, {}
    parity = []
    private = cache / "private"
    private.mkdir(exist_ok=True)
    for scope, module in modules.items():
        result = module.prepare_inputs(cache / "sources")
        cases = result["cases"]
        cohorts[scope] = cases
        for case in cases:
            audit.equal("source_input_admission", case["status"], "complete")
            observed = {"events": [asdict(event) for event in case["events"]], "length_q": case["length_q"]}
            input_raw = pretty(observed)
            row = ledger[case["id"]]
            audit.equal("original_input_file_hash", sha(input_raw), row["input_file_sha256"])
            (private / (case["id"] + ".input.json")).write_bytes(input_raw)
            prediction = infer_repeated_performance(case["events"], case["length_q"])
            raw = pretty(prediction)
            audit.equal("original_complete_prediction_file_hash", sha(raw), row["prediction_file_sha256"])
            audit.equal("original_complete_prediction_file_bytes", len(raw), row["prediction_bytes"])
            after = {"events": [asdict(event) for event in case["events"]], "length_q": case["length_q"]}
            audit.equal("input_preserved_after_replay", pretty(after), input_raw)
            (private / (case["id"] + ".prediction.json")).write_bytes(raw)
            predictions[case["id"]] = prediction
            parity.append({"id": case["id"], "input_sha256": sha(input_raw), "prediction_sha256": sha(raw)})
    audit.equal("all_eight_predictions_before_reference_acquisition", len(predictions), 8)
    print("All 8 original input and prediction hashes matched; acquiring reference sources.", flush=True)
    acquire(set(members) - input_paths)
    references = {}
    for scope, module in modules.items():
        references[scope] = module.load_evaluation(cache / "sources", cohorts[scope])["cases"]
        prior = {row["id"]: row for row in historical["source_admission"]["cohorts"][scope]["cases"]}
        for cid, value in references[scope].items():
            audit.equal("reference_source_admission", value["status"], "complete")
            for field in ("target_notes_sha256", "input_links_sha256", "canonical_score_map_sha256"):
                audit.equal("independent_source_audit_canonical_chain", value["receipt"][field], prior[cid][field])
            audit.equal("source_adapter_target_payload_hash", fingerprint(value["target_notes"]), prior[cid]["target_notes_sha256"])
    print("49 pinned sources and all canonical hashes verified; independently scoring real targets.", flush=True)
    summaries = {}
    private_outcomes = {}
    boundary_diagnostics = Counter()

    for scope, cases in cohorts.items():
        published = report["evaluation"]["cohorts"][scope]
        public_rows = {row["id"]: row for row in published["case_rows"]}
        ordinary_by_id = {}
        for case in cases:
            cid, prediction, source = case["id"], predictions[case["id"]], references[scope][case["id"]]
            row = public_rows[cid]
            audit.equal("public_input_content_hash", fingerprint([asdict(e) for e in case["events"]]), row["input_content_fingerprint"])
            audit.equal("public_prediction_content_hash", fingerprint(prediction), row["prediction_content_fingerprint"])
            ordinary = sorted((target for target in source["target_notes"] if not target["grace"]),
                              key=lambda target: (target["onset_q"], target["pitch"], target["score_id"]))
            ordinary_by_id[cid] = {target["score_id"]: target for target in ordinary}
            keys = [fingerprint([source["score_sha256"], target["score_id"]]) for target in ordinary]
            audit.equal("reference_key_order_from_source", row["reference_keys"], keys)
            audit.equal("reference_lattice_from_source", row["lattice_support_mask"], "".join("1" if canonical_tick(t["onset_q"], case["length_q"]) is not None else "0" for t in ordinary))
            events = {event.event_id: event for event in case["events"]}
            for method in METHODS:
                decisions = {assignment["event_id"]: assignment for assignment in prediction["arms"][method]["diagnostic_assignments"]}
                outcomes = [individual_outcome(target, events, decisions, case["length_q"]) for target in ordinary]
                private_outcomes[cid, method] = dict(zip((target["score_id"] for target in ordinary), outcomes, strict=True))
                masks = {"status": "".join(value["code"] for value in outcomes)}
                for field in ("onset_correct", "pitch_match", "truth_in_diagnostic_candidates", "diagnostic_collision"):
                    masks[field] = "".join(boolean_code(value[field]) for value in outcomes)
                audit.equal("independent_real_target_masks", masks, row["arms"][method]["reference_masks"])
                for field, count in outcomes_count(outcomes).items():
                    audit.equal("independent_real_case_score", count, row["arms"][method][field])
                for full, field in ((False, "conditional_observed_diagnostic_truth_available"),
                                    (True, "conditional_observed_retained_truth_available")):
                    audit.equal("independent_real_joint_truth", joint_available(case, prediction, method, ordinary, full), row["arms"][method][field])
            audit.equal("actual_repeat_links", len(prediction["repeat_context"]["links"]), 0)
            # Descriptive post-hoc geometry only; no model or candidate changes.
            for block, eligibility in zip(prediction["blocks"], prediction["repeat_context"]["eligibility"], strict=True):
                if eligibility["reason"] != "canonical_outside_observed_block":
                    continue
                kinds = set()
                for index in block["event_indices"]:
                    candidate_quarters = {fit["assignments"][index]["tick"] // 12 for fit in prediction["fits"]}
                    if len(candidate_quarters) == 1:
                        quarter = next(iter(candidate_quarters))
                        shift = quarter // 4 - block["index"]
                        if shift:
                            kinds.add("following_block" if shift > 0 else "previous_block")
                boundary_diagnostics[scope + "/" + "+".join(sorted(kinds))] += 1

        pair_counts = {method: Counter() for method in METHODS}
        for pair in published["pair_rows"]:
            if not pair["same_score"]:
                continue
            left, right = pair["left"], pair["right"]
            targets_l, targets_r = ordinary_by_id[left], ordinary_by_id[right]
            audit.equal("same_score_occurrence_population", set(targets_l), set(targets_r))
            for method in METHODS:
                outcomes_l = private_outcomes[left, method]
                outcomes_r = private_outcomes[right, method]
                codes = []
                for key in targets_l:
                    lt, rt = targets_l[key], targets_r[key]
                    audit.equal("same_score_full_target_identity", (lt["pitch"], lt["onset_q"], lt["duration_q"]), (rt["pitch"], rt["onset_q"], rt["duration_q"]))
                    a, b = outcomes_l[key], outcomes_r[key]
                    if "U" in (a["code"], b["code"]):
                        code = "U"
                    elif "A" in (a["code"], b["code"]):
                        code = "A"
                    elif a["code"] == b["code"] == "C":
                        code = "C"
                    else:
                        code = "W" if a["selection"] == b["selection"] else "D"
                    codes.append(code)
                audit.equal("independent_real_pair_mask_including_both_wrong", "".join(codes), pair["methods"][method]["reference_status_mask"])
                counts = Counter(codes)
                for code, field in PAIR_NAMES.items():
                    audit.equal("independent_real_pair_count", counts[code], pair["methods"][method]["ordinary_reference_pairs"][field])
                    pair_counts[method][field] += counts[code]
        summaries[scope] = {}
        for method in METHODS:
            values = [value for case in cases for value in private_outcomes[case["id"], method].values()]
            total = outcomes_count(values)
            expected = published["summary"]["methods"][method]
            for field, count in total.items():
                audit.equal("independent_real_cohort_score", count, expected[field])
            audit.equal("independent_real_cohort_pairs", dict(pair_counts[method]), expected["paired_references"])
            summaries[scope][method] = {**total, "paired_references": dict(pair_counts[method])}

    metadata = {
        "schema_version": 1, "status": "pass_for_exact_real_replay_and_independent_evaluation",
        "scope": "eight real input/prediction byte identities; canonical source-audit chain; independently computed target and paired-reference scores",
        "checks_passed": sum(audit.checks.values()), "checks_by_kind": dict(sorted(audit.checks.items())),
        "official_recovery_report_sha256": REPORT_SHA256, "official_recovery_run": 43261359821,
        "prior_independent_source_audit_sha256": SOURCE_AUDIT_SHA256,
        "script_sha256": sha(Path(__file__).read_bytes()),
        "original_input_and_prediction_parity": parity,
        "unique_source_members_verified": len(transfers),
        "unique_source_bytes_verified": sum(item["bytes"] for item in transfers),
        "source_network_requests": sum(item["downloaded"] for item in transfers),
        "source_network_bytes": sum(item["bytes"] for item in transfers if item["downloaded"]),
        "all_eight_replay_predictions_saved_before_reference_acquisition": True,
        "model_calls": 8, "study_evaluator_calls": 0,
        "scoring_helpers_imported": [],
        "reused_components": ["frozen nASAP source adapters and their parsers", "frozen repeat-context selector"],
        "ordinary_reference_scores": summaries,
        "descriptive_posthoc_excluded_block_candidate_direction": dict(boundary_diagnostics),
        "public_raw_sources_or_predictions": False,
        "remaining_unresolved_both_wrong_pair_categories": 0,
        "limitations": [
            "This is independent evaluation of byte-identical original model predictions, not an independently implemented model.",
            "Canonical truth is reconstructed by the frozen adapters and verified against the prior independently parsed source audit; no new independent annotation is claimed.",
            "Source alignment and supplied beat clocks condition the evaluation. Missing targets stay in the denominator.",
            "Private source files, targets and predictions remain outside the repository; public output contains only derived counts and hashes.",
            "Block direction counts are descriptive post-hoc geometry, not a new predeclared experiment or a proposed-model performance result.",
        ],
    }
    output.write_text(json.dumps(metadata, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({"status": metadata["status"], "checks_passed": metadata["checks_passed"]}), flush=True)


def default_repo():
    for parent in Path(__file__).resolve().parents:
        if (parent / "scripts/nasap_same_score_source.py").exists():
            return parent
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=default_repo())
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--source-audit", required=True, type=Path)
    parser.add_argument("--cache", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.repo is None:
        parser.error("--repo is required when the script is outside the repository")
    audit_real(args.repo, args.report, args.source_audit, args.cache, args.output)


if __name__ == "__main__":
    main()

"""Audit the frozen repeat-context recovery without calling its evaluator.

Python standard library only.  By default this audits original/recovery byte
identity and independently aggregates the public authored case ledger.  With
--replay-authored it also calls the unchanged, previously independently audited
generators and selector, verifies every original authored prediction SHA256,
then scores full decisions, per-hit outcomes, joint paths and repeat-link truth
with separate code below.  This is independent evaluation of an exact replay;
it is not a new independently implemented model or an independent truth source.
No musical source is downloaded.  Private replay files remain outside the repo.
Real source and per-target mask arithmetic have a separate source audit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import zipfile
from collections import Counter
from dataclasses import asdict
from itertools import combinations
from pathlib import Path

RECOVERY_SHA256 = "d77222eef446dbe9f24caa4b733139c59f2f06b96c8dcaf461dba34c3caa8528"
RECOVERY_BYTES = 1519299
ORIGINAL_SHA256 = "cf11f4757ae756878b108ab7b89a49a90db71b5c9fa04803a79f00d1c9e4f93e"
SCOPES = ("reused_authored", "factorial_authored")
METHODS = (
    "straight_narrow", "global_phase", "local_switch005",
    "repeat_soft0025", "repeat_soft010", "repeat_hard",
)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def pretty(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def compact(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


class Audit:
    def __init__(self):
        self.counts = Counter()
        self.max_numeric_difference = 0.0

    def equal(self, actual, expected, label):
        if isinstance(expected, dict):
            if not isinstance(actual, dict):
                raise TypeError(label + ": expected object")
            for key, value in expected.items():
                self.equal(actual[key], value, label + "/" + str(key))
            return
        if isinstance(expected, (list, tuple)):
            if len(actual) != len(expected):
                raise AssertionError(label + ": length mismatch")
            for index, (a, b) in enumerate(zip(actual, expected, strict=True)):
                self.equal(a, b, label + "/" + str(index))
            return
        self.counts[label.split("/")[0]] += 1
        if isinstance(expected, (int, float)) and not isinstance(expected, bool):
            difference = abs(actual - expected)
            self.max_numeric_difference = max(self.max_numeric_difference, difference)
            if difference > 1e-12:
                raise AssertionError(label + ": numeric mismatch")
        elif actual != expected:
            raise AssertionError(label + ": value mismatch")


def load_archive(path, expected_sha=None, expected_size=None):
    raw = path.read_bytes()
    if expected_sha is not None and digest(raw) != expected_sha:
        raise ValueError("archive identity differs from the official receipt")
    if expected_size is not None and len(raw) != expected_size:
        raise ValueError("archive size differs from the official receipt")
    with zipfile.ZipFile(path) as archive:
        if archive.namelist() != ["report.json"] or archive.testzip() is not None:
            raise ValueError("archive member identity or CRC changed")
        info = archive.getinfo("report.json")
        if info.file_size > 32000000:
            raise ValueError("report is outside the frozen byte budget")
        report_raw = archive.read("report.json")
    return json.loads(report_raw), {
        "zip_bytes": len(raw), "zip_sha256": digest(raw),
        "report_bytes": len(report_raw), "report_sha256": digest(report_raw),
    }


def check_chain(repo, report, original, identity, original_identity, audit):
    audit.equal(report["status"], "complete", "recovery_status")
    audit.equal(original["status"], "evaluation_failed", "original_failure_preserved")
    audit.equal(original["evaluation"], None, "original_failure_preserved")
    audit.equal(original["summary"], None, "original_failure_preserved")
    audit.equal(report["recovery"]["original_archive_sha256"], original_identity["zip_sha256"], "archive_chain")
    audit.equal(report["recovery"]["original_report_sha256"], original_identity["report_sha256"], "archive_chain")
    audit.equal(digest(pretty(report["evaluation"])), report["evaluation_sha256"], "evaluation_identity")
    audit.equal(len(report["cases"]), 1520, "population")
    audit.equal(report["planned_ids"], [r["id"] for r in report["cases"]], "population")
    for key in ("prediction_set_sha256", "private_prediction_bytes", "plan_sha256", "planned_ids", "planned_scopes"):
        audit.equal(report[key], original[key], "original_recovery_chain")
    fields = ("id", "scope", "input_file_sha256", "prediction_file_sha256", "source_receipt_sha256",
              "prediction_bytes", "receipt", "input_event_count", "arm_names", "event_mutation_check_passed")
    for old, new in zip(original["cases"], report["cases"], strict=True):
        for key in fields:
            audit.equal(new[key], old[key], "original_recovery_case_chain/" + key)
    files = {p: digest((repo / p).read_bytes()) for p in report["source_sha256"]}
    audit.equal(files, report["source_sha256"], "current_measured_source_identity")
    for path, sha in original["source_sha256"].items():
        if path == "scripts/research_test_manifest.json":
            audit.equal(sha, report["recovery_inventory"]["original_sha256"], "inventory_exception")
        else:
            audit.equal(files[path], sha, "unchanged_original_scientific_source")
    audits = {}
    for kind in ("model", "source"):
        path = repo / f"docs/research/receipts/repeat-context-{kind}-audit-43256776331.json"
        raw = path.read_bytes()
        data = json.loads(raw)
        audits[kind] = {"sha256": digest(raw), "status": data["status"]}
        if kind == "model":
            audit.equal(data["artifact_zip_sha256"], original_identity["zip_sha256"], "prior_model_audit_identity")
            audit.equal(data["report_sha256"], original_identity["report_sha256"], "prior_model_audit_identity")
            for field in ("input_files", "complete_prediction_files"):
                audit.equal(data["exact_hash_checks"][field], {"checked": 1520, "matched": 1520}, "prior_model_audit_coverage")
        else:
            audit.equal(data["input_archive"]["sha256"], original_identity["zip_sha256"], "prior_source_audit_identity")
            audit.equal(data["input_report"]["sha256"], original_identity["report_sha256"], "prior_source_audit_identity")
    audit.equal(identity["zip_sha256"], RECOVERY_SHA256, "official_recovery_identity")
    return audits


def group_values(rows, method):
    values = [r["arms"][method] for r in rows]
    counter = Counter()
    for value in values:
        counter.update(value["per_hit"])
    return {
        "cases": len(rows),
        "full_correct": sum(v["full_correct"] is True for v in values),
        "full_wrong": sum(v["full_correct"] is False for v in values),
        "full_abstained": sum(v["full_correct"] is None for v in values),
        "diagnostic_joint_truth_available": sum(v["diagnostic_joint_truth_available"] for v in values),
        "retained_joint_truth_available": sum(v["retained_joint_truth_available"] for v in values),
        "per_hit": dict(counter),
    }


def full_name(value):
    return "abstained" if value is None else "correct" if value else "wrong"


def aggregate_authored(report, audit):
    totals = {}
    for scope in SCOPES:
        cohort = report["evaluation"]["cohorts"][scope]
        rows = cohort["case_rows"]
        main = [r for r in rows if r["counterfactual_pair"] is None]
        summary = cohort["summary"]
        audit.equal(report["summary"][scope], summary, "summary_copy")
        audit.equal(summary["main_cases"], len(main), "main_population")
        audit.equal(summary["counterfactual_cases"], len(rows) - len(main), "counterfactual_population")
        totals[scope] = {}
        for method, recorded in summary["methods"].items():
            expected = group_values(main, method)
            audit.equal(recorded, expected, "authored_main_aggregation")
            totals[scope][method] = {k: v for k, v in expected.items() if k != "per_hit"}
            for grouping, keys in (
                ("by_profile", ("profile",)), ("by_take", ("take",)),
                ("factorial_cells", ("written_context", "stationarity", "vocabulary_support")),
                ("by_link_presence", ("has_links",)), ("by_trajectory_variant", ("variant",)),
            ):
                for cell in recorded.get(grouping, []):
                    selected = []
                    for row in main:
                        attrs = {**row, "has_links": bool(row["repeat_context"]["link_count"]),
                                 "variant": row.get("trajectory_variant")}
                        if all(attrs[key] == cell[key] for key in keys):
                            selected.append(row)
                    audit.equal(cell, group_values(selected, method), "authored_subgroup_aggregation")
            for baseline in METHODS[:3]:
                gains = losses = truth_losses = 0
                for row in main:
                    a, b = row["arms"][method], row["arms"][baseline]
                    gains += a["full_correct"] is True and b["full_correct"] is not True
                    losses += a["full_correct"] is not True and b["full_correct"] is True
                    truth_losses += not a["diagnostic_joint_truth_available"] and b["diagnostic_joint_truth_available"]
                audit.equal(recorded[f"full_correct_gained_vs_{baseline}"], gains, "gain_loss_aggregation")
                audit.equal(recorded[f"full_correct_lost_vs_{baseline}"], losses, "gain_loss_aggregation")
                audit.equal(recorded[f"joint_truth_lost_vs_{baseline}"], truth_losses, "gain_loss_aggregation")
            transitions = Counter(full_name(r["arms"]["local_switch005"]["full_correct"]) + "_to_" +
                                  full_name(r["arms"][method]["full_correct"]) for r in main)
            audit.equal(recorded["full_outcomes_vs_local"], dict(transitions), "full_transition_aggregation")
            pair_counts = Counter()
            for left, right in combinations(main, 2):
                prefix = "same_family" if left["family"] == right["family"] else "different_family"
                pair_counts[prefix + "_pairs"] += 1
                a = left["arms"][method]["full_selected_fingerprint"]
                b = right["arms"][method]["full_selected_fingerprint"]
                if a is not None and b is not None:
                    pair_counts[prefix + "_both_decided"] += 1
                    if a == b:
                        pair_counts[prefix + "_decided_equal"] += 1
            for prefix in ("same_family", "different_family"):
                for suffix in ("_pairs", "_both_decided", "_decided_equal"):
                    key = prefix + suffix
                    audit.equal(recorded[key], pair_counts[key], "direct_pair_enumeration")
            stable_correct = stable_wrong = 0
            family_records = [f for f in cohort["family_rows"] if f["method"] == method]
            for family in family_records:
                group = [r for r in main if r["family"] == family["family"]]
                audit.equal(family, group_values(group, method), "family_aggregation")
                sigs = {r["arms"][method]["full_selected_fingerprint"] for r in group}
                stable = len(sigs) == 1 and None not in sigs
                correct = stable and all(r["arms"][method]["full_correct"] for r in group)
                stable_correct += correct
                stable_wrong += stable and not correct
                audit.equal(family["all_cases_same_correct"], correct, "family_stability")
                audit.equal(family["all_cases_same_wrong"], stable and not correct, "family_stability")
            audit.equal(recorded["all_cases_correct_families"], stable_correct, "family_stability")
            audit.equal(recorded["stable_wrong_families"], stable_wrong, "family_stability")
        for pair in cohort["counterfactuals"]:
            group = [r for r in rows if r["id"] in pair["ids"]]
            audit.equal(len(group), 2, "counterfactual")
            for key in ("input_content_fingerprint", "prediction_content_fingerprint"):
                audit.equal(group[0][key], group[1][key], "counterfactual")
            audit.equal(group[0]["truth_fingerprint"] != group[1]["truth_fingerprint"], True, "counterfactual")
            for method, recorded in pair["methods"].items():
                expected = group_values(group, method)
                audit.equal(recorded, {k: expected[k] for k in recorded}, "counterfactual_aggregation")
    return totals


def score_hits(events, assignments, truth):
    counts = Counter({k: 0 for k in (
        "targets", "correct", "wrong", "abstained", "unobserved", "observed", "onset_correct",
        "pitch_mismatched_observations", "lattice_supported_targets",
        "truth_in_diagnostic_candidates", "diagnostic_collision_observations",
    )})
    for event, assigned in zip(events, assignments, strict=True):
        if event.event_id != assigned["event_id"]:
            raise ValueError("replay changed assignment identities")
        pitch, tick = truth[event.event_id]
        chosen = assigned["selected_tick"]
        outcome = "abstained" if chosen is None else "correct" if (event.pitch, chosen) == (pitch, tick) else "wrong"
        counts[outcome] += 1
        counts["targets"] += 1
        counts["observed"] += 1
        counts["onset_correct"] += chosen is not None and chosen == tick
        counts["pitch_mismatched_observations"] += event.pitch != pitch
        counts["lattice_supported_targets"] += tick is not None
        counts["truth_in_diagnostic_candidates"] += event.pitch == pitch and tick in assigned["candidate_ticks"]
        counts["diagnostic_collision_observations"] += assigned["collision"]
    return dict(counts)


def check_joint_paths(case, prediction, method, truth, full):
    mask = int(prediction["path_sets"][method]["full_mask_hex" if full else "diagnostic_mask_hex"], 16)
    # Check the complete saved path bitset directly, rather than a Cartesian
    # product of marginal event alternatives.
    size = len(prediction["blocks"])
    for index in range(4 ** size):
        if not mask & (1 << index):
            continue
        phases = [(index // 4 ** (size - 1 - b)) % 4 for b in range(size)]
        valid = True
        for i, event in enumerate(case["events"]):
            phase = phases[prediction["event_block_indices"][i]]
            assignment = prediction["fits"][phase]["assignments"][i]
            pitch, tick = truth[event.event_id]
            if event.pitch != pitch or tick not in assignment["alternatives"] or assignment["abs_residual_q"] > .08 + 1e-12:
                valid = False
                break
        if valid:
            return True
    return False


def link_truth(case, prediction, truth):
    counts = Counter({k: 0 for k in (
        "links_same_canonical", "links_different_canonical", "links_unscorable",
        "event_pairs_same_canonical", "event_pairs_different_canonical", "event_pairs_unscorable",
    )})
    for link in prediction["repeat_context"]["links"]:
        differs = False
        for i, j in link["event_index_pairs"]:
            left = truth[case["events"][i].event_id]
            right = truth[case["events"][j].event_id]
            same = left[0] == right[0] and right[1] - left[1] == 48 * (link["right_block"] - link["left_block"])
            counts["event_pairs_same_canonical" if same else "event_pairs_different_canonical"] += 1
            differs |= not same
        counts["links_different_canonical" if differs else "links_same_canonical"] += 1
    return dict(counts)


def replay_authored(repo, work, report, audit):
    if work.exists() or work.is_relative_to(repo):
        raise ValueError("use a fresh private work directory outside the repository")
    work.mkdir(parents=True, mode=0o700)
    sys.path.insert(0, str(repo))
    from scripts.repeat_context_phase import infer_repeated_performance
    from scripts.repeat_context_study import (
        load_factorial_evaluation,
        load_reused_evaluation,
        prepare_factorial_inputs,
        prepare_reused_inputs,
    )
    cases = prepare_reused_inputs() + prepare_factorial_inputs()
    ledger = {r["id"]: r for r in report["cases"]}
    public = {r["id"]: r for scope in SCOPES for r in report["evaluation"]["cohorts"][scope]["case_rows"]}
    for index, case in enumerate(cases):
        cid = case["id"]
        payload = {"events": [asdict(e) for e in case["events"]], "length_q": case["length_q"]}
        before = digest(pretty(payload))
        audit.equal(before, ledger[cid]["input_file_sha256"], "replayed_authored_input_hash")
        audit.equal(digest(compact(payload["events"])), public[cid]["input_content_fingerprint"], "replayed_authored_input_content_hash")
        prediction = infer_repeated_performance(case["events"], case["length_q"])
        raw = pretty(prediction)
        audit.equal(digest(raw), ledger[cid]["prediction_file_sha256"], "replayed_authored_complete_prediction_hash")
        audit.equal(digest(compact(prediction)), public[cid]["prediction_content_fingerprint"], "replayed_authored_prediction_content_hash")
        audit.equal(digest(pretty({"events": [asdict(e) for e in case["events"]], "length_q": case["length_q"]})), before, "replayed_input_preservation")
        (work / (cid + ".json")).write_bytes(raw)
        if (index + 1) % 250 == 0:
            print("Verified authored replay", index + 1, "/", len(cases), flush=True)
    # No evaluation loader is called until every regenerated prediction has
    # matched the original/recovery byte receipt and been retained privately.
    labels = {**load_reused_evaluation(), **load_factorial_evaluation()}
    contexts = {scope: Counter() for scope in SCOPES}
    for case in cases:
        cid = case["id"]
        prediction = json.loads((work / (cid + ".json")).read_bytes())
        label = labels[cid]
        truth = {t["event_id"]: (t["pitch"], t["tick"]) for t in label["truth"]}
        fp = digest(compact(sorted([list(v) for v in truth.values()])))
        audit.equal(fp, public[cid]["truth_fingerprint"], "authored_truth_identity")
        for method in METHODS:
            arm = prediction["arms"][method]
            observed = public[cid]["arms"][method]
            full = arm["full_selected_assignments"]
            correct = None if full is None else ({a["event_id"]: (a["pitch"], a["tick"]) for a in full} == truth)
            audit.equal(observed["full_correct"], correct, "independent_authored_full_score")
            audit.equal(observed["per_hit"], score_hits(case["events"], arm["diagnostic_assignments"], truth), "independent_authored_per_hit")
            for full_flag, key in ((False, "diagnostic_joint_truth_available"), (True, "retained_joint_truth_available")):
                audit.equal(observed[key], check_joint_paths(case, prediction, method, truth, full_flag), "independent_authored_joint_truth")
        template = {
            36: [q * 12 for q in range(int(case["length_q"]))],
            38: [q * 12 for q in range(int(case["length_q"])) if q % 4 in (1, 3)],
            42: [i * 6 for i in range(int(case["length_q"]) * 2)],
        }
        counters = Counter()
        assignments = []
        constant = {}
        for event in case["events"]:
            tick = template[event.pitch][counters[event.pitch]]
            counters[event.pitch] += 1
            constant[event.event_id] = (event.pitch, tick)
            assignments.append({"event_id": event.event_id, "selected_tick": tick, "candidate_ticks": [tick], "collision": False})
        constant_arm = public[cid]["arms"]["always_four_on_floor"]
        audit.equal(constant_arm["full_correct"], constant == truth, "independent_constant_control")
        audit.equal(constant_arm["per_hit"], score_hits(case["events"], assignments, truth), "independent_constant_control")
        counts = link_truth(case, prediction, truth)
        audit.equal(public[cid]["repeat_context"]["evaluation_only_link_truth"], counts, "independent_authored_link_truth")
        if label["counterfactual_pair"] is None:
            contexts[case["scope"]].update(counts)
    for scope, counts in contexts.items():
        audit.equal(report["summary"][scope]["context"]["evaluation_only_link_truth"], dict(counts), "independent_link_truth_aggregate")
    return {"cases": len(cases), "all_original_prediction_hashes_matched": True,
            "evaluation_loaders_called_after_all_replay_predictions_verified": True,
            "link_truth_totals": {k: dict(v) for k, v in contexts.items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--replay-authored", action="store_true")
    parser.add_argument("--work", type=Path)
    args = parser.parse_args()
    repo = args.repo.resolve()
    archive = args.archive or repo / "docs/research/receipts/repeat-context-recovery-43261359821.zip"
    if args.replay_authored and args.work is None:
        parser.error("--replay-authored requires --work outside the repository")
    started = time.monotonic()
    report, identity = load_archive(archive, RECOVERY_SHA256, RECOVERY_BYTES)
    original, original_identity = load_archive(repo / "docs/research/receipts/repeat-context-incomplete-43256776331.zip", ORIGINAL_SHA256)
    audit = Audit()
    inherited = check_chain(repo, report, original, identity, original_identity, audit)
    totals = aggregate_authored(report, audit)
    replay = replay_authored(repo, args.work.resolve(), report, audit) if args.replay_authored else None
    result = {
        "schema_version": 1, "status": "pass", "scope": "recovery identity, authored aggregates and optional independent authored evaluation",
        "input_archive": identity, "original_archive": original_identity,
        "prior_independent_audit_receipts": inherited,
        "script_sha256": digest(Path(__file__).read_bytes()),
        "checks_passed": sum(audit.counts.values()), "checks_by_kind": dict(audit.counts),
        "maximum_numeric_difference": audit.max_numeric_difference,
        "authored_summary": totals, "authored_replay": replay,
        "elapsed_seconds": time.monotonic() - started,
        "dependencies": "Python standard library; frozen repository generators and selector only when replay enabled",
        "limitations": [
            "Authored replay reuses the frozen generators and selector, tied to the prior independent model/source audits by complete file SHA256 parity.",
            "The study evaluator, outcome counters, joint-truth helpers and repeat-link truth scorer are never called by this audit.",
            "The independent code scores existing authored development cases; it adds no new accuracy sample or independent truth source.",
            "Real selected ticks are not regenerated here; real source/mask/paired arithmetic has a separate audit with explicit scope limits.",
            "This audit makes no product accuracy, audio-clock, duration, rest, engraving or naturalness claim.",
        ],
        "raw_musical_arrays_published": False, "source_network_downloads": 0,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(pretty(result))
    print(json.dumps({"status": result["status"], "checks_passed": result["checks_passed"],
                      "maximum_numeric_difference": audit.max_numeric_difference,
                      "authored_replay_cases": replay["cases"] if replay else 0}))


if __name__ == "__main__":
    main()

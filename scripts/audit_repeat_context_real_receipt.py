"""Independently audit public real-reference arithmetic and source continuity.

This standalone, standard-library script imports no repository estimator,
evaluator, generator or source parser. It consumes the official recovery report
and the previously committed independent source audit. It does not re-parse the
musical sources or independently infer correctness from private predicted ticks.
In particular, two individually wrong predictions cannot be distinguished as
same-wrong versus disagreement from the public case masks alone.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from itertools import combinations
from pathlib import Path

REPORT_SHA256 = "b64985586ec5f0340a61b45bce99107bccfd60d50bd3d19491e0f524c699bf93"
SOURCE_AUDIT_SHA256 = "b21728b8bd92d4e9525c79a72d8314a8ed5424ce9b85375192d95a2b81c7bca2"
METHODS = (
    "straight_narrow", "global_phase", "local_switch005",
    "repeat_soft0025", "repeat_soft010", "repeat_hard",
)
STATUS = {"C": "correct", "W": "wrong", "A": "abstained", "U": "unobserved"}
PAIR_STATUS = {
    "C": "same_correct", "W": "same_wrong", "D": "disagreement",
    "A": "abstention", "U": "unobserved",
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def audit(report_path, source_path):
    checks = Counter()
    residual_pair_counts = Counter()
    expected_pair_counts = Counter()

    def equal(kind, left, right):
        if left != right:
            raise ValueError(f"{kind}: {left!r} != {right!r}")
        checks[kind] += 1

    def valid(kind, value):
        equal(kind, value, True)

    report_bytes, source_bytes = report_path.read_bytes(), source_path.read_bytes()
    equal("official_recovery_report_hash", digest(report_bytes), REPORT_SHA256)
    equal("committed_source_audit_hash", digest(source_bytes), SOURCE_AUDIT_SHA256)
    report, source = json.loads(report_bytes), json.loads(source_bytes)
    equal("official_run", report["workflow_run_id"], "43261359821")
    equal("official_success", report["status"], "complete")
    equal("historical_source_audit_scope", source["status"], "pass_for_source_and_execution_ledger_only")
    ledger = {row["id"]: row for row in report["cases"]}
    results = {}

    for scope in ("reused_real", "additional_real"):
        cohort = report["evaluation"]["cohorts"][scope]
        rows = cohort["case_rows"]
        summary = cohort["summary"]
        historical = source["source_admission"]["cohorts"][scope]
        original_rows = {row["id"]: row for row in historical["cases"]}
        equal("real_case_population", {row["id"] for row in rows}, set(original_rows))
        equal("top_level_summary_identity", report["summary"][scope], summary)
        equal("source_target_denominator", summary["ordinary_targets"], historical["total_ordinary_targets"])
        equal("source_input_denominator", summary["input_attacks"], historical["total_input_attacks"])
        equal("source_grace_denominator", summary["grace_targets"], historical["total_grace_targets"])
        equal("row_target_denominator", sum(row["ordinary_targets"] for row in rows), summary["ordinary_targets"])
        equal("row_input_denominator", sum(row["input_event_count"] for row in rows), summary["input_attacks"])

        for row in rows:
            prior = original_rows[row["id"]]
            receipt = row["evaluation_receipt"]
            input_receipt = ledger[row["id"]]["receipt"]
            equal("source_input_event_hash", row["input_content_fingerprint"], prior["input_events_sha256"])
            for key in ("canonical_score_map_sha256", "target_notes_sha256", "input_links_sha256"):
                equal("source_canonical_hash", receipt[key], prior[key])
            for key in set(prior) & set(input_receipt):
                equal("source_input_receipt_field", input_receipt[key], prior[key])
            for key in ("score_id", "ordinary_targets", "grace_targets", "input_classifications"):
                equal("source_case_population_field", row[key], prior[key])
            equal("source_ordinary_coverage", row["ordinary_target_coverage"], prior["ordinary_coverage"])
            if "canonical_serialization" in receipt:
                for key, value in prior["canonical_serialization"].items():
                    equal("source_serialization_contract", receipt["canonical_serialization"][key], value)

            count = row["ordinary_targets"]
            keys, coverage = row["reference_keys"], row["reference_coverage"]
            equal("reference_key_count", len(keys), count)
            equal("reference_keys_unique", len(set(keys)), count)
            equal("reference_coverage_count", len(coverage), count)
            equal("reference_coverage_histogram", dict(Counter(coverage)), row["ordinary_target_coverage"])
            equal("input_classifications_exhaustive", sum(row["input_classifications"].values()), row["input_event_count"])
            equal("lattice_mask_length", len(row["lattice_support_mask"]), count)
            valid("lattice_mask_alphabet", set(row["lattice_support_mask"]) <= set("01"))
            equal("real_method_population", set(row["arms"]), set(METHODS))

            for method, arm in row["arms"].items():
                masks = arm["reference_masks"]
                for key, mask in masks.items():
                    equal("reference_mask_length", len(mask), count)
                    valid("reference_mask_alphabet", set(mask) <= (set(STATUS) if key == "status" else set("01?")))
                status = masks["status"]
                for code, field in STATUS.items():
                    equal("case_mask_count", status.count(code), arm[field])
                equal("case_mask_total", arm["targets"], count)
                equal("case_observed_total", arm["observed"], count - status.count("U"))
                for key, field in (("onset_correct", "onset_correct"),
                                   ("truth_in_diagnostic_candidates", "truth_in_diagnostic_candidates"),
                                   ("diagnostic_collision", "diagnostic_collision_observations")):
                    equal("case_boolean_mask_count", masks[key].count("1"), arm[field])
                equal("case_pitch_mismatch_count", masks["pitch_match"].count("0"), arm["pitch_mismatched_observations"])
                equal("case_lattice_count", row["lattice_support_mask"].count("1"), arm["lattice_supported_targets"])
                for index, outcome in enumerate(status):
                    equal("unobserved_target_retained", outcome == "U", coverage[index] != "observed")
                    if outcome == "C":
                        equal("correct_target_onset_and_pitch", (masks["onset_correct"][index], masks["pitch_match"][index]), ("1", "1"))
                        equal("correct_target_lattice_supported", row["lattice_support_mask"][index], "1")
                if method.startswith("repeat_"):
                    equal("real_no_repeat_links", row["repeat_context"]["link_count"], 0)
                    base = row["arms"]["local_switch005"]
                    equal("real_repeat_equals_local_masks", masks, base["reference_masks"])
                    for key in ("full_status", "full_selected_fingerprint", "diagnostic_status_counts",
                                "diagnostic_path_count", "full_path_count", "diagnostic_retained_states",
                                "full_retained_states", "conditional_observed_diagnostic_truth_available",
                                "conditional_observed_retained_truth_available"):
                        equal("real_repeat_equals_local_decisions", arm[key], base[key])

        by_id = {row["id"]: row for row in rows}
        expected_pairs = {frozenset(pair) for pair in combinations(by_id, 2)}
        equal("pair_population", {frozenset((p["left"], p["right"])) for p in cohort["pair_rows"]}, expected_pairs)
        historic_pairs = {frozenset((p["left"], p["right"])): p for p in historical["same_score_pairs"]}
        pair_totals = {method: Counter() for method in METHODS}
        for pair in cohort["pair_rows"]:
            left, right = by_id[pair["left"]], by_id[pair["right"]]
            equal("pair_score_classification", pair["same_score"], left["score_id"] == right["score_id"])
            if not pair["same_score"]:
                valid("different_score_source_hashes", left["score_sha256"] != right["score_sha256"])
                continue
            same_source = historic_pairs[frozenset((pair["left"], pair["right"]))]
            equal("same_score_source_hash", left["score_sha256"], right["score_sha256"])
            equal("same_score_canonical_content", left["ordinary_truth_content_fingerprint"], right["ordinary_truth_content_fingerprint"])
            equal("same_score_reference_keys", set(left["reference_keys"]), set(right["reference_keys"]))
            equal("same_score_original_pair_denominator", len(left["reference_keys"]), same_source["canonical_ordinary_pairs"])
            lookup = {key: i for i, key in enumerate(right["reference_keys"])}
            both_observed = sum(left["reference_coverage"][i] == right["reference_coverage"][lookup[key]] == "observed"
                                for i, key in enumerate(left["reference_keys"]))
            equal("same_score_original_joint_coverage", both_observed, same_source["both_observed_pairs"])
            for method in METHODS:
                result = pair["methods"][method]
                pmask = result["reference_status_mask"]
                equal("paired_mask_length", len(pmask), len(left["reference_keys"]))
                valid("paired_mask_alphabet", set(pmask) <= set(PAIR_STATUS))
                for code, field in PAIR_STATUS.items():
                    equal("paired_mask_count", pmask.count(code), result["ordinary_reference_pairs"][field])
                    pair_totals[method][field] += pmask.count(code)
                equal("paired_target_total", result["ordinary_reference_pairs"]["targets"], len(pmask))
                lm = left["arms"][method]["reference_masks"]["status"]
                rm = right["arms"][method]["reference_masks"]["status"]
                for index, key in enumerate(left["reference_keys"]):
                    a, b = lm[index], rm[lookup[key]]
                    if "U" in (a, b):
                        expected = "U"
                    elif "A" in (a, b):
                        expected = "A"
                    elif a == b == "C":
                        expected = "C"
                    elif "C" in (a, b):
                        expected = "D"
                    else:
                        valid("both_wrong_pair_valid_partition", pmask[index] in "WD")
                        residual_pair_counts[scope + "/" + method] += 1
                        continue
                    equal("pair_category_from_case_masks", pmask[index], expected)
                    expected_pair_counts[scope + "/" + method] += 1

        for method in METHODS:
            ms = summary["methods"][method]
            equal("paired_summary_from_masks", ms["paired_references"], dict(pair_totals[method]))
            equal("paired_denominator_including_missing", sum(ms["paired_references"].values()), historical["total_canonical_same_score_reference_pairs"])
            statuses = "".join(row["arms"][method]["reference_masks"]["status"] for row in rows)
            for code, field in STATUS.items():
                equal("real_summary_from_masks", ms[field], statuses.count(code))
            transitions = Counter()
            for row in rows:
                baseline = row["arms"]["local_switch005"]["reference_masks"]["status"]
                current = row["arms"][method]["reference_masks"]["status"]
                transitions.update(STATUS[a] + "_to_" + STATUS[b] for a, b in zip(baseline, current, strict=True))
            equal("real_transition_summary", dict(transitions), ms["outcomes_vs_local"])
            for baseline in ("straight_narrow", "global_phase", "local_switch005"):
                previous = "".join(row["arms"][baseline]["reference_masks"]["status"] for row in rows)
                gained = sum(a != "C" and b == "C" for a, b in zip(previous, statuses, strict=True))
                lost = sum(a == "C" and b != "C" for a, b in zip(previous, statuses, strict=True))
                equal("real_gains", ms["correct_gained_vs_" + baseline], gained)
                equal("real_losses", ms["correct_lost_vs_" + baseline], lost)
            rates = []
            for score in ms["by_score"]:
                score_masks = "".join(row["arms"][method]["reference_masks"]["status"]
                                      for row in rows if row["score_id"] == score["score_id"])
                equal("by_score_denominator", score["targets"], len(score_masks))
                for code, field in STATUS.items():
                    equal("by_score_mask_total", score[field], score_masks.count(code))
                rates.append(score_masks.count("C") / len(score_masks))
            equal("equal_score_rate", ms["equal_score_correct_rate"], sum(rates) / len(rates))

        results[scope] = {
            "input_attacks": summary["input_attacks"],
            "ordinary_targets": summary["ordinary_targets"],
            "canonical_same_score_reference_pairs": historical["total_canonical_same_score_reference_pairs"],
            "primary_outcomes": {k: summary["methods"]["repeat_soft010"][k]
                                 for k in ("correct", "wrong", "abstained", "unobserved")},
            "primary_paired_references": dict(pair_totals["repeat_soft010"]),
        }

    context_summaries = {}
    for scope, cohort in report["evaluation"]["cohorts"].items():
        rows = [row for row in cohort["case_rows"] if not row.get("counterfactual_pair")]
        reported = cohort["summary"]["context"]
        fields = ("block_count", "eligible_block_count", "link_count", "linked_event_pair_count",
                  "distinct_linked_event_count", "unlinked_event_count")
        aggregate = {key: sum(row["repeat_context"][key] for row in rows) for key in fields}
        aggregate["cases"] = len(rows)
        aggregate["cases_with_links"] = sum(row["repeat_context"]["link_count"] > 0 for row in rows)
        reasons, truth = Counter(), Counter()
        for row in rows:
            context = row["repeat_context"]
            reasons.update(context["eligibility_reason_counts"])
            truth.update(context["evaluation_only_link_truth"])
            equal("context_block_reason_partition", sum(context["eligibility_reason_counts"].values()), context["block_count"])
            equal("context_eligible_reason", context["eligibility_reason_counts"].get("eligible", 0), context["eligible_block_count"])
            equal("context_event_partition", context["distinct_linked_event_count"] + context["unlinked_event_count"], row.get("event_count", row.get("input_event_count")))
            lt = context["evaluation_only_link_truth"]
            equal("context_link_truth_partition", sum(lt["links_" + k] for k in ("same_canonical", "different_canonical", "unscorable")), context["link_count"])
            equal("context_event_pair_truth_partition", sum(lt["event_pairs_" + k] for k in ("same_canonical", "different_canonical", "unscorable")), context["linked_event_pair_count"])
        aggregate["eligibility_reason_counts"] = dict(reasons)
        aggregate["evaluation_only_link_truth"] = dict(truth)
        equal("context_summary_from_rows", aggregate, reported)
        context_summaries[scope] = aggregate

    return {
        "schema_version": 1,
        "status": "pass_for_public_real_arithmetic_and_source_continuity",
        "scope": "independent public-mask arithmetic, reference denominators, historical source-receipt continuity and context aggregation",
        "checks_passed": sum(checks.values()),
        "checks_by_kind": dict(sorted(checks.items())),
        "input_report": {"run_id": 43261359821, "bytes": len(report_bytes), "sha256": digest(report_bytes)},
        "input_source_audit": {"filename": source_path.name, "bytes": len(source_bytes), "sha256": digest(source_bytes)},
        "script_sha256": digest(Path(__file__).read_bytes()),
        "real_cohorts": results,
        "context_summaries": context_summaries,
        "pair_categories_uniquely_reconstructed_from_case_masks": dict(expected_pair_counts),
        "both_wrong_pair_categories_requiring_private_ticks_for_full_rejudgment": dict(residual_pair_counts),
        "repository_imports": [],
        "network_downloads": 0,
        "model_calls": 0,
        "source_files_reparsed": 0,
        "product_activation_claimed": False,
        "limitations": [
            "Original musical sources were independently parsed in the committed prior audit; this audit verifies receipt continuity and does not repeat that parsing.",
            "Individual correctness masks are accepted as public evaluation evidence; private predicted ticks are not available in this artifact.",
            "Both-wrong pairs are checked for a valid same-wrong/disagreement partition and summary arithmetic, but that choice cannot be independently adjudicated from public masks alone.",
            "False-repeat link counts are independently aggregated and partition-checked here, not rejudged from raw event pairs and canonical truth.",
            "The actual cohort has zero repeat links; equality to the local comparator does not establish successful repeated-context use on human performances.",
            "Fixed supplied beat clocks and publisher note alignment condition these metrics; no fresh audio transcription, inferred-clock, duration/rest or final-score quality claim follows.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--source-audit", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = audit(args.report, args.source_audit)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({"status": result["status"], "checks_passed": result["checks_passed"]}))


if __name__ == "__main__":
    main()

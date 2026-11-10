"""Validate metadata-only CPU reports; never rank note AMT and F0 together."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.run_cpu_vocadito_candidates import CANDIDATES, CASE_IDS, NOTE_MODELS, complete_macro


def summarize(reports: list[dict]) -> dict:
    seen = set()
    identities = {}
    source = None
    result = {"all_candidates_complete": False, "note_amt": [], "f0_tracking": [],
              "missing_candidates": [], "quality_approved": False,
              "speed_ranking_approved": False}
    for report in reports:
        candidate = report["candidate"]
        if candidate not in CANDIDATES or candidate in seen:
            raise ValueError("Unexpected or duplicate candidate report")
        seen.add(candidate)
        task = "note_amt" if candidate in NOTE_MODELS else "f0_tracking"
        if report["task"] != task or report.get("device") != "cpu":
            raise ValueError("Task or device mismatch")
        identity = (report.get("archive_sha256"), report.get("source_revision"))
        if not all(identity) or (source is not None and source != identity):
            raise ValueError("Different corpus or code revisions")
        source = identity
        case_ids = set()
        for row in report["cases"]:
            case = row["id"]
            if case not in CASE_IDS or case in case_ids:
                raise ValueError("Unexpected or duplicate recording")
            case_ids.add(case)
            refs = row["reference_sha256"]
            proof = (row["audio_sha256"], refs["A1"], refs["A2"], row["f0_reference_sha256"])
            if not all(proof) or (case in identities and identities[case] != proof):
                raise ValueError("Different audio or independent references")
            identities[case] = proof
        macro = complete_macro(report["cases"], task)
        if macro != report.get("macro") or (macro is not None) != report["all_cases_complete"]:
            raise ValueError("Claimed aggregate disagrees with complete per-case evidence")
        result[task].append({"candidate": candidate, "complete": macro is not None,
                             "scored_recordings": sum(r.get("status") == "scored" for r in report["cases"]),
                             "planned_recordings": 40, "macro": macro})
    result["missing_candidates"] = sorted(set(CANDIDATES) - seen)
    result["all_candidates_complete"] = not result["missing_candidates"] and all(
        row["complete"] for task in ("note_amt", "f0_tracking") for row in result[task]
    )
    result["source_identity"] = source
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    reports = [json.loads(p.read_text(encoding="utf-8")) for p in args.reports.glob("*.json")]
    result = summarize(reports)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["all_candidates_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

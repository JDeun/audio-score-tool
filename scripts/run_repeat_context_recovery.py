"""Recover only public JSON whitespace after exact replay of the frozen failed study.

The original runner, estimator, sources and evaluator remain unchanged. A single
explicit evaluation callback verifies every saved input/prediction file against
the original failed receipt before invoking the original evaluator once. The
legacy budget failure remains private evidence; compact public JSON preserves
the evaluated fields under the original byte limits.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import subprocess
import time
import zipfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

from scripts import run_repeat_context as legacy

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL_HEAD = "cbcf97e0dc7fbd56bc3052e3f8daa30475b36cad"
ORIGINAL_CHECKOUT = "357c7531fd3d10364c515b8a45a0607bea30afa4"
ORIGINAL_TREE = "5cccebbe6b4aa5342790feae9183b1be36505134"
ORIGINAL_RUN_ID = "43256776331"
ORIGINAL_ARCHIVE = "docs/research/receipts/repeat-context-incomplete-43256776331.zip"
ORIGINAL_INVENTORY_SHA256 = "e064a35c1927fc6e1004186552312de896fd7e99828a1789d1465a929e00b19f"
KNOWN_BUDGET_ERROR = "ValueError: combined public metadata exceeds the report budget"
MAX_REPORT_BYTES = 32_000_000
MAX_EVALUATION_BYTES = 30_000_000
NEW_SOURCE_PATHS = (
    "scripts/run_repeat_context_recovery.py",
    "tests/test_run_repeat_context_recovery.py",
    ".github/workflows/cpu-repeat-context-recovery.yml",
    "docs/research/REPEAT_CONTEXT_RECOVERY_2026-11-13.md",
    "scripts/research_test_manifest.json",
)
# Original 29 unchanged paths plus the exact failed archive. The historical
# inventory is verified against its committed blob; the current inventory grows.
FROZEN_SOURCE_SHA256 = {
    ".github/workflows/cpu-repeat-context.yml": "510f84df0b847520a117eb10fbe43470c964e4eeae8dcbd321eae8b9dca63bdf",
    ".github/workflows/cpu-same-score-expression.yml": "71d67983fd0526ad9be1df980ab99cde53322582ee28f9cf7e88d1f5e76930c3",
    "docs/research/REPEAT_CONTEXT_PROTOCOL_2026-11-13.md": "b9ad51eddc45d08df679c446afadebf4e1d17fc0b286b2d06f2c2afc598137b3",
    "docs/research/SAME_SCORE_EXPRESSION_PROTOCOL_2026-11-12.md": "d94b5f4a238f8534f20d9b998fffd97ec125ea84b1afce4d204c2fc9b6049472",
    "docs/research/receipts/repeat-context-incomplete-43256776331.zip": "cf11f4757ae756878b108ab7b89a49a90db71b5c9fa04803a79f00d1c9e4f93e",
    "docs/research/receipts/same-score-expression-43247249315.zip": "38107d18e89058ef4e870214e0ba5af0bb7b97eb92d1b7ef056e9096c30c7f17",
    "scripts/audit_nasap_duration_source.py": "c63c44b2a6c5a391d972b22417cba21830b71c0bed2dd6996b38f9f93044244c",
    "scripts/nasap_duration_probe.py": "881a0a7544745d5fe50317ca81bca8ea05adce510bbfb2facc46405c65ffa973",
    "scripts/nasap_joint_rhythm.py": "e2f136d486c0ef14206469db1a4b1c7a5dfc5dfcd55de3c3a80df2f6f5263681",
    "scripts/nasap_keyoff_paired.py": "97368c713177ac5537a6c22f57689d375260674a36efe5b92cbfbd64131a641a",
    "scripts/nasap_repeat_context_manifest.json": "87544fc4e8774a54f63cf49075ddec077171745a12eb98efd43edaa7b97669ba",
    "scripts/nasap_repeat_context_source.py": "bd16c2e7b0d67e98ff52b2d5db2b906b8708f026c8c9869b7e83638527488272",
    "scripts/nasap_same_score_manifest.json": "27c576542fef26dbca605db4a9f938cc00451702b2c7f441aa84013fe3496239",
    "scripts/nasap_same_score_source.py": "a1a60da73da4f25dad5ddd3b1576a2dbee42a5d750e7b212eea4b318042c1f0a",
    "scripts/performed_rhythm_invariance.py": "7f42567f97a5b5b51053bcd9e9a5a9859701190971d33df4c308af5f0f11ab22",
    "scripts/repeat_context_phase.py": "4380bfb2867cf3aa3902ee63205be8619fac75f524db01a6afdee02d038bda76",
    "scripts/repeat_context_study.py": "17a1bd689a146e1de442b3b26c6fb74d46584ce155f872b363431f19702cbb28",
    "scripts/rhythm_invariance_study.py": "adcf66f68514c844f33e9f3b77cfd1a658d7a965bd4226fa6cc0a9532d503e45",
    "scripts/run_repeat_context.py": "2e5361d8c1d63187ebd62868e12c9bc081d229beb1d8e368cdfd4830eb187445",
    "scripts/run_same_score_expression.py": "de53182ca4072d8193bac834f802445b434675af079d44a16dde0fd9cf59d28c",
    "scripts/same_score_expression_study.py": "3520016223c1655f5d5856631d831e714c7757c0b98642e48adf0c1cee8285c5",
    "scripts/same_score_phase.py": "109985eeb81f8119c202927b1c6f9e7e285cec83c38f549908e36a15c3c69aa3",
    "tests/test_nasap_repeat_context_source.py": "cfa4d7da4d180b20b76d47400d6e630a143b8aa8f003477f6a279b94292e2393",
    "tests/test_nasap_same_score_source.py": "521a1fe7c8d4f2f0457d21363f42bf4afc2bb84dcfbab64b91c2bd649c4de7ce",
    "tests/test_repeat_context_phase.py": "4294ae75722fa1d4e4f1649821f8de48ce1a85649de68bd3f9c13fe57eaf851d",
    "tests/test_repeat_context_study.py": "64f413a3c82e4f8834fd70fa61b857d553414bcbae08d69614c688040efb3095",
    "tests/test_run_repeat_context.py": "6bf2097dd00db00597d2d79c21cf36647270248072e0dfb88a98457f38650bf7",
    "tests/test_run_same_score_expression.py": "44317b858fa537ed887a6c335ab5b6456feee3e08e87fd3ddece255f0ddfe6ef",
    "tests/test_same_score_expression_study.py": "b924c45badffab8569cbe7fd7c018709d67c40ec81698c569aab2aa8f4a404a2",
    "tests/test_same_score_phase.py": "db0c2cf6ad780ce2f6977fbe9eb87c34579e72f69ee2f90672aeadf643ee7389"
}
MEASURED_SOURCE_PATHS = NEW_SOURCE_PATHS + tuple(FROZEN_SOURCE_SHA256)


@dataclass(frozen=True)
class Contract:
    archive: Path
    archive_bytes: int
    archive_sha256: str
    report_bytes: int
    report_sha256: str
    planned_scopes: tuple[tuple[str, tuple[str, ...]], ...]
    original_source_sha256: tuple[tuple[str, str], ...]
    source_head: str = ORIGINAL_HEAD
    checkout_revision: str = ORIGINAL_CHECKOUT
    checkout_tree: str = ORIGINAL_TREE
    run_id: str = ORIGINAL_RUN_ID
    report_limit: int = MAX_REPORT_BYTES
    evaluation_limit: int = MAX_EVALUATION_BYTES


CONTRACT = Contract(
    ROOT / ORIGINAL_ARCHIVE, 361958,
    "cf11f4757ae756878b108ab7b89a49a90db71b5c9fa04803a79f00d1c9e4f93e",
    2842632, "568898b9c1f1fb6d5d2671e1805305eaa2939b2d1580175f0e2d6fc43e16c559",
    tuple((scope, tuple(legacy.DECLARED_PLANS[scope])) for scope in legacy.SCOPES),
    tuple({**{p: sha for p, sha in FROZEN_SOURCE_SHA256.items() if p != ORIGINAL_ARCHIVE},
           "scripts/research_test_manifest.json": ORIGINAL_INVENTORY_SHA256}.items()),
)


@dataclass(frozen=True)
class Dependencies:
    execute_legacy: Callable
    legacy_dependencies: Callable
    provenance: Callable


def _dependencies():
    return Dependencies(legacy.run, legacy._dependencies, collect_provenance)


def compact(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def _file_sha256(path, maximum):
    if any(part.is_symlink() for part in (path, *path.parents)) or not path.is_file():
        raise ValueError("missing or linked evidence file")
    if path.stat().st_size > maximum:
        raise ValueError("evidence file exceeds its declared byte bound")
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1_048_576):
            sha.update(chunk)
    return sha.hexdigest()


def collect_provenance():
    hashes = {}
    if len(set(MEASURED_SOURCE_PATHS)) != len(MEASURED_SOURCE_PATHS):
        raise ValueError("duplicate recovery measurement")
    for relative in MEASURED_SOURCE_PATHS:
        hashes[relative] = _file_sha256(ROOT / relative, 1_000_000)
        if relative in FROZEN_SOURCE_SHA256 and hashes[relative] != FROZEN_SOURCE_SHA256[relative]:
            raise ValueError("the original scientific source or archive changed: " + relative)
    historical = subprocess.run(
        ["git", "show", ORIGINAL_HEAD + ":scripts/research_test_manifest.json"], cwd=ROOT,
        capture_output=True, check=True, timeout=10,
    ).stdout
    if legacy.digest(historical) != ORIGINAL_INVENTORY_SHA256:
        raise ValueError("historical scientific test inventory differs from its frozen commit")
    result = legacy.collect_provenance()
    result.update(
        source_sha256=hashes, frozen_source_sha256=dict(FROZEN_SOURCE_SHA256),
        recovery_base_revision=ORIGINAL_HEAD,
        recovery_inventory={"original_revision": ORIGINAL_HEAD,
                            "original_sha256": ORIGINAL_INVENTORY_SHA256,
                            "current_sha256": hashes["scripts/research_test_manifest.json"],
                            "historical_blob_verified": True},
    )
    return result


def _assert_public(value, private_roots):
    """Keep the frozen privacy rules, independently of JSON whitespace length."""
    forbidden = {"events", "raw_events", "event_arrays", "raw_midi", "raw_bytes", "assignments",
                 "private_predictions", "prediction_events", "audio_samples", "waveform",
                 "score_events", "score_rows", "alignment_rows", "full_candidate_assignments",
                 "full_selected_assignments", "diagnostic_assignments", "path_sets"}
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str) and (key in forbidden or key.endswith(("_path", "_paths"))):
                raise ValueError("private source or prediction field in public recovery metadata")
            if key in ("target_notes", "input_links") and isinstance(child, (dict, list, tuple)):
                raise ValueError("private evaluation records in public recovery metadata")
            _assert_public(child, private_roots)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _assert_public(child, private_roots)
    elif isinstance(value, str) and any(str(root) in value for root in private_roots):
        raise ValueError("private filesystem location in public recovery metadata")


def _save(output, report, contract, private_roots):
    _assert_public(report, private_roots)
    raw = compact(report)
    reserve = min(2_000_000, contract.report_limit // 10)
    if len(raw) > contract.report_limit - reserve:
        raise ValueError("compact public report still exceeds the original budget and reserve")
    legacy._atomic_write(output, raw)


def _plan(contract):
    return {scope: list(ids) for scope, ids in contract.planned_scopes}


def _initial_report(contract):
    plan = _plan(contract)
    ids = [tid for group in plan.values() for tid in group]
    return {
        "schema_version": 1, "status": "recovery_running", "planned_ids": ids, "planned_scopes": plan,
        "expected_scope_case_counts": {scope: len(group) for scope, group in plan.items()},
        "planned_inferences": len(ids), "completed_inferences": 0, "completed_preservation_checks": 0,
        "cases": [{"id": tid, "scope": scope, "status": "planned", "evaluation_status": "pending",
                   "input_file_sha256": None, "prediction_file_sha256": None,
                   "event_mutation_check_passed": False} for scope, group in plan.items() for tid in group],
        "evaluation": None, "summary": None, "evaluation_started": False,
        "all_predictions_saved_before_evaluation": False,
        "source_head": os.getenv("EXPERIMENT_HEAD", "local"),
        "source_revision": os.getenv("GITHUB_SHA", "local"),
        "workflow_run_id": os.getenv("GITHUB_RUN_ID"), "workflow_run_attempt": os.getenv("GITHUB_RUN_ATTEMPT"),
        "recovery": {
            "strategy": "public_json_whitespace_only", "original_run_id": contract.run_id,
            "original_source_head": contract.source_head, "original_archive_sha256": contract.archive_sha256,
            "original_report_sha256": contract.report_sha256,
            "public_report_encoding": "sorted compact JSON plus newline; finite numbers only",
            "private_prediction_encoding": "unchanged frozen indented JSON plus newline",
            "evaluation_sha256_encoding": "unchanged frozen indented JSON plus newline",
            "original_failure_retained": False, "legacy_invocations": 0, "study_evaluations": 0,
            "matched_input_files": 0, "matched_prediction_files": 0,
        },
    }


def _validate_complete_execution(report, contract):
    plan = _plan(contract)
    ids = [tid for group in plan.values() for tid in group]
    if (report["planned_scopes"] != plan or report["planned_ids"] != ids
            or [row["id"] for row in report["cases"]] != ids
            or report["planned_inferences"] != len(ids) or report["completed_inferences"] != len(ids)
            or report["completed_preservation_checks"] != len(ids)
            or not report["all_predictions_saved_before_evaluation"] or not report["evaluation_started"]
            or report["evaluation_loaded"] != {scope: True for scope in plan}):
        raise ValueError("the complete immutable prediction and evaluation-loading population is required")
    scopes = {tid: scope for scope, group in plan.items() for tid in group}
    if any(row["scope"] != scopes[row["id"]] or row["status"] != "inferred"
           or not row["event_mutation_check_passed"] or row["evaluation_status"] != "complete"
           for row in report["cases"]):
        raise ValueError("a planned case was not fully predicted and admitted")


def read_original(contract):
    if (contract.archive.stat().st_size != contract.archive_bytes
            or _file_sha256(contract.archive, contract.archive_bytes) != contract.archive_sha256):
        raise ValueError("the exact original failed archive changed")
    archive_bytes = contract.archive.read_bytes()
    if legacy.digest(archive_bytes) != contract.archive_sha256:
        raise ValueError("original archive changed while opening")
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        if (archive.namelist() != ["report.json"]
                or archive.getinfo("report.json").file_size != contract.report_bytes):
            raise ValueError("the original failed archive member inventory changed")
        raw = archive.read("report.json")
    if len(raw) != contract.report_bytes or legacy.digest(raw) != contract.report_sha256:
        raise ValueError("the exact original failed report changed")
    report = json.loads(raw)
    _validate_complete_execution(report, contract)
    if (report["status"] != "evaluation_failed" or report["failure_stage"] != "evaluation"
            or report["error_type"] != "ValueError" or report["evaluation"] is not None or report["summary"] is not None
            or report["source_head"] != contract.source_head
            or report["checkout_revision"] != contract.checkout_revision or report["checkout_tree"] != contract.checkout_tree
            or str(report["workflow_run_id"]) != contract.run_id or str(report["workflow_run_attempt"]) != "1"
            or report["source_sha256"] != dict(contract.original_source_sha256)):
        raise ValueError("the original failed execution provenance changed")
    return report


def _read_legacy_report(path, contract):
    if any(part.is_symlink() for part in (path, *path.parents)) or path.stat().st_size > contract.report_limit:
        raise ValueError("invalid replay receipt file")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("invalid replay receipt")
    return value


def verify_replay(original, replay, work, contract):
    _validate_complete_execution(replay, contract)
    expected_sources = dict(contract.original_source_sha256)
    if set(replay["source_sha256"]) != set(expected_sources):
        raise ValueError("the frozen runner scientific dependency inventory changed")
    for relative, expected in expected_sources.items():
        if relative != "scripts/research_test_manifest.json" and replay["source_sha256"][relative] != expected:
            raise ValueError("an original scientific dependency changed during replay")
    if replay["plan_sha256"] != original["plan_sha256"] or replay["prediction_set_sha256"] != original["prediction_set_sha256"]:
        raise ValueError("the original ordered prediction population changed")
    total_bytes = 0
    for expected, current in zip(original["cases"], replay["cases"], strict=True):
        for key in ("id", "scope", "input_event_count", "source_receipt_sha256", "prediction_bytes"):
            if current[key] != expected[key]:
                raise ValueError("an original input identity or preservation receipt changed")
        # Compare recorded receipt SHA directly: parsed JSON histogram keys are
        # strings, whereas the native source receipt can have integer keys.
        filename = legacy.digest(current["id"].encode()) + ".json"
        for directory, field in (("inputs", "input_file_sha256"), ("predictions", "prediction_file_sha256")):
            path = work / directory / filename
            actual = _file_sha256(path, legacy.MAX_PREDICTION_BYTES)
            if actual != current[field] or actual != expected[field]:
                raise ValueError("original receipt, replay row and private file do not have identical bytes")
            if directory == "predictions":
                if path.stat().st_size != current["prediction_bytes"]:
                    raise ValueError("private prediction byte count changed")
                total_bytes += path.stat().st_size
    if total_bytes != replay["private_prediction_bytes"] or total_bytes > legacy.MAX_ALL_PREDICTION_BYTES:
        raise ValueError("private prediction total changed or exceeded its frozen budget")
    for scope in legacy.REAL_SCOPES:
        for stage in ("inputs", "evaluation"):
            current = replay["source_acquisition"][scope][stage]
            expected = original["source_acquisition"][scope][stage]
            if current["members"] != expected["members"]:
                raise ValueError("source member bytes or identities changed during replay")
    count = len(original["cases"])
    return {"matched_input_files": count, "matched_prediction_files": count,
            "matched_source_receipts": count, "private_prediction_bytes": total_bytes,
            "comparison": "original recorded SHA == replay recorded SHA == actual private-file SHA"}


def _evaluation_fields(value, cases, predictions, replay, private_roots, contract):
    legacy._assert_frozen(cases, predictions, replay)
    if (not isinstance(value, dict) or not {"cohorts", "limitations"} <= set(value)
            or not isinstance(value["cohorts"], dict) or set(value["cohorts"]) != set(_plan(contract))):
        raise ValueError("all four complete cohort evaluations are required")
    sha = legacy._public_component(value, private_roots, contract.evaluation_limit)
    summary = {scope: value["cohorts"][scope]["summary"] for scope in _plan(contract)}
    if not all(isinstance(item, dict) for item in summary.values()):
        raise ValueError("all four original summaries are required")
    legacy._public_component(summary, private_roots)
    return summary, sha


def _known_failure(replay, exit_code, private_work):
    if (exit_code != 1 or replay["status"] != "evaluation_failed"
            or replay.get("failure_stage") != "evaluation" or replay.get("error_type") != "ValueError"
            or replay["evaluation"] is not None or replay["summary"] is not None):
        raise ValueError("the replay did not stop at the expected legacy public-budget failure")
    log = private_work / "failure.log"
    if log.is_symlink() or not log.is_file() or log.stat().st_size > 64_000:
        raise ValueError("the private legacy failure log is missing or oversized")
    if log.read_text().rstrip().splitlines()[-1] != KNOWN_BUDGET_ERROR:
        raise ValueError("the replay failure is not the known JSON byte-budget failure")


def run(work, output, *, deps=None, contract=CONTRACT):
    work, output = legacy._prepare_paths(work, output)
    started = time.monotonic()
    private_work, legacy_output = work / "legacy-run", work / "legacy-report.json"
    private_roots = (ROOT, work, output)
    report = _initial_report(contract)
    recovery = report["recovery"]
    _save(output, report, contract, private_roots)
    stage, captured, provenance = "recovery_provenance", {}, {}
    try:
        deps = _dependencies() if deps is None else deps
        provenance = deps.provenance()
        report.update(provenance)
        _save(output, report, contract, private_roots)
        base = deps.legacy_dependencies()

        def evaluate_once(cases, predictions, evaluation_map):
            nonlocal stage
            if captured:
                raise ValueError("only one evaluation callback is permitted")
            stage = "original_file_parity"
            replay = _read_legacy_report(legacy_output, contract)
            _validate_complete_execution(replay, contract)
            original = read_original(contract)
            parity = verify_replay(original, replay, private_work, contract)
            legacy._assert_frozen(cases, predictions, replay)
            recovery.update(parity)
            recovery["original_failure_retained"] = True
            _save(output, {**report, "recovery": recovery}, contract, private_roots)
            stage = "unchanged_evaluation"
            recovery["study_evaluations"] += 1
            value = base.evaluate_study(cases, predictions, evaluation_map)
            summary, sha = _evaluation_fields(value, cases, predictions, replay, private_roots, contract)
            captured.update(evaluation=value, summary=summary, evaluation_sha256=sha,
                            original=original, cases=cases, predictions=predictions)
            return value

        injected = replace(base, evaluate_study=evaluate_once)
        recovery["legacy_invocations"] += 1
        stage = "legacy_execution"
        exit_code = deps.execute_legacy(private_work, legacy_output, deps=injected)
        replay = _read_legacy_report(legacy_output, contract)
        report.update(replay)
        report.update(provenance)
        report["recovery"] = recovery
        if not captured or recovery["study_evaluations"] != 1:
            raise ValueError("no fully validated evaluation was captured")
        stage = "expected_legacy_failure"
        _known_failure(replay, exit_code, private_work)
        stage = "post_evaluation_preservation"
        recovery.update(verify_replay(captured["original"], replay, private_work, contract))
        legacy._assert_frozen(captured["cases"], captured["predictions"], replay)
        if legacy.digest(legacy.encoded(captured["evaluation"])) != captured["evaluation_sha256"]:
            raise ValueError("the captured unchanged evaluation was modified after its validation")
        recovery["parity_rechecked_after_evaluation"] = True
        recovery["original_failure"] = {
            "status": captured["original"]["status"], "failure_stage": captured["original"]["failure_stage"],
            "error_type": captured["original"]["error_type"], "evaluation": None, "summary": None,
        }
        recovery["replayed_legacy_failure"] = {
            "status": replay["status"], "failure_stage": replay["failure_stage"], "error_type": replay["error_type"],
            "known_budget_failure_verified": True, "elapsed_seconds": replay.get("elapsed_seconds"),
        }
        for key in ("failure_stage", "error_type", "reason"):
            report.pop(key, None)
        report.update(status="complete", evaluation=captured["evaluation"], summary=captured["summary"],
                      evaluation_sha256=captured["evaluation_sha256"],
                      elapsed_seconds=time.monotonic() - started)
        stage = "compact_publication"
        _save(output, report, contract, private_roots)
        return 0
    except Exception as exc:
        if legacy_output.is_file():
            try:
                partial = _read_legacy_report(legacy_output, contract)
                report.update(partial)
            except (OSError, ValueError, TypeError, KeyError):
                pass
        report.update(provenance)
        report["recovery"] = recovery
        report["evaluation"] = report["summary"] = None
        legacy._failure(report, "recovery_failed", stage, work, exc)
        report["elapsed_seconds"] = time.monotonic() - started
        _save(output, report, contract, private_roots)
        return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    return run(args.work, args.output)


if __name__ == "__main__":
    raise SystemExit(main())

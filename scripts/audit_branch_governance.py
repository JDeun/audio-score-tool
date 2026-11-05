"""Audit a GitHub main-branch protection policy from an exported REST snapshot.

Offline and read-only: no token handling, GitHub write requests, or policy
mutation. Admin access is required separately to *activate* the protections.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REQUIRED_CHECK = "verify"


def _checks(parameters: dict) -> set[str]:
    names = {
        item.get("context")
        for item in parameters.get("required_status_checks", [])
        if isinstance(item, dict)
    }
    names.update(
        item for item in parameters.get("contexts", [])
        if isinstance(item, str)
    )
    names.update(
        item.get("context")
        for item in parameters.get("checks", [])
        if isinstance(item, dict)
    )
    return {name for name in names if isinstance(name, str)}


def check_ruleset(data: dict[str, Any], *, branch: str = "main") -> list[str]:
    """Return explicit reasons this ruleset cannot protect the target branch."""
    issues = []
    if data.get("target") != "branch" or data.get("enforcement") != "active":
        issues.append("ruleset must actively enforce branch rules")
    conditions = data.get("conditions") or {}
    refs = conditions.get("ref_name") or {}
    includes = set(refs.get("include") or [])
    excludes = set(refs.get("exclude") or [])
    target = "refs/heads/" + branch
    if not ({target, "~DEFAULT_BRANCH", "~ALL"} & includes) or target in excludes:
        issues.append(f"ruleset must include {target} without excluding it")
    if data.get("bypass_actors"):
        issues.append("ruleset has bypass actors; admin bypass policy requires explicit review")
    rules = {item.get("type"): item for item in data.get("rules", [])
             if isinstance(item, dict)}
    for required in ("pull_request", "required_status_checks", "non_fast_forward", "deletion"):
        if required not in rules:
            issues.append(f"missing {required} rule")
    status = (rules.get("required_status_checks") or {}).get("parameters") or {}
    if REQUIRED_CHECK not in _checks(status):
        issues.append(f"missing required check: {REQUIRED_CHECK}")
    if status.get("strict_required_status_checks_policy") is not True:
        issues.append("required check must reject outdated head branches")
    return issues


def check_branch_protection(data: dict[str, Any]) -> list[str]:
    """Legacy protected-branch API fallback for repositories without rulesets."""
    failures = []
    if not isinstance(data.get("required_pull_request_reviews"), dict):
        failures.append("pull-request review protection is missing")
    status = data.get("required_status_checks") or {}
    if REQUIRED_CHECK not in _checks(status):
        failures.append(f"required check {REQUIRED_CHECK} is missing")
    if status.get("strict") is not True:
        failures.append("required checks must enforce up-to-date branches")
    for field in ("allow_force_pushes", "allow_deletions"):
        flag = data.get(field) or {}
        if flag.get("enabled") is not False:
            failures.append(f"{field} is not explicitly disabled")
    if (data.get("enforce_admins") or {}).get("enabled") is not True:
        failures.append("administrator bypass policy is not enforced")
    return failures


def audit(*, rulesets: list[dict] | None = None,
          protection: dict | None = None, branch: str = "main") -> dict:
    """Require one complete policy; unknown or empty policy never counts as safe."""
    rulesets = rulesets or []
    evaluations = []
    for candidate in rulesets:
        if not isinstance(candidate, dict):
            continue
        result = check_ruleset(candidate, branch=branch)
        evaluations.append({
            "name": str(candidate.get("name") or candidate.get("id") or "unidentified"),
            "violations": result,
        })
        if not result:
            return {"protected": True, "source": "ruleset", "branch": branch,
                    "violations": [], "evaluations": evaluations}
    if protection is not None:
        if not isinstance(protection, dict):
            raise ValueError("branch protection snapshot must be a JSON object")
        problems = check_branch_protection(protection)
        if not problems:
            return {"protected": True, "source": "branch_protection", "branch": branch,
                    "violations": [], "evaluations": evaluations}
        return {"protected": False, "source": "branch_protection", "branch": branch,
                "violations": problems, "evaluations": evaluations}
    return {
        "protected": False,
        "source": "unverified",
        "branch": branch,
        "violations": ["no complete verified branch protection or active repository ruleset provided"],
        "evaluations": evaluations,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline GitHub branch policy audit")
    parser.add_argument("--ruleset", type=Path, action="append", default=[],
                        help="complete repository ruleset detail JSON, repeatable")
    parser.add_argument("--protection", type=Path, help="branch protection GET JSON snapshot")
    parser.add_argument("--branch", default="main")
    args = parser.parse_args()
    snapshots = [json.loads(path.read_text(encoding="utf-8")) for path in args.ruleset]
    protection = (json.loads(args.protection.read_text(encoding="utf-8"))
                  if args.protection is not None else None)
    result = audit(rulesets=snapshots, protection=protection, branch=args.branch)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["protected"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

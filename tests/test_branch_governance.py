"""Ruleset/branch-protection policy acceptance tests; no live GitHub writes."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from scripts import audit_branch_governance as governance


def _ruleset() -> dict:
    return {
        "name": "main-release-gate",
        "target": "branch",
        "enforcement": "active",
        "conditions": {
            "ref_name": {"include": ["refs/heads/main"], "exclude": []},
        },
        "bypass_actors": [],
        "rules": [
            {"type": "pull_request", "parameters": {"required_approving_review_count": 0}},
            {"type": "required_status_checks", "parameters": {
                "strict_required_status_checks_policy": True,
                "required_status_checks": [{"context": "verify"}],
            }},
            {"type": "non_fast_forward"},
            {"type": "deletion"},
        ],
    }


def _legacy() -> dict:
    return {
        "required_pull_request_reviews": {"required_approving_review_count": 0},
        "required_status_checks": {"strict": True, "checks": [{"context": "verify"}]},
        "allow_force_pushes": {"enabled": False},
        "allow_deletions": {"enabled": False},
        "enforce_admins": {"enabled": True},
    }


def test_complete_ruleset_enforces_pr_ci_no_force_and_no_delete():
    assert governance.audit(rulesets=[_ruleset()])["protected"] is True


def test_complete_legacy_protection_is_accepted():
    result = governance.audit(protection=_legacy())
    assert result["protected"] is True
    assert result["source"] == "branch_protection"


@pytest.mark.parametrize("missing", [
    "pull_request", "required_status_checks", "non_fast_forward", "deletion",
])
def test_missing_ruleset_rule_rejected(missing: str):
    policy = _ruleset()
    policy["rules"] = [item for item in policy["rules"] if item["type"] != missing]
    assert governance.audit(rulesets=[policy])["protected"] is False


def test_stale_checks_or_other_branch_do_not_pass():
    policy = _ruleset()
    policy["rules"][1]["parameters"]["strict_required_status_checks_policy"] = False
    assert "outdated" in " ".join(governance.audit(rulesets=[policy])["evaluations"][0]["violations"])

    policy = _ruleset()
    policy["conditions"]["ref_name"]["include"] = ["refs/heads/develop"]
    assert governance.audit(rulesets=[policy])["protected"] is False


def test_bypass_rejected_until_manual_policy_review():
    policy = _ruleset()
    policy["bypass_actors"] = [{"actor_type": "RepositoryRole", "actor_id": 5}]
    assert "bypass" in " ".join(governance.check_ruleset(policy))


def test_legacy_force_push_or_delete_cannot_pass():
    for flag in ("allow_force_pushes", "allow_deletions"):
        data = _legacy()
        data[flag]["enabled"] = True
        assert governance.audit(protection=data)["protected"] is False


def test_no_admin_access_is_unknown_not_success():
    output = governance.audit(rulesets=[], protection=None)
    assert output["source"] == "unverified"
    assert output["protected"] is False
    assert output["violations"]


def test_cli_exits_nonzero_on_invalid_policy_and_zero_for_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
):
    filepath = tmp_path / "ruleset.json"
    filepath.write_text(json.dumps(_ruleset()), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["audit_branch_governance.py", "--ruleset", str(filepath)])
    assert governance.main() == 0
    assert json.loads(capsys.readouterr().out)["protected"] is True
    filepath.write_text(json.dumps({"rules": []}), encoding="utf-8")
    assert governance.main() == 1
    assert json.loads(capsys.readouterr().out)["protected"] is False

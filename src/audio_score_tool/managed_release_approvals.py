"""Offline release sign-off gate for app-managed runtime publication.

A catalog's "redistribution_status=approved" is an assertion, not evidence.
Only an exact catalog/evidence pair with separately reviewed license obligations
can make Setup Center's install operation eligible. This gate does not replace
legal counsel, independent signatures or clean-machine runtime acceptance.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.parse
from pathlib import Path
from typing import Any

_APPROVAL_FILENAME = "managed-release-approvals.json"
_SHA256 = re.compile(r"[a-f0-9]{64}\Z")
_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_UNREVIEWED = {"", "unknown", "tbd", "n/a", "runtime-specific", "...", "pending"}


def release_approvals_path() -> Path:
    override = os.getenv("AST_COMPONENT_APPROVALS")
    if override and os.getenv("AST_PACKAGED", "").strip() != "1":
        return Path(override).expanduser()
    return Path(__file__).with_name(_APPROVAL_FILENAME)


def load_release_approvals() -> dict[str, Any]:
    """A missing or unreadable approval file must never imply permission."""
    path = release_approvals_path()
    if path.is_symlink():
        raise ValueError("approval-record-unreadable")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("approval-record-unreadable") from exc
    if (
        not isinstance(value, dict)
        or value.get("schema") != 1
        or not isinstance(value.get("approvals"), dict)
    ):
        raise ValueError("approval-record-invalid")
    return value


def catalog_fingerprint(payload: dict[str, Any]) -> str:
    """Bind approval to the exact flattened catalog entry, not just a URL."""
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _reviewed_text(value: object) -> bool:
    return (
        isinstance(value, str)
        and value.strip().lower() not in _UNREVIEWED
        and len(value.strip()) <= 2048
    )


def _hex_sha(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _https_reference(value: object) -> bool:
    if not _reviewed_text(value):
        return False
    try:
        parsed = urllib.parse.urlsplit(str(value))
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and parsed.hostname.lower().rstrip(".") != "localhost"
        and not parsed.username
        and not parsed.password
        and not parsed.fragment
        and port in {None, 443}
    )


def check_release_approval(
    component: str,
    target: str,
    payload: dict[str, Any],
) -> str | None:
    """Reason for refusal, or None for one reviewed exact artifact/target.

    The remote verification proof originates from verify_managed_artifact_publication;
    license sign-off is supplied independently by an accountable human. Neither
    section can be generated as "approved" by a candidate preparation command.
    """
    try:
        data = load_release_approvals()
    except ValueError as exc:
        return str(exc)
    approved = data["approvals"].get(component)
    record = approved.get(target) if isinstance(approved, dict) else None
    if not isinstance(record, dict):
        return "approval-receipt-missing"
    if record.get("catalog_sha256") != catalog_fingerprint(payload):
        return "approval-catalog-drift"

    evidence = record.get("remote_evidence")
    if not isinstance(evidence, dict) or evidence.get("remote_artifact_verified") is not True:
        return "remote-evidence-missing"

    archive_hash = payload.get("sha256")
    tool_map = payload.get("tools")
    if not isinstance(tool_map, dict):
        return "remote-evidence-mismatch"
    evidence_tools = evidence.get("published_tool_sha256")
    if (
        evidence.get("schema_version") != "1"
        or evidence.get("component") != component
        or evidence.get("target") != target
        or evidence.get("version") != payload.get("version")
        or evidence.get("upstream_revision") != payload.get("upstream_revision")
        or evidence.get("published_archive_sha256") != archive_hash
        or evidence.get("published_url_sha256") != hashlib.sha256(
            str(payload.get("url", "")).encode("utf-8")
        ).hexdigest()
        or not _hex_sha(evidence.get("candidate_sha256"))
        or evidence.get("archive_checked_and_installed_locally") is not True
        or evidence.get("approval_required") is not True
        or evidence.get("redistribution_status") != "pending"
        or evidence.get("license_independently_approved") is not False
        or evidence.get("clean_machine_verified") is not False
        or not isinstance(evidence_tools, dict)
        or set(evidence_tools) != set(tool_map)
        or not all(_hex_sha(value) for value in evidence_tools.values())
        or not isinstance(evidence.get("published_archive_bytes"), int)
        or isinstance(evidence.get("published_archive_bytes"), bool)
        or not 0 < evidence["published_archive_bytes"] <= int(
            payload.get("max_download_bytes") or 8 * 1024**3
        )
    ):
        return "remote-evidence-mismatch"

    # The runtime archive hashes legitimately differ between Windows and
    # macOS. The checkpoint itself must have the same verified byte identity.
    if component == "transcription_engine" and target in {"windows-x86_64", "macos-aarch64"}:
        model = payload.get("model_identity")
        verified = evidence.get("published_model_identity")
        if (
            not isinstance(model, dict)
            or not isinstance(verified, dict)
            or model.get("model_key") != "mr_mt3"
            or model.get("checkpoint_path") != "checkpoints/mr_mt3/mt3.pth"
            or not _hex_sha(model.get("checkpoint_sha256"))
            or model.get("model_revision") != "sha256:" + model["checkpoint_sha256"]
            or model.get("runtime_revision") != payload.get("upstream_revision")
            or verified != {**model, "checkpoint_verified": True}
        ):
            return "model-evidence-mismatch"

    signoff = record.get("license_review")
    if not isinstance(signoff, dict):
        return "license-review-missing"
    if (
        signoff.get("decision") != "approved"
        or not _reviewed_text(signoff.get("reviewer"))
        or not _reviewed_text(signoff.get("reviewed_at_utc"))
        or not _https_reference(signoff.get("license_reference_url"))
        or not _https_reference(signoff.get("notice_url"))
        or not _hex_sha(signoff.get("notice_sha256"))
        or not _https_reference(signoff.get("source_offer_url"))
    ):
        return "license-review-incomplete"
    if not _VERSION.fullmatch(component) or not _VERSION.fullmatch(target):
        return "approval-record-invalid"
    return None

"""Verify *published HTTPS bytes* against a pending local managed artifact candidate.

This is a release-review command, NOT a redistribution approval or publisher.
No network requests happen without --fetch. It never edits the bundled catalog,
executes third-party tools, publishes archives, or reports clean-machine success.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from audio_score_tool.managed_components import (
    ComponentArtifact,
    ComponentIntegrityError,
    ComponentUnavailable,
    _download,
    _file_sha256,
    install_component_artifact,
)
from audio_score_tool.managed_publication_readiness import (
    _REQUIRED_TOOLS,
    CORE_COMPONENTS,
    OPTIONAL_COMPONENTS,
)

_ROOT = Path(__file__).resolve().parents[1]
_BUNDLED_CATALOG = _ROOT / "src/audio_score_tool/managed-component-catalog.json"
_ALLOWED_TARGET = re.compile(r"^(?:windows|macos|linux)-(?:x86_64|aarch64)$")
_UNREVIEWED = {"", "tbd", "unknown", "n/a", "runtime-specific", "..."}


def _reviewed(value: object, field: str) -> str:
    if not isinstance(value, str) or value.strip().lower() in _UNREVIEWED:
        raise ValueError(f"{field} must contain a reviewed value, not a placeholder")
    return value.strip()


def candidate_artifact(report: dict[str, Any]) -> tuple[ComponentArtifact, dict]:
    """Validate all pins before opening any network connection."""
    if not isinstance(report, dict) or report.get("schema_version") != "1":
        raise ValueError("Pending candidate must use schema_version '1'")
    component = _reviewed(report.get("component"), "component")
    target = _reviewed(report.get("target"), "target")
    if component not in CORE_COMPONENTS + OPTIONAL_COMPONENTS:
        raise ValueError("Unknown managed release component")
    if not _ALLOWED_TARGET.fullmatch(target):
        raise ValueError("Unsupported managed artifact target")
    payload = report.get("candidate")
    local = report.get("local_validation")
    if not isinstance(payload, dict) or not isinstance(local, dict):
        raise ValueError("Candidate must include local_validation and candidate objects")
    if report.get("approval_required") is not True:
        raise ValueError("Candidate must remain explicitly unapproved")
    if payload.get("redistribution_status") != "pending":
        raise ValueError("Only pending, unapproved candidates can be remotely verified")
    version = _reviewed(payload.get("version"), "version")
    license_name = _reviewed(payload.get("license"), "license")
    provenance = _reviewed(payload.get("provenance"), "provenance")
    revision = _reviewed(payload.get("upstream_revision"), "upstream_revision")
    if local.get("archive_checked_locally") is not True or local.get("integrity") != "verified":
        raise ValueError("Candidate requires successful local archive integrity validation")
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != {target}:
        raise ValueError("Pending candidate must pin exactly one requested target")
    settings = artifacts[target]
    if not isinstance(settings, dict):
        raise ValueError("Pinned managed artifact must be a JSON object")
    merged = dict(settings)
    merged.update({
        "component": component,
        "version": version,
        "license": license_name,
        "provenance": provenance,
    })
    artifact = ComponentArtifact.from_dict(merged)
    missing = sorted(_REQUIRED_TOOLS.get(component, frozenset()) - set(artifact.tools))
    if missing:
        raise ValueError("Required managed tools missing: " + ",".join(missing))
    if local.get("sha256") != artifact.sha256:
        raise ValueError("Local archive SHA-256 does not match candidate publication pin")
    tool_hashes = local.get("tool_sha256")
    if not isinstance(tool_hashes, dict) or set(tool_hashes) != set(artifact.tools):
        raise ValueError("Local tool hashes must match every published tool mapping")
    if any(
        not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{64}", value) is None
        for value in tool_hashes.values()
    ):
        raise ValueError("Local candidate contains invalid tool SHA-256")
    return artifact, {
        "target": target,
        "revision": revision,
        "tool_hashes": tool_hashes,
    }


def verify_published_candidate(
    report: dict[str, Any], *, local_archive: Path | None = None,
) -> dict[str, Any]:
    """Download one exact reviewed URL and test its bytes in an isolated install."""
    artifact, pins = candidate_artifact(report)
    if local_archive is not None:
        if local_archive.is_symlink() or not local_archive.is_file():
            raise ValueError("A regular local source archive is required")
        if local_archive.stat().st_size > artifact.max_download_bytes:
            raise ComponentIntegrityError("Local archive exceeds the declared download budget")
        if _file_sha256(local_archive) != artifact.sha256:
            raise ComponentIntegrityError("Local archive differs from pinned candidate bytes")

    with tempfile.TemporaryDirectory(prefix="ast-published-artifact-proof-") as temporary:
        isolated = Path(temporary)
        download = isolated / "published-artifact.bin"
        sha = _download(artifact, download)
        if sha != artifact.sha256 or _file_sha256(download) != artifact.sha256:
            raise ComponentIntegrityError("Published HTTPS artifact SHA-256 mismatch")
        downloaded_bytes = download.stat().st_size
        if downloaded_bytes <= 0 or downloaded_bytes > artifact.max_download_bytes:
            raise ComponentIntegrityError("Published HTTPS artifact size is invalid")
        status = install_component_artifact(
            artifact, root=isolated / "owned-component", local_archive=download,
        )
        if status.get("ready") is not True or status.get("integrity") != "verified":
            raise ComponentIntegrityError("Published managed artifact cannot be installed safely")
        actual_tools = {name: _file_sha256(Path(path)) for name, path in status["tools"].items()}
        if actual_tools != pins["tool_hashes"]:
            raise ComponentIntegrityError(
                "Published tool bytes differ from the locally verified candidate"
            )

    fingerprint = hashlib.sha256(
        json.dumps(report, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": "1",
        "component": artifact.component,
        "version": artifact.version,
        "target": pins["target"],
        "upstream_revision": pins["revision"],
        "candidate_sha256": fingerprint,
        # Do not leak URLs containing optional access parameters into public CI logs.
        "published_url_sha256": hashlib.sha256(artifact.url.encode()).hexdigest(),
        "published_archive_sha256": sha,
        "published_archive_bytes": downloaded_bytes,
        "published_tool_sha256": actual_tools,
        "remote_artifact_verified": True,
        "local_archive_rechecked": local_archive is not None,
        "archive_checked_and_installed_locally": True,
        "tools_executed": False,
        "clean_machine_verified": False,
        "license_independently_approved": False,
        "redistribution_status": "pending",
        "approval_required": True,
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def write_evidence(report: dict[str, Any], destination: Path) -> None:
    if destination.is_symlink() or destination.resolve() == _BUNDLED_CATALOG.resolve():
        raise ValueError("Publication evidence must not overwrite the managed catalog or symlink")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # No accidental replacement of existing independently reviewed evidence.
    with destination.open("x", encoding="utf-8") as output:
        json.dump(report, output, indent=2, sort_keys=True)
        output.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pending managed runtime remote SHA-256 verification (no approval)."
    )
    parser.add_argument("candidate", type=Path, help="Local pending candidate JSON report")
    parser.add_argument("--fetch", action="store_true", help="Explicitly download reviewed HTTPS asset")
    parser.add_argument("--local-archive", type=Path, help="Optional exact local archive recheck")
    parser.add_argument("--output", type=Path, help="New private pending evidence JSON")
    args = parser.parse_args()

    if args.output is not None and (
        args.output.is_symlink() or args.output.resolve() == _BUNDLED_CATALOG.resolve()
        or args.output.exists()
    ):
        parser.error("Evidence output must be a new non-symlink path outside the catalog")

    try:
        report = json.loads(args.candidate.read_text(encoding="utf-8"))
        artifact, pins = candidate_artifact(report)
        if not args.fetch:
            print(json.dumps({
                "component": artifact.component,
                "target": pins["target"],
                "ready_to_verify": True,
                "remote_artifact_verified": False,
                "redistribution_status": "pending",
            }))
            return 0
        if args.output is None:
            parser.error("--output is required when --fetch downloads real bytes")
        proof = verify_published_candidate(report, local_archive=args.local_archive)
        write_evidence(proof, args.output)
    except (OSError, ValueError, ComponentUnavailable, ComponentIntegrityError) as exc:
        parser.exit(2, f"Pending publication verification rejected: {exc}\n")
    print(json.dumps({
        "component": artifact.component, "target": pins["target"],
        "remote_artifact_verified": True, "approval_required": True,
        "evidence": str(args.output),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

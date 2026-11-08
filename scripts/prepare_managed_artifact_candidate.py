"""Prepare a *pending* managed runtime catalog candidate from a local archive.

This command never downloads from the network, executes binaries, edits the
bundled catalog or grants redistribution approval. It exercises the same
checksum, extraction, path and tool-integrity checks as the real installer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from pathlib import Path
from typing import Any

from audio_score_tool.managed_components import (
    ComponentArtifact,
    ComponentError,
    install_component_artifact,
)
from audio_score_tool.managed_publication_readiness import (
    _REQUIRED_TOOLS,
    CORE_COMPONENTS,
    OPTIONAL_COMPONENTS,
    STABLE_TARGETS,
)
from scripts.collect_mt3_frozen_inventory import _canonical_sha
from scripts.fetch_pinned_mrmt3_checkpoint import CHECKPOINT_SHA256

ROOT = Path(__file__).resolve().parents[1]
BUNDLED_CATALOG = ROOT / "src" / "audio_score_tool" / "managed-component-catalog.json"
_ALLOWED_TARGET = re.compile(r"^(?:windows|macos|linux)-(?:x86_64|aarch64)$")
_UNREVIEWED = {"", "unknown", "tbd", "n/a", "runtime-specific", "..."}
_MR_MT3_WEIGHT_SHA256 = CHECKPOINT_SHA256
_SHA = re.compile(r"[a-f0-9]{64}\Z")


def _required_label(value: str, name: str) -> str:
    stripped = value.strip()
    if stripped.lower() in _UNREVIEWED:
        raise ValueError(f"{name} requires an actual pinned value, not a placeholder.")
    return stripped


def parse_tools(values: list[str]) -> dict[str, str]:
    tools: dict[str, str] = {}
    for value in values:
        name, sep, relative = value.partition("=")
        name, relative = name.strip(), relative.strip()
        if not sep or not name or not relative or name in tools:
            raise ValueError("Use unique --tool NAME=relative/path entries.")
        tools[name] = relative
    if not tools:
        raise ValueError("At least one --tool mapping is required.")
    return tools


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()



def _bind_private_native_audit(
    archive_path: Path, *, component: str, target: str,
    archive_sha256: str, audit: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Require exact local MR-MT3 native inference evidence for core platforms.

    A receipt is not an independent signed attestation and cannot authorize
    redistribution. All bytes are still installed/hashed by the product below.
    Other provider/model releases need their own audited evidence contract.
    """
    required = component == "transcription_engine" and target in STABLE_TARGETS
    if not required:
        if audit is not None:
            raise ValueError("Native inference audit is only valid for stable MT3 runtime candidates")
        return None
    if not isinstance(audit, dict):
        raise ValueError("Stable transcription_engine requires a private native inference audit")
    executable = f"bin/mt3-infer{'.exe' if target.startswith('windows') else ''}"
    expected_names = {
        executable, "checkpoints/mr_mt3/mt3.pth",
        "provenance/frozen-native-qa.pending.json",
    }
    member_hashes = audit.get("member_sha256")
    tool_hashes = audit.get("tool_sha256")
    if (
        audit.get("schema_version") != "1"
        or not isinstance(audit.get("audit_integrity_sha256"), str)
        or not _SHA.fullmatch(audit["audit_integrity_sha256"])
        or audit["audit_integrity_sha256"] != _canonical_sha({
            name: value for name, value in audit.items()
            if name != "audit_integrity_sha256"
        })
        or audit.get("purpose") != "private-native-mr-mt3-release-review"
        or audit.get("component") != component
        or audit.get("model") != "mr_mt3"
        or audit.get("target") != target
        or audit.get("private_candidate_filename") != archive_path.name
        or audit.get("archive_sha256") != archive_sha256
        or type(audit.get("archive_bytes")) is not int
        or audit["archive_bytes"] != archive_path.stat().st_size
        or audit.get("model_checkpoint_sha256") != _MR_MT3_WEIGHT_SHA256
        or not isinstance(member_hashes, dict)
        or set(member_hashes) != expected_names
        or not all(isinstance(h, str) and _SHA.fullmatch(h) for h in member_hashes.values())
        or member_hashes["checkpoints/mr_mt3/mt3.pth"] != _MR_MT3_WEIGHT_SHA256
        or not isinstance(tool_hashes, dict)
        or set(tool_hashes) != {"mt3-infer"}
        or tool_hashes["mt3-infer"] != member_hashes[executable]
        or not isinstance(audit.get("frozen_inventory_sha256"), str)
        or not _SHA.fullmatch(audit["frozen_inventory_sha256"])
        or type(audit.get("embedded_frozen_archive_entries")) is not int
        or audit["embedded_frozen_archive_entries"] <= 0
        or type(audit.get("embedded_native_binary_entries")) is not int
        or audit["embedded_native_binary_entries"] <= 0
        or type(audit.get("embedded_pyz_modules")) is not int
        or audit["embedded_pyz_modules"] <= 0
        or type(audit.get("builder_distribution_inventory_count")) is not int
        or audit["builder_distribution_inventory_count"] <= 0
        or not isinstance(audit.get("native_qa_receipt_canonical_sha256"), str)
        or not _SHA.fullmatch(audit["native_qa_receipt_canonical_sha256"])
        or audit.get("local_bytes_match_native_qa") is not True
        or audit.get("checkpoint_not_deserialized_by_audit") is not True
        or audit.get("builder_packages_are_complete_frozen_sbom") is not False
        or audit.get("remote_artifact_verified") is not False
        or audit.get("license_independently_approved") is not False
        or audit.get("clean_machine_verified") is not False
        or audit.get("approval_required") is not True
        or audit.get("publication_ready") is not False
        or audit.get("redistribution_status") != "pending"
        or not isinstance(audit.get("release_blockers"), list)
        or len(audit["release_blockers"]) == 0
    ):
        raise ValueError("Private native inference audit is missing, inconsistent or approved improperly")
    return {
        "audit_sha256": hashlib.sha256(
            json.dumps(audit, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "archive_sha256": archive_sha256,
        "model": "mr_mt3",
        "model_checkpoint_sha256": _MR_MT3_WEIGHT_SHA256,
        "tool_sha256": {"mt3-infer": tool_hashes["mt3-infer"]},
        "native_qa_receipt_canonical_sha256": audit["native_qa_receipt_canonical_sha256"],
        "frozen_inventory_sha256": audit["frozen_inventory_sha256"],
        "inventory_is_complete_distributable_sbom": False,
        "third_party_license_approval": False,
        "native_inference_verified_by_local_receipt": True,
        "license_independently_approved": False,
        "clean_machine_verified": False,
        "redistribution_status": "pending",
    }


def draft_candidate(
    *,
    archive_path: Path,
    component: str,
    version: str,
    target: str,
    url: str,
    archive_format: str,
    tools: dict[str, str],
    license_name: str,
    provenance: str,
    upstream_revision: str,
    max_download_bytes: int = 8 * 1024**3,
    max_uncompressed_bytes: int = 4 * 1024**3,
    native_audit: dict[str, Any] | None = None,
) -> dict:
    if component not in set(CORE_COMPONENTS + OPTIONAL_COMPONENTS):
        raise ValueError("Unknown managed product component.")
    if not _ALLOWED_TARGET.fullmatch(target):
        raise ValueError("Target must be a supported OS/architecture pair.")
    if not archive_path.is_file() or archive_path.is_symlink():
        raise ValueError("A regular local artifact archive is required.")
    license_name = _required_label(license_name, "license")
    provenance = _required_label(provenance, "provenance")
    upstream_revision = _required_label(upstream_revision, "upstream_revision")

    missing = sorted(_REQUIRED_TOOLS.get(component, frozenset()) - set(tools))
    if missing:
        raise ValueError("Missing required managed tools: " + ",".join(missing))

    digest = sha256_file(archive_path)
    # On stable Windows/macOS, a launcher with a plausible filename and a
    # valid ZIP is not enough to establish functional model delivery.
    # Require the separate offline frozen+real-checkpoint audit receipt first.
    native_audit_binding = _bind_private_native_audit(
        archive_path, component=component, target=target,
        archive_sha256=digest, audit=native_audit,
    )
    artifact = ComponentArtifact(
        component=component,
        version=version,
        url=url,
        sha256=digest,
        archive=archive_format,
        tools=tools,
        max_download_bytes=max_download_bytes,
        max_uncompressed_bytes=max_uncompressed_bytes,
        license=license_name,
        provenance=provenance,
    )

    # Isolated local rehearsal; never touch the app's actual managed state.
    model_identity = None
    with tempfile.TemporaryDirectory(prefix="ast-candidate-verify-") as directory:
        status = install_component_artifact(
            artifact,
            root=Path(directory),
            local_archive=archive_path,
        )
        if status.get("ready") is not True or status.get("integrity") != "verified":
            raise ComponentError("Local artifact installation could not be verified.")
        tool_digests = {
            name: sha256_file(Path(path))
            for name, path in sorted(status["tools"].items())
        }
        if native_audit_binding is not None:
            # The native audit binds the exact ZIP, but the publication contract
            # also needs a reusable OS-independent *checkpoint* identity.
            # Check installed bytes, not a claimed filename or manifest string.
            checkpoint_path = "checkpoints/mr_mt3/mt3.pth"
            checkpoint = Path(directory) / "installed" / component / version / checkpoint_path
            if checkpoint.is_symlink() or not checkpoint.is_file():
                raise ValueError("Audited model checkpoint is absent from installed candidate")
            checkpoint_sha = sha256_file(checkpoint)
            if checkpoint_sha != native_audit_binding["model_checkpoint_sha256"]:
                raise ValueError("Installed model checkpoint SHA differs from native audit")
            model_identity = {
                "model_key": native_audit_binding["model"],
                # A content digest is immutable even when upstream uses a mutable main ref.
                "model_revision": "sha256:" + checkpoint_sha,
                "runtime_revision": upstream_revision,
                "checkpoint_path": checkpoint_path,
                "checkpoint_sha256": checkpoint_sha,
            }

    if native_audit_binding is not None and tool_digests != native_audit_binding["tool_sha256"]:
        raise ValueError("Installed tool hashes differ from the native inference audit")

    return {
        "schema_version": "1",
        "component": component,
        "target": target,
        "candidate": {
            "version": version,
            "license": license_name,
            "provenance": provenance,
            "upstream_revision": upstream_revision,
            # This tool cannot approve legal redistribution. Keep it fail-closed.
            "redistribution_status": "pending",
            "artifacts": {
                target: {
                    "url": artifact.url,
                    "sha256": artifact.sha256,
                    "archive": artifact.archive,
                    "tools": artifact.tools,
                    "max_download_bytes": artifact.max_download_bytes,
                    "max_uncompressed_bytes": artifact.max_uncompressed_bytes,
                    **({"model_identity": model_identity} if model_identity is not None else {}),
                }
            },
        },
        "local_validation": {
            "sha256": digest,
            "integrity": "verified",
            "tool_sha256": tool_digests,
            "archive_checked_locally": True,
            "remote_artifact_verified": False,
            "tools_executed": False,
            "clean_machine_verified": False,
            **({"model_identity_verified": True} if model_identity is not None else {}),
            **(
                {"native_inference_audit": native_audit_binding}
                if native_audit_binding is not None else {}
            ),
        },
        "approval_required": True,
    }


def write_report(report: dict, output: Path) -> None:
    if output.resolve() == BUNDLED_CATALOG.resolve():
        raise ValueError("Cannot overwrite the bundled managed-component-catalog.json.")
    output.parent.mkdir(parents=True, exist_ok=True)
    # Refuse overwriting another candidate's evidence accidentally.
    with output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a pending, locally verified managed component release candidate."
    )
    parser.add_argument("--component", required=True, choices=CORE_COMPONENTS + OPTIONAL_COMPONENTS)
    parser.add_argument("--target", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--archive-format", required=True, choices=("zip", "tar", "raw"))
    parser.add_argument("--url", required=True, help="Future reviewed HTTPS publication URL; not fetched.")
    parser.add_argument("--tool", action="append", required=True, help="NAME=relative/path")
    parser.add_argument("--license", required=True)
    parser.add_argument("--provenance", required=True)
    parser.add_argument("--upstream-revision", required=True)
    parser.add_argument(
        "--native-audit", type=Path,
        help="Required for stable Windows/macOS transcription_engine candidates: private audit pending JSON",
    )
    parser.add_argument("--max-download-bytes", type=int, default=8 * 1024**3)
    parser.add_argument("--max-uncompressed-bytes", type=int, default=4 * 1024**3)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    try:
        report = draft_candidate(
            archive_path=args.archive,
            component=args.component,
            version=args.version,
            target=args.target,
            url=args.url,
            archive_format=args.archive_format,
            tools=parse_tools(args.tool),
            license_name=args.license,
            provenance=args.provenance,
            upstream_revision=args.upstream_revision,
            max_download_bytes=args.max_download_bytes,
            max_uncompressed_bytes=args.max_uncompressed_bytes,
            native_audit=(
                json.loads(args.native_audit.read_text(encoding="utf-8"))
                if args.native_audit is not None else None
            ),
        )
        write_report(report, args.output)
    except (OSError, ValueError, ComponentError) as exc:
        parser.exit(2, f"Managed runtime candidate rejected: {exc}\n")

    print(f"Local archive verified; pending redistribution approval: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

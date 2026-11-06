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

from audio_score_tool.managed_components import (
    ComponentArtifact,
    ComponentError,
    install_component_artifact,
)
from audio_score_tool.managed_publication_readiness import (
    _REQUIRED_TOOLS,
    CORE_COMPONENTS,
    OPTIONAL_COMPONENTS,
)

ROOT = Path(__file__).resolve().parents[1]
BUNDLED_CATALOG = ROOT / "src" / "audio_score_tool" / "managed-component-catalog.json"
_ALLOWED_TARGET = re.compile(r"^(?:windows|macos|linux)-(?:x86_64|aarch64)$")
_UNREVIEWED = {"", "unknown", "tbd", "n/a", "runtime-specific", "..."}


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
        )
        write_report(report, args.output)
    except (OSError, ValueError, ComponentError) as exc:
        parser.exit(2, f"Managed runtime candidate rejected: {exc}\n")

    print(f"Local archive verified; pending redistribution approval: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

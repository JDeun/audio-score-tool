"""Combine two real, unapproved native MT3 QA receipts into a release review queue.

Only JSON proof files from the same trusted GitHub Actions run are consumed.
The report checks pinned source metadata, independently SHA-bound frozen
inventory and actual native byte/RECORD comparisons. It never downloads,
publishes, signs, or approves models/executables.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.collect_mt3_frozen_inventory import _canonical_sha
from scripts.fetch_pinned_mrmt3_checkpoint import (
    CHECKPOINT_SHA256,
    MODEL_REPO,
    MODEL_REVISION,
    SOURCE_URL,
)
from scripts.triage_mt3_frozen_dependencies import (
    MT3LicenseTriageError,
    triage_platforms,
)

_TARGETS = ("windows-x86_64", "macos-aarch64")
_MAX_RECEIPT_BYTES = 12 * 1024 * 1024
_PRIORITY = {
    "wheel_record_sha256_mismatch": 0,
    "size_limit_not_hashed": 1,
    "ambiguous": 2,
    "unmatched": 3,
    "wheel_record_sha256_missing": 4,
}


class NativeReleaseReviewError(ValueError):
    """A native QA receipt, its pinned source, or the review queue is invalid."""


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise NativeReleaseReviewError(message)


def _source_receipt(source: dict[str, Any]) -> None:
    _expect(
        isinstance(source, dict)
        and source.get("schema_version") == "1"
        and source.get("model") == "mr_mt3"
        and source.get("upstream_repository") == MODEL_REPO
        and source.get("upstream_revision") == MODEL_REVISION
        and source.get("upstream_source_url") == SOURCE_URL
        and source.get("checkpoint_sha256") == CHECKPOINT_SHA256
        and type(source.get("checkpoint_bytes")) is int
        and 1024 * 1024 <= source["checkpoint_bytes"] <= 1024**3
        and source.get("immutable_revision_requested") is True
        and source.get("checkpoint_sha256_verified") is True
        and source.get("model_checkpoint_deserialized") is False
        and source.get("model_redistribution_approved") is False
        and source.get("release_catalog_modified") is False
        and source.get("redistribution_status") == "pending",
        "Source receipt does not prove the exact pinned, still-unapproved checkpoint",
    )


def _native_receipt(native: dict[str, Any], target: str) -> None:
    real = native.get("real_native_inference") if isinstance(native, dict) else None
    _expect(
        isinstance(real, dict)
        and native.get("target") == target
        and native.get("model_adapter") == "mr_mt3"
        and native.get("actual_model_inference_verified") is True
        and native.get("private_candidate_staged_locally") is False
        and native.get("binaries_uploaded") is False
        and native.get("runtime_redistribution_approved") is False
        and native.get("model_license_approved") is False
        and real.get("model") == "mr_mt3"
        and real.get("checkpoint_sha256") == CHECKPOINT_SHA256
        and real.get("checkpoint_source") == SOURCE_URL
        and real.get("checkpoint_source_revision") == MODEL_REVISION
        and real.get("model_redistribution_approved") is False
        and real.get("model_weights_published") is False
        and real.get("redistribution_status") == "pending",
        "Native QA receipt does not bind the exact pinned MR-MT3 source",
    )


def aggregate_native_review(
    windows_native: dict[str, Any], macos_native: dict[str, Any],
    windows_source: dict[str, Any], macos_source: dict[str, Any],
) -> dict[str, Any]:
    """Recompute cross-platform triage and prioritize unresolved byte identities."""
    sources = {"windows-x86_64": windows_source, "macos-aarch64": macos_source}
    proofs = {"windows-x86_64": windows_native, "macos-aarch64": macos_native}
    for target in _TARGETS:
        _source_receipt(sources[target])
        _native_receipt(proofs[target], target)
    _expect(
        windows_source["checkpoint_bytes"] == macos_source["checkpoint_bytes"],
        "Windows/macOS pinned checkpoint byte lengths differ",
    )

    try:
        reviewed = triage_platforms(windows_native, macos_native)
    except (MT3LicenseTriageError, KeyError, TypeError, ValueError) as exc:
        raise NativeReleaseReviewError("Cross-platform MT3 frozen QA triage failed") from exc

    queue: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    origin = {}
    for target in _TARGETS:
        platform = reviewed["platforms"][target]
        _expect(platform["native_byte_evidence_available"] is True,
                f"Actual native byte evidence is missing for {target}")
        comparison = platform["native_byte_comparison_counts"]
        rows = platform["native_byte_review_queue"]
        _expect(isinstance(comparison, dict) and isinstance(rows, list),
                "Native byte verification queue is incomplete")
        _expect(
            sum(comparison.values()) == len(rows)
            and len(rows) == platform["recognizable_native_library_filename_count"],
            "Native byte review queue does not cover all candidates",
        )
        for row in rows:
            status = row["comparison"]
            counts[status] += 1
            if status == "exact_record_sha256_match":
                continue
            _expect(status in _PRIORITY, "Unknown native byte review status")
            queue.append({
                "target": target,
                "priority": _PRIORITY[status],
                "reason": status,
                "archive_path": row["archive_path"],
                "uncompressed_bytes": row["uncompressed_bytes"],
                "embedded_sha256": row["embedded_sha256"],
                "record_sha256": row["record_sha256"],
                "record_distribution_hint": row["record_distribution_hint"],
                "action": (
                    "Find an independently reviewed wheel and reconcile the changed bytes"
                    if status == "wheel_record_sha256_mismatch" else
                    "Identify the exact bundled native file, upstream source and license/notice obligations"
                ),
            })
        proof = proofs[target]
        origin[target] = {
            "native_receipt_sha256": _canonical_sha(proof),
            "source_receipt_sha256": _canonical_sha(sources[target]),
            "native_executable_sha256": proof["native_executable_sha256"],
            "frozen_inventory_sha256": proof["frozen_dependency_inventory"]["inventory_sha256"],
            "missing_builder_notice_metadata": platform[
                "builder_distribution_missing_notice_file_digests"
            ],
        }
    queue.sort(key=lambda row: (row["priority"], row["target"], row["archive_path"]))
    _expect(
        counts["exact_record_sha256_match"] + len(queue)
        == sum(reviewed["platforms"][target]["recognizable_native_library_filename_count"]
               for target in _TARGETS),
        "Unresolved file review queue does not cover both platforms",
    )
    return {
        "schema_version": "1",
        "purpose": "mt3-native-cross-platform-release-review",
        "targets": list(_TARGETS),
        "model": "mr_mt3",
        "model_repository": MODEL_REPO,
        "model_source_revision": MODEL_REVISION,
        "model_checkpoint_sha256": CHECKPOINT_SHA256,
        "verified_source_receipts": origin,
        "source_receipts_bound_to_native_qa": True,
        "native_file_comparison_counts": dict(sorted(counts.items())),
        "native_unresolved_file_count": len(queue),
        "native_file_priority_review_queue": queue,
        "third_party_review": reviewed,
        "independent_binary_attestation_verified": False,
        "complete_sbom_verified": False,
        "license_independently_approved": False,
        "model_redistribution_approved": False,
        "clean_machine_verified": False,
        "production_catalog_published": False,
        "publication_ready": False,
        "redistribution_status": "pending",
    }


def _read_json(path: Path) -> dict[str, Any]:
    if (
        path.is_symlink() or not path.is_file()
        or not 0 < path.stat().st_size <= _MAX_RECEIPT_BYTES
    ):
        raise NativeReleaseReviewError("A regular, bounded pending JSON receipt is required")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NativeReleaseReviewError("Native review receipt is not valid JSON") from exc
    if not isinstance(document, dict):
        raise NativeReleaseReviewError("Native review receipt must be a JSON object")
    return document


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate pending native MT3 QA receipts")
    parser.add_argument("--windows-native", required=True, type=Path)
    parser.add_argument("--macos-native", required=True, type=Path)
    parser.add_argument("--windows-source", required=True, type=Path)
    parser.add_argument("--macos-source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error("Output must be a new file; existing evidence cannot be overwritten")
    try:
        report = aggregate_native_review(
            _read_json(args.windows_native), _read_json(args.macos_native),
            _read_json(args.windows_source), _read_json(args.macos_source),
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Pending native MT3 review rejected: {exc}\n")
    print(json.dumps({
        "targets": report["targets"],
        "unresolved_native_files": report["native_unresolved_file_count"],
        "publication_ready": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

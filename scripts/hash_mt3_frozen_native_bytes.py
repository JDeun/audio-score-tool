"""Hash actual private PyInstaller CArchive native entries against wheel RECORD.

Only selected library *contents* are read in memory; this does not write
extracted binaries or upload code. Exact SHA equality identifies identical
bytes to a builder's wheel RECORD, not the legal owner, a signed upstream wheel,
transitive dependency closure, redistribution permission, or a complete SBOM.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Callable

from scripts.map_mt3_frozen_file_owners import native_filename_candidate

_SHA = re.compile(r"[a-f0-9]{64}\Z")
_MAX_MEMBER_BYTES = 512 * 1024 * 1024
_MAX_TOTAL_BYTES = 4 * 1024 * 1024 * 1024


class NativeByteAuditError(ValueError):
    """The final frozen binary or the claimed path/byte evidence is inconsistent."""


def _normalized(name: str) -> str:
    if not isinstance(name, str) or not name or len(name) > 1024:
        raise NativeByteAuditError("Frozen member name is invalid")
    result = name.replace("\\", "/")
    if (
        result.startswith("/") or ":" in result
        or any(x in {"", ".", ".."} for x in result.split("/"))
        or any(ord(c) < 32 or ord(c) == 127 for c in result)
    ):
        raise NativeByteAuditError("Frozen member path is unsafe")
    return result


def hash_frozen_native_records(
    executable: Path,
    archive_entries: list[dict[str, Any]],
    hints: dict[str, Any],
    *,
    target: str,
    reader_factory: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Read actual native members by raw TOC name and compare exact record hashes.

    The CArchive reader's extract() yields uncompressed member bytes. Members
    exceeding fixed memory and total-read caps are *unverified*, never matched.
    Only one RECORD path+SHA, not multiple owner hints, can be called a match.
    """
    if target not in {"windows-x86_64", "macos-aarch64"}:
        raise NativeByteAuditError("Unsupported native target")
    if executable.is_symlink() or not executable.is_file():
        raise NativeByteAuditError("Native executable must be a regular file")
    if reader_factory is None:
        from PyInstaller.archive.readers import CArchiveReader

        reader_factory = CArchiveReader
    try:
        reader = reader_factory(str(executable))
    except (OSError, ValueError, TypeError, RuntimeError) as exc:
        raise NativeByteAuditError("Cannot inspect actual frozen native archive") from exc
    toc = getattr(reader, "toc", None)
    if not isinstance(toc, dict):
        raise NativeByteAuditError("Frozen native archive lacks a TOC")

    raw_names: dict[str, str] = {}
    for raw, record in toc.items():
        if not isinstance(record, (tuple, list)) or len(record) != 5:
            raise NativeByteAuditError("Invalid frozen TOC entry")
        normalized = _normalized(raw)
        if record[4] != "b" or not native_filename_candidate(normalized):
            continue
        key = normalized.casefold() if target.startswith("windows") else normalized
        if key in raw_names:
            raise NativeByteAuditError("Duplicate native names in frozen archive")
        raw_names[key] = raw

    if not isinstance(archive_entries, list) or not isinstance(hints, dict):
        raise NativeByteAuditError("Frozen member inventory or wheel path hints missing")
    rows = hints.get("native_file_review_queue")
    if (
        not isinstance(rows, list)
        or hints.get("target") != target
        or len(rows) != len(raw_names)
    ):
        raise NativeByteAuditError("Wheel RECORD hints do not cover actual native entries")
    expected_sizes: dict[str, int] = {}
    for entry in archive_entries:
        if not isinstance(entry, dict) or entry.get("typecode") != "b":
            continue
        name = _normalized(entry.get("name"))
        if not native_filename_candidate(name):
            continue
        expected_sizes[name] = entry.get("uncompressed_bytes")

    counts = {
        "exact_record_sha256_match": 0,
        "wheel_record_sha256_mismatch": 0,
        "wheel_record_sha256_missing": 0,
        "ambiguous": 0,
        "unmatched": 0,
        "size_limit_not_hashed": 0,
    }
    records = []
    total = 0
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise NativeByteAuditError("Malformed wheel RECORD review row")
        path = _normalized(row.get("archive_path"))
        key = path.casefold() if target.startswith("windows") else path
        if key not in raw_names or key in seen or path not in expected_sizes:
            raise NativeByteAuditError("Frozen file/RECORD path mismatch")
        seen.add(key)
        size = expected_sizes[path]
        if type(size) is not int or size < 0:
            raise NativeByteAuditError("Frozen member has invalid uncompressed size")
        matches = row.get("wheel_record_matches")
        if not isinstance(matches, list):
            raise NativeByteAuditError("Malformed wheel RECORD source matches")
        digest = None
        distribution = None
        if len(matches) == 1:
            if row.get("match_status") != "single_record_path_match":
                raise NativeByteAuditError("Wheel RECORD match status changed")
            match = matches[0]
            if not isinstance(match, dict):
                raise NativeByteAuditError("Invalid wheel RECORD record")
            digest = match.get("wheel_record_sha256")
            if digest is not None and (not isinstance(digest, str) or not _SHA.fullmatch(digest)):
                raise NativeByteAuditError("Invalid wheel RECORD SHA")
            distribution = match.get("distribution")
            if not isinstance(distribution, str) or not distribution:
                raise NativeByteAuditError("Invalid distribution identifier")
        elif (len(matches) == 0 and row.get("match_status") != "unmatched") or (
            len(matches) > 1 and row.get("match_status") != "ambiguous"
        ):
            raise NativeByteAuditError("Ambiguous/unmatched wheel RECORD status changed")

        actual = None
        if size > _MAX_MEMBER_BYTES or total + size > _MAX_TOTAL_BYTES:
            comparison = "size_limit_not_hashed"
        else:
            try:
                payload = reader.extract(raw_names[key])
            except (OSError, ValueError, TypeError, RuntimeError, KeyError) as exc:
                raise NativeByteAuditError("Cannot read actual native CArchive member") from exc
            if not isinstance(payload, bytes) or len(payload) != size:
                raise NativeByteAuditError("Frozen native member byte size mismatch")
            total += len(payload)
            actual = hashlib.sha256(payload).hexdigest()
            del payload
            comparison = (
                "unmatched" if not matches else
                "ambiguous" if len(matches) > 1 else
                "wheel_record_sha256_missing" if digest is None else
                "exact_record_sha256_match" if actual == digest else
                "wheel_record_sha256_mismatch"
            )
        counts[comparison] += 1
        records.append({
            "archive_path": path,
            "uncompressed_bytes": size,
            "embedded_sha256": actual,
            "record_sha256": digest,
            "record_distribution_hint": distribution,
            "comparison": comparison,
        })
    if seen != set(raw_names):
        raise NativeByteAuditError("Some frozen native members were not audited")
    return {
        "schema_version": "1",
        "basis": "actual-PyInstaller-CArchive-member-sha256-vs-builder-wheel-RECORD",
        "target": target,
        "native_filename_candidate_count": len(records),
        "uncompressed_bytes_read": total,
        "counts": counts,
        "entries": sorted(records, key=lambda r: r["archive_path"]),
        "all_native_library_bytes_hashed": counts["size_limit_not_hashed"] == 0,
        "source_owner_independently_verified": False,
        "native_loader_dependency_closure_verified": False,
        "complete_sbom_verified": False,
        "license_independently_approved": False,
        "redistribution_status": "pending",
    }

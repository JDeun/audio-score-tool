"""Map frozen native filename candidates to wheel RECORD path candidates.

Exact normalized relative paths are a useful *review hint* for determining
which Python distribution might have supplied a file. They are not verified
binary byte identity, upstream source provenance, legal ownership, a license
grant, or a complete dynamic-library dependency graph. No code is executed,
no binary is extracted, no internet access, and no secrets/host paths are
included in the output.
"""
from __future__ import annotations

import base64
import re
from pathlib import PurePosixPath
from typing import Any, Iterable

_NATIVE_FILE = re.compile(
    r"(?:\.dll|\.pyd|\.dylib|\.exe|\.bundle|\.so(?:\.\d+)*)\Z",
    re.IGNORECASE,
)
_MAX_FILE_RECORDS = 200_000
_MAX_CANDIDATES = 100_000


class FileOwnerMappingError(ValueError):
    """Malformed frozen native file inventory or wheel RECORD metadata."""


def native_filename_candidate(name: str) -> bool:
    """Filename-only candidate; PE/Mach-O/ELF bytes remain uninspected."""
    return bool(
        _NATIVE_FILE.search(name)
        or ".framework/" in name.lower()
        or name.lower().endswith(".framework")
    )


def _normal_path(raw: object, *, wheel_record: bool = False) -> str | None:
    if not isinstance(raw, str) or not raw or len(raw) > 1024:
        if wheel_record:
            return None
        raise FileOwnerMappingError("Native archive file has invalid path metadata")
    path = raw.replace("\\", "/")
    if (
        path.startswith("/")
        or ":" in path
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in path)
        or any(part in {"", ".", ".."} for part in path.split("/"))
        or PurePosixPath(path).as_posix() != path
    ):
        if wheel_record:
            # Wheels can legitimately RECORD data/scripts outside site-packages.
            # Such files cannot exactly match frozen internal paths.
            return None
        raise FileOwnerMappingError("Native archive file contains unsafe relative path")
    return path


def _wheel_record_sha256(record: Any) -> str | None:
    file_hash = getattr(record, "hash", None)
    if file_hash is None or getattr(file_hash, "mode", None) != "sha256":
        return None
    value = getattr(file_hash, "value", None)
    if not isinstance(value, str) or len(value) > 128:
        raise FileOwnerMappingError("Wheel RECORD SHA-256 is malformed")
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, base64.binascii.Error) as exc:
        raise FileOwnerMappingError("Wheel RECORD SHA-256 cannot be decoded") from exc
    if len(decoded) != 32:
        raise FileOwnerMappingError("Wheel RECORD SHA-256 has invalid length")
    return decoded.hex()


def _distribution_identifiers(distribution: Any) -> tuple[str, str]:
    metadata = distribution.metadata
    name = str(metadata.get("Name", "")).strip()
    version = str(metadata.get("Version", "")).strip()
    if not name or not version or len(name) > 200 or len(version) > 100:
        raise FileOwnerMappingError("Builder distribution has invalid name/version")
    return name, version


def map_native_file_records(
    archive_entries: list[dict[str, Any]],
    distributions: Iterable[Any],
    *,
    target: str,
) -> dict[str, Any]:
    """Find exact relative-path matches between final CArchive and wheel RECORD.

    For Windows, comparisons are case-insensitive but canonical paths are
    retained. Duplicate/colliding RECORD paths from different packages stay
    *ambiguous* rather than assigning a speculative single owner.
    """
    if target not in {"windows-x86_64", "macos-aarch64"}:
        raise FileOwnerMappingError("Native file owner mapping supports only stable targets")
    if not isinstance(archive_entries, list) or len(archive_entries) > _MAX_CANDIDATES:
        raise FileOwnerMappingError("Frozen native archive inventory is invalid")

    candidates: dict[str, str] = {}
    for entry in archive_entries:
        if not isinstance(entry, dict):
            raise FileOwnerMappingError("Frozen archive entry metadata is invalid")
        if entry.get("typecode") != "b":
            continue
        path = _normal_path(entry.get("name"))
        if not native_filename_candidate(path):
            continue
        key = path.casefold() if target.startswith("windows") else path
        if key in candidates:
            raise FileOwnerMappingError("Colliding native archive paths cannot be attributed")
        candidates[key] = path

    owners: dict[str, list[dict[str, Any]]] = {name: [] for name in candidates}
    record_names: set[str] = set()
    unsafe_records = 0
    for distribution in distributions:
        name, version = _distribution_identifiers(distribution)
        dist_key = re.sub(r"[-_.]+", "-", name).lower()
        if dist_key in record_names:
            raise FileOwnerMappingError("Duplicate builder distributions cannot be attributed")
        record_names.add(dist_key)
        seen: set[str] = set()
        files = getattr(distribution, "files", None)
        for index, record in enumerate(files or ()):
            if index >= _MAX_FILE_RECORDS:
                raise FileOwnerMappingError("Wheel RECORD exceeds safe file count")
            normalized = _normal_path(str(record), wheel_record=True)
            if normalized is None:
                unsafe_records += 1
                continue
            key = normalized.casefold() if target.startswith("windows") else normalized
            if key not in owners:
                continue
            if key in seen:
                raise FileOwnerMappingError("Duplicate wheel RECORD path is ambiguous")
            seen.add(key)
            recorded_size = getattr(record, "size", None)
            if recorded_size is not None and (
                type(recorded_size) is not int or recorded_size < 0
            ):
                raise FileOwnerMappingError("Wheel RECORD file length is invalid")
            owners[key].append({
                "distribution": name,
                "version": version,
                "record_relative_path": normalized,
                "wheel_record_sha256": _wheel_record_sha256(record),
                "wheel_record_bytes": recorded_size,
                "record_sha256_matches_embedded_payload": False,
                "binary_source_independently_verified": False,
                "license_independently_approved": False,
            })

    mapped: list[dict[str, Any]] = []
    stats = {"single_record_path_match": 0, "unmatched": 0, "ambiguous": 0}
    for key, archive_path in sorted(candidates.items(), key=lambda x: x[1]):
        matches = sorted(owners[key], key=lambda x: x["distribution"].lower())
        status = (
            "unmatched" if not matches else
            "single_record_path_match" if len(matches) == 1 else "ambiguous"
        )
        stats[status] += 1
        mapped.append({
            "archive_path": archive_path,
            "match_status": status,
            "wheel_record_matches": matches,
        })
    return {
        "schema_version": "1",
        "mapping_basis": "wheel-RECORD-exact-relative-path-only",
        "target": target,
        "native_filename_candidate_count": len(candidates),
        "matched_candidate_count": stats["single_record_path_match"],
        "ambiguous_candidate_count": stats["ambiguous"],
        "unmatched_candidate_count": stats["unmatched"],
        "ignored_nonrelative_wheel_record_paths": unsafe_records,
        "native_file_review_queue": mapped,
        "binary_payload_equals_record_hash_verified": False,
        "dynamic_library_dependency_closure_verified": False,
        "source_owner_independently_verified": False,
        "license_independently_approved": False,
        "redistribution_status": "pending",
    }

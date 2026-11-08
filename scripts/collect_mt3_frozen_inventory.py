"""Inspect one private PyInstaller MT3 executable and its build environment.

Only metadata (names, sizes, Python distributions, license-file digests) leaves
the build runner. This is a *review inventory*, not a complete SBOM, a package
license verdict, a redistribution license, or clean-machine acceptance.

The frozen CArchive/PYZ inventories are obtained from the final executable,
rather than conflating builder-installed Python dependencies with shipped bytes.
No third-party code, model weight or library file is extracted or uploaded.
"""
from __future__ import annotations

import hashlib
import json
import re
from importlib.metadata import distributions as installed_distributions
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable

_MAX_ENTRIES = 100_000
_MAX_DISTRIBUTIONS = 3_000
_MAX_LICENSE_FILES = 16
_MAX_LICENSE_BYTES = 4 * 1024 * 1024
_SAFE_MODULE = re.compile(r"^[A-Za-z0-9_.-]{1,350}$")
_ALLOWED_TYPES = frozenset("abdlnmMsxzZ")  # includes PKG and embedded SYMLINK entries
_SHA = re.compile(r"^[a-f0-9]{64}$")


class FrozenInventoryError(ValueError):
    """An embedded dependency entry or builder license record is unreliable."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_sha(value: dict[str, Any]) -> str:
    return _hash_bytes(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )


def _safe_archive_name(name: object) -> str:
    if not isinstance(name, str) or not name or len(name) > 1024:
        raise FrozenInventoryError("Frozen archive has an invalid entry name")
    # PyInstaller's native Windows TOC uses backslashes inside *relative*
    # archive paths. Normalize these for evidence, while retaining the raw TOC
    # key for reader.open_embedded_archive(). Never accept drive/UNC paths.
    normalized = name.replace("\\", "/")
    if (
        normalized.startswith("/")
        or ":" in normalized
        or any(ord(char) < 32 or ord(char) == 127 for char in normalized)
        or any(part in {"", ".", ".."} for part in normalized.split("/"))
    ):
        raise FrozenInventoryError("Frozen archive entry may escape its internal namespace")
    path = PurePosixPath(normalized)
    if path.is_absolute() or path.as_posix() != normalized:
        raise FrozenInventoryError("Frozen archive entry has an unsafe path")
    return normalized


def inspect_frozen_archive(
    executable: Path, *,
    reader_factory: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Enumerate the final CArchive and embedded PYZ without extracting data.

    CArchiveReader.toc entries are (offset, compressed_bytes,
    uncompressed_bytes, compression_flag, typecode) in PyInstaller 6.17.
    PYZ.toc keys are the actual embedded Python module names.
    """
    if executable.is_symlink() or not executable.is_file():
        raise FrozenInventoryError("An existing, regular frozen executable is required")
    if reader_factory is None:
        try:
            from PyInstaller.archive.readers import CArchiveReader
        except ImportError as exc:
            raise FrozenInventoryError("PyInstaller archive reader must be installed") from exc
        reader_factory = CArchiveReader
    try:
        reader = reader_factory(str(executable))
    except (OSError, ValueError, TypeError, RuntimeError) as exc:
        raise FrozenInventoryError("Cannot inspect final PyInstaller executable archive") from exc
    toc = getattr(reader, "toc", None)
    if not isinstance(toc, dict) or not 0 < len(toc) <= _MAX_ENTRIES:
        raise FrozenInventoryError("Frozen CArchive has no usable entry table")
    entries: list[dict[str, Any]] = []
    pyz_modules: list[str] = []
    binary_entries: list[str] = []
    pyz_found = 0
    for original_name, record in toc.items():
        name = _safe_archive_name(original_name)
        if (
            not isinstance(record, (tuple, list))
            or len(record) != 5
            or any(type(record[i]) is not int or record[i] < 0 for i in range(4))
            or not isinstance(record[4], str)
            or record[4] not in _ALLOWED_TYPES
            or record[3] not in {0, 1}
            or record[2] < record[1] and record[3] == 0
        ):
            raise FrozenInventoryError("Frozen CArchive entry has unsupported metadata")
        _offset, stored, uncompressed, compressed, kind = record
        entries.append({
            "name": name, "typecode": kind,
            "stored_bytes": stored, "uncompressed_bytes": uncompressed,
            "compressed": bool(compressed),
        })
        if kind == "b":
            binary_entries.append(name)
        if kind == "z":
            pyz_found += 1
            if pyz_found != 1:
                raise FrozenInventoryError("Frozen CArchive contains duplicate PYZ modules")
            try:
                pyz = reader.open_embedded_archive(original_name)
            except (OSError, ValueError, TypeError, RuntimeError) as exc:
                raise FrozenInventoryError("Cannot inspect the embedded Python module table") from exc
            module_table = getattr(pyz, "toc", None)
            if not isinstance(module_table, dict) or not module_table:
                raise FrozenInventoryError("Frozen PYZ has no module table")
            for module in module_table:
                if not isinstance(module, str) or not _SAFE_MODULE.fullmatch(module):
                    raise FrozenInventoryError("Frozen PYZ has an unsafe module identifier")
                pyz_modules.append(module)
    if pyz_found != 1 or not binary_entries or not pyz_modules:
        raise FrozenInventoryError("Frozen runtime is missing PYZ modules or native binaries")
    if len(pyz_modules) > _MAX_ENTRIES or len(pyz_modules) != len(set(pyz_modules)):
        raise FrozenInventoryError("Frozen PYZ module inventory is empty, too large or duplicated")
    if len(entries) != len({item["name"] for item in entries}):
        raise FrozenInventoryError("Frozen CArchive names are duplicated")
    return {
        "archive_entry_count": len(entries),
        "pyz_module_count": len(pyz_modules),
        "native_binary_entry_count": len(binary_entries),
        "archive_entries": sorted(entries, key=lambda item: item["name"]),
        "pyz_modules": sorted(pyz_modules),
        "native_binary_entries": sorted(binary_entries),
    }


def _read_license_file(distribution: Any, relative: Any) -> dict[str, Any] | None:
    """Digest local .dist-info notices, not entire source/binary distributions."""
    label = str(relative).replace("\\", "/")
    if len(label) > 512 or ".." in label.split("/"):
        return None
    basename = label.rsplit("/", 1)[-1].lower()
    if ".dist-info/" not in label.lower() or not (
        basename.startswith(("license", "licence", "copying", "notice", "authors"))
        or basename.endswith((".license", ".notice"))
    ):
        return None
    try:
        file = Path(distribution.locate_file(relative))
        if file.is_symlink() or not file.is_file():
            return None
        size = file.stat().st_size
        if not 0 < size <= _MAX_LICENSE_BYTES:
            return None
        return {"name": basename, "sha256": _sha256_file(file), "bytes": size}
    except (OSError, ValueError, TypeError):
        return None


def inspect_builder_distributions(
    *, distributions_fn: Callable[[], Iterable[Any]] = installed_distributions,
) -> dict[str, Any]:
    """Collect builder-installed package metadata, clearly not bundle closure.

    License-Expression (PEP 639) is recorded without legal interpretation.
    Older license text and classifiers are ambiguous and require human review.
    """
    packages: list[dict[str, Any]] = []
    normalized: set[str] = set()
    for distribution in distributions_fn():
        metadata = distribution.metadata
        name = str(metadata.get("Name", "")).strip()
        ver = str(metadata.get("Version", "")).strip()
        if not name or not ver or len(name) > 200 or len(ver) > 100:
            raise FrozenInventoryError("An installed builder distribution has invalid metadata")
        key = re.sub(r"[-_.]+", "-", name).lower()
        if key in normalized:
            raise FrozenInventoryError("Duplicate builder distribution names are ambiguous")
        normalized.add(key)
        expr = str(metadata.get("License-Expression", "")).strip()
        generic = str(metadata.get("License", "")).strip()
        classifiers = [
            str(entry)[:320] for entry in (metadata.get_all("Classifier", []) or [])
            if str(entry).startswith("License ::")
        ]
        files = distribution.files
        notices: list[dict[str, Any]] = []
        for relative in files or ():
            if len(notices) >= _MAX_LICENSE_FILES:
                break
            review = _read_license_file(distribution, relative)
            if review is not None:
                notices.append(review)
        notices.sort(key=lambda item: (item["name"], item["sha256"]))
        packages.append({
            "name": name, "version": ver,
            "license_expression": expr[:320] if expr else None,
            "license_metadata_label": (
                generic[:320] if 0 < len(generic) <= 320 else None
            ),
            "license_metadata_text_sha256": (
                _hash_bytes(generic.encode("utf-8")) if len(generic) > 320 else None
            ),
            "license_classifiers": sorted(set(classifiers)),
            "local_notice_digests": notices,
            # A known license identifier or metadata is *not* proof that
            # distribution/transitive license obligations were satisfied.
            "license_independently_reviewed": False,
        })
        if len(packages) > _MAX_DISTRIBUTIONS:
            raise FrozenInventoryError("Builder distribution inventory exceeds safe bounds")
    if not packages:
        raise FrozenInventoryError("Builder has no installed distribution metadata")
    packages.sort(key=lambda item: item["name"].lower())
    inconclusive = sorted(
        item["name"] for item in packages
        if not (
            item["license_expression"] or item["license_metadata_label"]
            or item["license_classifiers"] or item["local_notice_digests"]
        )
    )
    return {
        "distributions": packages,
        "distribution_count": len(packages),
        "missing_license_metadata_names": inconclusive,
        "coverage_scope": "builder_environment_not_bundled_runtime_dependency_closure",
    }


def collect_frozen_inventory(
    executable: Path, *, target: str,
    reader_factory: Callable[[str], Any] | None = None,
    distributions_fn: Callable[[], Iterable[Any]] = installed_distributions,
) -> dict[str, Any]:
    if target not in {"windows-x86_64", "macos-aarch64"}:
        raise FrozenInventoryError("Native inventory is restricted to reviewed stable targets")
    embedded = inspect_frozen_archive(executable, reader_factory=reader_factory)
    builder = inspect_builder_distributions(distributions_fn=distributions_fn)
    packages = {re.sub(r"[-_.]+", "-", entry["name"]).lower(): entry["version"]
                for entry in builder["distributions"]}
    for name, ver in {
        "mt3-infer": "0.2.0",
        "torch": "2.7.1",
        "torchaudio": "2.7.1",
        "transformers": "4.57.6",
        "pyinstaller": "6.17.0",
    }.items():
        if packages.get(name) != ver:
            raise FrozenInventoryError(f"Missing or drifting pinned builder package: {name}")
    binary_sha = _sha256_file(executable)
    snapshot = {
        "schema_version": "1",
        "target": target,
        "frozen_executable_sha256": binary_sha,
        "frozen_archive_reader": "PyInstaller CArchiveReader 6.17.0",
        "frozen_archive": embedded,
        "builder": builder,
        "inventory_is_complete_distributable_sbom": False,
        "native_library_dependency_closure_independently_verified": False,
        "model_weights_in_frozen_executable": False,
        "third_party_license_approval": False,
        "redistribution_status": "pending",
    }
    inventory_sha = _canonical_sha(snapshot)
    if not _SHA.fullmatch(inventory_sha):
        raise FrozenInventoryError("Native dependency inventory digest is invalid")
    return {
        "schema_version": "1",
        "inventory_sha256": inventory_sha,
        "snapshot": snapshot,
        "inventory_is_complete_distributable_sbom": False,
        "legal_reviewer_signoff": False,
        "third_party_license_approval": False,
        "redistribution_status": "pending",
    }

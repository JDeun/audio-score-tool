"""Integrity verification for *all* app-managed runtime payload files.

The archive digest validates transport; this inventory validates the installed
bytes, including model weights, JRE libraries, and non-entrypoint launchers.
Only a successful exact file-set and SHA-256 match can authorize a runtime.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import threading
from collections import OrderedDict
from pathlib import Path

_MAX_FILES = 4096
_MAX_TREE_ENTRIES = 32768
_MAX_CACHED_GENERATIONS = 8
_SHA256_PATTERN = re.compile(r"[a-f0-9]{64}\Z")

# Cache *successful* content verification only. Every access still scans every
# path without following links and compares inode/size/mode/mtime/ctime. A
# changed file is always rehashed; cache entries never survive process restart.
_VERIFIED_CACHE: OrderedDict[
    tuple[str, str], dict[str, tuple[int, int, int, int, int, int]]
] = OrderedDict()
_CACHE_LOCK = threading.RLock()


class _UnsafePayload(ValueError):
    pass


def _safe_relative(path: object) -> bool:
    if not isinstance(path, str) or not path or "\\" in path or path.startswith("/"):
        return False
    return all(segment not in {"", ".", ".."} for segment in path.split("/"))


def _snapshot_tree(directory: Path) -> dict[str, tuple[int, int, int, int, int, int]]:
    """Observe exactly the regular files in a runtime, without following links."""
    if directory.is_symlink() or not directory.is_dir():
        raise _UnsafePayload("Managed payload root is not a regular directory.")
    files: dict[str, tuple[int, int, int, int, int, int]] = {}
    pending: list[tuple[Path, str]] = [(directory, "")]
    entries = 0
    while pending:
        parent, prefix = pending.pop()
        with os.scandir(parent) as children:
            for child in children:
                entries += 1
                if entries > _MAX_TREE_ENTRIES:
                    raise _UnsafePayload("Managed payload has too many entries.")
                rel = prefix + child.name
                if not _safe_relative(rel):
                    raise _UnsafePayload("Managed payload contains an unsafe path.")
                details = child.stat(follow_symlinks=False)
                if stat.S_ISDIR(details.st_mode):
                    pending.append((Path(child.path), rel + "/"))
                elif stat.S_ISREG(details.st_mode):
                    if len(files) >= _MAX_FILES:
                        raise _UnsafePayload("Managed payload has too many files.")
                    files[rel] = (
                        details.st_dev,
                        details.st_ino,
                        details.st_size,
                        details.st_mtime_ns,
                        details.st_ctime_ns,
                        details.st_mode,
                    )
                else:
                    # No symlinks, hard-to-audit special devices, pipes or sockets.
                    raise _UnsafePayload("Managed payload contains a link or special file.")
    if not files:
        raise _UnsafePayload("Managed payload contains no files.")
    return files


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_payload_inventory(directory: Path) -> dict[str, str]:
    """Record all installed archive file identities after tool chmod, pre-commit."""
    before = _snapshot_tree(directory)
    inventory = {
        relative: _digest_file(directory.joinpath(*relative.split("/")))
        for relative in sorted(before)
    }
    if before != _snapshot_tree(directory):
        raise _UnsafePayload("Managed payload changed while generating its inventory.")
    return inventory


def verify_payload_inventory(directory: Path, manifest: object) -> str | None:
    """Return a fail-closed integrity reason, or None when fully verified.

    Large checkpoints are hashed on first use or after stat changes. Repeated
    readiness/execution checks still examine *every* filesystem entry, avoiding
    repeated multi-gigabyte reads when installed files have not changed.
    """
    if not isinstance(manifest, dict) or not manifest:
        return "payload-manifest-missing"
    if len(manifest) > _MAX_FILES or any(
        not _safe_relative(path)
        or not isinstance(digest, str)
        or _SHA256_PATTERN.fullmatch(digest) is None
        for path, digest in manifest.items()
    ):
        return "payload-manifest-invalid"
    try:
        observed = _snapshot_tree(directory)
    except _UnsafePayload:
        return "payload-unsafe-file"
    except OSError:
        return "payload-unreadable"

    if set(manifest) - set(observed):
        return "payload-file-missing"
    if set(observed) - set(manifest):
        return "payload-unexpected-file"

    commitment = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    key = (str(directory.absolute()), commitment)
    with _CACHE_LOCK:
        if _VERIFIED_CACHE.get(key) == observed:
            _VERIFIED_CACHE.move_to_end(key)
            return None
        # Do not allow a stale successful result after any byte mismatch.
        _VERIFIED_CACHE.pop(key, None)

    try:
        for relative in sorted(manifest):
            actual = _digest_file(directory.joinpath(*relative.split("/")))
            if actual != manifest[relative]:
                return "payload-digest-mismatch"
        if observed != _snapshot_tree(directory):
            return "payload-changed-during-verification"
    except _UnsafePayload:
        return "payload-unsafe-file"
    except OSError:
        return "payload-unreadable"

    with _CACHE_LOCK:
        _VERIFIED_CACHE[key] = observed
        _VERIFIED_CACHE.move_to_end(key)
        while len(_VERIFIED_CACHE) > _MAX_CACHED_GENERATIONS:
            _VERIFIED_CACHE.popitem(last=False)
    return None

"""Acquire only pinned KRAISLER correspondence metadata for the fixed six IDs.

The unchanged gate source loader supplies strict HTTP 206, ZIP-directory, CRC,
and SHA checks. A cold run reads one metadata suffix and six small piano match
ranges; it never requests a WAV or downloads the complete archive. Original
members and the optional verified range cache must remain outside the repo.
"""
from __future__ import annotations

import argparse
import json
import re
import zlib
from pathlib import Path

try:
    from . import kraisler_source as frozen
except ImportError:  # Direct script invocation.
    import kraisler_source as frozen


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = Path(__file__).with_name("kraisler_alignment_manifest.json")
REGION_CACHE_NAME = "metadata_region.bin"
MAX_MANIFEST_BYTES = 100_000
MAX_MEMBER_BYTES = 512 * 1024
MAX_REQUEST_BYTES = 666_965
MAX_NETWORK_BYTES = 776_325
MAX_HTTP_REQUESTS = 7
FROZEN_SOURCE_SHA256 = {
    "scripts/kraisler_source.py":
        "94ba9c30adfd60dfc518a371a53b6fdaa722a44352a019311582b8125423e2bd",
    "scripts/kraisler_gate_manifest.json":
        "a18857a4b7a2025ea327f9a03855ca02dca0964110d973d5224b85dfbb258c60",
}
ROLES = {
    "notes": ("annotation_csv", "_notes_VN.csv", "notes_path"),
    "beats": ("annotation_csv", "_beats.csv", "beats_path"),
    "score": ("score_musicxml", "_VN.musicxml", "score_path"),
    "piano_match": ("alignment_match", "_PF.match", "match_path"),
    "piano_score": ("score_musicxml", "_PF.musicxml", "piano_score_path"),
}


def _read_regular(path, limit, label):
    frozen._require(path.is_file() and not path.is_symlink(),
                    f"{label} must be a regular file, not a symlink")
    frozen._require(0 < path.stat().st_size <= limit, f"{label} size is outside bounds")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    frozen._require(0 < len(raw) <= limit, f"{label} size is outside bounds")
    return raw


def _frozen_manifest():
    for relative, expected in FROZEN_SOURCE_SHA256.items():
        raw = _read_regular(ROOT / relative, MAX_MANIFEST_BYTES, "Frozen source")
        frozen._require(frozen._sha(raw) == expected, "Frozen source digest mismatch")
    return frozen.load_manifest(ROOT / "scripts/kraisler_gate_manifest.json")


def validate_alignment_manifest(manifest):
    """Keep the previous cohort and all 18 violin/beat members byte-identical."""
    previous = _frozen_manifest()
    try:
        frozen._require(type(manifest["schema_version"]) is int
                        and manifest["schema_version"] == 1
                        and manifest["dataset"] == "KRAISLER"
                        and type(manifest["record_id"]) is int
                        and manifest["record_id"] == 21082251,
                        "Changed alignment dataset identity")
        frozen._require(manifest["frozen_source_sha256"] == FROZEN_SOURCE_SHA256,
                        "Changed frozen source identity")
        for name in ("archive", "selection", "central_directory", "metadata_region"):
            frozen._require(manifest[name] == previous[name],
                            f"Changed frozen {name}")
        frozen._require(manifest["network_budget"] == {
            "maximum_requests": MAX_HTTP_REQUESTS,
            "maximum_bytes": MAX_NETWORK_BYTES,
            "maximum_single_request_bytes": MAX_REQUEST_BYTES,
        }, "Changed metadata network budget")
        sources = manifest["sources"]
        frozen._require([item["id"] for item in sources]
                        == previous["selection"]["selected_ids"],
                        "Incomplete, reordered, or duplicate cohort")
        region = manifest["metadata_region"]
        directory = manifest["central_directory"]
        ranges = []
        for item, old in zip(sources, previous["sources"], strict=True):
            tid = item["id"]
            frozen._require(item["source_id"] == old["source_id"]
                            and item["selection_sha256"] == old["selection_sha256"],
                            "Changed source identity")
            frozen._require(set(item["members"]) == set(ROLES),
                            "Only the five declared metadata roles are allowed")
            for role, (folder, suffix, _) in ROLES.items():
                member = item["members"][role]
                name = f"KRAISLER/{folder}/{tid}{suffix}"
                frozen._require(member["path"] == name, "Disallowed metadata member path")
                if role in ("notes", "beats", "score"):
                    frozen._require(member == old["members"][role],
                                    "Changed existing metadata member")
                frozen._require(member["flags"] == 0
                                and member["compression_method"] == 8
                                and member["local_header_bytes"] == 30 + len(name.encode()),
                                "Unsupported metadata ZIP header")
                frozen._require(frozen._positive_int(member["compressed_bytes"],
                                                    MAX_REQUEST_BYTES)
                                and frozen._positive_int(member["uncompressed_bytes"],
                                                         MAX_MEMBER_BYTES)
                                and frozen._positive_int(member["range_bytes"],
                                                         MAX_REQUEST_BYTES)
                                and member["range_bytes"] == member["local_header_bytes"]
                                + member["compressed_bytes"],
                                "Oversized or inconsistent metadata member")
                offset, length = member["local_header_offset"], member["range_bytes"]
                frozen._require(type(offset) is int and offset >= 0
                                and offset + length <= directory["offset"],
                                "Out-of-bounds metadata member")
                frozen._require(frozen._digest(member["sha256"])
                                and frozen._digest(member["range_sha256"])
                                and isinstance(member["crc32"], str)
                                and re.fullmatch(r"[0-9a-f]{8}", member["crc32"]) is not None,
                                "Invalid metadata member digest")
                if role == "piano_match":
                    frozen._require(offset + length <= region["offset"],
                                    "Piano match range overlaps metadata suffix")
                    ranges.append((offset, length))
                else:
                    frozen._require(region["offset"] <= offset
                                    and offset + length <= region["offset"] + region["bytes"],
                                    "Metadata member outside pinned suffix")
        ordered = sorted(ranges)
        frozen._require(len(set(ranges)) == 6
                        and all(left[0] + left[1] <= right[0]
                                for left, right in zip(ordered, ordered[1:]))
                        and sum(length for _, length in ranges) + region["bytes"]
                        == MAX_NETWORK_BYTES, "Changed piano match range budget")
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("Malformed KRAISLER alignment manifest") from exc
    return manifest


def _load_alignment_manifest(path=None):
    path = Path(path) if path is not None else MANIFEST_PATH
    raw = _read_regular(path, MAX_MANIFEST_BYTES, "Alignment manifest")
    try:
        manifest = validate_alignment_manifest(json.loads(raw))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("Malformed KRAISLER alignment manifest") from exc
    return manifest, raw


def load_alignment_manifest(path=None):
    return _load_alignment_manifest(path)[0]


class MetadataRangeFetcher(frozen.RangeFetcher):
    """Allow each declared metadata range once, within the smaller byte budget."""

    def __init__(self, manifest):
        super().__init__()
        region = manifest["metadata_region"]
        self._allowed = {(region["offset"], region["bytes"])}
        self._allowed.update((item["members"]["piano_match"]["local_header_offset"],
                              item["members"]["piano_match"]["range_bytes"])
                             for item in manifest["sources"])
        self._requested = set()

    def fetch(self, offset, length):
        request = (offset, length)
        frozen._require(type(offset) is int and type(length) is int
                        and request in self._allowed and request not in self._requested,
                        "Undeclared or repeated metadata HTTP range")
        frozen._require(length <= MAX_REQUEST_BYTES
                        and self.bytes_fetched + length <= MAX_NETWORK_BYTES
                        and self.requests_made < MAX_HTTP_REQUESTS,
                        "Metadata network budget exceeded")
        self._requested.add(request)
        return super().fetch(offset, length)


def _destination(path):
    path = Path(path).absolute()
    frozen._require(all(not component.is_symlink() for component in (path, *path.parents)),
                    "Source destination must not contain symlinks")
    path = path.resolve()
    frozen._require(not path.is_relative_to(ROOT),
                    "Original metadata must stay outside repository")
    frozen._require(not path.exists() or path.is_dir(), "Source destination must be a directory")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cached_member(path, member):
    raw = _read_regular(path, member["uncompressed_bytes"], "Cached metadata member")
    frozen._require(len(raw) == member["uncompressed_bytes"], "Cached metadata size mismatch")
    frozen._require(frozen._sha(raw) == member["sha256"], "Cached metadata digest mismatch")
    frozen._require(f"{zlib.crc32(raw):08x}" == member["crc32"], "Cached metadata CRC mismatch")
    return raw


def acquire_alignment_sources(destination, alignment_manifest_path=None):
    """Verify 30 metadata members and return private local paths plus receipts."""
    manifest, manifest_raw = _load_alignment_manifest(alignment_manifest_path)
    destination = _destination(destination)
    fetcher = MetadataRangeFetcher(manifest)
    region_spec = manifest["metadata_region"]
    region_path = frozen._output_path(destination, {"path": REGION_CACHE_NAME})
    region_cached = region_path.exists()
    if region_cached:
        region = _read_regular(region_path, region_spec["bytes"], "Cached metadata region")
    else:
        region = fetcher.fetch(region_spec["offset"], region_spec["bytes"])
    frozen._verify_metadata_region(region, manifest)
    if not region_cached:
        frozen._write_atomic(region_path, region)
    cases, cache_hits = [], 0
    for item in manifest["sources"]:
        paths, hashes = {}, {}
        for role, (_, _, path_key) in ROLES.items():
            member = item["members"][role]
            path = frozen._output_path(destination, member)
            if path.exists():
                _cached_member(path, member)
                cache_hits += 1
            else:
                offset, length = member["local_header_offset"], member["range_bytes"]
                if role == "piano_match":
                    raw = fetcher.fetch(offset, length)
                else:
                    start = offset - region_spec["offset"]
                    raw = region[start:start + length]
                decoded = frozen._decode_member(raw, member)
                frozen._write_atomic(path, decoded)
            paths[path_key] = str(path)
            hashes[role] = member["sha256"]
        cases.append({"id": item["id"], "source_id": item["source_id"], **paths,
                      "member_sha256": hashes})
    return {"status": "verified", "dataset": "KRAISLER", "record_id": 21082251,
            "manifest_sha256": frozen._sha(manifest_raw),
            "frozen_source_sha256": dict(FROZEN_SOURCE_SHA256),
            "central_directory_sha256": manifest["central_directory"]["sha256"],
            "metadata_region_sha256": region_spec["sha256"],
            "network_bytes": fetcher.bytes_fetched,
            "http_range_requests": fetcher.requests_made,
            "cache_hits": cache_hits, "metadata_region_cache_hit": region_cached,
            "verified_member_count": sum(len(item["members"]) for item in manifest["sources"]),
            "full_archive_downloaded": False, "full_archive_md5_verified": False,
            "media_acquired": False, "cases": cases}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    args = parser.parse_args()
    print(json.dumps(acquire_alignment_sources(args.destination, args.manifest), indent=2))


if __name__ == "__main__":
    main()

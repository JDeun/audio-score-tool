"""Acquire a frozen six-recording KRAISLER cohort with bounded HTTP ranges.

The source manifest pins exact compressed ranges and decoded member bytes. This
does not verify the publisher's MD5 for the complete 1.56 GB archive. Original
media and annotations are written only outside this repository.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import struct
import tempfile
import urllib.request
import wave
import zlib
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = Path(__file__).with_name("kraisler_gate_manifest.json")
ARCHIVE_URL = "https://zenodo.org/api/records/21082251/files/KRAISLER.zip/content"
ARCHIVE_BYTES = 1_558_287_213
SELECTION_PREFIX = "waveform-gate-kraisler-v1/"
MAX_REQUEST_BYTES = 10 * 1024 * 1024
MAX_NETWORK_BYTES = 40 * 1024 * 1024
MAX_MEMBER_BYTES = 12 * 1024 * 1024
ROLES = {
    "audio": ("performance_wav", "_VN_dry.wav"),
    "notes": ("annotation_csv", "_notes_VN.csv"),
    "beats": ("annotation_csv", "_beats.csv"),
    "score": ("score_musicxml", "_VN.musicxml"),
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _positive_int(value, limit):
    return type(value) is int and 0 < value <= limit


def _digest(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def validate_manifest(manifest):
    """Reject altered selection, archive identity, paths, or resource bounds."""
    population = [f"{number:02d}" for number in range(1, 21)]
    selected = sorted(population, key=lambda tid: _sha((SELECTION_PREFIX + tid).encode()))[:6]
    selection = manifest["selection"]
    _require(manifest["schema_version"] == 1 and manifest["record_id"] == 21082251,
             "Unexpected dataset identity")
    _require(selection["prefix"] == SELECTION_PREFIX
             and selection["population_ids"] == population
             and selection["selected_ids"] == selected
             and selection["count"] == 6
             and selection["replacement_allowed"] is False
             and selection["acoustic_condition"] == "dry"
             and selection["channel"] == "VN"
             and selection["crop"] == "complete source file", "Changed cohort selection")
    archive = manifest["archive"]
    _require(archive["url"] == ARCHIVE_URL and archive["bytes"] == ARCHIVE_BYTES
             and archive["published_md5"] == "22f6f51e9c356c1ea8f591d85603fd73"
             and archive["full_archive_md5_verified"] is False, "Changed archive identity")
    directory = manifest["central_directory"]
    _require(directory["offset"] == 1_558_254_047 and directory["bytes"] == 33_144
             and directory["entries"] == 389 and _digest(directory["sha256"]),
             "Changed central directory bounds")
    region = manifest["metadata_region"]
    _require(region["offset"] == 1_557_620_248 and region["bytes"] == 666_965
             and _digest(region["sha256"]), "Changed metadata region bounds")
    sources = manifest["sources"]
    _require([source["id"] for source in sources] == selected, "Incomplete or duplicate cohort")
    for source in sources:
        tid = source["id"]
        _require(source["source_id"] == "kraisler_" + tid
                 and source["selection_sha256"] == _sha((SELECTION_PREFIX + tid).encode()),
                 "Changed source identity")
        _require(set(source["members"]) == set(ROLES), "Incomplete source members")
        for role, (folder, suffix) in ROLES.items():
            member = source["members"][role]
            name = f"KRAISLER/{folder}/{tid}{suffix}"
            _require(member["path"] == name, "Disallowed member path")
            _require(member["local_header_bytes"] == 30 + len(name.encode())
                     and member["flags"] == 0 and member["compression_method"] == 8,
                     "Unsupported ZIP member header")
            _require(_positive_int(member["compressed_bytes"], MAX_REQUEST_BYTES)
                     and _positive_int(member["uncompressed_bytes"], MAX_MEMBER_BYTES)
                     and _positive_int(member["range_bytes"], MAX_REQUEST_BYTES)
                     and member["range_bytes"] == member["local_header_bytes"]
                     + member["compressed_bytes"], "Oversized or inconsistent member")
            offset = member["local_header_offset"]
            _require(type(offset) is int and offset >= 0
                     and offset + member["range_bytes"] <= directory["offset"],
                     "Out-of-bounds member")
            _require(_digest(member["sha256"]) and _digest(member["range_sha256"])
                     and isinstance(member["crc32"], str)
                     and re.fullmatch(r"[0-9a-f]{8}", member["crc32"]) is not None,
                     "Invalid member digest")
            if role != "audio":
                _require(region["offset"] <= offset
                         and offset + member["range_bytes"] <= region["offset"] + region["bytes"],
                         "Metadata member outside pinned region")
        audio = source["audio"]
        _require(audio["channels"] == 1 and audio["sample_rate"] == 44100
                 and audio["sample_width"] == 2
                 and _positive_int(audio["frames"], 44100 * 130)
                 and audio["frames"] >= 44100 * 40
                 and audio["duration_seconds"] == audio["frames"] / 44100,
                 "Unsupported WAV shape")
    return manifest


def load_manifest(path=None):
    path = Path(path) if path is not None else MANIFEST_PATH
    _require(path.is_file() and not path.is_symlink(), "Manifest must be a regular file")
    _require(path.stat().st_size < 100_000, "Manifest too large")
    try:
        return validate_manifest(json.loads(path.read_bytes()))
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Malformed KRAISLER manifest") from exc


class RangeFetcher:
    """Strict 206-only reader; an ignored Range never causes a full download."""

    def __init__(self):
        self.bytes_fetched = 0
        self.requests_made = 0

    def fetch(self, offset, length):
        _require(type(offset) is int and offset >= 0
                 and _positive_int(length, MAX_REQUEST_BYTES)
                 and offset + length <= ARCHIVE_BYTES, "Disallowed HTTP range")
        _require(self.bytes_fetched + length <= MAX_NETWORK_BYTES, "Network byte budget exceeded")
        end = offset + length - 1
        request = urllib.request.Request(
            ARCHIVE_URL, headers={"Range": f"bytes={offset}-{end}", "Accept-Encoding": "identity"}
        )
        with urllib.request.urlopen(request, timeout=45) as response:
            _require(response.status == 206, "Server ignored Range; refusing full archive")
            _require(response.headers.get("Content-Range") == f"bytes {offset}-{end}/{ARCHIVE_BYTES}",
                     "Unexpected Content-Range")
            length_header = response.headers.get("Content-Length")
            _require(length_header is None or length_header == str(length), "Unexpected Content-Length")
            _require(response.headers.get("Content-Encoding", "identity") == "identity",
                     "Unexpected Content-Encoding")
            raw = response.read(length + 1)
            _require(len(raw) == length, "Incorrect ranged byte count")
        self.bytes_fetched += len(raw)
        self.requests_made += 1
        return raw


def _central_entries(raw, expected_count):
    entries, offset = {}, 0
    while offset < len(raw):
        _require(len(raw) - offset >= 46, "Truncated central directory")
        header = struct.unpack_from("<4s6H3L5H2L", raw, offset)
        _require(header[0] == b"PK\x01\x02", "Invalid central directory signature")
        name_length, extra_length, comment_length = header[10:13]
        end = offset + 46 + name_length + extra_length + comment_length
        _require(end <= len(raw), "Truncated central directory entry")
        try:
            name = raw[offset + 46:offset + 46 + name_length].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Non-UTF8 central directory member") from exc
        _require(name not in entries and "\x00" not in name, "Duplicate or invalid archive member")
        entries[name] = {"flags": header[3], "compression_method": header[4],
                         "crc32": f"{header[7]:08x}", "compressed_bytes": header[8],
                         "uncompressed_bytes": header[9], "local_header_offset": header[16]}
        offset = end
    _require(len(entries) == expected_count, "Archive entry coverage changed")
    return entries


def _verify_metadata_region(raw, manifest):
    region, directory = manifest["metadata_region"], manifest["central_directory"]
    _require(len(raw) == region["bytes"] and _sha(raw) == region["sha256"],
             "Metadata region digest mismatch")
    start = directory["offset"] - region["offset"]
    central = raw[start:start + directory["bytes"]]
    _require(_sha(central) == directory["sha256"], "Central directory digest mismatch")
    eocd = struct.unpack("<4s4H2LH", raw[-22:])
    _require(eocd == (b"PK\x05\x06", 0, 0, directory["entries"], directory["entries"],
                      directory["bytes"], directory["offset"], 0), "Archive end record changed")
    entries = _central_entries(central, directory["entries"])
    for source in manifest["sources"]:
        for member in source["members"].values():
            actual = entries.get(member["path"])
            _require(actual is not None and all(member[key] == value for key, value in actual.items()),
                     "Manifest disagrees with central directory")


def _decode_member(raw, member):
    _require(len(raw) == member["range_bytes"] and _sha(raw) == member["range_sha256"],
             "Member range digest mismatch")
    _require(len(raw) >= 30, "Truncated local ZIP header")
    header = struct.unpack_from("<4s5H3L2H", raw)
    _require(header[0] == b"PK\x03\x04" and header[2] == member["flags"] == 0
             and header[3] == member["compression_method"] == 8
             and header[6] == int(member["crc32"], 16)
             and header[7] == member["compressed_bytes"]
             and header[8] == member["uncompressed_bytes"]
             and header[10] == 0 and 30 + header[9] == member["local_header_bytes"],
             "Local ZIP header disagrees with manifest")
    _require(raw[30:member["local_header_bytes"]] == member["path"].encode(),
             "Local ZIP member path mismatch")
    decoder = zlib.decompressobj(-15)
    try:
        decoded = decoder.decompress(raw[member["local_header_bytes"]:],
                                     member["uncompressed_bytes"] + 1)
    except zlib.error as exc:
        raise ValueError("Invalid compressed member") from exc
    _require(decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail
             and len(decoded) == member["uncompressed_bytes"], "Member decompression size mismatch")
    _require(f"{zlib.crc32(decoded):08x}" == member["crc32"], "Member CRC mismatch")
    _require(_sha(decoded) == member["sha256"], "Member SHA256 mismatch")
    return decoded


def _verify_wav(raw, expected):
    try:
        with wave.open(io.BytesIO(raw)) as recording:
            shape = (recording.getnchannels(), recording.getframerate(), recording.getsampwidth(),
                     recording.getnframes(), recording.getcomptype())
            _require(shape == (1, 44100, 2, expected["frames"], "NONE"), "WAV shape mismatch")
            _require(len(recording.readframes(expected["frames"] + 1)) == expected["frames"] * 2,
                     "Truncated WAV samples")
    except (wave.Error, EOFError) as exc:
        raise ValueError("Invalid WAV member") from exc


def _output_path(destination, member):
    path = destination.joinpath(*PurePosixPath(member["path"]).parts)
    _require(path.resolve().is_relative_to(destination), "Source destination escapes data directory")
    for component in (path, *path.parents):
        if component == destination:
            break
        _require(not component.is_symlink(), "Source path must not contain symlinks")
    return path


def _write_atomic(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def acquire_sources(destination, manifest_path=None):
    """Verify and acquire exactly six sources; return local paths and receipts."""
    manifest_file = Path(manifest_path) if manifest_path is not None else MANIFEST_PATH
    manifest = load_manifest(manifest_file)
    destination = Path(destination).resolve()
    _require(not destination.is_relative_to(ROOT), "Original sources must stay outside repository")
    destination.mkdir(parents=True, exist_ok=True)
    fetcher = RangeFetcher()
    region_spec = manifest["metadata_region"]
    region = fetcher.fetch(region_spec["offset"], region_spec["bytes"])
    _verify_metadata_region(region, manifest)
    cases, cache_hits = [], 0
    for source in manifest["sources"]:
        paths, hashes = {}, {}
        for role, member in source["members"].items():
            path = _output_path(destination, member)
            if path.exists():
                _require(path.is_file() and path.stat().st_size == member["uncompressed_bytes"],
                         "Cached source size mismatch")
                decoded = path.read_bytes()
                _require(_sha(decoded) == member["sha256"], "Cached source digest mismatch")
                cache_hits += 1
            else:
                offset, length = member["local_header_offset"], member["range_bytes"]
                if role == "audio":
                    raw = fetcher.fetch(offset, length)
                else:
                    start = offset - region_spec["offset"]
                    raw = region[start:start + length]
                decoded = _decode_member(raw, member)
                if role == "audio":
                    _verify_wav(decoded, source["audio"])
                _write_atomic(path, decoded)
            if role == "audio":
                _verify_wav(decoded, source["audio"])
            paths[role + "_path"] = str(path)
            hashes[role] = member["sha256"]
        cases.append({"id": source["id"], "source_id": source["source_id"], **paths,
                      "member_sha256": hashes, "audio": source["audio"]})
    return {"status": "verified", "dataset": "KRAISLER", "record_id": 21082251,
            "manifest_sha256": _sha(manifest_file.read_bytes()),
            "central_directory_sha256": manifest["central_directory"]["sha256"],
            "metadata_region_sha256": manifest["metadata_region"]["sha256"],
            "network_bytes": fetcher.bytes_fetched, "http_range_requests": fetcher.requests_made,
            "cache_hits": cache_hits, "full_archive_downloaded": False,
            "full_archive_md5_verified": False, "cases": cases}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    args = parser.parse_args()
    print(json.dumps(acquire_sources(args.destination, args.manifest), indent=2))


if __name__ == "__main__":
    main()

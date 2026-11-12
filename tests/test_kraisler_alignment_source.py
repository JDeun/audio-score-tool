"""Metadata-only range, cohort, and cache contracts using invented ZIP members."""
from __future__ import annotations

import copy
import hashlib
import io
import json
import struct
import zipfile
from pathlib import Path

import pytest

from scripts import kraisler_alignment_source as source


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def archive_fixture():
    """A small invented archive; none of these bytes are dataset annotations."""
    ids = ["02", "19", "08", "12", "05", "06"]
    files = {"KRAISLER/performance_wav/02_VN_dry.wav": b"never fetch this media sentinel"}
    for tid in ids:
        files[f"KRAISLER/alignment_match/{tid}_PF.match"] = f"invented match {tid}\n".encode()
    for tid in ids:
        for role, (folder, suffix, _) in source.ROLES.items():
            if role != "piano_match":
                files[f"KRAISLER/{folder}/{tid}{suffix}"] = f"invented {role} {tid}\n".encode()
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw in files.items():
            archive.writestr(name, raw)
    raw_zip = stream.getvalue()
    cases = []
    with zipfile.ZipFile(io.BytesIO(raw_zip)) as archive:
        for tid in ids:
            members = {}
            for role, (folder, suffix, _) in source.ROLES.items():
                name = f"KRAISLER/{folder}/{tid}{suffix}"
                info = archive.getinfo(name)
                header_bytes = 30 + len(name.encode())
                length = header_bytes + info.compress_size
                member_range = raw_zip[info.header_offset:info.header_offset + length]
                members[role] = {
                    "path": name, "local_header_offset": info.header_offset,
                    "local_header_bytes": header_bytes, "compressed_bytes": info.compress_size,
                    "uncompressed_bytes": info.file_size, "crc32": f"{info.CRC:08x}",
                    "compression_method": 8, "flags": 0, "range_bytes": length,
                    "range_sha256": digest(member_range), "sha256": digest(files[name]),
                }
            cases.append({"id": tid, "source_id": "kraisler_" + tid, "members": members})
    region_offset = min(case["members"]["notes"]["local_header_offset"] for case in cases)
    end = struct.unpack("<4s4H2LH", raw_zip[-22:])
    central = raw_zip[end[6]:end[6] + end[5]]
    manifest = {
        "metadata_region": {"offset": region_offset, "bytes": len(raw_zip) - region_offset,
                            "sha256": digest(raw_zip[region_offset:])},
        "central_directory": {"offset": end[6], "bytes": end[5], "entries": end[4],
                              "sha256": digest(central)},
        "sources": cases,
    }
    return raw_zip, manifest


class Response:
    def __init__(self, raw, offset, length):
        self.status = 206
        self.headers = {
            "Content-Range": f"bytes {offset}-{offset + length - 1}/{source.frozen.ARCHIVE_BYTES}",
            "Content-Length": str(length),
        }
        self.body = raw[offset:offset + length]
        self.reads = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, count):
        self.reads.append(count)
        return self.body[:count]


def install_fixture(monkeypatch):
    raw, manifest = archive_fixture()
    calls = []
    monkeypatch.setattr(source, "_load_alignment_manifest",
                        lambda path=None: (manifest, json.dumps(manifest).encode()))

    def fetch(request, timeout):
        assert request.full_url == source.frozen.ARCHIVE_URL
        assert timeout == 45
        start, end = map(int, request.get_header("Range").removeprefix("bytes=").split("-"))
        calls.append((start, end - start + 1))
        return Response(raw, start, end - start + 1)

    monkeypatch.setattr(source.frozen.urllib.request, "urlopen", fetch)
    return raw, manifest, calls


def test_frozen_manifest_keeps_six_ids_and_exact_old_metadata_members():
    manifest = source.load_alignment_manifest()
    previous = source.frozen.load_manifest()
    assert [item["id"] for item in manifest["sources"]] == ["02", "19", "08", "12", "05", "06"]
    for item, old in zip(manifest["sources"], previous["sources"], strict=True):
        assert set(item["members"]) == set(source.ROLES)
        for role in ("notes", "beats", "score"):
            assert item["members"][role] == old["members"][role]
    assert source.frozen._sha(source.frozen.MANIFEST_PATH.read_bytes()) == (
        "a18857a4b7a2025ea327f9a03855ca02dca0964110d973d5224b85dfbb258c60"
    )


@pytest.mark.parametrize("change", [
    "missing", "duplicate", "reordered", "audio", "old_member", "traversal",
    "source_identity", "frozen_identity", "oversized", "range_budget", "outside_suffix",
])
def test_manifest_rejects_cohort_payload_and_budget_changes(change):
    manifest = copy.deepcopy(source.load_alignment_manifest())
    first = manifest["sources"][0]
    if change == "missing":
        manifest["sources"].pop()
    elif change == "duplicate":
        manifest["sources"][-1] = first
    elif change == "reordered":
        manifest["sources"].reverse()
    elif change == "audio":
        first["members"]["audio"] = {}
    elif change == "old_member":
        first["members"]["notes"]["sha256"] = "0" * 64
    elif change == "traversal":
        first["members"]["piano_match"]["path"] = "../../private.txt"
    elif change == "source_identity":
        first["source_id"] = "replacement"
    elif change == "frozen_identity":
        manifest["frozen_source_sha256"]["scripts/kraisler_source.py"] = "0" * 64
    elif change == "oversized":
        first["members"]["piano_score"]["uncompressed_bytes"] = source.MAX_MEMBER_BYTES + 1
    elif change == "range_budget":
        first["members"]["piano_match"]["compressed_bytes"] += 1
        first["members"]["piano_match"]["range_bytes"] += 1
    else:
        first["members"]["piano_score"]["local_header_offset"] = 0
    with pytest.raises(ValueError):
        source.validate_alignment_manifest(manifest)


def test_cold_acquisition_requests_only_seven_metadata_ranges_and_cache_is_network_free(
        monkeypatch, tmp_path):
    _, manifest, calls = install_fixture(monkeypatch)
    destination = tmp_path / "sources"
    result = source.acquire_alignment_sources(destination)
    region = manifest["metadata_region"]
    expected = {(region["offset"], region["bytes"])} | {
        (item["members"]["piano_match"]["local_header_offset"],
         item["members"]["piano_match"]["range_bytes"]) for item in manifest["sources"]
    }
    assert set(calls) == expected and len(calls) == 7
    assert result["http_range_requests"] == 7
    assert result["network_bytes"] == sum(length for _, length in expected)
    assert result["verified_member_count"] == 30 and result["cache_hits"] == 0
    assert result["media_acquired"] is False and result["full_archive_md5_verified"] is False
    assert not (destination / "KRAISLER/performance_wav").exists()
    for case in result["cases"]:
        for role, (_, _, path_key) in source.ROLES.items():
            assert digest(Path(case[path_key]).read_bytes()) == case["member_sha256"][role]
    cached = source.acquire_alignment_sources(destination)
    assert len(calls) == 7
    assert cached["network_bytes"] == 0 and cached["http_range_requests"] == 0
    assert cached["cache_hits"] == 30 and cached["metadata_region_cache_hit"] is True


@pytest.mark.parametrize("target", ["region", "member"])
def test_corrupted_cache_is_rejected_without_refetch_or_overwrite(monkeypatch, tmp_path, target):
    _, _, calls = install_fixture(monkeypatch)
    destination = tmp_path / "sources"
    result = source.acquire_alignment_sources(destination)
    path = (destination / source.REGION_CACHE_NAME if target == "region"
            else Path(result["cases"][0]["match_path"]))
    damaged = bytearray(path.read_bytes())
    damaged[-1] ^= 1
    path.write_bytes(damaged)
    with pytest.raises(ValueError, match="digest mismatch"):
        source.acquire_alignment_sources(destination)
    assert len(calls) == 7 and path.read_bytes() == bytes(damaged)


@pytest.mark.parametrize("target", ["destination", "region", "member", "parent"])
def test_symlinked_destination_cache_or_member_is_rejected(monkeypatch, tmp_path, target):
    install_fixture(monkeypatch)
    destination = tmp_path / "sources"
    if target == "destination":
        outside = tmp_path / "outside"
        outside.mkdir()
        destination.symlink_to(outside, target_is_directory=True)
    else:
        destination.mkdir()
        if target == "parent":
            outside = tmp_path / "outside"
            outside.mkdir()
            (destination / "KRAISLER").symlink_to(outside, target_is_directory=True)
        else:
            outside = tmp_path / "untouched.txt"
            outside.write_text("untouched")
            link = (destination / source.REGION_CACHE_NAME if target == "region"
                    else destination / "KRAISLER/annotation_csv/02_notes_VN.csv")
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(outside)
    with pytest.raises(ValueError, match="symlinks|escapes"):
        source.acquire_alignment_sources(destination)
    if outside.is_file():
        assert outside.read_text() == "untouched"


def test_metadata_cannot_be_written_under_repository():
    with pytest.raises(ValueError, match="outside repository"):
        source._destination(source.ROOT / "accidental-alignment-source-download")


def test_supplementary_member_must_agree_with_verified_central_directory(monkeypatch, tmp_path):
    _, manifest, calls = install_fixture(monkeypatch)
    manifest["sources"][0]["members"]["piano_match"]["crc32"] = "00000000"
    destination = tmp_path / "sources"
    with pytest.raises(ValueError, match="central directory"):
        source.acquire_alignment_sources(destination)
    assert len(calls) == 1 and not (destination / "KRAISLER").exists()


def test_undeclared_media_and_repeat_ranges_are_rejected_before_network(monkeypatch):
    _, manifest, calls = install_fixture(monkeypatch)
    fetcher = source.MetadataRangeFetcher(manifest)
    with pytest.raises(ValueError, match="Undeclared"):
        fetcher.fetch(0, 30)
    assert calls == []
    region = manifest["metadata_region"]
    fetcher.fetch(region["offset"], region["bytes"])
    with pytest.raises(ValueError, match="repeated"):
        fetcher.fetch(region["offset"], region["bytes"])
    assert len(calls) == 1


def test_ignored_range_does_not_read_a_full_archive(monkeypatch, tmp_path):
    raw, manifest, _ = install_fixture(monkeypatch)
    region = manifest["metadata_region"]
    response = Response(raw, region["offset"], region["bytes"])
    response.status = 200
    monkeypatch.setattr(source.frozen.urllib.request, "urlopen", lambda *args, **kwargs: response)
    with pytest.raises(ValueError, match="ignored Range"):
        source.acquire_alignment_sources(tmp_path / "sources")
    assert response.reads == []

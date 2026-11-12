"""Fail-closed source transport/provenance tests without network or source media."""
from __future__ import annotations

import copy
import hashlib
import io
import json
import struct
import wave
import zipfile
from pathlib import Path

import pytest

from scripts import kraisler_source as source


def digest(data):
    return hashlib.sha256(data).hexdigest()


def archive_fixture():
    """An invented tiny ZIP, not KRAISLER audio, score, or annotations."""
    audio = io.BytesIO()
    with wave.open(audio, "wb") as recording:
        recording.setnchannels(1)
        recording.setsampwidth(2)
        recording.setframerate(44100)
        recording.writeframes(b"\0\0" * 441)
    files = {
        "KRAISLER/performance_wav/02_VN_dry.wav": audio.getvalue(),
        "KRAISLER/annotation_csv/02_notes_VN.csv": b"onset,offset,midi,velocity\n0,0.01,60,127\n",
        "KRAISLER/annotation_csv/02_beats.csv": b"beat_time,beat_type,time_signature,piano,violin\n",
        "KRAISLER/score_musicxml/02_VN.musicxml": b"<score-partwise/>\n",
    }
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw in files.items():
            archive.writestr(name, raw)
    raw_zip = stream.getvalue()
    members = {}
    with zipfile.ZipFile(io.BytesIO(raw_zip)) as archive:
        for role, (folder, suffix) in source.ROLES.items():
            name = f"KRAISLER/{folder}/02{suffix}"
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
    end = struct.unpack("<4s4H2LH", raw_zip[-22:])
    directory = raw_zip[end[6]:end[6] + end[5]]
    manifest = {
        "metadata_region": {"offset": 0, "bytes": len(raw_zip), "sha256": digest(raw_zip)},
        "central_directory": {"offset": end[6], "bytes": end[5], "entries": end[4],
                              "sha256": digest(directory)},
        "sources": [{"id": "02", "source_id": "kraisler_02", "members": members,
                     "audio": {"frames": 441, "channels": 1, "sample_rate": 44100,
                               "sample_width": 2, "duration_seconds": 0.01}}],
    }
    return raw_zip, manifest


@pytest.mark.parametrize("change", ["missing", "duplicate", "replacement", "traversal", "url", "size"])
def test_manifest_rejects_population_and_transport_changes(change):
    manifest = copy.deepcopy(source.load_manifest())
    if change == "missing":
        manifest["sources"].pop()
    elif change == "duplicate":
        manifest["sources"][-1] = manifest["sources"][0]
    elif change == "replacement":
        manifest["selection"]["replacement_allowed"] = True
    elif change == "traversal":
        manifest["sources"][0]["members"]["audio"]["path"] = "KRAISLER/../../secret.wav"
    elif change == "url":
        manifest["archive"]["url"] = "https://example.test/different.zip"
    else:
        manifest["sources"][0]["members"]["audio"]["uncompressed_bytes"] = 2**40
    with pytest.raises(ValueError):
        source.validate_manifest(manifest)


class Response:
    def __init__(self, status, headers, body):
        self.status, self.headers, self.body = status, headers, body
        self.reads = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, count):
        self.reads.append(count)
        return self.body[:count]


@pytest.mark.parametrize("change", ["ignored", "wrong_offset", "wrong_total", "encoding", "length"])
def test_invalid_range_response_is_rejected_before_body_read(monkeypatch, change):
    response = Response(206, {"Content-Range": f"bytes 10-13/{source.ARCHIVE_BYTES}",
                              "Content-Length": "4"}, b"data")
    if change == "ignored":
        response.status = 200
    elif change == "wrong_offset":
        response.headers["Content-Range"] = f"bytes 11-14/{source.ARCHIVE_BYTES}"
    elif change == "wrong_total":
        response.headers["Content-Range"] = "bytes 10-13/12345678"
    elif change == "encoding":
        response.headers["Content-Encoding"] = "gzip"
    else:
        response.headers["Content-Length"] = "999999999"
    monkeypatch.setattr(source.urllib.request, "urlopen", lambda *args, **kwargs: response)
    with pytest.raises(ValueError):
        source.RangeFetcher().fetch(10, 4)
    assert response.reads == []


@pytest.mark.parametrize("body", [b"abc", b"abcde"])
def test_range_byte_count_is_exact_and_bounded(monkeypatch, body):
    response = Response(206, {"Content-Range": f"bytes 10-13/{source.ARCHIVE_BYTES}"}, body)
    monkeypatch.setattr(source.urllib.request, "urlopen", lambda *args, **kwargs: response)
    with pytest.raises(ValueError, match="byte count"):
        source.RangeFetcher().fetch(10, 4)
    assert response.reads == [5]


def test_range_budget_stops_before_another_network_call(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Over-budget transport was attempted")
    monkeypatch.setattr(source.urllib.request, "urlopen", forbidden)
    fetcher = source.RangeFetcher()
    fetcher.bytes_fetched = source.MAX_NETWORK_BYTES
    with pytest.raises(ValueError, match="budget"):
        fetcher.fetch(0, 1)


@pytest.mark.parametrize("change", ["compressed_corruption", "decoded_sha", "header_path", "trailing_stream"])
def test_corrupt_member_cannot_be_written(change):
    raw_zip, manifest = archive_fixture()
    member = copy.deepcopy(manifest["sources"][0]["members"]["notes"])
    start = member["local_header_offset"]
    raw = bytearray(raw_zip[start:start + member["range_bytes"]])
    if change == "compressed_corruption":
        raw[-1] ^= 1
    elif change == "decoded_sha":
        member["sha256"] = "0" * 64
    elif change == "header_path":
        raw[30] = ord("X")
        member["range_sha256"] = digest(raw)
    else:
        raw += b"unaccounted"
        member["range_bytes"] = len(raw)
        member["compressed_bytes"] += len(b"unaccounted")
        struct.pack_into("<L", raw, 18, member["compressed_bytes"])
        member["range_sha256"] = digest(raw)
    with pytest.raises(ValueError):
        source._decode_member(bytes(raw), member)


def test_central_directory_must_agree_with_selected_member_identity():
    raw_zip, manifest = archive_fixture()
    source._verify_metadata_region(raw_zip, manifest)
    manifest["sources"][0]["members"]["notes"]["crc32"] = "00000000"
    with pytest.raises(ValueError, match="central directory"):
        source._verify_metadata_region(raw_zip, manifest)


def test_acquisition_verifies_payloads_and_refuses_bad_cache(monkeypatch, tmp_path):
    raw_zip, manifest = archive_fixture()
    manifest_path = tmp_path / "fixture-manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    monkeypatch.setattr(source, "load_manifest", lambda path: manifest)

    class FakeFetcher:
        def __init__(self):
            self.bytes_fetched = self.requests_made = 0

        def fetch(self, offset, length):
            self.bytes_fetched += length
            self.requests_made += 1
            return raw_zip[offset:offset + length]

    monkeypatch.setattr(source, "RangeFetcher", FakeFetcher)
    result = source.acquire_sources(tmp_path / "sources", manifest_path)
    assert result["status"] == "verified"
    assert result["full_archive_md5_verified"] is False
    case = result["cases"][0]
    for role in source.ROLES:
        assert digest(Path(case[role + "_path"]).read_bytes()) == case["member_sha256"][role]
    cached = source.acquire_sources(tmp_path / "sources", manifest_path)
    assert cached["cache_hits"] == 4
    assert cached["http_range_requests"] == 1
    path = Path(case["notes_path"])
    data = bytearray(path.read_bytes())
    data[-2] ^= 1
    path.write_bytes(data)
    with pytest.raises(ValueError, match="Cached source digest"):
        source.acquire_sources(tmp_path / "sources", manifest_path)


def test_original_sources_cannot_be_written_in_repository():
    with pytest.raises(ValueError, match="outside repository"):
        source.acquire_sources(source.ROOT / "accidental-source-download")


def test_symlinked_member_is_rejected(tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("keep this")
    destination = tmp_path / "source"
    destination.mkdir()
    (destination / "audio.wav").symlink_to(outside)
    with pytest.raises(ValueError, match="escapes|symlinks"):
        source._output_path(destination, {"path": "audio.wav"})
    assert outside.read_text() == "keep this"

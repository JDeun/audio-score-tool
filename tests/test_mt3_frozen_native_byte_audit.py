"""Synthetic, offline CArchive payload-vs-wheel RECORD SHA comparison tests."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts import hash_mt3_frozen_native_bytes as audit


class Reader:
    contents = {
        "torch\\lib\\a.dll": b"correct-original-library",
        "torch\\lib\\b.dll": b"wrong-build-library",
        "libmissing.dll": b"unattributed-native",
        "module.py": b"not-an-executable",
    }

    def __init__(self, _file: str):
        self.toc = {
            name: (0, len(value), len(value), 0, "b")
            for name, value in self.contents.items()
        }
        self.extracted: list[str] = []

    def extract(self, name: str) -> bytes:
        self.extracted.append(name)
        return self.contents[name]


def _input():
    rows = [
        {
            "archive_path": name.replace("\\", "/"),
            "match_status": "single_record_path_match" if name.endswith(("a.dll", "b.dll")) else "unmatched",
            "wheel_record_matches": (
                [{
                    "distribution": "torch", "version": "2.7.1",
                    "wheel_record_sha256": (
                        hashlib.sha256(Reader.contents["torch\\lib\\a.dll"]).hexdigest()
                        if name.endswith("a.dll") else "f" * 64
                    ),
                }] if name.endswith(("a.dll", "b.dll")) else []
            ),
        }
        for name in Reader.contents if name.endswith(".dll")
    ]
    entries = [
        {"name": n.replace("\\", "/"), "typecode": "b", "uncompressed_bytes": len(v)}
        for n, v in Reader.contents.items()
    ]
    return entries, {"target": "windows-x86_64", "native_file_review_queue": rows}


def test_exact_embedded_bytes_and_mismatched_wheel_record_are_distinguished(tmp_path: Path):
    exe = tmp_path / "fake-native.exe"
    exe.write_bytes(b"MZ-synthetic")
    entries, hints = _input()
    report = audit.hash_frozen_native_records(
        exe, entries, hints, target="windows-x86_64", reader_factory=Reader,
    )
    assert report["native_filename_candidate_count"] == 3
    assert report["counts"]["exact_record_sha256_match"] == 1
    assert report["counts"]["wheel_record_sha256_mismatch"] == 1
    assert report["counts"]["unmatched"] == 1
    assert report["uncompressed_bytes_read"] == sum(
        len(v) for name, v in Reader.contents.items() if name.endswith(".dll")
    )
    assert report["license_independently_approved"] is False
    assert report["complete_sbom_verified"] is False
    assert str(tmp_path) not in str(report)
    assert b"correct-original-library" not in str(report).encode("utf-8")


def test_read_limit_does_not_present_unhashed_binary_as_verified(tmp_path, monkeypatch):
    exe = tmp_path / "fake-native.exe"
    exe.write_bytes(b"MZ-synthetic")
    entries, hints = _input()
    monkeypatch.setattr(audit, "_MAX_MEMBER_BYTES", 10)
    report = audit.hash_frozen_native_records(
        exe, entries, hints, target="windows-x86_64", reader_factory=Reader,
    )
    assert report["all_native_library_bytes_hashed"] is False
    assert report["counts"]["size_limit_not_hashed"] == 3
    assert all(row["embedded_sha256"] is None for row in report["entries"])
    assert report["counts"]["exact_record_sha256_match"] == 0


@pytest.mark.parametrize("failure", ["duplicate", "missing", "wrong-size", "unsafe-path"])
def test_invalid_source_or_frozen_member_data_is_rejected(tmp_path, failure):
    exe = tmp_path / "fake.exe"
    exe.write_bytes(b"synthetic")
    entries, hints = _input()
    if failure == "duplicate":
        hints["native_file_review_queue"].append(hints["native_file_review_queue"][0])
    elif failure == "missing":
        hints["native_file_review_queue"].pop()
    elif failure == "wrong-size":
        entries[0]["uncompressed_bytes"] += 1
    else:
        hints["native_file_review_queue"][0]["archive_path"] = "../unsafe.dll"
    with pytest.raises(audit.NativeByteAuditError):
        audit.hash_frozen_native_records(
            exe, entries, hints, target="windows-x86_64", reader_factory=Reader,
        )

"""Offline synthetic tests of frozen library ↔ wheel RECORD filename mapping."""
from __future__ import annotations

import base64
import hashlib
from email.message import Message
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import map_mt3_frozen_file_owners as owners


class Record(str):
    def __new__(cls, value: str, *, payload: bytes | None = None):
        value_obj = str.__new__(cls, value)
        if payload is None:
            value_obj.hash = None
            value_obj.size = None
        else:
            value_obj.hash = SimpleNamespace(
                mode="sha256",
                value=base64.urlsafe_b64encode(hashlib.sha256(payload).digest())
                .rstrip(b"=").decode("ascii"),
            )
            value_obj.size = len(payload)
        return value_obj


class Dist:
    def __init__(self, name: str, files: list[Record], version: str = "2.7.1"):
        self.metadata = Message()
        self.metadata["Name"] = name
        self.metadata["Version"] = version
        self.files = files


def _files(*paths: str) -> list[dict]:
    return [
        {"name": path, "typecode": "b", "uncompressed_bytes": 128}
        for path in paths
    ]


def test_exact_wheel_record_path_match_is_evidence_hint_only():
    frozen = _files(
        "torch/lib/torch_cpu.dll", "torch/_C.cp311-win_amd64.pyd",
        "libfoo.dll", "python/source.py",
    )
    packages = [
        Dist("torch", [
            Record("torch/lib/torch_cpu.dll", payload=b"installed-source-file"),
            Record("torch/_C.cp311-win_amd64.pyd"),
            Record("torch/LICENSE"),
        ]),
        Dist("numpy", [Record("numpy/core/multiarray.pyd")]),
    ]
    result = owners.map_native_file_records(frozen, packages, target="windows-x86_64")
    assert result["native_filename_candidate_count"] == 3
    assert result["matched_candidate_count"] == 2
    assert result["unmatched_candidate_count"] == 1
    assert result["ambiguous_candidate_count"] == 0
    by_path = {x["archive_path"]: x for x in result["native_file_review_queue"]}
    matched = by_path["torch/lib/torch_cpu.dll"]
    assert matched["match_status"] == "single_record_path_match"
    assert matched["wheel_record_matches"][0]["distribution"] == "torch"
    assert matched["wheel_record_matches"][0]["wheel_record_sha256"] == hashlib.sha256(
        b"installed-source-file"
    ).hexdigest()
    assert matched["wheel_record_matches"][0]["record_sha256_matches_embedded_payload"] is False
    assert matched["wheel_record_matches"][0]["license_independently_approved"] is False
    assert by_path["libfoo.dll"]["match_status"] == "unmatched"
    assert result["source_owner_independently_verified"] is False
    assert result["binary_payload_equals_record_hash_verified"] is False
    assert result["redistribution_status"] == "pending"


def test_case_insensitive_windows_and_case_sensitive_macos_are_distinct():
    frozen = _files("Torch/LIB/Torch_CPU.DLL")
    pkg = [Dist("torch", [Record("torch/lib/torch_cpu.dll")])]
    windows = owners.map_native_file_records(frozen, pkg, target="windows-x86_64")
    macos = owners.map_native_file_records(frozen, pkg, target="macos-aarch64")
    assert windows["matched_candidate_count"] == 1
    assert macos["unmatched_candidate_count"] == 1


def test_ambiguous_filename_stays_unassigned():
    frozen = _files("bin/shared.dll")
    packages = [
        Dist("First", [Record("bin/shared.dll")]),
        Dist("Second", [Record("bin/shared.dll")]),
    ]
    result = owners.map_native_file_records(frozen, packages, target="windows-x86_64")
    assert result["ambiguous_candidate_count"] == 1
    candidates = result["native_file_review_queue"][0]["wheel_record_matches"]
    assert {x["distribution"] for x in candidates} == {"First", "Second"}
    assert all(x["binary_source_independently_verified"] is False for x in candidates)


def test_unrelated_or_external_scripts_do_not_claim_owner():
    frozen = _files("top/libmystery.dll")
    packages = [
        Dist("foo", [
            Record("../../bin/libmystery.dll"),
            Record("/usr/lib/libmystery.dll"),
            Record("C:\\\\Windows\\\\libmystery.dll"),
        ]),
    ]
    result = owners.map_native_file_records(frozen, packages, target="windows-x86_64")
    assert result["unmatched_candidate_count"] == 1
    assert result["ignored_nonrelative_wheel_record_paths"] == 3


@pytest.mark.parametrize("input_path", [
    "../native.dll", "C:\\\\absolute.dll", "/absolute.dll", "dir\\\\..\\\\escape.dll",
    "a//b.dll",
])
def test_unsafe_frozen_paths_rejected(input_path: str):
    with pytest.raises(owners.FileOwnerMappingError, match="unsafe"):
        owners.map_native_file_records(_files(input_path), [], target="windows-x86_64")


def test_casefold_collision_in_frozen_archive_rejected():
    with pytest.raises(owners.FileOwnerMappingError, match="Colliding"):
        owners.map_native_file_records(
            _files("Torch/X.dll", "torch/x.dll"), [], target="windows-x86_64",
        )


def test_duplicate_normalized_wheel_record_path_rejected():
    frozen = _files("torch/lib/native.dll")
    pkg = [Dist("torch", [Record("torch/lib/native.dll"), Record("torch\\lib\\native.dll")])]
    with pytest.raises(owners.FileOwnerMappingError, match="Duplicate wheel RECORD"):
        owners.map_native_file_records(frozen, pkg, target="windows-x86_64")


def test_duplicate_distribution_names_rejected():
    with pytest.raises(owners.FileOwnerMappingError, match="Duplicate builder"):
        owners.map_native_file_records(
            _files("torch/lib/native.dll"),
            [Dist("torch", []), Dist("Torch", [])],
            target="windows-x86_64",
        )


def test_corrupted_or_non_sha256_wheel_record_does_not_create_fake_digest():
    frozen = _files("torch/lib/native.dll")
    good = Record("torch/lib/native.dll")
    good.hash = SimpleNamespace(mode="md5", value="f" * 32)
    result = owners.map_native_file_records(
        frozen, [Dist("torch", [good])], target="windows-x86_64",
    )
    assert result["native_file_review_queue"][0]["wheel_record_matches"][0][
        "wheel_record_sha256"
    ] is None
    corrupt = Record("torch/lib/native.dll")
    corrupt.hash = SimpleNamespace(mode="sha256", value="not-a-real-digest")
    with pytest.raises(owners.FileOwnerMappingError, match="length"):
        owners.map_native_file_records(
            frozen, [Dist("torch", [corrupt])], target="windows-x86_64",
        )


def test_file_records_are_not_extracted_or_transferred_to_a_release(tmp_path: Path):
    dummy = tmp_path / "secret.lib"
    dummy.write_bytes(b"private-third-party-source")
    result = owners.map_native_file_records(
        _files("torch/lib/torch_cpu.dll"),
        [Dist("torch", [Record("torch/lib/torch_cpu.dll")])],
        target="windows-x86_64",
    )
    assert str(tmp_path) not in str(result)
    assert dummy.read_bytes() not in str(result).encode()
    assert result["license_independently_approved"] is False

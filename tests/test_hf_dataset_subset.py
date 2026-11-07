"""No-network, synthetic bytes-only contracts for small, rights-gated Hub subsets."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import ingest_hf_dataset_subset as hub

BYTES = b"self-owned synthetic chord annotation\n"
DIGEST = hashlib.sha256(BYTES).hexdigest()


def _plan(*, split: str = "test", dataset: str = "sample-a", license: str = "cc-by-4.0") -> dict:
    return {
        "schema_version": 1,
        "datasets": [{
            "id": dataset,
            "repo_id": "organization/research-data",
            "revision": "a" * 40,
            "license": license,
            "rights_reviewed": True,
            "files": [{
                "path": "annotations/small.json",
                "size_bytes": len(BYTES),
                "sha256": DIGEST,
                "recording_id": "owned-recording-a",
                "split": split,
            }],
        }],
    }


def test_metadata_only_default_never_touches_the_network_or_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    def no_remote(*_args, **_kwargs):
        raise AssertionError("a dry run must never access the Hub")

    monkeypatch.setattr(hub, "_remote_size", no_remote)
    monkeypatch.setattr(hub, "_download", no_remote)
    dest = tmp_path / "private"
    result = hub.ingest(_plan(), dest)
    assert result["file_count"] == 1
    assert result["total_bytes"] == len(BYTES)
    assert result["executed"] is False
    assert result["verified_files"] == 0
    assert not dest.exists()
    assert result["license_and_alignment_independently_verified"] is False


def test_small_synthetic_verified_file_ingested_with_correct_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    source = tmp_path / "owned-synthetic-annotation.json"
    source.write_bytes(BYTES)
    monkeypatch.setattr(hub, "_remote_size", lambda _item: len(BYTES))
    monkeypatch.setattr(hub, "_download", lambda _item, _cache: source)
    destination = tmp_path / "private"
    result = hub.ingest(_plan(), destination, fetch=True)
    assert result["verified_files"] == 1
    target = (destination / "sample-a" / ("a" * 40) / "annotations/small.json")
    assert target.read_bytes() == BYTES
    assert hub.ingest(_plan(), destination, fetch=True)["verified_files"] == 1


def test_remote_size_mismatch_fails_before_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(hub, "_remote_size", lambda _: len(BYTES) + 1)

    def fail_download(*_args):
        raise AssertionError("download must not run before size preflight")

    monkeypatch.setattr(hub, "_download", fail_download)
    with pytest.raises(ValueError, match="remote size mismatch"):
        hub.ingest(_plan(), tmp_path / "private", fetch=True)


def test_corrupted_fetched_bytes_not_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    source = tmp_path / "corrupt.bin"
    source.write_bytes(b"x" * len(BYTES))
    monkeypatch.setattr(hub, "_remote_size", lambda _: len(BYTES))
    monkeypatch.setattr(hub, "_download", lambda *_: source)
    target = tmp_path / "private" / "sample-a" / ("a" * 40) / "annotations/small.json"
    with pytest.raises(ValueError, match="checksum"):
        hub.ingest(_plan(), tmp_path / "private", fetch=True)
    assert not target.exists()


def test_unreviewed_source_is_not_fetchable():
    payload = _plan()
    payload["datasets"][0]["rights_reviewed"] = False
    with pytest.raises(ValueError, match="operator rights review"):
        hub.validate_subset_plan(payload)


def test_commercial_rejects_nc_sources_even_with_operator_review():
    with pytest.raises(ValueError, match="commercial"):
        hub.validate_subset_plan(_plan(license="cc-by-nc-sa-4.0"), commercial=True)
    assert hub.validate_subset_plan(_plan(license="cc-by-nc-sa-4.0"))["commercial"] is False


@pytest.mark.parametrize("path", [
    "../escape.json", "/private/file.json", "dir/../../escape.wav",
    "a\\b.mp3", "dir//b.wav", "file%2Fescaped", "file:uri",
])
def test_unsafe_paths_rejected(path: str):
    payload = _plan()
    payload["datasets"][0]["files"][0]["path"] = path
    with pytest.raises(ValueError, match="unsafe|relative|plain"):
        hub.validate_subset_plan(payload)


@pytest.mark.parametrize("value", [
    "other", "verify_upstream", "unknown", "per_source",
])
def test_unresolved_licenses_fail_closed(value: str):
    with pytest.raises(ValueError, match="license"):
        hub.validate_subset_plan(_plan(license=value))


def test_cross_split_recording_id_overlap_rejected():
    payload = _plan()
    second = json.loads(json.dumps(payload["datasets"][0]))
    second["id"] = "sample-b"
    second["repo_id"] = "other-team/mirror"
    second["files"][0]["split"] = "train"
    payload["datasets"].append(second)
    with pytest.raises(ValueError, match="cross-split"):
        hub.validate_subset_plan(payload)


def test_cross_split_same_audio_sha_even_with_different_recording_names():
    payload = _plan()
    payload["datasets"][0]["files"][0]["audio_sha256"] = "b" * 64
    second = json.loads(json.dumps(payload["datasets"][0]))
    second["id"] = "sample-b"
    second["repo_id"] = "other-team/secondary"
    second["files"][0]["split"] = "train"
    second["files"][0]["recording_id"] = "alias-for-recording"
    payload["datasets"].append(second)
    with pytest.raises(ValueError, match="cross-split"):
        hub.validate_subset_plan(payload)


def test_file_count_and_total_budget_bound_bulk_aggregate_download():
    payload = _plan()
    files = payload["datasets"][0]["files"]
    for index in range(8):
        sample = dict(files[0])
        sample["path"] = f"annotations/extra-{index}.json"
        files.append(sample)
    with pytest.raises(ValueError, match="budget"):
        hub.validate_subset_plan(payload)

    payload = _plan()
    payload["datasets"][0]["files"][0]["size_bytes"] = hub.MAX_FILE_BYTES + 1
    with pytest.raises(ValueError, match="32MiB"):
        hub.validate_subset_plan(payload)


def test_private_root_must_not_be_inside_repository(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
):
    monkeypatch.setattr(hub, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="outside"):
        hub.ingest(_plan(), tmp_path / "dataset-files", fetch=True)


def test_existing_tampered_file_is_never_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    source = tmp_path / "valid.bin"
    source.write_bytes(BYTES)
    monkeypatch.setattr(hub, "_remote_size", lambda _: len(BYTES))
    monkeypatch.setattr(hub, "_download", lambda *_: source)
    destination = tmp_path / "private"
    target = destination / "sample-a" / ("a" * 40) / "annotations/small.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"bad")
    with pytest.raises(ValueError, match="refusing overwrite"):
        hub.ingest(_plan(), destination, fetch=True)
    assert target.read_bytes() == b"bad"



def _two_file_plan() -> dict:
    payload = _plan()
    second = dict(payload["datasets"][0]["files"][0])
    second["path"] = "annotations/other.json"
    payload["datasets"][0]["files"].append(second)
    return payload


def test_multiple_annotation_files_count_as_one_recording():
    report = hub.validate_subset_plan(_two_file_plan())
    assert report["file_count"] == 2
    assert report["recording_count"] == 1
    assert report["recordings"][0]["file_count"] == 2


def test_same_split_repackaged_audio_hash_cannot_double_count_a_recording():
    plan = _plan()
    plan["datasets"][0]["files"][0]["audio_sha256"] = "b" * 64
    other = json.loads(json.dumps(plan["datasets"][0]))
    other["id"] = "source-b"
    other["repo_id"] = "different-owner/repackaged"
    other["files"][0]["recording_id"] = "other-label-for-same-audio"
    plan["datasets"].append(other)
    with pytest.raises(ValueError, match="duplicate recording audio_sha256"):
        hub.validate_subset_plan(plan)


def test_same_recording_with_inconsistent_audio_hash_is_not_accepted():
    plan = _two_file_plan()
    plan["datasets"][0]["files"][0]["audio_sha256"] = "b" * 64
    plan["datasets"][0]["files"][1]["audio_sha256"] = "c" * 64
    with pytest.raises(ValueError, match="inconsistent audio_sha256"):
        hub.validate_subset_plan(plan)


def test_corrupt_second_file_cannot_leave_verified_first_file_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    plan = _two_file_plan()
    source = tmp_path / "valid.bin"
    bad = tmp_path / "bad.bin"
    source.write_bytes(BYTES)
    bad.write_bytes(b"x" * len(BYTES))
    monkeypatch.setattr(hub, "_remote_size", lambda _item: len(BYTES))
    monkeypatch.setattr(
        hub, "_download",
        lambda item, _cache: source if item["path"].endswith("small.json") else bad,
    )
    root = tmp_path / "private"
    with pytest.raises(ValueError, match="download checksum"):
        hub.ingest(plan, root, fetch=True)
    assert not list(root.rglob("*.json"))
    assert not list(root.glob(".hf-subset-staging-*"))


def test_remote_size_checks_all_sources_before_downloading_anything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    plan = _two_file_plan()
    seen: list[str] = []

    def remote(item):
        seen.append(item["path"])
        return len(BYTES) if len(seen) == 1 else len(BYTES) + 1

    def unexpected_download(*_args):
        raise AssertionError("no download before all remote size checks")

    monkeypatch.setattr(hub, "_remote_size", remote)
    monkeypatch.setattr(hub, "_download", unexpected_download)
    root = tmp_path / "private"
    with pytest.raises(ValueError, match="remote size mismatch"):
        hub.ingest(plan, root, fetch=True)
    assert len(seen) == 2
    assert not list(root.rglob("*.json"))


def test_failed_commit_rolls_back_newly_materialized_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    plan = _two_file_plan()
    source = tmp_path / "valid.bin"
    source.write_bytes(BYTES)
    monkeypatch.setattr(hub, "_remote_size", lambda _item: len(BYTES))
    monkeypatch.setattr(hub, "_download", lambda *_args: source)
    original = hub.os.link
    calls = 0

    def fail_second_link(source_path, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected atomic commit error")
        return original(source_path, target)

    monkeypatch.setattr(hub.os, "link", fail_second_link)
    root = tmp_path / "private"
    with pytest.raises(OSError, match="injected atomic"):
        hub.ingest(plan, root, fetch=True)
    assert calls == 2
    assert not list(root.rglob("*.json"))
    assert not list(root.glob(".hf-subset-staging-*"))


def test_private_root_symlink_cannot_escape_to_another_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    root, outside = tmp_path / "private", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "sample-a").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(hub, "_remote_size", lambda _item: len(BYTES))
    with pytest.raises(ValueError, match="unsafe dataset destination|symlinked"):
        hub.ingest(_plan(), root, fetch=True)
    assert not list(outside.iterdir())


def test_multi_file_fetch_is_idempotent_without_re_downloading_shards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    plan = _two_file_plan()
    source = tmp_path / "valid.bin"
    source.write_bytes(BYTES)
    monkeypatch.setattr(hub, "_remote_size", lambda _item: len(BYTES))
    count = 0

    def download(_item, _cache):
        nonlocal count
        count += 1
        return source

    monkeypatch.setattr(hub, "_download", download)
    root = tmp_path / "private"
    first = hub.ingest(plan, root, fetch=True)
    second = hub.ingest(plan, root, fetch=True)
    assert first["verified_files"] == second["verified_files"] == 2
    assert first["recording_count"] == second["recording_count"] == 1
    assert count == 2
    assert not list(root.glob(".hf-subset-staging-*"))

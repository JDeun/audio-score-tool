"""Pinned MR-MT3 upstream retrieval; synthetic offline fixtures only."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from scripts import fetch_pinned_mrmt3_checkpoint as source


@pytest.fixture
def fake_hf(monkeypatch, tmp_path: Path):
    blob = (b"synthetic-not-a-pytorch-checkpoint" * 3500)
    digest = hashlib.sha256(blob).hexdigest()
    monkeypatch.setattr(source, "CHECKPOINT_SHA256", digest)
    monkeypatch.setattr(source, "_MIN_BYTES", 100)
    calls = []

    def fake_download(*, repo_id, filename, revision, cache_dir):
        calls.append((repo_id, filename, revision, cache_dir))
        cache = Path(cache_dir)
        cache.mkdir(parents=True, exist_ok=True)
        asset = cache / "checkpoint"
        asset.write_bytes(blob)
        return str(asset)

    # Only the dynamically imported hub function is replaced. No network.
    from huggingface_hub import hf_hub_download
    monkeypatch.setattr("huggingface_hub.hf_hub_download", fake_download)
    yield blob, digest, calls
    monkeypatch.setattr("huggingface_hub.hf_hub_download", hf_hub_download)


def test_immutable_revision_and_exact_checkpoint_digest(fake_hf, tmp_path: Path):
    blob, digest, calls = fake_hf
    root = tmp_path / "app-models"
    result = source.fetch_pinned_checkpoint(root, cache_dir=tmp_path / "hf-cache")
    assert calls == [(
        "gudgud1014/MR-MT3", "mt3.pth",
        "7bd24c3e1dc26468a6a9354c0a4f174405c9bad8",
        str(tmp_path / "hf-cache"),
    )]
    assert (root / "mr_mt3/mt3.pth").read_bytes() == blob
    assert result["checkpoint_sha256"] == digest
    assert result["immutable_revision_requested"] is True
    assert result["model_redistribution_approved"] is False
    assert result["redistribution_status"] == "pending"
    assert not list(root.rglob("*.part"))


def test_wrong_upstream_checkpoint_never_replaces_valid_file(fake_hf, monkeypatch, tmp_path):
    blob, digest, _ = fake_hf
    root = tmp_path / "model"
    final = root / "mr_mt3/mt3.pth"
    final.parent.mkdir(parents=True)
    final.write_bytes(blob)
    monkeypatch.setattr(source, "CHECKPOINT_SHA256", "f" * 64)
    with pytest.raises(source.PinnedCheckpointError, match="Existing checkpoint"):
        source.fetch_pinned_checkpoint(root, cache_dir=tmp_path / "hf-cache")
    assert final.read_bytes() == blob
    assert not list(root.rglob("*.part"))
    assert digest != "f" * 64


def test_tampered_download_fail_closed_before_install(fake_hf, monkeypatch, tmp_path):
    blob, _, calls = fake_hf
    monkeypatch.setattr(source, "CHECKPOINT_SHA256", "e" * 64)
    with pytest.raises(source.PinnedCheckpointError, match="SHA-256 mismatch"):
        source.fetch_pinned_checkpoint(tmp_path / "models", cache_dir=tmp_path / "cache")
    assert len(calls) == 1
    assert not (tmp_path / "models/mr_mt3/mt3.pth").exists()
    assert not list((tmp_path / "models").rglob("*.part"))
    assert len(blob) > 100


def test_refuses_output_paths_in_git_tree_or_linked_model_path(fake_hf, tmp_path):
    with pytest.raises(source.PinnedCheckpointError, match="outside the Git repository"):
        source.fetch_pinned_checkpoint(source._ROOT / "checkpoint", cache_dir=tmp_path / "cache")
    linked = tmp_path / "linked"
    actual = tmp_path / "models"
    actual.mkdir()
    linked.symlink_to(actual, target_is_directory=True)
    with pytest.raises(source.PinnedCheckpointError, match="cannot be linked"):
        source.fetch_pinned_checkpoint(linked, cache_dir=tmp_path / "cache")
    with pytest.raises(source.PinnedCheckpointError, match="separate"):
        source.fetch_pinned_checkpoint(tmp_path / "common", cache_dir=tmp_path / "common/cache")


def test_cli_writes_pending_metadata_only_and_does_not_clobber(fake_hf, tmp_path, monkeypatch, capsys):
    out = tmp_path / "pending.json"
    monkeypatch.setattr(sys, "argv", [
        "fetch_pinned_mrmt3_checkpoint.py",
        "--checkpoint-dir", str(tmp_path / "models"),
        "--cache-dir", str(tmp_path / "cache"),
        "--output", str(out),
    ])
    assert source.main() == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["redistribution_status"] == "pending"
    assert payload["checkpoint_sha256"] == fake_hf[1]
    assert str(tmp_path) not in json.dumps(payload)
    assert "redistribution pending" in capsys.readouterr().out
    with pytest.raises(SystemExit) as error:
        source.main()
    assert error.value.code == 2

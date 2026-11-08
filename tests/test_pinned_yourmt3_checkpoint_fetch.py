"""Synthetic-only tests: pin original YourMT3 Space Git-LFS checkpoint."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from scripts import fetch_pinned_yourmt3_checkpoint as model


@pytest.fixture
def fake_hf(tmp_path: Path, monkeypatch):
    payload = b"synthetic-not-weights" * 9000
    sha = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(model, "CHECKPOINT_SHA256", sha)
    monkeypatch.setattr(model, "_MIN_BYTES", 100)
    seen = []

    def fake_download(*, repo_type, repo_id, filename, revision, cache_dir):
        seen.append((repo_type, repo_id, filename, revision))
        cache = Path(cache_dir)
        cache.mkdir(parents=True, exist_ok=True)
        file = cache / "weight"
        file.write_bytes(payload)
        return str(file)

    monkeypatch.setattr("huggingface_hub.hf_hub_download", fake_download)
    return payload, sha, seen


def test_pinned_hf_space_full_blob_sha_and_internal_layout(fake_hf, tmp_path):
    payload, sha, seen = fake_hf
    target = tmp_path / "model"
    proof = model.fetch_pinned_checkpoint(target, cache_dir=tmp_path / "cache")
    assert seen == [
        ("space", "mimbres/YourMT3", model.CHECKPOINT_FILENAME, model.MODEL_REVISION),
    ]
    output = target / "yourmt3" / model.MODEL_VARIANT / "last.ckpt"
    assert output.read_bytes() == payload
    assert proof["checkpoint_sha256"] == sha
    assert proof["immutable_revision_requested"] is True
    assert proof["model_redistribution_approved"] is False
    assert proof["redistribution_status"] == "pending"
    assert not list(target.rglob("*.part"))


def test_mutated_space_blob_never_staged(fake_hf, monkeypatch, tmp_path):
    monkeypatch.setattr(model, "CHECKPOINT_SHA256", "a" * 64)
    with pytest.raises(model.YourMT3CheckpointError, match="SHA-256 mismatch"):
        model.fetch_pinned_checkpoint(tmp_path / "models", cache_dir=tmp_path / "hf")
    assert not list((tmp_path / "models").rglob("*.ckpt"))
    assert not list((tmp_path / "models").rglob("*.part"))


def test_existing_unknown_checkpoint_not_overwritten(fake_hf, monkeypatch, tmp_path):
    root = tmp_path / "model"
    dst = root / "yourmt3" / model.MODEL_VARIANT / "last.ckpt"
    dst.parent.mkdir(parents=True)
    dst.write_bytes(b"unapproved-weight")
    with pytest.raises(model.YourMT3CheckpointError, match="Existing"):
        model.fetch_pinned_checkpoint(root, cache_dir=tmp_path / "cache")
    assert dst.read_bytes() == b"unapproved-weight"


def test_private_root_and_cache_must_be_disjoint(fake_hf, tmp_path):
    with pytest.raises(ValueError, match="outside the Git repository"):
        model.fetch_pinned_checkpoint(model._private_directory.__globals__["_ROOT"] / "weights",
                                      cache_dir=tmp_path / "cache")
    with pytest.raises(model.YourMT3CheckpointError, match="disjoint"):
        model.fetch_pinned_checkpoint(tmp_path / "common", cache_dir=tmp_path / "common/cache")


def test_cli_writes_metadata_only_and_rejects_overwrite(fake_hf, monkeypatch, tmp_path, capsys):
    target = tmp_path / "review.pending.json"
    monkeypatch.setattr(sys, "argv", [
        "fetch_pinned_yourmt3_checkpoint.py",
        "--checkpoint-dir", str(tmp_path / "weights"),
        "--cache-dir", str(tmp_path / "cache"),
        "--output", str(target),
    ])
    assert model.main() == 0
    proof = json.loads(target.read_text(encoding="utf-8"))
    assert proof["checkpoint_sha256"] == fake_hf[1]
    assert proof["checkpoint_deserialized"] is False
    assert "weights" not in json.dumps(proof)
    assert "rights review pending" in capsys.readouterr().out
    with pytest.raises(SystemExit) as exc:
        model.main()
    assert exc.value.code == 2

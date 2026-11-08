"""Synthetic-only v1 quality/runtime identity binding contracts."""

from __future__ import annotations

import copy

import pytest

from audio_score_tool import v1_release_readiness as readiness

_DIGEST = "a" * 64
_MODEL = {
    "model_key": "mr_mt3",
    "model_revision": "sha256:" + _DIGEST,
    "runtime_revision": "mt3-infer-0.2.0",
    "checkpoint_path": "checkpoints/mr_mt3/mt3.pth",
    "checkpoint_sha256": _DIGEST,
}
_QUALITY = {
    "engine": {
        "id": "mt3_infer",
        "model_revision": _MODEL["model_revision"],
        "runtime_revision": _MODEL["runtime_revision"],
        "artifact_sha256": _DIGEST,
    }
}


def _catalog(monkeypatch, overrides=None):
    data = {
        "windows-x86_64": {"model_identity": copy.deepcopy(_MODEL)},
        "macos-aarch64": {"model_identity": copy.deepcopy(_MODEL)},
    }
    for target, payload in (overrides or {}).items():
        data[target] = payload
    monkeypatch.setattr(
        readiness, "_artifact_payload",
        lambda component, target: data.get(target)
        if component == "transcription_engine" else None,
    )


def test_approved_checkpoint_binds_both_distinct_os_archives(monkeypatch):
    # No requirement that the Windows and macOS *archive* digests match.
    _catalog(monkeypatch)
    result = readiness.verify_release_model_binding(_QUALITY)
    assert result["ready"] is True
    assert result["checkpoint_sha256"] == _DIGEST
    assert result["targets"] == ["windows-x86_64", "macos-aarch64"]


@pytest.mark.parametrize("field", [
    "model_revision", "runtime_revision", "checkpoint_sha256",
    "model_key", "checkpoint_path",
])
def test_one_platform_model_substitution_prevents_v1_release(monkeypatch, field):
    modified = copy.deepcopy(_MODEL)
    modified[field] = "b" * 64 if field == "checkpoint_sha256" else "different"
    _catalog(monkeypatch, {"macos-aarch64": {"model_identity": modified}})
    with pytest.raises(RuntimeError, match="v1 model"):
        readiness.verify_release_model_binding(_QUALITY)


@pytest.mark.parametrize("payload", [None, {}, {"model_identity": {}}])
def test_missing_model_evidence_refuses_release(monkeypatch, payload):
    _catalog(monkeypatch, {"windows-x86_64": payload})
    with pytest.raises(RuntimeError, match="model identity"):
        readiness.verify_release_model_binding(_QUALITY)


def test_noncommercial_or_unsupported_engine_refused(monkeypatch):
    _catalog(monkeypatch)
    quality = copy.deepcopy(_QUALITY)
    quality["engine"]["id"] = "muscriptor"
    with pytest.raises(RuntimeError, match="supported commercial"):
        readiness.verify_release_model_binding(quality)

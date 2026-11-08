"""No-network regressions for real checkpoint packaging QA (synthetic bytes)."""
from __future__ import annotations

import os
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from audio_score_tool.managed_tool_resolver import registered_managed_component_root
from scripts import smoke_real_mt3_managed_checkpoint as qa


def _fixture(tmp_path: Path, model: str = "mr_mt3") -> tuple[Path, Path, Path]:
    cache = tmp_path / "real-qa-source-cache"
    selected = cache / model
    selected.mkdir(parents=True)
    (selected / "weights.safetensors").write_bytes(b"original synthetic model weights")
    (selected / "config.yaml").write_text("model: synthetic-fixture")
    launcher = tmp_path / "host-runner-script"
    launcher.write_text("#!/bin/sh\nexit 0\n")
    launcher.chmod(0o755)
    audio = tmp_path / "owned-original.wav"
    audio.write_bytes(b"RIFF" + b"0" * 55)
    return cache, launcher, audio


def test_full_model_directory_is_included_not_just_weight_file(tmp_path: Path):
    cache, _launcher, _audio = _fixture(tmp_path)
    files = qa._source_files(cache, "mr_mt3")
    assert {relative for _, relative in files} == {
        "checkpoints/mr_mt3/config.yaml",
        "checkpoints/mr_mt3/weights.safetensors",
    }
    archive = tmp_path / "local-ci-only.zip"
    runner = tmp_path / "runner-script"
    runner.write_text("#!/bin/sh\nexit 0\n")
    digests = qa._write_zip(archive, runner, files)
    assert set(digests) == {"bin/mt3-infer", *(relative for _, relative in files)}
    with zipfile.ZipFile(archive) as source:
        assert set(source.namelist()) == set(digests)
        assert all(info.compress_type == zipfile.ZIP_STORED for info in source.infolist())
        assert (source.read("checkpoints/mr_mt3/weights.safetensors")
                == b"original synthetic model weights")


@pytest.mark.parametrize("invalid", [
    "not-available", "unsupported-model", "missing-weight", "linked-weight", "linked-directory",
])
def test_fails_closed_for_missing_or_unsafe_model_files(
    tmp_path: Path, invalid: str,
):
    cache, _launcher, _audio = _fixture(tmp_path)
    selected = cache / "mr_mt3"
    if invalid == "not-available":
        selected.rename(tmp_path / "moved-out")
    elif invalid == "missing-weight":
        (selected / "weights.safetensors").unlink()
    elif invalid == "linked-weight":
        weight = selected / "weights.safetensors"
        target = tmp_path / "external-checkpoint"
        target.write_bytes(weight.read_bytes())
        weight.unlink()
        try:
            weight.symlink_to(target)
        except (OSError, NotImplementedError):
            pytest.skip("Symlinks unavailable")
    elif invalid == "linked-directory":
        folder = selected / "external"
        outside = tmp_path / "outside"
        outside.mkdir()
        try:
            folder.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("Directory symlinks unavailable")
    with pytest.raises(qa.ManagedRealCheckpointError):
        qa._source_files(cache, "unsupported" if invalid == "unsupported-model" else "mr_mt3")


def test_product_installer_and_packaged_real_inference_entry_are_reached_without_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    cache, launcher, audio = _fixture(tmp_path)
    monkeypatch.setattr(qa, "_qa_entrypoint", lambda: launcher)
    called = []

    class FakeMT3:
        def __init__(self, settings):
            self.settings = settings
            called.append(("settings", settings.mt3_model, os.getenv("PATH")))

        def ready(self):
            root = registered_managed_component_root(
                "transcription_engine", required_tool="mt3-infer",
            )
            assert root is not None
            assert (root / "checkpoints/mr_mt3/weights.safetensors").read_bytes()
            assert os.environ["MT3_CHECKPOINT_DIR"].endswith("untrusted-ambient")
            return True

        def transcribe(self, audio_path, destination, *, device):
            called.append(("transcribe", self.settings.mt3_model, device))
            destination.mkdir(parents=True)
            midi = destination / "score.mid"
            midi.write_bytes(b"not-an-actual-MIDI: unit fixture")
            xml = destination / "score.musicxml"
            xml.write_text("<synthetic-test-only />")
            return SimpleNamespace(midi_path=midi, musicxml_path=xml)

    monkeypatch.setattr(qa, "MT3InferEngine", FakeMT3)
    monkeypatch.setattr(qa, "verify_model_outputs", lambda *_: {"notes": 2, "parts": 1, "midi_notes": 2})
    result = qa.run_real_managed_mt3(
        model="mr_mt3",
        audio=audio,
        checkpoint_directory=cache,
        destination=tmp_path / "report.pending.json",
    )
    assert result["schema"] == 1
    assert result["model"] == "mr_mt3"
    assert result["checkpoint_files"] == 2
    assert result["all_payload_sha256_verified"] is True
    assert result["actual_pretrained_weights_executed"] is True  # mocked only in this unit test
    assert result["qa_launcher_requires_host_python"] is True
    assert result["model_redistribution_rights_verified"] is False
    assert result["third_party_artifacts_published"] is False
    assert result["redistribution_status"] == "pending"
    assert called == [("settings", "mr_mt3", ""), ("transcribe", "mr_mt3", "cpu")]


def test_manifest_sha_only_and_no_model_weight_artifacts_in_workflow():
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github/workflows/tier2-actual-models.yml"
    ).read_text()
    assert "smoke_real_mt3_managed_checkpoint.py" in workflow
    assert "MT3_CHECKPOINT_DIR" in workflow
    assert "managed-real-checkpoint.pending.json" in workflow
    assert "out/**/*.json" in workflow
    assert "out/**/*.safetensors" not in workflow
    assert "out/**/*.pt" not in workflow

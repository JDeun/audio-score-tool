"""Packaged MT3 inference must use only pinned model weights inside its owner runtime."""
from __future__ import annotations

import hashlib
import json
import stat
import sys
import zipfile
from pathlib import Path

import pytest

from audio_score_tool.config import Settings
from audio_score_tool.managed_components import (
    ComponentArtifact,
    component_status,
    install_component_artifact,
)
from audio_score_tool.managed_tool_resolver import registered_managed_component_root
from audio_score_tool.transcription_engine import (
    MT3InferEngine,
    TranscriptionEngineUnavailable,
)

_TOOLS = {"mt3-infer": "bin/mt3-infer"}


def _install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *,
    model: str = "mr_mt3", with_weights: bool = True,
) -> tuple[Path, Path]:
    component_root = tmp_path / "components"
    archive = tmp_path / "synthetic-mt3-infer.zip"
    members = {"bin/mt3-infer": b"local original synthetic native CLI"}
    if with_weights:
        members[f"checkpoints/{model}/weights.safetensors"] = b"synthetic model checkpoint"
    with zipfile.ZipFile(archive, "w") as output:
        for filename, contents in members.items():
            info = zipfile.ZipInfo(filename)
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o755) << 16
            output.writestr(info, contents)
    artifact = ComponentArtifact(
        component="transcription_engine",
        version="review-v1",
        url="https://example.invalid/synthetic-ci-only.zip",
        sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        archive="zip", tools=_TOOLS,
        license="local synthetic fixture",
        provenance="original test bytes, never third-party model",
    )
    status = install_component_artifact(
        artifact, root=component_root, local_archive=archive,
    )
    assert status["ready"]
    monkeypatch.setenv("AST_PACKAGED", "1")
    monkeypatch.setenv("AST_COMPONENT_DIR", str(component_root))
    monkeypatch.setattr(
        "audio_score_tool.transcription_engine.backend_status",
        lambda _: {"music21": True},
    )
    return component_root, component_root / "installed/transcription_engine/review-v1"


def _engine(model: str = "mr_mt3") -> MT3InferEngine:
    return MT3InferEngine(Settings(
        usage_mode="commercial", transcription_engine="mt3_infer",
        mt3_model=model,
    ))


def test_approved_installed_mr_checkpoint_is_discovered_only_under_its_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    root, installed = _install(tmp_path, monkeypatch)
    engine = _engine()
    assert engine.ready() is True
    assert engine._packaged_checkpoint_root() == installed / "checkpoints"
    assert registered_managed_component_root(
        "transcription_engine", required_tool="mt3-infer",
    ) == installed
    assert component_status("transcription_engine", root=root)["payload_file_count"] == 2


def test_packaged_inference_passes_verified_checkpoint_path_and_forbids_ambient_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    _root, installed = _install(tmp_path, monkeypatch)
    fake_cache = tmp_path / "untrusted-home-model"
    fake_cache.mkdir()
    monkeypatch.setenv("MT3_CHECKPOINT_DIR", str(fake_cache))
    monkeypatch.setenv("HF_HUB_OFFLINE", "0")
    engine = _engine()
    used: list[tuple[str, list, dict]] = []

    def run(command, args, **kwargs):
        used.append((str(command), list(args), dict(kwargs)))
        midi = Path(args[args.index("-o") + 1])
        midi.write_bytes(b"synthetic MIDI after model execution")
        return object()

    def convert(_midi, xml):
        Path(xml).write_text("<synthetic />", encoding="utf-8")

    monkeypatch.setattr("audio_score_tool.transcription_engine.run_command", run)
    monkeypatch.setattr("audio_score_tool.transcription_engine.midi_to_musicxml", convert)
    result = engine.transcribe(tmp_path / "original.wav", tmp_path / "out", device="cpu")
    assert result.midi_path.is_file() and result.musicxml_path.is_file()
    assert len(used) == 1
    command, args, kwargs = used[0]
    assert command == str(installed / "bin/mt3-infer")
    assert args[args.index("-m") + 1] == "mr_mt3"
    env = kwargs["env"]
    assert env["MT3_CHECKPOINT_DIR"] == str(installed / "checkpoints")
    assert env["MT3_CHECKPOINT_DIR"] != str(fake_cache)
    assert env["HF_HUB_OFFLINE"] == "1"
    assert env["TRANSFORMERS_OFFLINE"] == "1"
    assert env["HF_DATASETS_OFFLINE"] == "1"
    assert env["HF_HUB_DISABLE_TELEMETRY"] == "1"


@pytest.mark.parametrize("mode", [
    "no-checkpoints", "wrong-model-only", "empty-weights",
])
def test_packaged_transcription_fails_before_cli_when_model_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str,
):
    root, installed = _install(
        tmp_path, monkeypatch,
        model="yourmt3" if mode == "wrong-model-only" else "mr_mt3",
        with_weights=mode != "no-checkpoints",
    )
    if mode == "empty-weights":
        # Mutating a hashed checkpoint is a separate integrity failure; it
        # must never be treated as a valid local model.
        (installed / "checkpoints/mr_mt3/weights.safetensors").write_bytes(b"")
    monkeypatch.setattr(
        "audio_score_tool.transcription_engine.run_command",
        lambda *_args, **_kw: (_ for _ in ()).throw(
            AssertionError("Missing/unverified checkpoint triggered model CLI")
        ),
    )
    engine = _engine("mr_mt3")
    assert component_status("transcription_engine", root=root)["ready"] is (
        mode != "empty-weights"
    )
    assert engine.ready() is False
    with pytest.raises(TranscriptionEngineUnavailable, match="checkpoint"):
        engine.transcribe(tmp_path / "original.wav", tmp_path / "result", device="cpu")
    assert not (tmp_path / "result").exists()


def test_tampered_managed_checkpoint_blocks_execution_even_when_launcher_is_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    root, installed = _install(tmp_path, monkeypatch)
    engine = _engine()
    assert engine.ready()
    (installed / "checkpoints/mr_mt3/weights.safetensors").write_bytes(b"mutated")
    assert component_status("transcription_engine", root=root)["integrity"] == (
        "payload-digest-mismatch"
    )
    assert engine.ready() is False


def test_nonpackaged_mt3_developer_command_remains_usable(monkeypatch):
    monkeypatch.delenv("AST_PACKAGED", raising=False)
    monkeypatch.setattr(
        "audio_score_tool.transcription_engine.backend_status",
        lambda _: {"music21": True},
    )
    engine = MT3InferEngine(Settings(
        usage_mode="commercial", transcription_engine="mt3_infer",
        mt3_model="mr_mt3", mt3_infer_cmd=sys.executable,
    ))
    assert engine.ready() is True
    assert engine._packaged_checkpoint_root() is None


def test_forged_managed_state_owner_cannot_supply_checkpoint_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    root, _installed = _install(tmp_path, monkeypatch)
    document = root / "state.json"
    state = json.loads(document.read_text())
    state["components"]["transcription_engine"]["root"] = (
        "installed/other-component/review-v1"
    )
    document.write_text(json.dumps(state))
    assert registered_managed_component_root(
        "transcription_engine", required_tool="mt3-infer",
    ) is None
    assert _engine().ready() is False

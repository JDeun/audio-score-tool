"""Private separation validation without downloading or executing model weights."""
from __future__ import annotations

import argparse
import hashlib
import random
import shutil
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import separate_benchmark_stems as separation


def _wav(path: Path, *, frames=4410, rate=44100, channels=2, width=2):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(channels)
        audio.setsampwidth(width)
        audio.setframerate(rate)
        audio.writeframes(b"\x00" * frames * channels * width)
    return path


def _outputs(root: Path, source: Path, model: str, **kwargs):
    return {
        name: _wav(root / model / source.stem / f"{name}.wav", **kwargs)
        for name in separation.STEMS[model]
    }


@pytest.mark.parametrize("model", tuple(separation.STEMS))
def test_validation_keeps_every_stem_including_silent_audio(tmp_path, model):
    source = _wav(tmp_path / "source.with.dots.wav", channels=1)
    root = tmp_path / "separated"
    expected = _outputs(root, source, model)
    paths, receipt = separation._validate_stems(source, root, model, separation._wave_info(source))
    assert paths == expected
    assert set(receipt) == set(separation.STEMS[model])
    assert all(item["frames"] == 4410 and item["duration_seconds"] == 0.1
               for item in receipt.values())
    assert receipt["vocals"]["sha256"] == hashlib.sha256(paths["vocals"].read_bytes()).hexdigest()


@pytest.mark.parametrize("problem", ["missing", "duplicate", "wrong_basename", "empty", "linked"])
def test_refuses_incomplete_ambiguous_or_linked_outputs(tmp_path, problem):
    source = _wav(tmp_path / "source.wav")
    root = tmp_path / "separated"
    paths = _outputs(root, source, "htdemucs_6s")
    if problem == "missing":
        paths["guitar"].unlink()
    elif problem == "duplicate":
        duplicate = root / "unrelated" / "vocals.wav"
        duplicate.parent.mkdir()
        shutil.copyfile(paths["vocals"], duplicate)
    elif problem == "wrong_basename":
        paths["vocals"].parent.rename(paths["vocals"].parent.with_name("unrelated"))
    elif problem == "empty":
        _wav(paths["piano"], frames=0)
    else:
        paths["bass"].unlink()
        paths["bass"].symlink_to(source)
    with pytest.raises(separation.SeparationError):
        separation._validate_stems(source, root, "htdemucs_6s", separation._wave_info(source))


def test_rejects_truncated_pcm_payload(tmp_path):
    source = _wav(tmp_path / "truncated.wav")
    source.write_bytes(source.read_bytes()[:-4])
    with pytest.raises(separation.SeparationError, match="Truncated PCM"):
        separation._wave_info(source)


def test_allows_one_sample_resampling_rounding_but_not_time_shift(tmp_path):
    source = _wav(tmp_path / "source.wav", frames=4801, rate=48000)
    root = tmp_path / "separated"
    paths = _outputs(root, source, "htdemucs", frames=4411)
    _, receipt = separation._validate_stems(source, root, "htdemucs", separation._wave_info(source))
    assert receipt["bass"]["duration_error_output_samples"] == pytest.approx(0.08125)
    _wav(paths["bass"], frames=4413)
    with pytest.raises(separation.SeparationError, match="more than one sample"):
        separation._validate_stems(source, root, "htdemucs", separation._wave_info(source))


@pytest.mark.parametrize("changes", [{"channels": 1}, {"width": 3}, {"rate": 22050}])
def test_refuses_non_product_pcm_output(tmp_path, changes):
    source = _wav(tmp_path / "source.wav")
    root = tmp_path / "separated"
    paths = _outputs(root, source, "htdemucs")
    _wav(paths["vocals"], **changes)
    with pytest.raises(separation.SeparationError, match="PCM16"):
        separation._validate_stems(source, root, "htdemucs", separation._wave_info(source))


def test_refuses_inter_stem_misalignment_even_within_source_tolerance(tmp_path):
    source = _wav(tmp_path / "source.wav")
    root = tmp_path / "separated"
    paths = _outputs(root, source, "htdemucs")
    _wav(paths["bass"], frames=4411)
    with pytest.raises(separation.SeparationError, match="different frame counts"):
        separation._validate_stems(source, root, "htdemucs", separation._wave_info(source))


def test_refuses_existing_output_before_loading_heavy_runtime(tmp_path, monkeypatch):
    source = _wav(tmp_path / "source.wav")
    root = tmp_path / "already-created"
    root.mkdir()
    monkeypatch.setattr(separation, "_load_runtime", lambda: pytest.fail("must not load Demucs"))
    with pytest.raises(separation.SeparationError, match="already exists"):
        separation.run_separation(source, root)


def test_refuses_raw_output_inside_repository(tmp_path, monkeypatch):
    monkeypatch.setattr(separation, "_ROOT", tmp_path / "repo")
    with pytest.raises(separation.SeparationError, match="outside the Git repository"):
        separation._new_private_root(tmp_path / "repo" / "raw")


def test_runtime_version_is_checked_before_heavy_imports(monkeypatch):
    monkeypatch.setattr(separation, "version", lambda _: "4.0.0")
    with pytest.raises(separation.SeparationError, match="Expected demucs==4.0.1"):
        separation._load_runtime()


def _fake_runtime(tmp_path, monkeypatch, model, *, tamper=None, cached=False):
    """Only the Demucs execution is mocked; WAV and checkpoint evidence is real."""
    source = _wav(tmp_path / "source.wav", channels=1)
    torch_home = tmp_path / "torch"
    monkeypatch.setenv("TORCH_HOME", str(torch_home))
    monkeypatch.delenv("TORCH_FORCE_WEIGHTS_ONLY_LOAD", raising=False)
    monkeypatch.delenv("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD", raising=False)
    payload = b"synthetic local test weights, never deserialized"
    digest = hashlib.sha256(payload).hexdigest()
    signature = separation.CHECKPOINTS[model][0]
    filename = f"{signature}-{digest[:8]}.th"
    monkeypatch.setitem(separation.CHECKPOINTS, model, (signature, filename, digest[:8]))
    package = tmp_path / "package" / "demucs"
    remote = package / "remote"
    remote.mkdir(parents=True)
    (remote / f"{model}.yaml").write_text(f"models: ['{signature}']\n", encoding="utf-8")
    (remote / "files.txt").write_text(f"root: hybrid_transformer/\n{filename}\n", encoding="utf-8")
    checkpoint = torch_home / "hub" / "checkpoints" / filename
    if cached:
        checkpoint.parent.mkdir(parents=True)
        checkpoint.write_bytes(payload)
    calls = []

    def get_parser():
        parser = argparse.ArgumentParser()
        parser.add_argument("-n", dest="name")
        parser.add_argument("-d", dest="device")
        parser.add_argument("--shifts", type=int, default=1)
        parser.add_argument("--clip-mode", default="rescale")
        parser.add_argument("--filename", default="{track}/{stem}.{ext}")
        parser.add_argument("-o", type=Path, dest="out")
        parser.add_argument("tracks", type=Path, nargs="+")
        parser.set_defaults(split=True, overlap=0.25, segment=None, jobs=0, stem=None)
        return parser

    def main(args):
        parsed = get_parser().parse_args(args)
        calls.append(("separate", parsed, random.random()))
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        checkpoint.write_bytes(payload)
        # An unrelated cached model must not be reported as used or even hashed.
        (checkpoint.parent / "unrelated.th").write_bytes(b"unrelated")
        _outputs(parsed.out, parsed.tracks[0], parsed.name)
        if tamper:
            tamper(parsed, checkpoint)

    numpy = SimpleNamespace(__version__="test-numpy", random=SimpleNamespace(
        seed=lambda value: calls.append(("numpy_seed", value)),
    ))
    torch = SimpleNamespace(
        __version__="test-torch", hub=SimpleNamespace(get_dir=lambda: str(torch_home / "hub")),
        manual_seed=lambda value: calls.append(("torch_seed", value)),
        cuda=SimpleNamespace(is_available=lambda: True,
                             manual_seed_all=lambda value: calls.append(("cuda_seed", value))),
    )
    separate = SimpleNamespace(__file__=str(package / "separate.py"), get_parser=get_parser, main=main)
    monkeypatch.setattr(separation, "_load_runtime", lambda: (separate, numpy, torch))
    return source, checkpoint, calls, digest


@pytest.mark.parametrize("model", tuple(separation.STEMS))
def test_real_cli_contract_seed_and_source_bound_receipt(tmp_path, monkeypatch, model):
    source, checkpoint, calls, digest = _fake_runtime(tmp_path, monkeypatch, model)
    paths, receipt = separation.run_separation(source, tmp_path / "out", model=model, seed=42)
    assert list(paths) == list(separation.STEMS[model])
    assert calls[:3] == [("numpy_seed", 42), ("torch_seed", 42), ("cuda_seed", 42)]
    _, parsed, random_value = calls[3]
    assert random_value == random.Random(42).random()
    assert parsed.tracks == [source]
    assert parsed.name == model and parsed.device == "cpu"
    assert parsed.shifts == 1 and parsed.clip_mode == "rescale"
    assert parsed.filename == "{track}/{stem}.{ext}"
    assert receipt["input"]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert receipt["checkpoint"]["sha256"] == digest
    assert receipt["checkpoint"]["filename"] == checkpoint.name
    assert receipt["checkpoint"]["cached_before_run"] is False
    assert receipt["checkpoint"]["official_full_sha256_available"] is False
    assert receipt["identity"]["checkpoint_sha256"] == digest
    assert receipt["identity"]["options"]["bits_per_sample"] == 16
    assert receipt["identity"]["options"]["two_stems"] is None
    assert receipt["torch_load_environment"]["modified_by_runner"] is False
    assert receipt["source_media_published"] is False
    assert "unrelated" not in str(receipt)


def test_existing_corrupt_checkpoint_is_refused_before_deserialization(tmp_path, monkeypatch):
    source, checkpoint, calls, _ = _fake_runtime(tmp_path, monkeypatch, "htdemucs", cached=True)
    checkpoint.write_bytes(b"corrupt old cache")
    with pytest.raises(separation.SeparationError, match="official prefix"):
        separation.run_separation(source, tmp_path / "out", model="htdemucs")
    assert not calls
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("tamper_target", ["input", "checkpoint"])
def test_detects_changed_input_or_corrupt_download(tmp_path, monkeypatch, tamper_target):
    def tamper(parsed, checkpoint):
        target = parsed.tracks[0] if tamper_target == "input" else checkpoint
        target.write_bytes(target.read_bytes() + b"changed")

    source, _, _, _ = _fake_runtime(tmp_path, monkeypatch, "htdemucs", tamper=tamper)
    with pytest.raises(separation.SeparationError, match="changed|official prefix"):
        separation.run_separation(source, tmp_path / "out", model="htdemucs")


def test_refuses_forced_weights_only_without_changing_environment(tmp_path, monkeypatch):
    source, _, calls, _ = _fake_runtime(tmp_path, monkeypatch, "htdemucs")
    monkeypatch.setenv("TORCH_FORCE_WEIGHTS_ONLY_LOAD", "1")
    with pytest.raises(separation.SeparationError, match="conflicts"):
        separation.run_separation(source, tmp_path / "out", model="htdemucs")
    assert not calls

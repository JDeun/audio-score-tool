"""Synthetic source-bound experiments; no pretrained inference or downloads."""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
import wave
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import mido
import pytest

from scripts import prepare_cocochorales_official_sample as samples
from scripts import run_cocochorales_stem_ablation as ablation

TRACKS = tuple(samples.SAMPLE_BLOBS)
STEMS = ("drums", "bass", "other", "vocals", "guitar", "piano")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _midi(path: Path, pitches: tuple[int, ...] = (60,)) -> None:
    score = mido.MidiFile(ticks_per_beat=480)
    score.tracks.append(mido.MidiTrack())
    for pitch in pitches:
        score.tracks.append(mido.MidiTrack([
            mido.Message("program_change", channel=0, program=40),
            mido.Message("note_on", channel=0, note=pitch, velocity=80),
            mido.Message("note_off", channel=0, note=pitch, time=480),
        ]))
    score.save(path)


@dataclass
class Source:
    root: Path
    track: str
    audio: Path
    reference: Path
    pairs: dict
    registry: dict
    proof: dict


def _source(tmp_path: Path, track: str) -> Source:
    """Use authored bytes and receipt-shaped fixtures, never claim real source QA."""
    root = tmp_path / "corpus" / track
    folder = root / track
    folder.mkdir(parents=True)
    audio, reference = folder / "mix.wav", folder / "mix.mid"
    with wave.open(str(audio), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes((TRACKS.index(track) + 1).to_bytes(2, "little") * 16000)
    _midi(reference)
    pairs = {"schema_version": 1, "cases": [{
        "id": f"coco-{track}", "recording_id": track,
        "dataset_id": "cocochorales", "split": "train",
        "rights_reviewed": True, "license": "CC-BY-4.0",
        "audio": {"locator": f"private://{track}/mix.wav", "sha256": _sha(audio)},
        "reference_midi": {
            "locator": f"private://{track}/mix.mid", "sha256": _sha(reference),
        },
    }]}
    registry = {"schema_version": 1, "datasets": [{
        "id": "cocochorales", "task": "ensemble_amt", "audio_included": True,
        "status": "verified_for_evaluation", "license": "CC-BY-4.0",
    }]}
    proof = {
        "schema_version": 1, "dataset": "cocochorales", "source_kind": "official-sample-zip",
        "official_source": "https://magenta.tensorflow.org/datasets/cocochorales",
        "official_sample_page": samples.SOURCE_PAGE,
        "source_repository": samples.SOURCE_REPO,
        "source_revision": samples.SOURCE_COMMIT,
        "official_release": samples.SOURCE_RELEASE,
        "official_format_source_commit": samples.SOURCE_FORMAT_COMMIT,
        "official_archive_path": f"{samples.SAMPLE_ROOT}/{track}.zip",
        "archive_git_blob_sha1": samples.SAMPLE_BLOBS[track][0],
        "archive_bytes": samples.SAMPLE_BLOBS[track][1],
        "archive_sha256": "a" * 64, "track_count": 1,
        "operator_rights_reviewed": True, "source_media_published": False,
        "upstream_rights_independently_verified": False,
        "tracks": [{
            "track_id": track, "split": "train", "mix_wav_sha256": _sha(audio),
            "mix_midi_sha256": _sha(reference),
            "instruments": [{"voice": voice, "instrument": "violin", "midi_program": 40}
                            for voice in range(4)],
        }],
    }
    return Source(root, track, audio, reference, pairs, registry, proof)


class Experiment:
    def __init__(self, tmp_path: Path):
        self.root = tmp_path
        self.calls: list[tuple[list, dict]] = []
        self.direct_pitches = (60,)
        # Two copies of the same note must count as two predictions, not one.
        self.stem_pitches = {stem: (60,) if stem in {"guitar", "piano"} else ()
                            for stem in STEMS}
        self.failed_stem: tuple[str, str] | None = None
        self.mutate: Path | None = None

    def infer(self, command: list, **kwargs):
        self.calls.append((command, kwargs))
        audio = Path(command[command.index("transcribe") + 1])
        target = Path(command[command.index("-o") + 1])
        stem = "direct" if audio.name == "mix.wav" else audio.stem
        track = target.parent.parent.name
        if (track, stem) == self.failed_stem:
            return SimpleNamespace(returncode=9)
        if self.mutate is not None:
            self.mutate.write_bytes(self.mutate.read_bytes() + b"changed-during-inference")
            self.mutate = None
        pitches = self.direct_pitches if stem == "direct" else self.stem_pitches[stem]
        _midi(target, pitches)
        return SimpleNamespace(returncode=0)

    def separate(self, audio, output, *, model, device, seed):
        output.mkdir(parents=True)
        stems = {}
        for name in STEMS:
            stem = output / f"{name}.wav"
            shutil.copyfile(audio, stem)
            stems[name] = stem
        identity = {
            "model": model, "demucs_version": "4.0.1", "device": device, "seed": seed,
            "options": {"shifts": 1, "clip_mode": "rescale", "overlap": 0.25},
            "checkpoint_sha256": "34c22ccb" + "a" * 56,
            "runtime": {"torch": "2.7.1+cpu", "torchaudio": "2.7.1+cpu"},
            "package_model": {"yaml_sha256": "b" * 64,
                              "reference_source_revision": "ef66d254cd6d558e207eeff2c4b8d053db2e77dd"},
        }
        return stems, {
            "identity": identity, "input": {"sha256": _sha(audio)},
            "stems": {name: {"sha256": _sha(path)} for name, path in stems.items()},
            "elapsed_seconds": TRACKS.index(audio.parent.name) + 0.25,
            "checkpoint": {"cached_before_run": audio.parent.name != TRACKS[0]},
            "source_media_published": False,
        }

    def run(self, source: Source) -> dict:
        return ablation.run_experiment(
            source.pairs, source.registry, source.proof, corpus_root=source.root,
            work_root=self.root / "work" / source.track, model="mr_mt3",
            checkpoint_root=self.root / "checkpoints", separator="htdemucs_6s",
        )


@pytest.fixture
def experiment(tmp_path, monkeypatch):
    runner = Experiment(tmp_path)
    monkeypatch.setattr(ablation, "model_identity", lambda model, _root: {
        "model": model, "checkpoint_sha256": ablation.mr.CHECKPOINT_SHA256,
        "runtime_versions": {"torch": "2.7.1+cpu", "transformers": "4.57.6"},
    })
    monkeypatch.setattr(ablation.subprocess, "run", runner.infer)
    monkeypatch.setattr(ablation, "run_separation", runner.separate)
    return runner


@pytest.fixture
def reports(tmp_path, experiment):
    return [experiment.run(_source(tmp_path, track)) for track in TRACKS]


def test_all_six_stems_keep_duplicate_notes_and_valid_empty_predictions(tmp_path, experiment):
    source = _source(tmp_path, TRACKS[0])
    report = experiment.run(source)
    row = report["cases"][0]
    assert report["all_cases_complete"] is True
    assert row["audio_sha256"] == _sha(source.audio)
    assert row["reference_midi_sha256"] == _sha(source.reference)
    assert row["direct_mix"]["audio_sha256"] == row["audio_sha256"]
    separated = row["estimated_stems"]
    assert separated["separation"]["input"]["sha256"] == row["audio_sha256"]
    assert set(separated["stems"]) == set(STEMS)
    assert len(experiment.calls) == 7
    assert separated["predicted_note_count"] == 2
    assert separated["stems"]["vocals"]["status"] == "scored"
    assert separated["stems"]["vocals"]["empty_prediction"] is True
    for metric in ablation.METRICS:
        assert row["direct_mix"]["metrics"][metric]["f1"] == 1.0
        assert separated["metrics"][metric]["f1"] == pytest.approx(2 / 3)
        assert separated["metrics"][metric]["precision"] == 0.5
        assert row["stems_minus_mix_f1"][metric] == pytest.approx(-1 / 3)
    assert report["release_quality_approved"] is False


def test_all_empty_midi_outputs_are_complete_measured_zeroes(tmp_path, experiment):
    experiment.direct_pitches = ()
    experiment.stem_pitches = dict.fromkeys(STEMS, ())
    row = experiment.run(_source(tmp_path, TRACKS[0]))["cases"][0]
    assert row["both_scored"] is True
    for arm in ("direct_mix", "estimated_stems"):
        assert row[arm]["status"] == "scored"
        assert row[arm]["predicted_note_count"] == 0
        assert all(row[arm]["metrics"][metric]["f1"] == 0 for metric in ablation.METRICS)


def test_failed_stem_invalidates_whole_arm_and_prevents_partial_macro(tmp_path, experiment):
    experiment.failed_stem = (TRACKS[2], "bass")
    results = [experiment.run(_source(tmp_path, track)) for track in TRACKS]
    row = results[2]["cases"][0]
    separated = row["estimated_stems"]
    assert separated["status"] == "failed"
    assert separated["stems"]["bass"]["status"] == "failed"
    assert separated["stems"]["piano"]["status"] == "scored"
    assert len(experiment.calls) == 28
    assert "metrics" not in separated
    assert row["both_scored"] is False
    assert row["stems_minus_mix_f1"] is None
    combined = ablation.aggregate_reports(results)
    assert len(combined["cases"]) == 4
    assert combined["complete_paired_case_count"] == 3
    assert combined["all_cases_complete"] is False
    assert combined["macro_f1"] is None
    assert combined["macro_stems_minus_mix_f1"] is None


@pytest.mark.parametrize("changed", [
    "audio-hash", "reference-hash", "proof-audio", "proof-reference", "source-revision", "split",
])
def test_mismatched_original_or_reference_proof_fails_before_inference(
    tmp_path, experiment, changed,
):
    source = _source(tmp_path, TRACKS[0])
    case = source.pairs["cases"][0]
    if changed == "audio-hash":
        case["audio"]["sha256"] = "0" * 64
    elif changed == "reference-hash":
        case["reference_midi"]["sha256"] = "0" * 64
    elif changed == "proof-audio":
        source.proof["tracks"][0]["mix_wav_sha256"] = "0" * 64
    elif changed == "proof-reference":
        source.proof["tracks"][0]["mix_midi_sha256"] = "0" * 64
    elif changed == "source-revision":
        source.proof["source_revision"] = "0" * 40
    else:
        case["split"] = "test"
    with pytest.raises(ValueError):
        experiment.run(source)
    assert not experiment.calls
    assert not (tmp_path / "work").exists()


@pytest.mark.parametrize("asset", ["audio", "reference"])
def test_original_changes_during_inference_cannot_produce_a_completed_report(
    tmp_path, experiment, asset,
):
    source = _source(tmp_path, TRACKS[0])
    experiment.mutate = getattr(source, asset)
    with pytest.raises(ValueError, match="Original audio/reference changed"):
        experiment.run(source)


def test_four_distinct_tracks_keep_per_case_source_proofs_and_unbiased_macro(reports):
    # Runtime/cache history and the input bytes differ between tracks. These
    # are observations, not reasons to merge only a successful subset.
    assert len({report["cases"][0]["audio_sha256"] for report in reports}) == 4
    result = ablation.aggregate_reports(reports)
    assert result["all_cases_complete"] is True
    assert result["complete_paired_case_count"] == 4
    assert {row["track_id"] for row in result["cases"]} == set(TRACKS)
    for row, original in zip(result["cases"], reports, strict=True):
        assert row["source_proof_sha256"] == original["source_proof_sha256"]
        assert row["paired_fingerprint"] == original["paired_fingerprint"]
    for metric in ablation.METRICS:
        assert result["macro_f1"]["direct_mix"][metric] == 1.0
        assert result["macro_f1"]["estimated_stems"][metric] == pytest.approx(2 / 3)
    assert result["heldout_generalization_measured"] is False


@pytest.mark.parametrize("change", ["missing", "duplicate", "extra"])
def test_aggregate_requires_exactly_four_distinct_planned_tracks(reports, change):
    if change == "missing":
        reports.pop()
    elif change == "duplicate":
        reports[-1] = copy.deepcopy(reports[0])
    else:
        reports.append(copy.deepcopy(reports[0]))
    with pytest.raises(ValueError, match="all four distinct"):
        ablation.aggregate_reports(reports)


@pytest.mark.parametrize("change", [
    "amt-model", "amt-checkpoint", "amt-runtime", "separator-name", "separator-options",
    "separator-checkpoint", "separator-runtime", "separator-package", "metric-method",
])
def test_aggregate_rejects_different_model_runtime_separator_and_scoring_conditions(reports, change):
    changed = reports[-1]
    identity = changed["cases"][0]["estimated_stems"]["separation"]["identity"]
    if change == "amt-model":
        changed["model_identity"]["model"] = "yourmt3"
    elif change == "amt-checkpoint":
        changed["model_identity"]["checkpoint_sha256"] = "c" * 64
    elif change == "amt-runtime":
        changed["model_identity"]["runtime_versions"]["torch"] = "2.8.0"
    elif change == "separator-name":
        changed["separator"] = "htdemucs"
    elif change == "separator-options":
        identity["options"]["shifts"] = 10
    elif change == "separator-checkpoint":
        identity["checkpoint_sha256"] = "c" * 64
    elif change == "separator-runtime":
        identity["runtime"]["torch"] = "2.8.0"
    elif change == "separator-package":
        identity["package_model"]["yaml_sha256"] = "c" * 64
    else:
        changed["evaluation_method"] = "greedy-matching"
    with pytest.raises(ValueError, match="different"):
        ablation.aggregate_reports(reports)


def test_aggregate_rejects_forged_completion_flag(reports):
    reports[-1]["cases"][0]["estimated_stems"]["status"] = "failed"
    with pytest.raises(ValueError, match="completion flag"):
        ablation.aggregate_reports(reports)


@pytest.mark.parametrize("model", ["mr_mt3", "yourmt3"])
def test_raw_bridge_uses_pinned_offline_flags_and_accepts_empty_midi(tmp_path, experiment, model):
    source = _source(tmp_path, TRACKS[0])
    experiment.direct_pitches = ()
    output = tmp_path / "raw-prediction"
    checkpoint_root = tmp_path / "checkpoints"
    notes, receipt = ablation.infer_raw_midi(
        source.audio, output, model=model, checkpoint_root=checkpoint_root, device="cpu",
    )
    assert notes == []
    assert receipt["status"] == "scored"
    assert receipt["empty_prediction"] is True
    command, options = experiment.calls[0]
    assert command[:2] == [sys.executable, "-c"]
    assert "from audio_score_tool.mt3_program_midi import main;raise SystemExit(main())" in command[2]
    for setup in ("random.seed(0)", "numpy.random.seed(0)", "torch.manual_seed(0)",
                  "torch.set_num_threads(2)"):
        assert setup in command[2]
    assert command[3:] == [
        "transcribe", str(source.audio), "-o", str(output / "prediction.mid"),
        "-m", model, "--device", "cpu", "--no-download",
    ]
    environment = options["env"]
    assert environment["MT3_CHECKPOINT_DIR"] == str(checkpoint_root.resolve())
    for flag in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE"):
        assert environment[flag] == "1"
    assert environment["PYTHONHASHSEED"] == "0"
    assert environment["OMP_NUM_THREADS"] == environment["MKL_NUM_THREADS"] == "2"
    assert receipt["audio_sha256"] == _sha(source.audio)
    assert receipt["prediction_midi_sha256"] == _sha(output / "prediction.mid")


@pytest.mark.parametrize("model", ["mr_mt3", "yourmt3"])
def test_model_identity_rejects_changed_checkpoint_bytes_and_runtime(tmp_path, monkeypatch, model):
    publisher = ablation.mr if model == "mr_mt3" else ablation.your
    relative = (Path("mr_mt3") / publisher.CHECKPOINT_NAME if model == "mr_mt3"
                else Path("yourmt3") / publisher.MODEL_VARIANT / "last.ckpt")
    checkpoint = tmp_path / relative
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(b"synthetic-checkpoint-never-unpickled")
    monkeypatch.setattr(publisher, "CHECKPOINT_SHA256", _sha(checkpoint))
    versions = {
        "mt3-infer": "0.2.0", "torch": "2.7.1+cpu", "torchaudio": "2.7.1+cpu",
        "transformers": "4.57.6" if model == "mr_mt3" else "4.44.2", "demucs": "4.0.1",
    }
    monkeypatch.setattr(ablation, "version", versions.__getitem__)
    assert ablation.model_identity(model, tmp_path)["checkpoint_sha256"] == _sha(checkpoint)
    versions["transformers"] = "4.99.0"
    with pytest.raises(ValueError, match="pinned model runtimes"):
        ablation.model_identity(model, tmp_path)
    versions["transformers"] = "4.57.6" if model == "mr_mt3" else "4.44.2"
    checkpoint.write_bytes(b"different-checkpoint")
    with pytest.raises(ValueError, match="pinned model"):
        ablation.model_identity(model, tmp_path)


def test_failed_experiment_cli_writes_all_case_evidence_and_returns_failure(
    tmp_path, monkeypatch, reports,
):
    failed = reports[-1]["cases"][0]
    failed["estimated_stems"]["status"] = "failed"
    failed["estimated_stems"].pop("metrics")
    failed["both_scored"] = False
    failed["stems_minus_mix_f1"] = None
    paths = []
    for number, report in enumerate(reports):
        path = tmp_path / f"case-{number}.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        paths.append(str(path))
    output = tmp_path / "aggregate.json"
    monkeypatch.setattr(sys, "argv", ["ablation", "--aggregate", *paths, "--output", str(output)])
    assert ablation.main() == 1
    result = json.loads(output.read_text(encoding="utf-8"))
    assert len(result["cases"]) == 4
    assert result["macro_f1"] is None

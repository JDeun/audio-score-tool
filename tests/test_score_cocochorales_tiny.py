"""Synthetic-only paired CocoChorales scoring: no external dataset or weights."""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import wave
from pathlib import Path

import mido
import pytest

from scripts import score_cocochorales_tiny as scoring
from scripts.validate_tier2_dataset_pairs import validate_pairs


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_midi(path: Path, *, offset_ticks: int = 480, program: int = 40) -> None:
    score = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    score.tracks.append(track)
    track.append(mido.Message("program_change", channel=0, program=program, time=0))
    track.append(mido.Message("note_on", channel=0, note=60, velocity=80, time=0))
    track.append(mido.Message("note_off", channel=0, note=60, velocity=0, time=offset_ticks))
    score.save(str(path))


def _fixture(tmp_path: Path) -> tuple[dict, dict, dict, Path, Path]:
    root = tmp_path / "owned-private-source"
    track = root / "string_track000001"
    track.mkdir(parents=True)
    audio = track / "mix.wav"
    with wave.open(str(audio), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0\0" * 16000 * 2)
    reference = track / "mix.mid"
    _write_midi(reference)
    case_id = "coco-string_track000001"
    pairs = {
        "schema_version": 1,
        "cases": [{
            "id": case_id,
            "dataset_id": "cocochorales",
            "recording_id": "string_track000001",
            "split": "train",
            "rights_reviewed": True,
            "license": "CC-BY-4.0",
            "audio": {
                "locator": "private://string_track000001/mix.wav",
                "sha256": _sha(audio),
            },
            "reference_midi": {
                "locator": "private://string_track000001/mix.mid",
                "sha256": _sha(reference),
            },
        }],
    }
    registry = {"schema_version": 1, "datasets": [{
        "id": "cocochorales", "task": "ensemble_amt",
        "source": "https://magenta.tensorflow.org/datasets/cocochorales",
        "license": "CC-BY-4.0", "audio_included": True,
        "status": "verified_for_evaluation",
    }]}
    source = {
        "schema_version": 1, "dataset": "cocochorales",
        "official_release": "cocochorales_full_v1_zipped",
        "official_format_source_commit": "4647edbce6719fe907e17fcc072651def168eaa5",
        "official_shard": "main_dataset/train/1.tar.bz2",
        "official_published_md5_verified": True,
        "archive_md5": scoring._OFFICIAL_MD5["train"],
        "archive_sha256": "b" * 64,
        "operator_rights_reviewed": True,
        "source_media_published": False,
        "upstream_rights_independently_verified": False,
        "tracks": [{
            "track_id": "string_track000001", "split": "train",
            "mix_wav_sha256": _sha(audio),
            "mix_midi_sha256": _sha(reference),
            "instruments": [
                {"voice": i, "instrument": "violin", "midi_program": 40}
                for i in range(4)
            ],
        }],
    }
    predictions = tmp_path / "private-model-predictions"
    predictions.mkdir()
    shutil.copyfile(reference, predictions / f"{case_id}.mid")
    (predictions / f"{case_id}.musicxml").write_text(
        '<score-partwise version="4.0"><part-list>'
        '<score-part id="P1"><part-name>Violin</part-name></score-part>'
        '</part-list><part id="P1"><measure number="1">'
        '<note><pitch><step>C</step><octave>4</octave></pitch>'
        '<duration>480</duration></note></measure></part></score-partwise>',
        encoding="utf-8",
    )
    _verified, manifest = validate_pairs(pairs, registry, corpus_root=root)
    (predictions / "tier2-prediction-provenance.json").write_text(
        json.dumps({
            "schema_version": "1",
            "corpus_version": manifest["corpus_version"],
            "engine": {
                "id": "mt3_infer", "model_revision": "checkpoint-revision",
                "runtime_revision": "runtime-1", "artifact_sha256": "a" * 64,
            },
            "case_ids": [case_id], "device": "cpu",
            "case_inference_seconds": {case_id: 1.25},
            "peak_memory_bytes_measured": False,
        }),
        encoding="utf-8",
    )
    return pairs, registry, source, root, predictions


def _score(pair, registry, source, root, predictions) -> dict:
    return scoring.score_cocochorales(
        pair, registry, source,
        corpus_root=root, predictions_root=predictions,
    )


def test_identical_original_midi_predictions_reach_perfect_onset_offset_f1(tmp_path):
    p, registry, source, root, predictions = _fixture(tmp_path)
    result = _score(p, registry, source, root, predictions)
    assert result["case_count"] == 1
    assert result["scored_case_count"] == 1
    case = result["cases"][0]
    assert case["status"] == "scored"
    assert case["note_onset_f1"] == pytest.approx(1.0)
    assert case["note_onset_offset_f1"] == pytest.approx(1.0)
    assert case["instrument_onset_offset_f1"] == pytest.approx(1.0)
    assert case["matched_onset_offset_notes"] == 1
    assert case["musicxml"] == {"parts": 1, "notes": 1}
    assert case["model_inference_seconds"] == 1.25
    assert case["peak_memory_measured"] is False
    assert case["human_publish_time_seconds"] is None
    assert result["release_quality_approved"] is False
    assert result["source_media_published"] is False
    assert str(root) not in json.dumps(result)


def test_offset_and_instrument_scores_are_independent_of_onset_f1(tmp_path):
    p, registry, source, root, predictions = _fixture(tmp_path)
    midi = predictions / "coco-string_track000001.mid"
    _write_midi(midi, offset_ticks=960)
    result = _score(p, registry, source, root, predictions)["cases"][0]
    assert result["note_onset_f1"] == pytest.approx(1)
    assert result["note_onset_offset_f1"] == pytest.approx(0)
    assert result["instrument_onset_offset_f1"] == pytest.approx(0)

    _write_midi(midi, program=56)
    result = _score(p, registry, source, root, predictions)["cases"][0]
    assert result["note_onset_f1"] == pytest.approx(1)
    assert result["note_onset_offset_f1"] == pytest.approx(1)
    assert result["instrument_onset_offset_f1"] == pytest.approx(0)


@pytest.mark.parametrize("kind", [
    "wrong-audio-sha", "wrong-midi-sha", "unreviewed-rights",
    "unreviewed-registry", "fake-source-md5", "wrong-source-commit",
    "wrong-model-case-id", "wrong-corpus", "missing-model-proof",
])
def test_missing_rights_source_or_exact_corpus_identity_blocks_scoring(tmp_path, kind):
    p, registry, source, root, predictions = _fixture(tmp_path)
    prov = predictions / "tier2-prediction-provenance.json"
    if kind == "wrong-audio-sha":
        p["cases"][0]["audio"]["sha256"] = "c" * 64
    elif kind == "wrong-midi-sha":
        source["tracks"][0]["mix_midi_sha256"] = "c" * 64
    elif kind == "unreviewed-rights":
        p["cases"][0]["rights_reviewed"] = False
    elif kind == "unreviewed-registry":
        registry["datasets"][0]["status"] = "planned"
    elif kind == "fake-source-md5":
        source["archive_md5"] = "d" * 32
    elif kind == "wrong-source-commit":
        source["official_format_source_commit"] = "0" * 40
    elif kind == "wrong-model-case-id":
        data = json.loads(prov.read_text())
        data["case_ids"] = ["another-case"]
        prov.write_text(json.dumps(data))
    elif kind == "wrong-corpus":
        data = json.loads(prov.read_text())
        data["corpus_version"] = "wrong"
        prov.write_text(json.dumps(data))
    else:
        prov.unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        _score(p, registry, source, root, predictions)


def test_bad_or_missing_musicxml_is_not_a_successful_prediction(tmp_path):
    p, registry, source, root, predictions = _fixture(tmp_path)
    xml = predictions / "coco-string_track000001.musicxml"
    xml.write_text("<invalid-xml/>", encoding="utf-8")
    result = _score(p, registry, source, root, predictions)
    assert result["scored_case_count"] == 0
    assert result["cases"][0]["failure_reason"] == "invalid-prediction-midi-or-musicxml"
    xml.unlink()
    result = _score(p, registry, source, root, predictions)
    assert result["cases"][0]["failure_reason"] == "prediction-artifact-missing-or-linked"


def test_untrusted_or_unmeasured_latency_claim_fails_closed(tmp_path):
    p, registry, source, root, predictions = _fixture(tmp_path)
    prov = predictions / "tier2-prediction-provenance.json"
    data = json.loads(prov.read_text())
    data["case_inference_seconds"] = {"another-case": 2}
    prov.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="inference time"):
        _score(p, registry, source, root, predictions)


def test_more_than_four_original_pairs_are_scored_without_silent_truncation(tmp_path):
    p, registry, source, root, predictions = _fixture(tmp_path)
    original = p["cases"][0]
    original_source = source["tracks"][0]
    original_id = original["id"]
    for number in range(2, 8):
        name = f"string_track{number:06d}"
        case_id = f"coco-{name}"
        folder = root / name
        folder.mkdir()
        for filename in ("mix.wav", "mix.mid"):
            shutil.copy2(root / "string_track000001" / filename, folder / filename)
        case = copy.deepcopy(original)
        case["id"] = case_id
        case["recording_id"] = name
        case["audio"]["locator"] = f"private://{name}/mix.wav"
        case["reference_midi"]["locator"] = f"private://{name}/mix.mid"
        p["cases"].append(case)
        track = copy.deepcopy(original_source)
        track["track_id"] = name
        source["tracks"].append(track)
        for suffix in ("mid", "musicxml"):
            shutil.copy2(
                predictions / f"{original_id}.{suffix}",
                predictions / f"{case_id}.{suffix}",
            )
    provenance = predictions / "tier2-prediction-provenance.json"
    payload = json.loads(provenance.read_text(encoding="utf-8"))
    payload["case_ids"] = [case["id"] for case in p["cases"]]
    payload["case_inference_seconds"] = {case_id: 1.25 for case_id in payload["case_ids"]}
    provenance.write_text(json.dumps(payload), encoding="utf-8")
    report = _score(p, registry, source, root, predictions)
    assert report["case_count"] == 7
    assert report["scored_case_count"] == 7
    assert all(case["note_onset_offset_f1"] == 1 for case in report["cases"])
    assert report["release_quality_approved"] is False

"""Official tiny CocoChorales archive integrity and private extraction contracts.

All fixtures are originally generated WAV/MIDI/YAML. No real source archive is
downloaded or copied into CI artifacts.
"""
from __future__ import annotations

import hashlib
import io
import json
import tarfile
import wave
from pathlib import Path

import mido
import pytest

from scripts import extract_cocochorales_tiny as extraction
from scripts.prepare_cocochorales_pairs import prepare_pairs


def _audio() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as recorder:
        recorder.setnchannels(1)
        recorder.setsampwidth(2)
        recorder.setframerate(16000)
        recorder.writeframes(b"\x00\x00" * 16000 * 2)
    return output.getvalue()


def _midi() -> bytes:
    document = mido.MidiFile(ticks_per_beat=480)
    voice = mido.MidiTrack()
    document.tracks.append(voice)
    voice.extend([
        mido.Message("program_change", channel=0, program=40, time=0),
        mido.Message("note_on", channel=0, note=60, velocity=90, time=0),
        mido.Message("note_off", channel=0, note=60, velocity=0, time=480),
    ])
    output = io.BytesIO()
    document.save(file=output)
    return output.getvalue()


def _payloads():
    return {
        "mix.wav": _audio(),
        "mix.mid": _midi(),
        "metadata.yaml": (
            b"ensemble: string\ninstrument_name:\n"
            b"  0: violin\n  1: violin\n  2: viola\n  3: cello\n"
            b"midi_program_number:\n"
            b"  0: 40\n  1: 40\n  2: 41\n  3: 42\n"
        ),
    }


def _fixture(tmp_path: Path, monkeypatch, *, tamper=None, track_count=1):
    selection = {
        "schema_version": 1,
        "dataset_id": "cocochorales",
        "official_source": "https://magenta.tensorflow.org/datasets/cocochorales",
        "source_release_revision": "cocochorales_full_v1_zipped",
        "license": "CC-BY-4.0",
        "rights_reviewed": True,
        "tracks": [
            {"track_id": f"string_track{number:06d}", "split": "train"}
            for number in range(1, track_count + 1)
        ],
    }
    archive = tmp_path / "1.tar.bz2"
    members = [
        (f"string_track{number:06d}/{filename}", contents)
        for number in range(1, track_count + 1)
        for filename, contents in _payloads().items()
    ]
    if tamper == "missing":
        members.pop()
    if tamper == "path-traversal":
        members.append(("../outside.wav", b"unexpected"))
    if tamper == "duplicate":
        members.append(members[0])
    with tarfile.open(archive, "w:bz2") as output:
        for name, contents in members:
            info = tarfile.TarInfo(name)
            info.size = len(contents)
            output.addfile(info, io.BytesIO(contents))
    monkeypatch.setitem(
        extraction._OFFICIAL_MD5,
        "train",
        hashlib.md5(archive.read_bytes()).hexdigest(),
    )
    return archive, selection


def test_verified_official_archive_extracts_one_pair_only_and_no_stems(tmp_path, monkeypatch):
    archive, selection = _fixture(tmp_path, monkeypatch)
    destination = tmp_path / "owned-private-pairs"
    report = extraction.extract_official_shard(archive, selection, output_root=destination)
    assert report["archive_sha256"] == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert report["official_published_md5_verified"] is True
    assert report["official_format_source_commit"] == "4647edbce6719fe907e17fcc072651def168eaa5"
    assert report["audio_midi_file_count"] == 2
    assert report["model_inference_performed"] is False
    assert report["source_media_published"] is False
    assert report["upstream_rights_independently_verified"] is False
    paths = sorted(p.relative_to(destination).as_posix() for p in destination.rglob("*") if p.is_file())
    assert paths == [
        "string_track000001/metadata.yaml",
        "string_track000001/mix.mid",
        "string_track000001/mix.wav",
    ]
    pair, audit = prepare_pairs(selection, corpus_root=destination)
    assert pair["cases"][0]["split"] == "train"
    assert audit["tracks"][0]["instruments"][3]["instrument"] == "cello"
    assert not list(tmp_path.glob(".coco-tiny-*"))
    assert str(tmp_path) not in json.dumps(report)


def test_archive_md5_mismatch_is_rejected_before_extraction(tmp_path, monkeypatch):
    archive, selection = _fixture(tmp_path, monkeypatch)
    monkeypatch.setitem(extraction._OFFICIAL_MD5, "train", "f" * 32)
    destination = tmp_path / "private"
    with pytest.raises(ValueError, match="published source"):
        extraction.extract_official_shard(archive, selection, output_root=destination)
    assert not destination.exists()


@pytest.mark.parametrize("tamper", ["missing", "duplicate", "path-traversal"])
def test_corrupt_or_missing_archive_members_never_expose_partial_media(tmp_path, monkeypatch, tamper):
    archive, selection = _fixture(tmp_path, monkeypatch, tamper=tamper)
    destination = tmp_path / "private"
    with pytest.raises(ValueError, match="unsafe|duplicate|lacks"):
        extraction.extract_official_shard(archive, selection, output_root=destination)
    assert not destination.exists()
    assert not (tmp_path / "outside.wav").exists()


@pytest.mark.parametrize("change", [
    {"rights_reviewed": False},
    {"license": "CC-BY-NC-4.0"},
    {"source_release_revision": "HuggingFace-mirror"},
    {"tracks": [{"track_id": "string_track000001", "split": "test"}]},
    {"tracks": [{"track_id": "string_track000001", "split": "train"}] * 2},
    {"tracks": []},
])
def test_invalid_source_attestation_or_split_fails(tmp_path, monkeypatch, change):
    archive, selection = _fixture(tmp_path, monkeypatch)
    selection.update(change)
    destination = tmp_path / "private"
    with pytest.raises(ValueError, match="source|rights|track|license|at least"):
        extraction.extract_official_shard(archive, selection, output_root=destination)
    assert not destination.exists()


def test_never_overwrites_existing_private_root(tmp_path, monkeypatch):
    archive, selection = _fixture(tmp_path, monkeypatch)
    destination = tmp_path / "private"
    destination.mkdir()
    existing = destination / "keep"
    existing.write_text("unchanged")
    with pytest.raises(ValueError, match="new private"):
        extraction.extract_official_shard(archive, selection, output_root=destination)
    assert existing.read_text() == "unchanged"


def test_metadata_only_cli_no_overwrite(tmp_path, monkeypatch, capsys):
    archive, selection = _fixture(tmp_path, monkeypatch)
    plan = tmp_path / "selection.json"
    plan.write_text(json.dumps(selection))
    report = tmp_path / "source-proof.pending.json"
    destination = tmp_path / "private"
    monkeypatch.setattr("sys.argv", [
        "extract_cocochorales_tiny.py",
        "--archive", str(archive), "--selection", str(plan),
        "--output-root", str(destination), "--report", str(report),
    ])
    assert extraction.main() == 0
    assert json.loads(report.read_text())["track_count"] == 1
    assert "source_sha256" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        extraction.main()
    assert report.is_file()


def test_six_official_pairs_extract_without_any_media_count_cap(tmp_path, monkeypatch):
    archive, selection = _fixture(tmp_path, monkeypatch, track_count=6)
    target = tmp_path / "many-private-tracks"
    proof = extraction.extract_official_shard(archive, selection, output_root=target)
    assert proof["track_count"] == 6
    assert proof["audio_midi_file_count"] == 12
    assert proof["selected_file_count"] == 18
    assert proof["selected_uncompressed_bytes"] > 0
    assert len(proof["tracks"]) == 6
    assert len(list(target.glob("*/mix.wav"))) == 6
    assert len(list(target.glob("*/mix.mid"))) == 6


def test_total_selected_extraction_byte_budget_blocks_compression_bombs(tmp_path, monkeypatch):
    archive, selection = _fixture(tmp_path, monkeypatch, track_count=6)
    monkeypatch.setattr(extraction, "_MAX_EXTRACTED_BYTES", 100)
    target = tmp_path / "refused-private-output"
    with pytest.raises(ValueError, match="total extraction budget"):
        extraction.extract_official_shard(archive, selection, output_root=target)
    assert not target.exists()
    assert not list(tmp_path.glob(".coco-tiny-*"))

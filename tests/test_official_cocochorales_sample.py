"""Private official sample ZIP contract; all media generated here, no download."""
from __future__ import annotations

import hashlib
import io
import json
import stat
import wave
import zipfile
from pathlib import Path

import mido
import pytest

from scripts import prepare_cocochorales_official_sample as sample
from scripts.score_cocochorales_tiny import score_cocochorales


def _wav() -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\0\0" * (16000 * 2))
    return out.getvalue()


def _midi() -> bytes:
    score = mido.MidiFile(ticks_per_beat=480)
    notes = mido.MidiTrack()
    notes.extend([
        mido.Message("program_change", channel=0, program=40, time=0),
        mido.Message("note_on", channel=0, note=60, velocity=85, time=0),
        mido.Message("note_off", channel=0, note=60, velocity=0, time=480),
    ])
    score.tracks.append(notes)
    out = io.BytesIO()
    score.save(file=out)
    return out.getvalue()


def _zip(tmp_path: Path, monkeypatch, *, change=None) -> Path:
    track = "string_track001010"
    path = tmp_path / f"{track}.zip"
    members = {
        f"{track}/mix.wav": _wav(),
        f"{track}/mix.mid": _midi(),
        f"{track}/metadata.yaml": (
            b"ensemble: string\ninstrument_name:\n"
            b"  0: violin\n  1: violin\n  2: viola\n  3: cello\n"
            b"midi_program_number:\n"
            b"  0: 40\n  1: 40\n  2: 41\n  3: 42\n"
        ),
    }
    if change == "missing":
        members.pop(f"{track}/mix.mid")
    if change == "traversal":
        members["../outside"] = b"escaped"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as writer:
        for name, contents in members.items():
            writer.writestr(name, contents)
        if change == "symlink":
            info = zipfile.ZipInfo(f"{track}/evil-link")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            writer.writestr(info, b"../../outside")
    length = path.stat().st_size
    sha = hashlib.sha1(f"blob {length}\0".encode())
    sha.update(path.read_bytes())
    monkeypatch.setitem(sample.SAMPLE_BLOBS, track, (sha.hexdigest(), length))
    return path


def test_exact_official_zip_prepares_private_pair_and_benchmark_manifest(tmp_path, monkeypatch):
    asset = _zip(tmp_path, monkeypatch)
    corpus, metadata = tmp_path / "private-corpus", tmp_path / "private-report"
    report = sample.prepare_official_sample(
        asset, "string_track001010", corpus_root=corpus, metadata_root=metadata,
    )
    assert report["track_count"] == 1
    assert report["source_kind"] == "official-sample-zip"
    assert report["archive_sha256"] == hashlib.sha256(asset.read_bytes()).hexdigest()
    assert report["source_revision"] == sample.SOURCE_COMMIT
    assert report["operator_rights_reviewed"] is True
    assert report["upstream_rights_independently_verified"] is False
    assert report["source_media_published"] is False
    assert report["selected_uncompressed_bytes"] > 0
    assert sorted(p.relative_to(corpus).as_posix() for p in corpus.rglob("*") if p.is_file()) == [
        "string_track001010/metadata.yaml",
        "string_track001010/mix.mid",
        "string_track001010/mix.wav",
    ]
    pairs = json.loads((metadata / "pairs.json").read_text(encoding="utf-8"))
    registry = json.loads((metadata / "reviewed-registry.json").read_text(encoding="utf-8"))
    manifest = json.loads((metadata / "tier2-manifest.json").read_text(encoding="utf-8"))
    assert pairs["cases"][0]["recording_id"] == "string_track001010"
    assert pairs["cases"][0]["split"] == "train"
    assert registry["datasets"][0]["evaluation_scope"].startswith("official pinned")
    assert len(manifest["cases"]) == 1
    assert str(tmp_path) not in json.dumps(report)


@pytest.mark.parametrize("change", ["missing", "traversal", "symlink"])
def test_unsafe_zip_or_missing_original_reference_fails_without_media(tmp_path, monkeypatch, change):
    asset = _zip(tmp_path, monkeypatch, change=change)
    target = tmp_path / "private-corpus"
    with pytest.raises(ValueError, match="unsafe|symlink|include original"):
        sample.prepare_official_sample(
            asset, "string_track001010",
            corpus_root=target, metadata_root=tmp_path / "private-report",
        )
    assert not target.exists()


def test_modified_official_blob_refused_before_extraction(tmp_path, monkeypatch):
    asset = _zip(tmp_path, monkeypatch)
    monkeypatch.setitem(sample.SAMPLE_BLOBS, "string_track001010", ("f" * 40, asset.stat().st_size))
    with pytest.raises(ValueError, match="pinned upstream Git blob"):
        sample.prepare_official_sample(
            asset, "string_track001010",
            corpus_root=tmp_path / "private-corpus",
            metadata_root=tmp_path / "private-report",
        )


def test_existing_or_repository_media_location_cannot_be_overwritten(tmp_path, monkeypatch):
    asset = _zip(tmp_path, monkeypatch)
    (tmp_path / "private-corpus").mkdir()
    with pytest.raises(ValueError, match="new private"):
        sample.prepare_official_sample(
            asset, "string_track001010", corpus_root=tmp_path / "private-corpus",
            metadata_root=tmp_path / "private-report",
        )
    with pytest.raises(ValueError, match="new private"):
        sample.prepare_official_sample(
            asset, "string_track001010", corpus_root=sample._ROOT / "private-corpus",
            metadata_root=tmp_path / "private-report",
        )


def test_real_sample_source_proof_is_consumable_by_existing_note_scorer(
    tmp_path, monkeypatch,
):
    asset = _zip(tmp_path, monkeypatch)
    corpus, metadata = tmp_path / "private-corpus", tmp_path / "private-report"
    proof = sample.prepare_official_sample(
        asset, "string_track001010", corpus_root=corpus, metadata_root=metadata,
    )
    pairs = json.loads((metadata / "pairs.json").read_text())
    registry = json.loads((metadata / "reviewed-registry.json").read_text())
    manifest = json.loads((metadata / "tier2-manifest.json").read_text())
    predicted = tmp_path / "private-predictions"
    predicted.mkdir()
    case = pairs["cases"][0]["id"]
    (predicted / f"{case}.mid").write_bytes((corpus / "string_track001010/mix.mid").read_bytes())
    (predicted / f"{case}.musicxml").write_text(
        '<score-partwise version="4.0"><part id="P1"><measure number="1">'
        '<note><pitch><step>C</step><octave>4</octave></pitch><duration>480</duration></note>'
        '</measure></part></score-partwise>',
        encoding="utf-8",
    )
    (predicted / "tier2-prediction-provenance.json").write_text(json.dumps({
        "schema_version": "1", "corpus_version": manifest["corpus_version"],
        "case_ids": [case],
        "engine": {
            "id": "mt3_infer", "model_revision": "sha256:" + "b" * 64,
            "runtime_revision": "synthetic-runtime", "artifact_sha256": "b" * 64,
        },
        "case_inference_seconds": {case: 1.3},
    }), encoding="utf-8")
    report = score_cocochorales(
        pairs, registry, proof, corpus_root=corpus, predictions_root=predicted,
    )
    assert report["scored_case_count"] == 1
    assert report["cases"][0]["note_onset_offset_f1"] == pytest.approx(1.0)
    assert report["cases"][0]["instrument_onset_offset_f1"] == pytest.approx(1.0)
    assert report["release_quality_approved"] is False

    proof["source_revision"] = "mutable-main"
    with pytest.raises(ValueError, match="sample archive provenance"):
        score_cocochorales(
            pairs, registry, proof, corpus_root=corpus, predictions_root=predicted,
        )


def test_real_measurement_workflow_never_uploads_original_media():
    source = (
        Path(__file__).resolve().parents[1]
        / ".github/workflows/cocochorales-real-mt3-benchmark.yml"
    ).read_text(encoding="utf-8")
    assert "scripts.prepare_cocochorales_official_sample" in source
    assert "scripts.generate_tier2_predictions" in source
    assert "scripts.score_cocochorales_tiny" in source
    assert "scripts.fetch_pinned_mrmt3_checkpoint" in source
    assert sample.SOURCE_COMMIT in source
    uploaded = source.split("name: Upload metadata only", 1)[1]
    assert "mt3-real-score.pending.json" in uploaded
    assert ".zip" not in uploaded
    assert ".wav" not in uploaded
    assert ".mid" not in uploaded
    assert ".musicxml" not in uploaded
    assert ".pth" not in uploaded

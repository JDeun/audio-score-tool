from __future__ import annotations

import hashlib
import json
import shutil

import pytest

from audio_score_tool import model_evidence as evidence
from audio_score_tool import song_store_v2
from audio_score_tool.song_store_v2 import SongStoreV2

XML = '<score-partwise><part-list/><part id="P1"><measure number="1"/></part></score-partwise>'


@pytest.fixture
def case(tmp_path, monkeypatch):
    jobs = tmp_path / "jobs"
    score = jobs / "test-song" / "outputs" / "input" / "score"
    native = score / "native"
    native.mkdir(parents=True)
    (score / "score.musicxml").write_text(XML)
    (score / "score.mid").write_bytes(b"canonical MIDI")
    (score / "analysis.json").write_text('{"model_revision":"pinned","checkpoint_sha256":"hash"}')
    (native / "score.abc").write_text("X:1\nM:4/4\nK:C\nC4|")
    (native / "melody_vocal.mid").write_bytes(b"raw vocal MIDI")
    (native / "playback.json").write_text('{"measures":[]}')
    (native / "model.safetensors").write_bytes(b"not copied")
    (jobs / "test-song" / "input.wav").write_bytes(b"original waveform")
    monkeypatch.setattr(song_store_v2, "jobs_dir", lambda: jobs)
    store = SongStoreV2(path=tmp_path / "db.sqlite", cache_root=tmp_path / "cache",
                        asset_root=tmp_path / "assets", export_root=tmp_path / "exports")
    job = {"job_id": "test-song", "status": "done", "kind": "transcription",
           "filename": "demo.wav", "source_kind": "local", "score_mode": "lead_sheet",
           "transcription_engine": "sheetsage2", "transcription_selection_version": 1,
           "result": {"score_dir": str(score), "musicxml": str(score / "score.musicxml"),
                      "midi": str(score / "score.mid")}}
    return store, jobs, score, job


def test_raw_predictions_survive_job_removal_and_score_edits(case):
    store, jobs, score, job = case
    assert store.sync_completed_jobs([job]) == 1
    report = store.analysis("test-song", "model_evidence")
    assert report["status"] == "preserved"
    assert report["source_audio_sha256"] == hashlib.sha256(b"original waveform").hexdigest()
    folder = store.asset_root / "test-song" / "model-evidence"
    assert not (folder / "native" / "model.safetensors").exists()
    assert (folder / "native" / "melody_vocal.mid").read_bytes() == b"raw vocal MIDI"
    buffer = store.checkout_current("test-song")
    buffer.write_text(XML.replace('number="1"', 'number="2"'))
    store.commit_edit_from_path("test-song", buffer)
    shutil.rmtree(jobs / "test-song")
    assert store.preserve_job_evidence(job)
    assert store.get("test-song")["revision"] == 2
    assert (folder / "score.musicxml").read_text() == XML
    for item in report["files"]:
        assert hashlib.sha256((folder / item["path"]).read_bytes()).hexdigest() == item["sha256"]


def test_fixed_recipe_keeps_both_raw_providers_after_job_disposal(case):
    store, jobs, score, job = case
    job["transcription_engine"] = "vocal_lead_v1"
    (score / "structure").mkdir()
    shutil.copytree(score / "native", score / "structure/native")
    (score / "structure/analysis.json").write_text('{"model":"sheetsage2"}')
    (score / "recipe.json").write_text('{"engine":"vocal_lead_v1"}')
    (score / "interpretation.json").write_text('{"unrepresented_note_indices":[1]}')
    (score / "vocal").mkdir()
    (score / "vocal/score.mid").write_bytes(b"YourMT3 original, distinct from S2")
    (score / "vocal/selected.mid").write_bytes(b"selected original voice")
    (score / "vocal/score.runtime.json").write_text('{"seed":0}')
    assert store.sync_completed_jobs([job]) == 1
    folder = store.asset_root / "test-song/model-evidence"
    shutil.rmtree(jobs / "test-song")
    assert store.preserve_job_evidence(job)
    assert (folder / "vocal/score.mid").read_bytes() == b"YourMT3 original, distinct from S2"
    assert (folder / "structure/native/melody_vocal.mid").read_bytes() == b"raw vocal MIDI"
    assert (folder / "interpretation.json").is_file()
    assert not (folder / "structure/native/model.safetensors").exists()


def test_fixed_recipe_missing_original_provider_blocks_disposal(case):
    store, _jobs, _score, job = case
    job["transcription_engine"] = "vocal_lead_v1"
    assert not store.preserve_job_evidence(job)
    assert store.sync_completed_jobs([job]) == 0


@pytest.mark.parametrize("target", ["source", "parent", "destination"])
def test_symlink_escape_never_copies_foreign_files(case, tmp_path, target):
    store, jobs, score, job = case
    outside = tmp_path / "outside"
    outside.mkdir()
    if target == "source":
        raw = score / "native" / "melody_vocal.mid"
        raw.unlink()
        secret = outside / "secret.mid"
        secret.write_bytes(b"private")
        raw.symlink_to(secret)
    elif target == "parent":
        shutil.move(score / "native", outside / "native")
        (score / "native").symlink_to(outside / "native", target_is_directory=True)
    else:
        (store.asset_root / "test-song").symlink_to(outside, target_is_directory=True)
    assert not store.preserve_job_evidence(job)
    assert not (outside / "model-evidence").exists()
    assert store.sync_completed_jobs([job]) == 0


def test_partial_copy_is_atomic_and_retryable(case, monkeypatch):
    store, jobs, score, job = case
    original = evidence._digest
    def fail(path):
        if path.name == "playback.json":
            raise OSError("disk unavailable")
        return original(path)
    monkeypatch.setattr(evidence, "_digest", fail)
    assert store.sync_completed_jobs([job]) == 0
    assert store.get("test-song") is None
    owner = store.asset_root / "test-song"
    assert not list(owner.glob(".model-evidence-*"))
    assert not (owner / "model-evidence").exists()
    monkeypatch.setattr(evidence, "_digest", original)
    assert store.sync_completed_jobs([job]) == 1


def test_existing_song_backfills_raw_evidence_before_cleanup(case):
    store, jobs, score, job = case
    legacy = {**job, "result": {"musicxml": str(score / "score.musicxml")}}
    assert store.sync_completed_jobs([legacy]) == 1
    assert store.analysis("test-song", "model_evidence")["status"] == "unavailable"
    assert store.sync_completed_jobs([job]) == 0
    assert store.analysis("test-song", "model_evidence")["status"] == "preserved"


def test_corrupt_saved_raw_data_blocks_disposal_without_overwriting(case):
    store, jobs, score, job = case
    assert store.sync_completed_jobs([job]) == 1
    raw = store.asset_root / "test-song" / "model-evidence" / "native" / "melody_vocal.mid"
    raw.write_bytes(b"corrupt")
    assert not store.preserve_job_evidence(job)
    assert raw.read_bytes() == b"corrupt"
    assert (jobs / "test-song").exists()


def test_oversized_and_incomplete_evidence_are_not_silently_dropped(case, monkeypatch):
    store, jobs, score, job = case
    monkeypatch.setattr(evidence, "MAX_FILE_BYTES", 4)
    assert not store.preserve_job_evidence(job)
    monkeypatch.setattr(evidence, "MAX_FILE_BYTES", 16 * 1024 * 1024)
    (score / "native" / "playback.json").unlink()
    assert not store.preserve_job_evidence(job)


def test_manifest_path_cannot_escape_owned_directory(case, tmp_path):
    store, jobs, score, job = case
    assert store.sync_completed_jobs([job]) == 1
    path = store.asset_root / "test-song" / "model-evidence" / "manifest.json"
    payload = json.loads(path.read_text())
    payload["files"][0]["path"] = str(tmp_path / "foreign.mid")
    path.write_text(json.dumps(payload))
    assert not store.preserve_job_evidence(job)


@pytest.mark.parametrize("cleanup", [False, True])
def test_actual_job_deletion_preserves_raw_observations(case, monkeypatch, cleanup):
    from audio_score_tool import api, job_lifecycle_api_v2, storage_api_v2
    from audio_score_tool.job_store import JobStore

    store, jobs, score, job = case
    records = JobStore(store.path)
    records.create(job["job_id"], filename=job["filename"], kind="transcription",
                   transcription_engine="sheetsage2", score_mode="lead_sheet")
    records.update(job["job_id"], status="done", result=job["result"])
    monkeypatch.setattr(api, "_store", records)
    for module in (job_lifecycle_api_v2, storage_api_v2):
        monkeypatch.setattr(module, "_songs", store)
        monkeypatch.setattr(module, "jobs_dir", lambda: jobs)
    if cleanup:
        monkeypatch.setattr(storage_api_v2, "storage_status", lambda: {})
        result = storage_api_v2.cleanup_storage_v2(keep=0)
        assert result["deleted_jobs"] == 1
    else:
        assert job_lifecycle_api_v2.delete_job_v2(job["job_id"])["deleted"]
    assert not (jobs / job["job_id"]).exists()
    assert store.get(job["job_id"]) is not None
    assert store.preserve_job_evidence(job)
    assert (store.asset_root / job["job_id"] / "model-evidence/native/score.abc").is_file()


@pytest.mark.parametrize("cleanup", [False, True])
def test_actual_cleanup_refuses_corrupt_evidence(case, monkeypatch, cleanup):
    from fastapi import HTTPException

    from audio_score_tool import api, job_lifecycle_api_v2, storage_api_v2
    from audio_score_tool.job_store import JobStore

    store, jobs, score, job = case
    records = JobStore(store.path)
    records.create(job["job_id"], filename=job["filename"], kind="transcription")
    records.update(job["job_id"], status="done", result=job["result"])
    assert store.sync_completed_jobs([job]) == 1
    (store.asset_root / job["job_id"] / "model-evidence/score.mid").write_bytes(b"broken")
    monkeypatch.setattr(api, "_store", records)
    for module in (job_lifecycle_api_v2, storage_api_v2):
        monkeypatch.setattr(module, "_songs", store)
        monkeypatch.setattr(module, "jobs_dir", lambda: jobs)
    if cleanup:
        monkeypatch.setattr(storage_api_v2, "storage_status", lambda: {})
        result = storage_api_v2.cleanup_storage_v2(keep=0)
        assert result["protected_uningested_jobs"] == 1
        assert result["deleted_jobs"] == 0
    else:
        with pytest.raises(HTTPException) as caught:
            job_lifecycle_api_v2.delete_job_v2(job["job_id"])
        assert caught.value.status_code == 409
    assert records.get(job["job_id"]) is not None
    assert (jobs / job["job_id"]).is_dir()


@pytest.mark.parametrize("cleanup", [False, True])
@pytest.mark.parametrize("damage", ["missing", "corrupt", "no_source"])
def test_cleanup_requires_verified_original_audio(case, monkeypatch, cleanup, damage):
    from fastapi import HTTPException

    from audio_score_tool import api, job_lifecycle_api_v2, storage_api_v2
    from audio_score_tool.job_store import JobStore

    store, jobs, _, job = case
    records = JobStore(store.path)
    records.create(job["job_id"], filename=job["filename"], kind="transcription",
                   transcription_engine="sheetsage2", score_mode="lead_sheet")
    records.update(job["job_id"], status="done", result=job["result"])
    assert store.sync_completed_jobs([job]) == 1
    saved = store.asset_root / job["job_id"] / "original-audio.wav"
    if damage == "missing":
        saved.unlink()
    else:
        saved.write_bytes(b"x" * len(b"original waveform"))
    if damage == "no_source":
        (jobs / job["job_id"] / "input.wav").unlink()
    monkeypatch.setattr(api, "_store", records)
    for module in (job_lifecycle_api_v2, storage_api_v2):
        monkeypatch.setattr(module, "_songs", store)
        monkeypatch.setattr(module, "jobs_dir", lambda: jobs)
    if cleanup:
        monkeypatch.setattr(storage_api_v2, "storage_status", lambda: {})
        result = storage_api_v2.cleanup_storage_v2(keep=0)
        assert result["deleted_jobs"] == (0 if damage == "no_source" else 1)
    elif damage == "no_source":
        with pytest.raises(HTTPException) as caught:
            job_lifecycle_api_v2.delete_job_v2(job["job_id"])
        assert caught.value.status_code == 409
    else:
        assert job_lifecycle_api_v2.delete_job_v2(job["job_id"])["deleted"]
    if damage == "no_source":
        assert records.get(job["job_id"]) is not None
        assert saved.read_bytes() == b"x" * len(b"original waveform")
    else:
        assert not (jobs / job["job_id"]).exists()
        assert saved.read_bytes() == b"original waveform"
        assert store.preserve_job_evidence(job)
        saved.write_bytes(b"x" * len(b"original waveform"))
        assert not store.preserve_job_evidence(job)


@pytest.mark.parametrize("obstacle", ["source_symlink", "destination_symlink", "partial_copy"])
def test_original_audio_recovery_rejects_unsafe_or_partial_copy(case, tmp_path, monkeypatch, obstacle):
    store, jobs, _, job = case
    assert store.sync_completed_jobs([job]) == 1
    saved = store.asset_root / job["job_id"] / "original-audio.wav"
    saved.unlink()
    outside = tmp_path / "outside.wav"
    outside.write_bytes(b"original waveform")
    if obstacle == "source_symlink":
        source = jobs / job["job_id"] / "input.wav"
        source.unlink()
        source.symlink_to(outside)
    elif obstacle == "destination_symlink":
        saved.symlink_to(outside)
    else:
        def partial(source, destination):
            destination.write(b"partial")
            raise OSError("interrupted")
        monkeypatch.setattr(song_store_v2.shutil, "copyfileobj", partial)
    assert not store.preserve_job_evidence(job)
    assert outside.read_bytes() == b"original waveform"
    assert not (saved.parent / "original-audio.wav.copying").exists()
    assert saved.is_symlink() if obstacle == "destination_symlink" else not saved.exists()


def test_corrupt_job_and_song_audio_cannot_be_discarded(case):
    store, jobs, _, job = case
    assert store.sync_completed_jobs([job]) == 1
    saved = store.asset_root / job["job_id"] / "original-audio.wav"
    saved.write_bytes(b"bad saved audio")
    (jobs / job["job_id"] / "input.wav").write_bytes(b"bad job audio")
    assert not store.preserve_job_evidence(job)
    assert saved.read_bytes() == b"bad saved audio"


def test_audio_recovery_does_not_follow_external_job_path(case, tmp_path):
    store, jobs, _, job = case
    assert store.sync_completed_jobs([job]) == 1
    saved = store.asset_root / job["job_id"] / "original-audio.wav"
    saved.unlink()
    outside = tmp_path / "foreign"
    shutil.move(jobs / job["job_id"], outside)
    (jobs / job["job_id"]).symlink_to(outside, target_is_directory=True)
    assert not store.preserve_job_evidence(job)
    assert not saved.exists()


def test_youtube_mp4_original_survives_with_nested_analysis_wav(case):
    store, jobs, score, job = case
    root = jobs / job["job_id"]
    (root / "input.wav").rename(root / "input.mp4")
    analysis = score.parent / "structure" / "analysis.wav"
    analysis.parent.mkdir(parents=True)
    analysis.write_bytes(b"decoded analysis")
    job["source_kind"] = "youtube"
    assert store.sync_completed_jobs([job]) == 1
    assert store.analysis(job["job_id"], "model_evidence")["source_audio_sha256"] == hashlib.sha256(b"original waveform").hexdigest()
    shutil.rmtree(root)
    assert store.preserve_job_evidence(job)
    assert (store.asset_root / job["job_id"] / "original-audio.mp4").read_bytes() == b"original waveform"


def test_fixed_v2_requires_pitch_observation_and_preserves_after_job_removal(case):
    store, jobs, score, job = case
    job['transcription_engine'] = 'vocal_lead_v1'
    (score / 'structure').mkdir()
    shutil.copytree(score / 'native', score / 'structure/native')
    (score / 'structure/analysis.json').write_text('{}')
    (score / 'recipe.json').write_text('{"recipe_version":2}')
    (score / 'interpretation.json').write_text('{}')
    (score / 'vocal').mkdir()
    for name in ('score.mid', 'selected.mid', 'score.runtime.json'):
        (score / 'vocal' / name).write_bytes(b'fixture')
    assert not store.preserve_job_evidence(job)
    for bad in ('[]', '{"recipe_version":3}', '{"recipe_version":true}'):
        (score / 'recipe.json').write_text(bad)
        assert not store.preserve_job_evidence(job)
    (score / 'recipe.json').write_text('{"recipe_version":2}')
    pitch = score / 'vocal/pitch.npz'
    pitch.write_bytes(b'owned observation')
    (score / 'vocal/pitch.runtime.json').write_text('[]')
    assert not store.preserve_job_evidence(job)
    (score / 'vocal/pitch.runtime.json').write_text(json.dumps({'prediction_sha256': hashlib.sha256(pitch.read_bytes()).hexdigest()}))
    assert store.sync_completed_jobs([job]) == 1
    shutil.rmtree(jobs / 'test-song')
    assert store.preserve_job_evidence(job)
    assert (store.asset_root / 'test-song/model-evidence/vocal/pitch.npz').read_bytes() == b'owned observation'

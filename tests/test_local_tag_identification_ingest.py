"""Model-free local-only identification integration and original-audio lifecycle."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from audio_score_tool import local_source_identification as identifier
from audio_score_tool import revision_api_v2, runtime_services, song_store_v2
from audio_score_tool.api import app
from audio_score_tool.settings_store import SettingsStore
from audio_score_tool.song_store_v2 import SongStoreV2

XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <work><work-title>fixture</work-title></work>
  <part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list>
  <part id="P1"><measure number="1">
    <attributes><divisions>1</divisions></attributes>
    <note><rest/><duration>4</duration><type>whole</type></note>
  </measure></part>
</score-partwise>
"""


@pytest.fixture
def env(tmp_path: Path, monkeypatch):
    root = tmp_path / "jobs"
    root.mkdir()
    settings = SettingsStore(tmp_path / "settings.json")
    monkeypatch.setattr(song_store_v2, "jobs_dir", lambda: root)
    monkeypatch.setattr(song_store_v2, "SettingsStore", lambda: settings)
    monkeypatch.setattr(runtime_services, "_settings_store", settings)
    store = SongStoreV2(
        path=tmp_path / "app.sqlite3",
        cache_root=tmp_path / "cache",
        asset_root=tmp_path / "assets",
        export_root=tmp_path / "exports",
    )
    monkeypatch.setattr(revision_api_v2, "_song_store", store)
    monkeypatch.setattr(
        revision_api_v2,
        "_require_song",
        lambda song_id: store.get(song_id),
    )
    return store, settings, root


def _job(root: Path, kind: str = "transcription", job_id: str = "job-1") -> dict:
    output = root / job_id / "outputs" / "score.musicxml"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(XML, encoding="utf-8")
    if kind not in {"notation-import", "omr"}:
        (root / job_id / "input.mp3").write_bytes(b"synthetic local MP3 fixture")
    return {
        "job_id": job_id, "kind": kind, "status": "done",
        "filename": "recording.mp3" if kind == "transcription" else "source.musicxml",
        "result": {"musicxml": str(output)},
    }


def test_original_audio_is_retained_even_when_auto_identification_is_off(env):
    store, settings, root = env
    assert settings.read().get("auto_local_identification_enabled") is None
    calls = []
    original = identifier.read_embedded_tags

    def no_tag_scan(_path):
        calls.append(True)
        return original(_path)

    # The opt-in setting must suppress all automatic tag/file inspection.
    from pytest import MonkeyPatch
    with MonkeyPatch.context() as patch:
        patch.setattr(identifier, "read_embedded_tags", no_tag_scan)
        assert store.sync_completed_jobs([_job(root)]) == 1

    audio = store.asset_root / "job-1" / "original-audio.mp3"
    assert audio.read_bytes() == b"synthetic local MP3 fixture"
    assert not calls
    assert store.get("job-1")["revision"] == 1
    assert store.analysis("job-1", "local_tag_identification") is None
    assert store.sync_completed_jobs([_job(root)]) == 0


def test_opted_in_identification_saves_title_artist_and_one_undo_revision(
    env, monkeypatch,
):
    store, settings, root = env
    settings.update({"auto_local_identification_enabled": "true"})
    seen = []

    def tags(path: Path):
        seen.append(path)
        return {
            "provider": "embedded_tags", "title": "Trusted title",
            "artist": "Trusted artist", "confidence": 1.0,
        }

    monkeypatch.setattr(identifier, "read_embedded_tags", tags)
    # No network/process functions are used by the local-only implementation.
    monkeypatch.setattr(
        identifier, "read_embedded_tags", tags
    )
    assert store.sync_completed_jobs([_job(root)]) == 1
    song = store.get("job-1")
    assert song["title"] == "Trusted title"
    assert song["artist"] == "Trusted artist"
    assert song["revision"] == 2
    assert "Trusted title" in store.score_xml("job-1")
    assert len(seen) == 1
    analysis = store.analysis("job-1", "local_tag_identification")
    assert analysis["network_attempted"] is False
    assert analysis["fingerprint_attempted"] is False
    assert analysis["applied"] is True
    assert analysis["status"] == "identified"

    # Reconciliation/restart cannot repeat the mutation.
    assert store.sync_completed_jobs([_job(root)]) == 0
    assert store.get("job-1")["revision"] == 2
    assert len(seen) == 1

    result = TestClient(app).post("/api/songs/job-1/undo")
    assert result.status_code == 200, result.text
    assert store.get("job-1")["revision"] == 1
    assert store.get("job-1")["artist"] is None
    assert "Trusted title" not in store.score_xml("job-1")


def test_missing_artist_does_not_apply_or_consume_revision(env, monkeypatch):
    store, settings, root = env
    settings.update({"auto_local_identification_enabled": "true"})
    monkeypatch.setattr(
        identifier, "read_embedded_tags",
        lambda _: {"title": "Weak tag", "artist": None, "confidence": 0.86},
    )
    assert store.sync_completed_jobs([_job(root)]) == 1
    assert store.get("job-1")["revision"] == 1
    assert store.analysis("job-1", "local_tag_identification")["status"] == "insufficient_local_tags"


def test_invalid_audio_and_tag_reader_failure_cannot_break_core_song(env, monkeypatch):
    store, settings, root = env
    settings.update({"auto_local_identification_enabled": "true"})
    monkeypatch.setattr(
        identifier, "read_embedded_tags",
        lambda _: (_ for _ in ()).throw(ValueError("invalid audio tags")),
    )
    assert store.sync_completed_jobs([_job(root)]) == 1
    assert store.get("job-1")["revision"] == 1
    report = store.analysis("job-1", "local_tag_identification")
    assert report["status"] == "local_identification_failed"
    assert "invalid audio tags" in report["error"]


@pytest.mark.parametrize("kind", ["omr", "notation-import"])
def test_non_audio_import_never_attempts_tag_inspection(env, monkeypatch, kind: str):
    store, settings, root = env
    settings.update({"auto_local_identification_enabled": "true"})
    monkeypatch.setattr(
        identifier, "read_embedded_tags",
        lambda _: (_ for _ in ()).throw(AssertionError("non-audio source scanned")),
    )
    assert store.sync_completed_jobs([_job(root, kind=kind)]) == 1
    assert store.get("job-1")["revision"] == 1
    assert store.analysis("job-1", "local_tag_identification") is None


def test_symlinked_job_audio_is_not_preserved_or_inspected(env, monkeypatch, tmp_path):
    store, settings, root = env
    settings.update({"auto_local_identification_enabled": "true"})
    job = _job(root)
    original = root / "job-1" / "input.mp3"
    original.unlink()
    outside = tmp_path / "secret.mp3"
    outside.write_bytes(b"private")
    original.symlink_to(outside)
    monkeypatch.setattr(
        identifier, "read_embedded_tags",
        lambda _: (_ for _ in ()).throw(AssertionError("symlink must not be read")),
    )
    assert store.sync_completed_jobs([job]) == 1
    assert not (store.asset_root / "job-1" / "original-audio.mp3").exists()
    assert store.get("job-1")["revision"] == 1


def test_setting_api_is_persisted_and_off_by_default(env):
    _store, settings, _root = env
    client = TestClient(app)
    assert client.get("/api/settings/local-identification").json() == {
        "enabled": False,
        "scope": "local_embedded_tags_only",
        "external_requests": False,
    }
    on = client.put("/api/settings/local-identification", json={"enabled": True})
    assert on.status_code == 200, on.text
    assert on.json()["enabled"] is True
    assert settings.read()["auto_local_identification_enabled"] == "true"
    assert SettingsStore(settings.path).read()["auto_local_identification_enabled"] == "true"
    off = client.put("/api/settings/local-identification", json={"enabled": False})
    assert off.status_code == 200
    assert off.json()["enabled"] is False
    assert settings.read()["auto_local_identification_enabled"] == "false"

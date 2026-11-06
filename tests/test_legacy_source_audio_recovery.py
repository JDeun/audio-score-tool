"""Legacy audio Song recovery from owned Job input during explicit identification."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from audio_score_tool import enrichment_api, song_store_v2
from audio_score_tool.api import app
from audio_score_tool.song_store_v2 import SongStoreV2

MUSICXML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0"><work><work-title>Legacy</work-title></work>
<part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list>
<part id="P1"><measure number="1"><note><rest/><duration>1</duration><type>quarter</type>
</note></measure></part></score-partwise>
"""


@pytest.fixture
def legacy(tmp_path: Path, monkeypatch):
    root = tmp_path / "jobs"
    root.mkdir()
    monkeypatch.setattr(song_store_v2, "jobs_dir", lambda: root)
    store = SongStoreV2(
        path=tmp_path / "db.sqlite3",
        cache_root=tmp_path / "cache",
        asset_root=tmp_path / "assets",
        export_root=tmp_path / "exports",
    )
    monkeypatch.setattr(enrichment_api, "_store", store)
    monkeypatch.setattr(
        enrichment_api, "runtime_settings",
        lambda: SimpleNamespace(usage_mode="commercial"),
    )
    monkeypatch.delenv("AST_MUSICBRAINZ_COMMERCIAL_ENTITLED", raising=False)
    monkeypatch.delenv("AST_ACOUSTID_COMMERCIAL_ENTITLED", raising=False)
    monkeypatch.delenv("ACOUSTID_CLIENT_KEY", raising=False)

    score = tmp_path / "score.musicxml"
    score.write_text(MUSICXML, encoding="utf-8")
    assert store.sync_completed_jobs([{
        "job_id": "legacy-1",
        "kind": "transcription",
        "status": "done",
        "filename": "old-song.mp3",
        "result": {"musicxml": str(score)},
    }]) == 1
    assert not (store.asset_root / "legacy-1" / "original-audio.mp3").exists()
    return store, root


def test_legacy_audio_job_is_recovered_only_when_user_identifies(
    legacy, monkeypatch,
):
    store, root = legacy
    job_audio = root / "legacy-1" / "input.mp3"
    job_audio.parent.mkdir(parents=True, exist_ok=True)
    job_audio.write_bytes(b"synthetic owned audio")
    seen = []

    def identify(path: Path, **_kwargs) -> dict:
        seen.append(path)
        return {
            "embedded_tags": {"title": "Trusted", "artist": "Local artist", "isrc": None},
            "selected": {"title": "Trusted", "artist": "Local artist", "confidence": 1.0},
            "acoustid": {"attempted": False},
            "policy": {},
        }

    monkeypatch.setattr(enrichment_api, "identify_source", identify)
    monkeypatch.setattr(
        enrichment_api, "search_musicbrainz",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("No external lookup is authorized")
        ),
    )
    client = TestClient(app)
    response = client.post(
        "/api/songs/legacy-1/identify-source",
        json={"apply_high_confidence_metadata": False, "refresh": True},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "identified"
    recovered = store.asset_root / "legacy-1" / "original-audio.mp3"
    assert recovered.read_bytes() == job_audio.read_bytes()
    assert seen == [recovered]
    assert store.get("legacy-1")["revision"] == 1

    job_audio.unlink()
    second = client.post(
        "/api/songs/legacy-1/identify-source",
        json={"apply_high_confidence_metadata": False, "refresh": True},
    )
    assert second.status_code == 200
    assert seen == [recovered, recovered]


def test_legacy_job_audio_missing_after_cleanup_is_reported_honestly(legacy):
    store, _root = legacy
    response = TestClient(app).post(
        "/api/songs/legacy-1/identify-source",
        json={"apply_high_confidence_metadata": False},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "no_audio"
    assert store.get("legacy-1")["revision"] == 1


def test_legacy_input_symlink_does_not_escape_job_root(
    legacy, tmp_path: Path, monkeypatch,
):
    _store, root = legacy
    outside = tmp_path / "private.mp3"
    outside.write_bytes(b"private-data")
    job_audio = root / "legacy-1" / "input.mp3"
    job_audio.parent.mkdir(parents=True, exist_ok=True)
    job_audio.symlink_to(outside)
    monkeypatch.setattr(
        enrichment_api, "identify_source",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Symlinked audio must never be inspected")
        ),
    )
    response = TestClient(app).post(
        "/api/songs/legacy-1/identify-source",
        json={"apply_high_confidence_metadata": False},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "no_audio"
    assert outside.read_bytes() == b"private-data"

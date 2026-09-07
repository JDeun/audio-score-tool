from pathlib import Path

from audio_score_tool.source_identification import _first_tag, identify_source


def test_first_tag_prefers_clean_embedded_metadata():
    tags = {"title": ["Song Title"], "artist": ["Artist Name"], "album": ["Album"]}
    assert _first_tag(tags, "title") == "Song Title"
    assert _first_tag(tags, "artist", "albumartist") == "Artist Name"


def test_identification_without_api_key_keeps_network_optional(tmp_path: Path, monkeypatch):
    source = tmp_path / "unknown.bin"
    source.write_bytes(b"not-a-real-audio-file")
    monkeypatch.delenv("ACOUSTID_CLIENT_KEY", raising=False)

    report = identify_source(source, usage_mode="personal")

    assert report["selected"] is None
    assert report["acoustid"]["attempted"] is False
    assert "ACOUSTID_CLIENT_KEY" in report["acoustid"]["error"]
    assert report["policy"]["model_is_last_resort"] is True


def test_commercial_mode_does_not_use_acoustid_without_entitlement(tmp_path: Path, monkeypatch):
    source = tmp_path / "unknown.bin"
    source.write_bytes(b"not-a-real-audio-file")
    monkeypatch.setenv("ACOUSTID_CLIENT_KEY", "test-client-key")

    report = identify_source(
        source,
        usage_mode="commercial",
        acoustid_commercial_entitled=False,
    )

    assert report["acoustid"]["attempted"] is False
    assert "entitlement" in report["acoustid"]["error"]

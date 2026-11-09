"""Local embedded audio tags precede filename; YouTube uses video title only."""
from __future__ import annotations

from audio_score_tool.source_metadata_hints import (
    SourceLookupHints,
    resolve_source_lookup_hints,
)


def test_local_embedded_artist_and_title_override_bad_original_filename(tmp_path, monkeypatch):
    from audio_score_tool import source_identification

    media = tmp_path / "weird_input_001.mp3"
    media.write_bytes(b"fictional-test-file")
    monkeypatch.setattr(
        source_identification, "read_embedded_tags",
        lambda _: {
            "title": "American Idiot",
            "artist": "Green Day",
            "album": "American Idiot",
            "date": "2004",
        },
    )
    assert resolve_source_lookup_hints(
        "local", "Track334993.mp3", audio_path=media,
    ) == SourceLookupHints(
        "American Idiot", "Green Day", "embedded_tags", "American Idiot",
    )


def test_local_falls_back_to_filename_when_no_embedded_tags(tmp_path, monkeypatch):
    from audio_score_tool import source_identification

    media = tmp_path / "input.wav"
    media.write_bytes(b"fictional-test-audio")
    monkeypatch.setattr(source_identification, "read_embedded_tags", lambda _: {})
    assert resolve_source_lookup_hints(
        "local", "Green Day - American Idiot.wav", audio_path=media,
    ) == SourceLookupHints("American Idiot", "Green Day", "filename")


def test_partial_tags_can_complement_matching_filename_but_not_conflicting_one(
    tmp_path, monkeypatch,
):
    from audio_score_tool import source_identification

    media = tmp_path / "input.flac"
    media.write_bytes(b"fictional-test-file")
    monkeypatch.setattr(source_identification, "read_embedded_tags", lambda _: {
        "title": "American Idiot", "artist": None, "album": "American Idiot",
    })
    assert resolve_source_lookup_hints(
        "local", "Green Day - American Idiot.flac", audio_path=media,
    ) == SourceLookupHints(
        "American Idiot", "Green Day", "combined_tags_filename", "American Idiot",
    )
    assert resolve_source_lookup_hints(
        "local", "Another Artist - Other song.flac", audio_path=media,
    ) is None
    assert resolve_source_lookup_hints(
        "local", "unrecognized_file.flac", audio_path=media,
    ) is None


def test_youtube_does_not_use_local_tags_or_uploader_to_invent_artist(
    tmp_path, monkeypatch,
):
    from audio_score_tool import source_identification

    media = tmp_path / "download.m4a"
    media.write_bytes(b"fictional-video-audio")
    def forbidden(_):
        raise AssertionError("Never use downloaded audio tags for YouTube identity")

    monkeypatch.setattr(source_identification, "read_embedded_tags", forbidden)
    assert resolve_source_lookup_hints(
        "youtube", "Green Day - American Idiot (Official Music Video)",
        audio_path=media,
    ) == SourceLookupHints(
        "American Idiot", "Green Day", "youtube_title",
    )
    assert resolve_source_lookup_hints(
        "youtube", "Unknown video title", audio_path=media,
    ) is None
    assert resolve_source_lookup_hints(
        "notation", "Green Day - American Idiot.musicxml",
    ) is None


def test_audio_metadata_provenance_does_not_use_unverified_values(tmp_path, monkeypatch):
    from audio_score_tool import source_identification

    media = tmp_path / "input.mp3"
    media.write_bytes(b"fictional-test-file")
    monkeypatch.setattr(source_identification, "read_embedded_tags", lambda _: {
        "title": "Unknown", "artist": "Unknown", "album": "Unknown",
    })
    assert resolve_source_lookup_hints(
        "local", "readme123.mp3", audio_path=media,
    ) is None
    assert resolve_source_lookup_hints(
        "local", "Band - Correct song.mp3", audio_path=media,
    ) == SourceLookupHints("Correct song", "Band", "filename")

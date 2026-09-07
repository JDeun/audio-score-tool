import pytest

from audio_score_tool.enrichment import EnrichmentError, LyricsProvider, choose_high_confidence, fetch_lyrics


def test_choose_high_confidence_requires_threshold():
    candidates = [{"score": 88, "title": "A"}, {"score": 96, "title": "B"}]
    assert choose_high_confidence(candidates, threshold=92)["title"] == "B"
    assert choose_high_confidence([{"score": 91}], threshold=92) is None


def test_remote_lyrics_provider_requires_https():
    with pytest.raises(EnrichmentError):
        fetch_lyrics(
            LyricsProvider("unsafe", "http://example.com/lyrics?artist={artist}&title={title}"),
            title="Song",
            artist="Artist",
        )

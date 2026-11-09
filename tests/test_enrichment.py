import pytest

from audio_score_tool import enrichment
from audio_score_tool.enrichment import (
    EnrichmentError,
    LyricsProvider,
    choose_high_confidence,
    fetch_lyrics,
)


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


def test_lyrics_provider_rejects_unknown_template_placeholder():
    with pytest.raises(EnrichmentError, match="title.*artist"):
        fetch_lyrics(
            LyricsProvider("broken", "https://example.com/lyrics?id={track_id}"),
            title="Song",
            artist="Artist",
        )


def test_lyrics_provider_rejects_non_url_template():
    with pytest.raises(EnrichmentError, match="valid http"):
        fetch_lyrics(
            LyricsProvider("broken", "not-a-url/{title}"),
            title="Song",
            artist="Artist",
        )



def test_musicbrainz_transient_503_retries_once_without_retrying_rate_limits(monkeypatch):
    monkeypatch.setattr(enrichment, "_last_mb_request", 0.0)
    delays = []
    monkeypatch.setattr(enrichment.time, "sleep", lambda duration: delays.append(duration))
    seen = []

    def temporarily_unavailable(*_args, **_kwargs):
        seen.append("attempt")
        if len(seen) == 1:
            raise EnrichmentError("HTTP Error 503: Service Unavailable")
        return {"recordings": []}

    monkeypatch.setattr(enrichment, "_json_request", temporarily_unavailable)
    assert enrichment.search_musicbrainz("Any", "Artist") == []
    assert len(seen) == 2
    assert any(delay >= 2.0 for delay in delays)

    seen.clear()
    delays.clear()
    monkeypatch.setattr(enrichment, "_last_mb_request", 0.0)
    def throttled(*_args, **_kwargs):
        seen.append("attempt")
        raise EnrichmentError("HTTP Error 429: Too Many Requests")

    monkeypatch.setattr(enrichment, "_json_request", throttled)
    with pytest.raises(EnrichmentError, match="429"):
        enrichment.search_musicbrainz("Any", "Artist")
    assert len(seen) == 1
    assert not any(delay >= 2.0 for delay in delays)

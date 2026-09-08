from audio_score_tool.reference_lyrics import align_reference_lyrics, reference_tokens


def test_reference_tokens_strip_lrc_timestamps():
    assert reference_tokens("[00:01.20]hello world\n[00:03.00]again") == ["hello", "world", "again"]


def test_reference_lyrics_keep_whisper_timing_for_equal_words():
    payload = {
        "segments": [
            {
                "words": [
                    {"word": "hello", "start": 1.0, "end": 1.4, "score": 0.9},
                    {"word": "world", "start": 1.5, "end": 2.0, "score": 0.9},
                ]
            }
        ]
    }
    timed, stats = align_reference_lyrics(payload, "hello world", language="en")
    assert [(word.text, word.start, word.end) for word in timed] == [
        ("hello", 1.0, 1.4),
        ("world", 1.5, 2.0),
    ]
    assert stats["coverage"] == 1.0


def test_reference_lyrics_distribute_replacement_over_acoustic_span():
    payload = {
        "segments": [
            {"words": [{"word": "wrong", "start": 2.0, "end": 3.0}]}
        ]
    }
    timed, stats = align_reference_lyrics(payload, "clean lyric", language="en")
    assert [word.text for word in timed] == ["clean", "lyric"]
    assert timed[0].start == 2.0
    assert timed[-1].end == 3.0
    assert stats["timing_source"] == "whisperx"

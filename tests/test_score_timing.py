"""An explicit audio origin is shared by playback and waveform alignment."""
import pytest
from music21 import metadata, stream, tempo

from audio_score_tool.score_timing import AUDIO_ORIGIN_FIELD, score_time_clocks


def test_audio_origin_survives_clock_inversion_and_tempo_changes():
    score = stream.Score()
    score.metadata = metadata.Metadata()
    score.metadata.addCustom(AUDIO_ORIGIN_FIELD, "0.037")
    part = stream.Part()
    part.insert(0, tempo.MetronomeMark(number=60))
    part.insert(2, tempo.MetronomeMark(number=120))
    score.insert(0, part)
    seconds, quarters = score_time_clocks(score)
    for position, expected in [(0,.037),(1,1.037),(2,2.037),(3,2.537)]:
        assert seconds(position) == pytest.approx(expected)
        assert quarters(expected) == pytest.approx(position)


@pytest.mark.parametrize("values", [["nan"],["inf"],["-1"],["0","1"]])
def test_invalid_audio_origins_are_rejected(values):
    score = stream.Score()
    score.metadata = metadata.Metadata()
    for value in values:
        score.metadata.addCustom(AUDIO_ORIGIN_FIELD, value)
    with pytest.raises(ValueError, match="origin"):
        score_time_clocks(score)

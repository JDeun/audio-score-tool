from dataclasses import replace

import mido
import numpy as np
import pytest

from audio_score_tool.lead_notation import verify_notated_midi, vocal_grid
from audio_score_tool.metrics import MidiNote


def event(pitch, start, end):
    return MidiNote(pitch=pitch, onset=start, offset=end, channel=0, program=65, is_drum=False)


@pytest.mark.parametrize("fault", [None, "pitch", "time", "missing"])
def test_final_midi_must_preserve_interpreted_attacks_gaps_and_audio_time(tmp_path, fault):
    def write(path, events):
        midi = mido.MidiFile(ticks_per_beat=10000)
        track = mido.MidiTrack()
        midi.tracks.append(track)
        cursor = 0
        for pitch,start,end in events:
            onset, offset = round(start*20000), round(end*20000)
            track.append(mido.Message("note_on", note=pitch, velocity=80, time=onset-cursor))
            track.append(mido.Message("note_off", note=pitch, time=offset-onset))
            cursor = offset
        midi.save(path)
    source = tmp_path / "source.mid"
    rendered = tmp_path / "rendered.mid"
    write(source, [(60,.11,.31),(60,.41,.59)])
    unchanged = source.read_bytes()
    interpretation = {"grid_audio_seconds":[.1,.2,.3,.4,.5,.6],
                      "source_note_indices":[0,0,-1,1,1]}
    performed = [(60,.1,.3),(60,.4,.6)]
    if fault == "pitch":
        performed[1] = (61,.4,.6)
    elif fault == "time":
        performed[1] = (60,.41,.6)
    elif fault == "missing":
        performed.pop()
    write(rendered, performed)
    if fault:
        with pytest.raises(ValueError, match="Notation conversion changed"):
            verify_notated_midi(source, rendered, interpretation)
    else:
        report = verify_notated_midi(source, rendered, interpretation)
        assert report["performed_notes"] == 2 and report["matched_interpretation"]
        assert report["original_song_accuracy"] is None
    assert source.read_bytes() == unchanged


def test_grid_interpretation_preserves_pitch_and_raw_performance():
    raw = [event(60, 0.02, 0.51), event(62, 0.52, 0.96)]
    original = tuple(raw)
    cells, report = vocal_grid(raw, [0, 0.25, 0.5, 0.75, 1])
    assert cells.tolist() == [123, 122, 127, 126, 0]
    assert report["source_note_indices"] == [0, 0, 1, 1]
    assert report["unrepresented_note_indices"] == []
    assert tuple(raw) == original
    assert report["raw_events_mutated"] is False
    assert report["quality_approved"] is False


def test_rearticulated_same_pitch_is_not_merged():
    cells, report = vocal_grid([event(60, 0, 0.5), event(60, 0.5, 1)], [0, 0.25, 0.5, 0.75, 1])
    assert cells.tolist() == [123, 122, 123, 122, 0]
    assert report["notated_attacks"] == 2


def test_sub_grid_ornament_is_reported_without_stretching_or_changing_its_pitch():
    raw = [event(60, 0, 0.4), event(64, 0.4, 0.43), event(62, 0.5, 0.75)]
    cells, report = vocal_grid(raw, [0, 0.25, 0.5, 0.75, 1])
    assert cells.tolist() == [123, 122, 127, 0, 0]
    assert report["unrepresented_note_indices"] == [1]
    assert report["represented_note_count"] == 2
    assert raw[1] == event(64, 0.4, 0.43)


def test_overlap_and_out_of_order_events_retain_traceable_source_indices():
    cells, report = vocal_grid([event(64, 0.4, 1), event(60, 0, 0.6)], [0, 0.25, 0.5, 0.75, 1])
    assert cells.tolist() == [123, 122, 131, 130, 0]
    assert report["source_note_indices"] == [1, 1, 0, 0]


def test_simultaneous_competing_pitches_are_explicit_review_regions():
    cells, report = vocal_grid([event(60, 0, 1), event(64, 0, 1)], [0, 0.25, 0.5, 0.75, 1])
    assert report["overlap_review_cells"] == [0, 1, 2, 3]
    assert report["unrepresented_note_indices"] == [1]
    assert cells.tolist() == [123, 122, 122, 122, 0]


def test_variable_audio_grid_and_leading_silence_are_not_assumed_constant_bpm():
    cells, report = vocal_grid([event(57, 0.6, 1.6)], [0, 0.2, 0.6, 1.0, 1.6])
    assert cells.tolist() == [0, 0, 117, 116, 0]
    assert report["source_note_indices"] == [-1, -1, 0, 0]


@pytest.mark.parametrize("times", [[], [0], [0, 0], [1, 0], [-1, 0], [0, float("nan")],
                                   [0, float("inf")], [False, 1]])
def test_invalid_observed_clocks_are_rejected(times):
    with pytest.raises(ValueError):
        vocal_grid([event(60, 0, 1)], times)


@pytest.mark.parametrize("bad", [replace(event(60, 0, 1), pitch=128),
                                 replace(event(60, 0, 1), is_drum=True),
                                 replace(event(60, 0, 1), onset=float("nan")),
                                 replace(event(60, 0, 1), onset=True), event(60, 1, 0)])
def test_invalid_vocal_events_are_rejected(bad):
    with pytest.raises(ValueError):
        vocal_grid([bad], [0, 0.5, 1])


def test_empty_or_wholly_unrepresentable_vocal_is_never_a_successful_score():
    for notes in ([], [event(60, 0.01, 0.02)], [event(60, 3, 4)]):
        with pytest.raises(ValueError):
            vocal_grid(notes, [0, 0.25, 0.5, 0.75, 1])


def test_linear_working_memory_handles_long_source_notes():
    grid = np.linspace(0, 3600, 100001)
    cells, report = vocal_grid([event(60, 0, 3600)], grid)
    assert len(cells) == len(grid)
    assert report["notated_attacks"] == 1

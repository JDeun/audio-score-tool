from dataclasses import replace
from itertools import permutations

import mido
import pytest

from audio_score_tool.metrics import MidiNote, midi_notes
from audio_score_tool.stem_ablation import METHOD_ID, score_note_events

_METRICS = ("onset", "onset_offset", "instrument_onset_offset")


def _note(onset=0.0, offset=1.0, *, pitch=60, program=40, channel=0, drum=False):
    return MidiNote(pitch, onset, offset, channel, program, drum)


def test_maximum_matching_recovers_two_notes_missed_by_nearest_greedy_matching():
    predicted = [_note(0.06), _note(0.11)]
    reference = [_note(0.10), _note(0.15)]
    for pred_order in permutations(predicted):
        for ref_order in permutations(reference):
            result = score_note_events(pred_order, ref_order)
            for metric in _METRICS:
                assert result[metric] == {
                    "precision": 1.0, "recall": 1.0, "f1": 1.0, "matched": 2,
                }
    assert result["method"] == METHOD_ID
    assert result["onset_tolerance_seconds"] == 0.05
    assert result["offset_minimum_tolerance_seconds"] == 0.05
    assert result["offset_reference_duration_ratio"] == 0.2


def test_matching_can_reassign_a_previous_match_along_an_augmenting_path():
    # The first reference can use either prediction; the second can only use
    # the earliest prediction. A first-fit matcher needs to undo its first pair.
    result = score_note_events([_note(0.06), _note(0.11)], [_note(0.10), _note(0.05)])
    assert all(result[metric]["matched"] == 2 for metric in _METRICS)


def test_duplicate_predictions_remain_false_positives_in_the_multiset_union():
    shared = _note()
    result = score_note_events([shared, shared], [shared])
    assert result["predicted_note_count"] == 2
    assert result["reference_note_count"] == 1
    for metric in _METRICS:
        assert result[metric]["matched"] == 1
        assert result[metric]["precision"] == 0.5
        assert result[metric]["recall"] == 1.0
        assert result[metric]["f1"] == pytest.approx(2 / 3)
    # True unison multiplicity in the reference is also retained.
    both = score_note_events([shared, shared], [shared, shared])
    assert all(both[metric]["f1"] == 1.0 for metric in _METRICS)


def test_same_program_nested_pitch_offsets_survive_without_midi_reserialization():
    notes = [_note(0.0, 1.0), _note(0.25, 0.5)]
    original = list(notes)
    result = score_note_events(notes, original)
    assert notes == original
    assert [(note.onset, note.offset) for note in notes] == [(0.0, 1.0), (0.25, 0.5)]
    assert all(result[metric]["f1"] == 1.0 for metric in _METRICS)
    swapped_offsets = [_note(0.0, 0.5), _note(0.25, 1.0)]
    changed = score_note_events(swapped_offsets, original)
    assert changed["onset"]["f1"] == 1.0
    assert changed["onset_offset"]["f1"] == 0.0


def test_silent_prediction_is_a_valid_zero_score_and_empty_reference_is_rejected():
    result = score_note_events([], [_note()])
    assert result["predicted_note_count"] == 0
    for metric in _METRICS:
        assert result[metric] == {
            "precision": 0.0, "recall": 0.0, "f1": 0.0, "matched": 0,
        }
    with pytest.raises(ValueError, match="reference must contain"):
        score_note_events([], [])


def test_wrong_instrument_does_not_hide_correct_pitch_and_timing():
    result = score_note_events([_note(program=41)], [_note(program=40)])
    assert result["onset"]["f1"] == 1.0
    assert result["onset_offset"]["f1"] == 1.0
    assert result["instrument_onset_offset"]["f1"] == 0.0
    assert result["instrument_onset_offset"]["matched"] == 0


def test_wrong_pitch_cannot_match_even_with_identical_time_and_instrument():
    result = score_note_events([_note(pitch=61)], [_note(pitch=60)])
    assert all(result[metric]["matched"] == 0 for metric in _METRICS)


def test_instrument_matching_is_independent_of_agnostic_matching_and_channel_numbers():
    result = score_note_events(
        [_note(program=41, channel=0), _note(program=40, channel=1)],
        [_note(program=40, channel=7), _note(program=41, channel=8)],
    )
    assert all(result[metric]["matched"] == 2 for metric in _METRICS)


def test_percussion_identity_ignores_drum_program_but_distinguishes_pitched_notes():
    drum = _note(pitch=36, program=8, channel=9, drum=True)
    same_drum = _note(pitch=36, program=0, channel=9, drum=True)
    assert score_note_events([drum], [same_drum])["instrument_onset_offset"]["f1"] == 1.0
    pitched = _note(pitch=36, program=8)
    result = score_note_events([pitched], [drum])
    assert result["onset_offset"]["f1"] == 1.0
    assert result["instrument_onset_offset"]["f1"] == 0.0


@pytest.mark.parametrize(("onset", "offset", "expected_onset", "expected_full"), [
    (0.4, 0.85, 1.0, 1.0),  # Exact 50 ms onset and offset boundaries.
    (0.35, 0.89, 1.0, 1.0),  # Exact 20%-of-reference offset boundary.
    (0.400001, 0.8, 0.0, 0.0),
    (0.35, 0.890001, 1.0, 0.0),  # 20% of the reference's 450 ms duration is 90 ms.
])
def test_onset_and_relative_offset_thresholds_are_inclusive(
    onset, offset, expected_onset, expected_full,
):
    result = score_note_events([_note(onset, offset)], [_note(0.35, 0.8)])
    assert result["onset"]["f1"] == expected_onset
    assert result["onset_offset"]["f1"] == expected_full


@pytest.mark.parametrize(("offset", "expected"), [(1.15, 1.0), (1.150001, 0.0)])
def test_short_note_offset_uses_fifty_millisecond_minimum(offset, expected):
    result = score_note_events([_note(1.0, offset)], [_note(1.0, 1.1)])
    assert result["onset_offset"]["f1"] == expected


@pytest.mark.parametrize(("field", "value"), [
    ("onset", float("nan")), ("offset", float("inf")),
    ("onset", -0.01), ("offset", 0.0), ("offset", -1.0),
    ("onset", True), ("offset", 10**400),
    ("pitch", 128), ("program", -1), ("channel", 16), ("is_drum", 1),
])
def test_invalid_event_fields_are_rejected_in_either_input(field, value):
    invalid = replace(_note(), **{field: value})
    with pytest.raises(ValueError):
        score_note_events([invalid], [_note()])
    with pytest.raises(ValueError):
        score_note_events([_note()], [invalid])


def test_tempo_aware_per_file_union_retains_time_and_gm_when_channels_collide(tmp_path):
    first = mido.MidiFile(type=1, ticks_per_beat=480)
    first.tracks.append(mido.MidiTrack([
        mido.MetaMessage("set_tempo", tempo=500_000, time=0),
        mido.Message("program_change", channel=0, program=40, time=0),
        mido.Message("note_on", channel=0, note=60, velocity=90, time=0),
        mido.MetaMessage("set_tempo", tempo=1_000_000, time=480),
        mido.Message("note_off", channel=0, note=60, time=480),
    ]))
    second = mido.MidiFile(type=1, ticks_per_beat=960)
    second.tracks.append(mido.MidiTrack([
        mido.MetaMessage("set_tempo", tempo=1_000_000, time=0),
        mido.Message("program_change", channel=0, program=41, time=0),
        mido.Message("note_on", channel=0, note=64, velocity=90, time=480),
        mido.Message("note_off", channel=0, note=64, time=480),
    ]))
    paths = [tmp_path / "stem-a.mid", tmp_path / "stem-b.mid"]
    first.save(paths[0])
    second.save(paths[1])
    combined = midi_notes(paths[0]) + midi_notes(paths[1])
    assert [(n.onset, n.offset, n.program) for n in combined] == [
        (0.0, 1.5, 40), (0.5, 1.0, 41),
    ]
    reference = [_note(0.0, 1.5, channel=2), _note(0.5, 1.0, pitch=64, program=41, channel=3)]
    result = score_note_events(combined, reference)
    assert all(result[metric]["f1"] == 1.0 for metric in _METRICS)

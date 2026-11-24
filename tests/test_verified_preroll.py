"""Only the verified empty DBN opening scaffold can become an audio origin."""

import json
import xml.etree.ElementTree as ET

import mido
import pytest
from music21 import clef, converter, meter, stream

from audio_score_tool.metrics import midi_notes
from audio_score_tool.notation_backend import _verovio_toolkit, musicxml_to_midi
from audio_score_tool.score_timing import score_audio_origin, score_time_clocks
from audio_score_tool.sheetsage2_score import import_native_lead_sheet

ORIGIN = .28
ENDING = 2.88
EMPTY_PICKUP = "z8 |"
ABC = """X:1
T:Synthetic
M:4/4
L:1/8
Q:1/4=180
V:Vocal clef=alto
K:G
V: Vocal
z8 |
g2 a2 b2 c2 |
z8 |]
"""
BEAT_ROWS = [(0, 4, 4, 4), (ORIGIN, 1, 4, 4), (.62, 2, 4, 4), (.95, 3, 4, 4), (1.28, 4, 4, 4),
             (1.6, 1, 4, 4), (1.95, 2, 4, 4), (2.27, 3, 4, 4), (2.59, 4, 4, 4), (2.91, 1, 4, 4)]


def _raw_vocal(path, onset=ORIGIN):
    midi = mido.MidiFile(ticks_per_beat=1000)
    voice = midi.add_track()
    voice.append(mido.MetaMessage("set_tempo", tempo=500000))
    voice.append(mido.Message("note_on", note=67, velocity=80, time=round(onset * 2000)))
    voice.append(mido.Message("note_off", note=67, time=100))
    midi.save(path)


def _native(root, *, abc=ABC, beats=BEAT_ROWS, first_bar=1, leading_rest=.75, last_bar=1):
    (root / "score.abc").write_text(abc)
    mapping = [dict(index=0, start=0, end=ORIGIN, score_start=0, score_end=first_bar, leading_rest=leading_rest),
               dict(index=1, start=ORIGIN, end=1.6, score_start=first_bar, score_end=first_bar + 1),
               dict(index=2, start=1.6, end=ENDING, score_start=first_bar + 1, score_end=first_bar + 1 + last_bar)]
    (root / "playback.json").write_text(json.dumps({"measures": mapping}))
    (root / "notation").mkdir()
    (root / "notation/song_beats.txt").write_text("".join("\t".join(map(str, row)) + "\n" for row in beats))
    (root / "notation/song_chords.txt").write_text("0\t0.28\tN\n0.28\t1.6\tG:maj\n1.6\t2.88\tD:maj\n")
    (root / "notation/song_keys.txt").write_text("0\t2.88\tG:maj\n")
    _raw_vocal(root / "melody_vocal.mid")
    observed = [dict(zip(("time_seconds", "beat", "numerator", "denominator"), row, strict=True)) for row in beats[1:-1]]
    # Only the four cells before the first downbeat establish the eligibility for removal.
    grid = [a[0] + (min(b[0], ENDING) - a[0]) * i / 4 for a, b in zip(beats, beats[1:]) for i in range(4)] + [ENDING]
    return {"beat_clock": {"leading_derived_count": 1, "observed_beat_rows": observed,
                           "phase_compatible_downbeat_rows": [row for row in observed if row["beat"] == 1]},
            "grid_audio_seconds": grid, "source_note_indices": [-1] * (len(grid) - 1)}, mapping


def test_verified_preroll_uses_source_origin_and_preserves_terminal_harmony(tmp_path):
    interpretation, mapping = _native(tmp_path)
    legacy, current = tmp_path / "legacy.musicxml", tmp_path / "current.musicxml"
    assert import_native_lead_sheet(tmp_path, legacy)["measures"] == 3
    result = import_native_lead_sheet(tmp_path, current, interpretation=interpretation)
    assert result["measures"] == 2
    assert result["omitted_empty_preroll_measure"] == {
        "native_measure_index": 0, "native_measure": mapping[0], "first_published_native_measure_index": 1,
    }
    assert result["initial_audio_offset_seconds"] == ORIGIN
    assert json.loads((tmp_path / "playback.json").read_text())["measures"] == mapping
    score = converter.parse(current)
    assert score_audio_origin(score) == ORIGIN
    assert [m.number for m in score.parts[0].getElementsByClass(stream.Measure)] == [1, 2]
    assert score.parts[0].measure(1).timeSignature.ratioString == "4/4"
    assert score.parts[0].measure(1).keySignature.sharps == 1
    assert isinstance(score.parts[0].measure(1).clef, clef.AltoClef)
    assert score_time_clocks(score)[0](8) == pytest.approx(ENDING, abs=1e-8)
    xml = ET.parse(current)
    assert len(xml.findall("./part/measure[2]/harmony")) == 1
    assert xml.find("./part/measure[2]/note/rest").get("measure") == "yes"
    assert all(float(sound.attrib["tempo"]) < 60_000_000 for sound in xml.findall(".//sound[@tempo]"))

    old_midi = musicxml_to_midi(legacy, tmp_path / "legacy.mid")
    new_midi = musicxml_to_midi(current, tmp_path / "current.mid")
    smf = mido.MidiFile(new_midi)
    max_tick_seconds = max(event.tempo for track in smf.tracks for event in track if event.type == "set_tempo") / (1e6 * smf.ticks_per_beat)
    original_notes, current_notes = midi_notes(old_midi), midi_notes(new_midi)
    assert [item.pitch for item in current_notes] == [item.pitch for item in original_notes]
    for original, corrected in zip(original_notes, current_notes, strict=True):
        assert corrected.onset == pytest.approx(original.onset, abs=max_tick_seconds + 3e-6)
        assert corrected.offset == pytest.approx(original.offset, abs=max_tick_seconds + 3e-6)

    renderer = _verovio_toolkit()
    assert renderer.loadFile(str(current))
    svg = ET.fromstring(renderer.renderToSVG(1))
    rendered_measures = [e for e in svg.iter() if "measure" in e.get("class", "").split()]
    assert len(rendered_measures) == 2
    assert any("note" in e.get("class", "").split() for e in rendered_measures[0].iter())


@pytest.mark.parametrize("evidence", ["raw_pickup", "written_pickup", "occupied_grid", "observed_opening", "clock_disagreement",
                                       "chord", "key_change", "structure_change", "annotation", "repeat", "coda", "short_meter"])
def test_opening_with_content_or_insufficient_provenance_stays(tmp_path, evidence):
    abc = ABC
    beats, first_bar, leading_rest = BEAT_ROWS, 1, .75
    if evidence == "written_pickup":
        abc = abc.replace(EMPTY_PICKUP, "z6 g2 |")
    elif evidence == "annotation":
        abc = abc.replace(EMPTY_PICKUP, '"^Opening" z8 |')
    elif evidence == "repeat":
        abc = abc.replace(EMPTY_PICKUP, "z8 |:")
    elif evidence == "coda":
        abc = abc.replace(EMPTY_PICKUP, "!coda! z8 |")
    elif evidence == "short_meter":
        abc = abc.replace("M:4/4", "M:3/4").replace(EMPTY_PICKUP, "z6 |\nM:4/4", 1)
        beats, first_bar, leading_rest = [(0, 3, 3, 4), *BEAT_ROWS[1:]], .75, .5
    interpretation, _ = _native(tmp_path, abc=abc, beats=beats, first_bar=first_bar, leading_rest=leading_rest)
    if evidence == "raw_pickup":
        _raw_vocal(tmp_path / "melody_vocal.mid", onset=.1)
    elif evidence == "occupied_grid":
        interpretation["source_note_indices"][0] = 0
    elif evidence == "observed_opening":
        interpretation["beat_clock"]["leading_derived_count"] = 0
    elif evidence == "clock_disagreement":
        interpretation["beat_clock"]["phase_compatible_downbeat_rows"] = []
    elif evidence == "chord":
        (tmp_path / "notation/song_chords.txt").write_text("0\t0.14\tN\n0.14\t2.88\tG:maj\n")
    elif evidence == "key_change":
        (tmp_path / "notation/song_keys.txt").write_text("0\t0.14\tF:maj\n0.14\t2.88\tG:maj\n")
    elif evidence == "structure_change":
        (tmp_path / "notation/song_structures.txt").write_text("0\t0.14\tintro\n0.14\t2.88\tverse\n")
    result = import_native_lead_sheet(tmp_path, tmp_path / "score.musicxml", interpretation=interpretation)
    assert result["measures"] == 3
    assert result["initial_audio_offset_seconds"] == 0
    assert "omitted_empty_preroll_measure" not in result


def test_preroll_candidate_must_pass_native_measure_validation(tmp_path):
    interpretation, mapping = _native(tmp_path)
    mapping[0]["score_end"] = .75
    (tmp_path / "playback.json").write_text(json.dumps({"measures": mapping}))
    target = tmp_path / "score.musicxml"
    with pytest.raises(ValueError, match="beat/measure grid"):
        import_native_lead_sheet(tmp_path, target, interpretation=interpretation)
    assert not target.exists()


def test_preroll_keeps_later_meter_and_clipped_note_release(tmp_path):
    abc = ABC.replace("z8 |]", "M:3/4\nz4 d2 |]")
    beats = [*BEAT_ROWS[:5], (1.6, 1, 3, 4), (2.04, 2, 3, 4), (2.49, 3, 3, 4), (2.94, 1, 3, 4)]
    interpretation, _ = _native(tmp_path, abc=abc, beats=beats, last_bar=.75)
    target = tmp_path / "score.musicxml"
    assert import_native_lead_sheet(tmp_path, target, interpretation=interpretation)["measures"] == 2
    score = converter.parse(target)
    assert [m.ratioString for m in score.recurse().getElementsByClass(meter.TimeSignature)] == ["4/4", "3/4"]
    output = musicxml_to_midi(target, tmp_path / "score.mid")
    assert midi_notes(output)[-1].offset == pytest.approx(ENDING, abs=.00005)


def test_preroll_keeps_chord_quantized_on_original_clock_near_cell_midpoint(tmp_path):
    interpretation, _ = _native(tmp_path)
    # This transition falls between the decision boundaries with and without the old 3 µs pad.
    (tmp_path / "notation/song_chords.txt").write_text("0\t0.28\tN\n0.28\t0.407500001\tG:maj\n"
                                                     "0.407500001\t1.6\tA:min\n1.6\t2.88\tD:maj\n")
    prior = import_native_lead_sheet(tmp_path, tmp_path / "prior.musicxml")
    after = import_native_lead_sheet(tmp_path, tmp_path / "after.musicxml", interpretation=interpretation)
    assert prior["timed_metadata"]["chords"][1]["score_quarters"] == 4.25
    assert after["timed_metadata"]["chords"][1]["score_quarters"] == .25


def test_observed_full_opening_rest_is_kept(tmp_path):
    interpretation, mapping = _native(tmp_path)
    shift = 1.04
    for row in mapping:
        if row["start"]:
            row["start"] += shift
        row["end"] += shift
    mapping[0]["leading_rest"] = 0
    starting_measure = [(0, 1, 4, 4), (.33, 2, 4, 4), (.66, 3, 4, 4), (.99, 4, 4, 4)]
    beats = [*starting_measure, *((t + shift, b, n, d) for t, b, n, d in BEAT_ROWS[1:])]
    (tmp_path / "playback.json").write_text(json.dumps({"measures": mapping}))
    (tmp_path / "notation/song_beats.txt").write_text("".join("\t".join(map(str, row)) + "\n" for row in beats))
    _raw_vocal(tmp_path / "melody_vocal.mid", onset=ORIGIN + shift)
    interpretation["beat_clock"]["leading_derived_count"] = 0
    target = tmp_path / "score.musicxml"
    assert import_native_lead_sheet(tmp_path, target, interpretation=interpretation)["measures"] == 3
    assert ET.parse(target).find("./part/measure[1]/note/rest").get("measure") == "yes"

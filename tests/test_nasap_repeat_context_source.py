"""Additional source serialization/admission contracts, without cohort inference."""
from __future__ import annotations

import copy
import io
import struct
from fractions import Fraction

import mido
import pytest

from scripts import nasap_repeat_context_source as source


def binary32(value):
    return struct.unpack("!f", struct.pack("!f", float(value)))[0]


def row(nid, onset, duration, pitch, *, serialized=False, voice="1"):
    def value(number):
        return repr(binary32(number)) if serialized else str(number)
    return {"id": nid + "-1", "onset_quarter": value(onset), "onset_beat": value(onset),
            "duration_quarter": value(duration), "duration_beat": value(duration),
            "pitch": str(pitch), "voice": voice}


def score_xml(second):
    return ('''<score-partwise><part id="P1"><measure number="1">
    <attributes><divisions>12</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
    <note id="n1"><pitch><step>C</step><octave>4</octave></pitch><duration>48</duration><voice>1</voice></note>
    </measure><measure number="2">''' + second + '</measure></part></score-partwise>').encode()


TRIPLET_XML = score_xml('''
<note id="n2"><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration><voice>1</voice></note>
<note id="n3"><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration><voice>1</voice></note>
<note><rest/><duration>46</duration><voice>1</voice></note>''')


def triplet_rows(serialized=True):
    return [row("n1", 0, 4, 60, serialized=serialized),
            row("n2", 4, Fraction(1, 12), 62, serialized=serialized),
            row("n3", Fraction(49, 12), Fraction(1, 12), 64, serialized=serialized)]


@pytest.fixture
def parser():
    return source.previous._parser(source.load_manifest())


def test_manifest_has_distinct_population_and_complete_budget():
    m = source.load_manifest()
    assert [c["id"] for c in m["cases"]] == ["nasap005", "nasap006", "nasap007", "nasap008"]
    assert [c["score_id"] for c in m["cases"]] == ["score003", "score003", "score004", "score004"]
    assert m["budget"] == {"member_count": 25, "total_bytes": 2360916,
        "input_member_count": 8, "input_bytes": 69674, "maximum_member_bytes": 4000000}
    assert m["combined_independent_workdirs"] == {"actual_member_reads_cold": 50,
        "actual_bytes_cold": 4602128, "unique_member_count": 49,
        "unique_member_bytes": 3985273, "metadata_downloaded_twice": True}
    assert m["selection"]["replacements"] == []
    assert m["selection_before_source_read"]["source_outcomes_inspected"] is False


@pytest.mark.parametrize("mutation", ["case_order", "window", "proof", "budget", "metadata"])
def test_manifest_population_and_selection_evidence_fail_closed(mutation):
    m = copy.deepcopy(source.load_manifest())
    if mutation == "case_order":
        m["cases"][0], m["cases"][1] = m["cases"][1], m["cases"][0]
    elif mutation == "window":
        m["selection"]["length_q"] = 24
    elif mutation == "proof":
        m["selection_before_source_read"]["source_outcomes_inspected"] = True
    elif mutation == "budget":
        m["budget"]["total_bytes"] -= 1
    else:
        m["members"]["metadata.csv"]["sha256"] = "0" * 64
    with pytest.raises(ValueError):
        source.validate_manifest(m)


def test_manifest_byte_digest_checked(tmp_path, monkeypatch):
    p = tmp_path / "manifest.json"
    p.write_bytes(source.MANIFEST_PATH.read_bytes() + b" ")
    monkeypatch.setattr(source, "MANIFEST_PATH", p)
    with pytest.raises(ValueError, match="digest"):
        source.load_manifest()


@pytest.mark.parametrize("actual,expected", [("0.25", Fraction(1, 4)), ("-0.0", 0),
                                             (Fraction(1, 12), Fraction(1, 12))])
def test_exact_fraction_route(actual, expected):
    assert source.serialization_kind(actual, expected) == "exact"


@pytest.mark.parametrize("actual,expected", [("0.083333336", Fraction(1, 12)),
                                             ("87.083336", Fraction(1045, 12)),
                                             ("1000.00001", Fraction(1000))])
def test_binary32_identity_route_is_discrete(actual, expected):
    assert source.serialization_kind(actual, expected) == "binary32"


def test_adjacent_binary32_value_is_rejected_even_with_tiny_absolute_delta():
    value = Fraction(1, 12)
    bits = int.from_bytes(struct.pack("!f", float(value)), "big")
    adjacent = struct.unpack("!f", (bits + 1).to_bytes(4, "big"))[0]
    assert abs(adjacent - float(value)) < 1e-7
    with pytest.raises(source.AdmissionError, match="serialization_mismatch"):
        source.serialization_kind(repr(adjacent), value)


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "not-a-number", None])
def test_nonfinite_or_malformed_scalar_not_admitted(value):
    with pytest.raises(source.AdmissionError):
        source.serialization_kind(value, Fraction(1, 12))


def test_binary32_contract_keeps_xml_fraction_truth_and_original_rows(parser):
    rows = triplet_rows()
    original = copy.deepcopy(rows)
    canonical, receipt = source.canonical_score(TRIPLET_XML, rows, parser)
    assert rows == original
    assert canonical["n2-1"]["duration"] == Fraction(1, 12)
    assert canonical["n3-1"]["onset"] == Fraction(49, 12)
    assert canonical["n3-1"]["onset"] != Fraction(rows[2]["onset_quarter"])
    assert receipt["checked_timing_scalars"] == 12
    assert receipt["exact_timing_scalars"] == 6
    assert receipt["binary32_admitted_timing_scalars"] == 6
    assert receipt["exact_fraction_mismatches"] == 6
    assert receipt["exact_mismatch_note_count"] == 2
    assert receipt["previous_strict_canonical_status"] == "failed"
    assert receipt["previous_strict_failure_reason"] == "xml_csv_canonical_mismatch"
    assert receipt["absolute_or_relative_tolerance_used"] is False
    assert receipt["mismatches_inside_evaluation_window"] == 6
    assert receipt["mismatches_outside_evaluation_window"] == 0
    assert receipt["all_mismatches_outside_evaluation_window"] is False


def test_exact_source_records_no_binary32_admission(parser):
    canonical, receipt = source.canonical_score(TRIPLET_XML, triplet_rows(False), parser)
    assert canonical["n2-1"]["duration"] == Fraction(1, 12)
    assert receipt["checked_timing_scalars"] == receipt["exact_timing_scalars"] == 12
    assert receipt["binary32_admitted_timing_scalars"] == 0
    assert receipt["max_abs_difference_q"] == 0
    assert receipt["previous_strict_canonical_status"] == "passed"
    assert receipt["previous_strict_failure_reason"] is None
    assert receipt["all_mismatches_outside_evaluation_window"] is None


@pytest.mark.parametrize("field", source.TIMING_FIELDS)
def test_every_timing_scalar_is_verified(field, parser):
    rows = triplet_rows()
    rows[2][field] = "123.456"
    with pytest.raises(source.AdmissionError, match="serialization_mismatch"):
        source.canonical_score(TRIPLET_XML, rows, parser)


@pytest.mark.parametrize("change", ["pitch", "voice", "missing", "duplicate", "occurrence"])
def test_serialization_does_not_relax_symbolic_identity(change, parser):
    rows = triplet_rows()
    if change == "pitch":
        rows[2]["pitch"] = "65"
    elif change == "voice":
        rows[2]["voice"] = "2"
    elif change == "missing":
        rows.pop()
    elif change == "duplicate":
        rows.append(dict(rows[2]))
    else:
        rows[2]["id"] = "n3-2"
    with pytest.raises(source.AdmissionError):
        source.canonical_score(TRIPLET_XML, rows, parser)


def test_tie_continuation_must_be_contiguous(parser):
    raw = score_xml('<note id="n2"><pitch><step>C</step><octave>4</octave></pitch>'
                    '<duration>48</duration><tie type="stop"/><voice>1</voice></note>')
    with pytest.raises(source.AdmissionError):
        source.canonical_score(raw, [row("n1", 0, 8, 60)], parser)


def test_grace_canonical_position_remains_an_exact_xml_fraction(parser):
    raw = score_xml('''<note id="n2"><pitch><step>D</step><octave>4</octave></pitch><duration>4</duration><voice>1</voice></note>
    <note id="g1"><grace/><pitch><step>F</step><octave>4</octave></pitch><voice>1</voice></note>
    <note id="n3"><pitch><step>E</step><octave>4</octave></pitch><duration>44</duration><voice>1</voice></note>''')
    rows = [row("n1", 0, 4, 60), row("n2", 4, Fraction(1, 3), 62, serialized=True),
            row("g1", Fraction(13, 3), 0, 65, serialized=True),
            row("n3", Fraction(13, 3), Fraction(11, 3), 64, serialized=True)]
    canonical, receipt = source.canonical_score(raw, rows, parser)
    assert canonical["g1-1"]["onset"] == Fraction(13, 3)
    assert canonical["g1-1"]["duration"] == 0 and canonical["g1-1"]["grace"] is True
    assert receipt["binary32_admitted_timing_scalars"] > 0


def midi_bytes():
    midi = mido.MidiFile(type=1, ticks_per_beat=384)
    midi.tracks.append(mido.MidiTrack([mido.MetaMessage("set_tempo", tempo=500000),
                                     mido.MetaMessage("end_of_track")]))
    midi.tracks.append(mido.MidiTrack([mido.Message("note_on", note=60, velocity=71, time=1152),
                                     mido.Message("note_off", note=60, velocity=0, time=96),
                                     mido.MetaMessage("end_of_track", time=14000)]))
    out = io.BytesIO()
    midi.save(file=out)
    return out.getvalue()


def beat_bytes():
    rows = []
    for i in range(42):
        t = .5 + .5 * i
        tag = "db" if i >= 2 and (i - 2) % 4 == 0 else "b"
        if i == 2:
            tag += ",4/4"
        rows.append(f"{t}\t{t}\t{tag}")
    return ("\n".join(rows) + "\n").encode()


def test_input_stage_opens_only_new_midi_and_performance_annotations(tmp_path, monkeypatch):
    manifest, accessed = source.load_manifest(), []
    old_hash, old_pairs = source.previous.MANIFEST_SHA256, source.previous.CASE_PAIRS
    def get(reader, path):
        accessed.append(path)
        if path.endswith(".mid"):
            return midi_bytes()
        assert path.endswith("_annotations.txt") and not path.endswith("midi_score_annotations.txt")
        return beat_bytes()
    monkeypatch.setattr(source.SourceReader, "get", get)
    result = source.prepare_inputs(tmp_path)
    assert set(accessed) == {c[k] for c in manifest["cases"] for k in source.previous.INPUT_FIELDS}
    assert [c["id"] for c in result["cases"]] == ["nasap005", "nasap006", "nasap007", "nasap008"]
    assert all(c["scope"] == "real_additional_same_score" for c in result["cases"])
    assert all(c["events"][0].onset_q == 0 and c["events"][0].velocity == 71 for c in result["cases"])
    assert all(not {"score_id", "performance_id", "evaluation", "target_notes"} & set(c) for c in result["cases"])
    assert source.previous.MANIFEST_SHA256 == old_hash and source.previous.CASE_PAIRS == old_pairs


def test_individual_input_failure_keeps_new_scope_and_planned_row(tmp_path, monkeypatch):
    manifest = source.load_manifest()
    def get(reader, path):
        if path == manifest["cases"][0]["midi"]:
            return b"invalid midi"
        return midi_bytes() if path.endswith(".mid") else beat_bytes()
    monkeypatch.setattr(source.SourceReader, "get", get)
    result = source.prepare_inputs(tmp_path)
    assert len(result["cases"]) == 4
    assert result["cases"][0]["status"] == "failed"
    assert result["cases"][0]["scope"] == "real_additional_same_score"
    assert result["source_receipt"]["complete_recordings"] == 3
    assert result["source_receipt"]["failed_recordings"] == 1


def test_global_integrity_failure_is_not_a_replaceable_case(tmp_path, monkeypatch):
    def get(*args):
        raise ValueError("source byte identity mismatch")
    monkeypatch.setattr(source.SourceReader, "get", get)
    with pytest.raises(ValueError, match="identity"):
        source.prepare_inputs(tmp_path)


def test_receipt_uses_new_manifest_and_stage_counters(tmp_path):
    reader = source.SourceReader(tmp_path, source.load_manifest())
    receipt = reader.receipt("inputs", [{"status": "complete"}] * 4)
    assert receipt["manifest_sha256"] == source.MANIFEST_SHA256
    assert receipt["manifest_sha256"] != source.previous.MANIFEST_SHA256
    assert receipt["full_source_bytes"] == 2360916
    assert receipt["scope"] == "real_additional_same_score"
    assert receipt["stage_counters_are_cumulative"] is False


def test_delayed_evaluation_rejects_old_or_reordered_population_before_read(tmp_path, monkeypatch):
    monkeypatch.setattr(source.SourceReader, "get", lambda *a: pytest.fail("source read before population validation"))
    with pytest.raises(ValueError, match="population"):
        source.load_evaluation(tmp_path, [{"id": f"nasap{i:03d}"} for i in range(1, 5)])

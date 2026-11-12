"""Synthetic source contracts; no real-cohort inference or network is run."""
from __future__ import annotations

import copy
import io
import json
from fractions import Fraction
from pathlib import Path

import mido
import pytest

from scripts import nasap_same_score_source as source

ROOT = Path(source.__file__).resolve().parents[1]


def midi_bytes(notes=None, tempos=((0, 500000),), controls=(), end_tick=15000):
    notes = [(1152, 1300, 60, 71), (1400, 1500, 64, 83)] if notes is None else notes
    midi = mido.MidiFile(type=1, ticks_per_beat=384)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    before = 0
    for tick, tempo in tempos:
        track.append(mido.MetaMessage("set_tempo", tempo=tempo, time=tick - before))
        before = tick
    track.append(mido.MetaMessage("end_of_track", time=0))
    track = mido.MidiTrack()
    midi.tracks.append(track)
    messages = []
    for index, (on, off, pitch, velocity) in enumerate(notes):
        messages.append((on, index * 2 + 1, mido.Message("note_on", note=pitch, velocity=velocity)))
        if off is not None:
            messages.append((off, index * 2, mido.Message("note_off", note=pitch, velocity=0)))
    for index, (tick, controller, value) in enumerate(controls):
        messages.append((tick, 10000 + index, mido.Message("control_change", control=controller, value=value)))
    before = 0
    for tick, _, msg in sorted(messages, key=lambda x: x[:2]):
        track.append(msg.copy(time=tick - before))
        before = tick
    track.append(mido.MetaMessage("end_of_track", time=max(end_tick, before) - before))
    out = io.BytesIO()
    midi.save(file=out)
    return out.getvalue()


def annotations(count=42, start=.5, step=.5, first_downbeat=2):
    rows = []
    for i in range(count):
        label = "db" if i >= first_downbeat and (i - first_downbeat) % 4 == 0 else "b"
        label += ",4/4" if i == first_downbeat else ""
        t = start + step * i
        rows.append(f"{t}\t{t}\t{label}")
    return ("\n".join(rows) + "\n").encode()


def test_manifest_population_and_literal_budget():
    manifest = source.load_manifest()
    assert [c["id"] for c in manifest["cases"]] == [f"nasap{i:03d}" for i in range(1, 5)]
    assert manifest["budget"] == {"member_count": 25, "total_bytes": 2241212,
        "input_member_count": 8, "input_bytes": 48459, "maximum_member_bytes": 4000000}
    assert len({c["xml"] for c in manifest["cases"]}) == 2
    assert manifest["selection"]["fresh_holdout_claimed"] is False
    assert set(manifest["parser_dependencies"]) == set(source.PARSER_PATHS)


def test_manifest_tampering_fails_before_source_access(tmp_path, monkeypatch):
    p = tmp_path / "manifest.json"
    p.write_bytes(source.MANIFEST_PATH.read_bytes() + b" ")
    monkeypatch.setattr(source, "MANIFEST_PATH", p)
    with pytest.raises(ValueError, match="manifest digest"):
        source.load_manifest()


@pytest.mark.parametrize("mutation", ["swap", "extra", "budget", "duration", "hash"])
def test_manifest_rejects_changed_population(mutation):
    m = copy.deepcopy(source.load_manifest())
    if mutation == "swap":
        m["cases"][0], m["cases"][1] = m["cases"][1], m["cases"][0]
    elif mutation == "extra":
        m["members"]["extra.mid"] = {"bytes": 1, "sha256": "0" * 64}
    elif mutation == "budget":
        m["budget"]["total_bytes"] -= 1
    elif mutation == "duration":
        m["selection"]["length_q"] = 60
    else:
        m["members"]["metadata.csv"]["sha256"] = "0" * 64
    with pytest.raises(ValueError):
        source.validate_manifest(m)


@pytest.mark.parametrize("path", ["../x", "/x", "x//y", "x/../y", "x?query", "x\\y", "x\ny"])
def test_unsafe_members_refused(path):
    with pytest.raises(ValueError, match="unsafe"):
        source._safe_path(path)


def reader_fixture(tmp_path, raw=b"original"):
    manifest = {"members": {"member.txt": {"bytes": len(raw), "sha256": source.sha256(raw)}}}
    return source.SourceReader(tmp_path, manifest), raw


def test_corrupt_cache_never_replaced_or_downloaded(tmp_path, monkeypatch):
    reader, raw = reader_fixture(tmp_path)
    p = tmp_path / "member.txt"
    p.write_bytes(b"tampered")
    monkeypatch.setattr(source.urllib.request, "urlopen", lambda *a, **k: pytest.fail("network after bad cache"))
    with pytest.raises(ValueError, match="identity"):
        reader.get("member.txt")
    assert p.read_bytes() != raw


def test_exact_cache_counts_a_member_once(tmp_path):
    reader, raw = reader_fixture(tmp_path)
    (tmp_path / "member.txt").write_bytes(raw)
    assert reader.get("member.txt") == raw
    assert reader.get("member.txt") == raw
    assert reader.cache_hits == 1 and reader.http_requests == reader.downloaded_bytes == 0


def test_linked_cache_refused(tmp_path):
    reader, raw = reader_fixture(tmp_path)
    (tmp_path / "other").write_bytes(raw)
    (tmp_path / "member.txt").symlink_to(tmp_path / "other")
    with pytest.raises(ValueError, match="linked"):
        reader.get("member.txt")


class Response:
    def __init__(self, raw, *, url=None, status=200, headers=None):
        self.raw, self.status = raw, status
        self.url = source.SOURCE_BASE + "member.txt" if url is None else url
        self.headers = {"Content-Length": str(len(raw))} if headers is None else headers
        self.read_limits = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, n):
        self.read_limits.append(n)
        return self.raw[:n]


def test_exact_bounded_download_and_reuse(tmp_path, monkeypatch):
    reader, raw = reader_fixture(tmp_path)
    response = Response(raw)
    monkeypatch.setattr(source.urllib.request, "urlopen", lambda *a, **k: response)
    assert reader.get("member.txt") == raw
    assert response.read_limits == [len(raw) + 1]
    assert reader.http_requests == 1 and reader.downloaded_bytes == len(raw)
    assert (tmp_path / "member.txt").read_bytes() == raw


@pytest.mark.parametrize("kind", ["redirect", "status", "encoding", "length", "digest", "oversize"])
def test_download_identity_fail_closed(tmp_path, monkeypatch, kind):
    reader, raw = reader_fixture(tmp_path)
    kwargs, payload = {}, raw
    if kind == "redirect":
        kwargs["url"] = "https://example.invalid/member.txt"
    elif kind == "status":
        kwargs["status"] = 206
    elif kind == "encoding":
        kwargs["headers"] = {"Content-Encoding": "gzip"}
    elif kind == "length":
        kwargs["headers"] = {"Content-Length": "999"}
    elif kind == "digest":
        payload = b"tampered"
    else:
        payload = raw + b"x"
        kwargs["headers"] = {}
    monkeypatch.setattr(source.urllib.request, "urlopen", lambda *a, **k: Response(payload, **kwargs))
    with pytest.raises(ValueError):
        reader.get("member.txt")
    assert not (tmp_path / "member.txt").exists()


def test_original_midi_clock_is_seconds_not_symbolic_beats():
    raw = midi_bytes([(1152, 1400, 60, 71)])
    notes, _, summary = source.parse_midi(raw)
    assert notes[0]["onset_sec"] == 1.5
    assert summary["single_encoding_tempo_us_per_quarter"] == 500000
    assert summary["midi_tempo_used_as_musical_score_clock"] is False
    events, _, _ = source.parse_input(raw, annotations())
    assert events[0].onset_q == 0.0
    assert 1152 / 384 == 3.0


def test_piecewise_midi_tempo_converts_before_supplied_clock():
    raw = midi_bytes([(1536, 1600, 60, 80)], tempos=((0, 500000), (768, 1000000)))
    notes, _, summary = source.parse_midi(raw)
    assert notes[0]["onset_sec"] == 3.0
    assert summary["source_tempo_unique_count"] == 2
    events, _, _ = source.parse_input(raw, annotations())
    assert events[0].onset_q == 3.0


def test_fixed_half_open_window_preserves_microtiming_velocity_and_note_off():
    raw = midi_bytes([(1000, 1100, 59, 30), (1152, 1400, 60, 71),
                      (1401, 1450, 60, 83), (13439, 14000, 65, 101), (13440, 14000, 67, 44)],
                     controls=((1200, 64, 127), (14100, 64, 0)))
    events, state, receipt = source.parse_input(raw, annotations())
    assert [e.event_id for e in events] == ["e000001", "e000002", "e000003"]
    assert [e.velocity for e in events] == [71, 83, 101]
    assert events[1].onset_q == pytest.approx((1401 / 768 - 1.5) * 2, abs=1e-14)
    assert 31 < events[-1].onset_q < 32
    assert state["notes"][state["selected"][-1]]["offset_sec"] > state["clock"]["end_s"]
    assert receipt["source_note_on_count"] == 5
    assert receipt["selected_note_on_count"] == 3
    assert receipt["excluded_before_window"] == receipt["excluded_at_or_after_window"] == 1
    assert receipt["source_controller_count"] == 2
    assert receipt["performance_export_verified"] is False


def test_key_release_and_controller_changes_do_not_change_onset_input():
    first = source.parse_input(midi_bytes([(1152, 1250, 60, 70)]), annotations())
    second = source.parse_input(midi_bytes([(1152, 1500, 60, 70)], controls=((1200, 64, 127),)), annotations())
    assert first[0] == second[0]
    assert first[2]["input_events_sha256"] == second[2]["input_events_sha256"]
    assert first[2]["source_note_events_sha256"] != second[2]["source_note_events_sha256"]
    assert first[2]["source_controllers_sha256"] != second[2]["source_controllers_sha256"]


def test_missing_key_off_stays_an_onset_and_is_counted():
    events, state, receipt = source.parse_input(midi_bytes([(1152, None, 60, 70)]), annotations())
    assert len(events) == 1 and state["notes"][0]["offset_sec"] is None
    assert receipt["missing_key_release_count"] == 1


@pytest.mark.parametrize("raw", [b"", b"bad midi", midi_bytes() + b"extra"])
def test_malformed_midi_refused(raw):
    with pytest.raises(source.AdmissionError):
        source.parse_midi(raw)


@pytest.mark.parametrize("change", ["short", "duplicate", "irregular", "meter", "phase", "nan"])
def test_clock_admission_refuses_unsupported_context(change):
    rows = annotations().decode().splitlines()
    if change == "short":
        rows = rows[:30]
    elif change == "duplicate":
        rows[4] = rows[3]
    elif change == "irregular":
        rows[8] = rows[8].replace("\tb", "\tbR")
    elif change == "meter":
        rows[2] = rows[2].replace("4/4", "3/4")
    elif change == "phase":
        rows[7] = rows[7].rsplit("\t", 1)[0] + "\tdb"
    else:
        rows[0] = "nan\tnan\tb"
    with pytest.raises(source.AdmissionError):
        source.parse_annotations(("\n".join(rows) + "\n").encode())


def test_clock_never_extrapolates():
    clock = source.parse_annotations(annotations())
    with pytest.raises(source.AdmissionError, match="extrapolation"):
        source._clock_q(clock["times"][0] - .001, clock)
    with pytest.raises(source.AdmissionError, match="extrapolation"):
        source._clock_q(clock["times"][-1] + .001, clock)


def test_prepare_inputs_never_opens_evaluation_files_and_preserves_failure(tmp_path, monkeypatch):
    manifest, reads = source.load_manifest(), []
    def get(reader, path):
        reads.append(path)
        if path.endswith(".mid"):
            return b"bad midi" if path == manifest["cases"][1]["midi"] else midi_bytes()
        assert path.endswith("_annotations.txt") and not path.endswith("midi_score_annotations.txt")
        return annotations()
    monkeypatch.setattr(source.SourceReader, "get", get)
    monkeypatch.setattr(source, "_parser", lambda *a: pytest.fail("score parser during input"))
    prepared = source.prepare_inputs(tmp_path)
    assert set(reads) == {c[k] for c in manifest["cases"] for k in source.INPUT_FIELDS}
    assert [c["status"] for c in prepared["cases"]] == ["complete", "failed", "complete", "complete"]
    assert prepared["cases"][1]["events"] == ()
    assert prepared["source_receipt"]["complete_recordings"] == 3
    assert prepared["source_receipt"]["failed_recordings"] == 1
    for case in prepared["cases"]:
        assert not {"score_id", "performance_id", "target_notes", "evaluation"} & set(case)


def test_prepare_inputs_does_not_swallow_integrity_errors(tmp_path, monkeypatch):
    def get(*args):
        raise ValueError("source byte identity mismatch")
    monkeypatch.setattr(source.SourceReader, "get", get)
    with pytest.raises(ValueError, match="identity"):
        source.prepare_inputs(tmp_path)


def test_source_unavailability_keeps_the_planned_case(tmp_path, monkeypatch):
    manifest = source.load_manifest()
    def get(reader, path):
        if path == manifest["cases"][2]["midi"]:
            raise source.AdmissionError("source_unavailable")
        return midi_bytes() if path.endswith(".mid") else annotations()
    monkeypatch.setattr(source.SourceReader, "get", get)
    result = source.prepare_inputs(tmp_path)
    assert len(result["cases"]) == 4
    assert result["cases"][2]["receipt"]["failure"] == "source_unavailable"
    assert result["source_receipt"]["failed_recordings"] == 1


def test_evaluation_rejects_population_reordering_before_read(tmp_path, monkeypatch):
    cases = [{"id": f"nasap{i:03d}"} for i in (2, 1, 3, 4)]
    monkeypatch.setattr(source.SourceReader, "get", lambda *a: pytest.fail("read before population check"))
    with pytest.raises(ValueError, match="population"):
        source.load_evaluation(tmp_path, cases)


def test_frozen_parser_dependency_is_checked_before_import():
    manifest = copy.deepcopy(source.load_manifest())
    manifest["parser_dependencies"][source.PARSER_PATHS[0]] = "0" * 64
    with pytest.raises(ValueError, match="parser dependency"):
        source._parser(manifest)


XML = b'''<score-partwise><part id="P1">
<measure number="1"><attributes><divisions>4</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
<note id="n1"><pitch><step>C</step><octave>4</octave></pitch><duration>16</duration><tie type="start"/><voice>1</voice></note></measure>
<measure number="2"><note id="n2"><pitch><step>C</step><octave>4</octave></pitch><duration>16</duration><tie type="stop"/><voice>1</voice></note></measure>
<measure number="3"><note id="n3"><grace/><pitch><step>D</step><octave>4</octave></pitch><voice>1</voice></note>
<note id="n4"><pitch><step>E</step><octave>4</octave></pitch><duration>16</duration><voice>1</voice></note></measure>
</part></score-partwise>'''


def canonical_rows():
    return [{"id": nid + "-1", "onset_quarter": str(on), "duration_quarter": str(duration),
             "onset_beat": str(on), "duration_beat": str(duration), "pitch": str(pitch)}
            for nid, on, duration, pitch in (("n1", 0, 8, 60), ("n3", 8, 0, 62), ("n4", 8, 4, 64))]


def test_xml_ties_and_grace_have_distinct_canonical_semantics():
    parser = source._parser(source.load_manifest())
    canonical = source.canonical_score(XML, canonical_rows(), parser)
    assert len(canonical) == 3 and "n2-1" not in canonical
    assert canonical["n1-1"]["duration"] == 8
    assert canonical["n3-1"]["grace"] is True
    assert canonical["n4-1"]["onset"] == 8


@pytest.mark.parametrize("change", ["pitch", "onset", "missing", "repeat", "occurrence"])
def test_canonical_mismatch_is_not_repaired(change):
    parser = source._parser(source.load_manifest())
    raw, rows = XML, canonical_rows()
    if change == "pitch":
        rows[0]["pitch"] = "61"
    elif change == "onset":
        rows[0]["onset_quarter"] = "0.25"
    elif change == "missing":
        rows.pop()
    elif change == "repeat":
        raw = raw.replace(b'</part>', b'<barline><repeat direction="backward"/></barline></part>')
    else:
        rows[0]["id"] = "n1-2"
    with pytest.raises(source.AdmissionError):
        source.canonical_score(raw, rows, parser)


def evaluation_fixture():
    raw = midi_bytes([(768, 900, 67, 60), (1152, 1300, 60, 71),
                      (1536, 1700, 62, 80), (1920, 2050, 70, 81),
                      (2304, 2450, 72, 82), (2688, 2800, 74, 83)])
    events, state, _ = source.parse_input(raw, annotations())
    names = ["outside", "ordinary", "wrong_pitch", "extra", "grace", "outside_target"]
    score_ids = ["s3-1", "s1-1", "s2-1", "insertion", "g1-1", "s5-1"]
    pp, alignment = [], []
    for name, sid, note in zip(names, score_ids, state["notes"]):
        pp.append({"id": name, "track": str(note["track"]), "channel": str(note["channel"]),
                   "pitch": str(note["pitch"]), "onset_sec": str(note["onset_sec"]),
                   "velocity": str(note["velocity"]), "last_beat": ".5", "last_beat_ref": "2"})
        alignment.append({"xml_id": sid, "midi_id": name, "track": str(note["track"]),
                          "channel": str(note["channel"]), "pitch": str(note["pitch"]),
                          "onset": str(note["onset_sec"])})
    alignment.append({"xml_id": "s4-1", "midi_id": "deletion", "track": None,
                      "channel": None, "pitch": None, "onset": None})
    canonical = {sid: {"onset": Fraction(on), "duration": Fraction(0 if grace else 1),
                       "pitch": pitch, "grace": grace} for sid, on, pitch, grace in (
        ("s1-1", 4, 60, False), ("s2-1", 5, 64, False), ("s3-1", 6, 67, False),
        ("s4-1", 7, 68, False), ("g1-1", 8, 72, True), ("s5-1", 3, 74, False))}
    parts = [{"last_beat": "2", "last_beat_ref": ".5"} for _ in canonical]
    case = {"id": "nasap001", "score_id": "score001", "performance_id": "nasap001", "xml_sha256": "a" * 64}
    return case, state, canonical, parts, pp, alignment, annotations()


def test_all_target_and_input_denominators_survive_source_discrepancies():
    result = source.evaluate_source(*evaluation_fixture())
    r = result["receipt"]
    assert r["target_ordinary"] == 4 and r["target_grace"] == 1
    assert r["target_coverage_counts"] == {"observed": 3, "deletion": 1,
        "outside_input_window": 1, "ambiguous": 0, "unsupported_alignment": 0}
    assert r["input_classification_counts"] == {"ordinary_target": 2, "grace_target": 1,
        "insertion": 1, "matched_outside_target_window": 1, "unsupported": 0}
    assert r["observed_target_wrong_pitch_count"] == 1
    assert sum(r["input_classification_counts"].values()) == 5
    assert len(result["target_notes"]) == 5 and len(result["input_links"]) == 5
    wrong = next(t for t in result["target_notes"] if t["score_id"] == "s2-1")
    assert wrong["coverage"] == "observed" and wrong["pitch"] == 64 and wrong["event_id"] is not None


def test_ambiguous_alignment_does_not_drop_input_or_target():
    args = list(evaluation_fixture())
    args[5].append(dict(args[5][1]))
    result = source.evaluate_source(*args)
    assert result["receipt"]["target_notes"] == 5
    assert result["receipt"]["selected_note_on_count"] == 5
    assert result["receipt"]["target_coverage_counts"]["ambiguous"] == 1
    assert result["receipt"]["input_classification_counts"]["unsupported"] == 1


@pytest.mark.parametrize("field,value", [("track", "0"), ("channel", "1"), ("pitch", "61"), ("onset", "99")])
def test_alignment_identity_requires_track_channel_pitch_and_time(field, value):
    args = list(evaluation_fixture())
    args[5][1][field] = value
    result = source.evaluate_source(*args)
    assert result["receipt"]["unsupported_alignment_rows"] == 1
    assert result["receipt"]["input_classification_counts"]["unsupported"] == 1
    assert result["receipt"]["target_notes"] == 5


def test_wrong_author_origin_is_rejected_not_fitted():
    args = list(evaluation_fixture())
    args[4][0]["last_beat_ref"] = "3"
    with pytest.raises(source.AdmissionError, match="origin"):
        source.evaluate_source(*args)


def test_public_receipts_contain_no_raw_arrays_or_paths():
    events, _, receipt = source.parse_input(midi_bytes(), annotations())
    evaluated = source.evaluate_source(*evaluation_fixture())["receipt"]
    text = json.dumps([receipt, evaluated])
    for banned in ("onset_sec", "offset_sec", "target_notes\": [", "input_links\": [", "/tmp/", "last_beat_ref"):
        assert banned not in text
    assert len(events) == 2
    def walk(value):
        if isinstance(value, dict):
            for child in value.values():
                walk(child)
        else:
            assert not isinstance(value, (list, tuple))
    walk(receipt)
    walk(evaluated)

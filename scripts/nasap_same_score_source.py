"""Bounded nASAP source admission with a delayed written-score evaluator.

Input preparation reads only original performance MIDI and supplied performance
beat annotations. MIDI ticks encode seconds, not score quarters. Written score,
note alignment and author score-coordinate columns are opened only by the
explicit evaluation loader after the caller saves every prediction. Original
files remain private; public receipts contain hashes and derived counts only.
"""
from __future__ import annotations

import bisect
import csv
import hashlib
import importlib.metadata
import io
import json
import math
import re
import struct
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import asdict
from fractions import Fraction
from pathlib import Path, PurePosixPath

REVISION = "4097b45757bed854818cf87e77b92323ebf90615"
SOURCE_BASE = "https://raw.githubusercontent.com/CPJKU/asap-dataset/" + REVISION + "/"
MANIFEST_PATH = Path(__file__).with_name("nasap_same_score_manifest.json")
MANIFEST_SHA256 = "27c576542fef26dbca605db4a9f938cc00451702b2c7f441aa84013fe3496239"
METADATA_SHA256 = "5c6622cae9ae34643fc5b35150de5e2891fd8ffbddd1fd579fa6b984014e6924"
MIDO_VERSION = "1.3.3"
LENGTH_Q = 32.0
SCORE_ORIGIN_Q = Fraction(4)
MAX_FILE_BYTES = 4_000_000
MAX_MIDI_MESSAGES = 100_000
MAX_ROWS = 20_000
MIDI_ONSET_TOLERANCE_S = 1e-7
AUTHOR_BEAT_TOLERANCE_S = 1e-4
CASE_PAIRS = (
    ("bwv_848", "Denisova06M"), ("bwv_848", "Lee01M"),
    ("bwv_854", "LuA01M"), ("bwv_854", "MiyashitaM01M"),
)
PATH_FIELDS = ("midi", "performance_annotations", "xml", "score_annotations",
               "part", "ppart", "alignment")
INPUT_FIELDS = ("midi", "performance_annotations")
PARSER_PATHS = (
    "scripts/nasap_joint_rhythm.py", "scripts/nasap_duration_probe.py",
    "scripts/nasap_keyoff_paired.py", "scripts/audit_nasap_duration_source.py",
)
PART_FIELDS = ("onset_beat", "duration_beat", "onset_quarter", "duration_quarter",
               "onset_div", "duration_div", "pitch", "voice", "id",
               "last_beat", "last_beat_ref")
PPART_FIELDS = ("onset_sec", "duration_sec", "pitch", "velocity", "track", "channel",
                "id", "last_beat", "last_beat_ref")
ALIGNMENT_FIELDS = ("xml_id", "midi_id", "track", "channel", "pitch", "onset")
INPUT_CLASSES = ("ordinary_target", "grace_target", "insertion",
                 "matched_outside_target_window", "unsupported")
COVERAGE_CLASSES = ("observed", "deletion", "outside_input_window", "ambiguous",
                    "unsupported_alignment")


class AdmissionError(ValueError):
    """Case-level source semantics failure; the planned case remains present."""

    def __init__(self, code, diagnostics=None):
        super().__init__(code)
        self.code = code
        self.diagnostics = {} if diagnostics is None else diagnostics


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _admit(condition, reason):
    if not condition:
        raise AdmissionError(reason)


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def fingerprint(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                            allow_nan=False).encode())


def _safe_path(path):
    _require(isinstance(path, str) and path and not PurePosixPath(path).is_absolute()
             and "\\" not in path and "?" not in path and "#" not in path
             and all(p not in ("", ".", "..") for p in path.split("/"))
             and not any(ord(c) < 32 for c in path), "unsafe source path")


def validate_manifest(manifest):
    _require(manifest.get("schema_version") == 1
             and manifest.get("revision") == REVISION
             and manifest.get("source_base") == SOURCE_BASE
             and manifest.get("license") == "CC-BY-NC-SA-4.0", "source revision changed")
    cases, members = manifest.get("cases", []), manifest.get("members", {})
    _require(len(cases) == 4 and len(members) == 25, "fixed population changed")
    paths, input_paths = {"metadata.csv"}, set()
    for i, (case, (piece, take)) in enumerate(zip(cases, CASE_PAIRS)):
        base = "Bach/Fugue/" + piece + "/"
        expected = {"midi": base + take + ".mid",
                    "performance_annotations": base + take + "_annotations.txt",
                    "xml": base + "xml_score.musicxml",
                    "score_annotations": base + "midi_score_annotations.txt",
                    "part": base + take + "_note_alignments/parangonada_data/part.csv",
                    "ppart": base + take + "_note_alignments/parangonada_data/ppart.csv",
                    "alignment": base + take + "_note_alignments/note_alignment.tsv"}
        _require(case.get("id") == f"nasap{i + 1:03d}"
                 and case.get("performance_id") == case["id"]
                 and case.get("score_id") == f"score{i // 2 + 1:03d}"
                 and all(case.get(k) == v for k, v in expected.items()),
                 "case identity or order changed")
        paths.update(expected.values())
        input_paths.update(case[k] for k in INPUT_FIELDS)
    _require(set(members) == paths, "source member population changed")
    for path, item in members.items():
        _safe_path(path)
        _require(set(item) == {"bytes", "sha256"}
                 and type(item["bytes"]) is int and 0 < item["bytes"] <= MAX_FILE_BYTES
                 and isinstance(item["sha256"], str)
                 and re.fullmatch(r"[0-9a-f]{64}", item["sha256"]),
                 "invalid source member identity")
    _require(members["metadata.csv"]["sha256"] == METADATA_SHA256,
             "metadata identity changed")
    _require(manifest.get("budget") == {
        "member_count": 25, "total_bytes": sum(m["bytes"] for m in members.values()),
        "input_member_count": 8, "input_bytes": sum(members[p]["bytes"] for p in input_paths),
        "maximum_member_bytes": MAX_FILE_BYTES,
    }, "source budget changed")
    selection = manifest.get("selection", {})
    _require(selection.get("length_q") == LENGTH_Q and selection.get("bars") == 8
             and selection.get("meter") == "4/4"
             and selection.get("planned_recordings") == 4
             and selection.get("planned_scores") == 2
             and selection.get("fresh_holdout_claimed") is False
             and selection.get("predictions_before_evaluation_sources") is True,
             "source scope changed")
    _require(set(manifest.get("parser_dependencies", {})) == set(PARSER_PATHS)
             and manifest.get("mido_version") == MIDO_VERSION,
             "parser dependency set changed")


def load_manifest():
    raw = MANIFEST_PATH.read_bytes()
    _require(len(raw) <= 100_000 and sha256(raw) == MANIFEST_SHA256,
             "frozen source manifest digest mismatch")
    manifest = json.loads(raw)
    validate_manifest(manifest)
    return manifest


def _safe_directory(path):
    path = Path(path).absolute()
    for parent in (path, *path.parents):
        _require(not parent.is_symlink(), "linked work path refused")
        _require(not parent.exists() or parent.is_dir(), "work path is not a directory")
    path.mkdir(parents=True, exist_ok=True)
    return path


class SourceReader:
    """An exact-byte cache; corrupt cache entries fail without replacement."""

    def __init__(self, work, manifest):
        self.work = _safe_directory(work)
        self.manifest = manifest
        self.members = {}
        self.http_requests = self.downloaded_bytes = self.cache_hits = 0

    def get(self, member_path):
        _safe_path(member_path)
        _require(member_path in self.manifest["members"], "unplanned source member")
        identity = self.manifest["members"][member_path]
        path = self.work / member_path
        _safe_directory(path.parent)
        _require(not path.is_symlink(), "linked source cache refused")
        if path.exists():
            _require(path.is_file() and path.stat().st_size == identity["bytes"],
                     "cached source size mismatch")
            raw = path.read_bytes()
            hit = True
        else:
            url = SOURCE_BASE + urllib.parse.quote(member_path, safe="/")
            request = urllib.request.Request(url, headers={
                "User-Agent": "audio-score-source-admission/1.0", "Accept-Encoding": "identity",
            })
            self.http_requests += 1
            try:
                with urllib.request.urlopen(request, timeout=45) as response:
                    _require(response.status == 200 and response.url == url,
                             "unexpected source response or redirect")
                    length = response.headers.get("Content-Length")
                    _require(length is None or length == str(identity["bytes"]),
                             "source Content-Length mismatch")
                    _require(response.headers.get("Content-Encoding", "identity") == "identity",
                             "encoded source response refused")
                    raw = response.read(identity["bytes"] + 1)
            except (urllib.error.URLError, TimeoutError) as exc:
                raise AdmissionError("source_unavailable") from exc
            hit = False
        _require(len(raw) == identity["bytes"] and sha256(raw) == identity["sha256"],
                 "source byte identity mismatch")
        if not hit:
            with path.open("xb") as handle:
                handle.write(raw)
        if member_path not in self.members:
            self.cache_hits += int(hit)
            self.downloaded_bytes += 0 if hit else len(raw)
            self.members[member_path] = dict(identity)
        return raw

    def receipt(self, stage, cases):
        complete = sum(c.get("status") == "complete" for c in cases)
        return {
            "stage": stage, "dataset": "nASAP", "revision": REVISION,
            "official_repository": self.manifest["official_repository"],
            "license": self.manifest["license"], "manifest_sha256": MANIFEST_SHA256,
            "members": dict(sorted(self.members.items())),
            "verified_member_count": len(self.members), "cache_hits": self.cache_hits,
            "http_requests": self.http_requests, "downloaded_bytes": self.downloaded_bytes,
            "full_source_member_count": self.manifest["budget"]["member_count"],
            "full_source_bytes": self.manifest["budget"]["total_bytes"],
            "planned_recordings": 4, "complete_recordings": complete,
            "failed_recordings": 4 - complete, "audio_acquired": False,
            "fresh_holdout_claimed": False, "raw_arrays_exported": False,
            "stage_counters_are_cumulative": False,
        }


def _counts(values):
    return {str(k): v for k, v in sorted(Counter(values).items())}


def _velocity(values):
    return {"count": len(values), "sum": sum(values), "min": min(values) if values else None,
            "max": max(values) if values else None, "unique_count": len(set(values))}


def parse_midi(raw):
    """Preserve all note-ons and exact MIDI clock conversion; never quantize."""
    if importlib.metadata.version("mido") != MIDO_VERSION:
        raise RuntimeError("mido 1.3.3 is required")
    import mido

    _admit(isinstance(raw, bytes) and 14 <= len(raw) <= MAX_FILE_BYTES,
           "midi_byte_budget")
    _admit(raw[:8] == b"MThd\x00\x00\x00\x06", "malformed_midi_header")
    track_count, pos = int.from_bytes(raw[10:12], "big"), 14
    for _ in range(track_count):
        _admit(pos + 8 <= len(raw) and raw[pos:pos + 4] == b"MTrk", "malformed_midi_track")
        pos += 8 + int.from_bytes(raw[pos + 4:pos + 8], "big")
        _admit(pos <= len(raw), "malformed_midi_track")
    _admit(pos == len(raw), "trailing_midi_bytes")
    try:
        midi = mido.MidiFile(file=io.BytesIO(raw))
    except (EOFError, OSError, ValueError, TypeError, KeyError, struct.error) as exc:
        raise AdmissionError("malformed_midi") from exc
    _admit(midi.type in (0, 1) and 1 <= len(midi.tracks) <= 16, "unsupported_midi_format")
    _admit(type(midi.ticks_per_beat) is int and 0 < midi.ticks_per_beat < 32768,
           "unsupported_midi_clock")
    timeline = []
    for track_index, track in enumerate(midi.tracks):
        _admit(bool(track) and track[-1].type == "end_of_track"
               and sum(m.type == "end_of_track" for m in track) == 1,
               "missing_or_multiple_track_end")
        tick = 0
        for order, msg in enumerate(track):
            _admit(type(msg.time) is int and msg.time >= 0, "invalid_delta_tick")
            tick += msg.time
            timeline.append((tick, track_index, order, msg))
            _admit(len(timeline) <= MAX_MIDI_MESSAGES, "midi_message_budget")
    timeline.sort(key=lambda x: x[:3])
    notes, controls, tempos, active = [], [], [], defaultdict(list)
    seconds, last_tick, tempo, unmatched_off = Fraction(0), 0, 500000, 0
    for tick, track, order, message in timeline:
        seconds += Fraction((tick - last_tick) * tempo, midi.ticks_per_beat * 1_000_000)
        last_tick = tick
        if message.type == "set_tempo":
            _admit(message.tempo > 0, "invalid_midi_tempo")
            if tempos and tempos[-1][0] == tick:
                _admit(tempos[-1][1] == message.tempo, "conflicting_midi_tempos")
            tempo = message.tempo
            tempos.append((tick, tempo))
        elif message.type == "control_change":
            controls.append((tick, track, message.channel, message.control, message.value,
                             float(seconds)))
        elif message.type == "note_on" and message.velocity > 0:
            index = len(notes)
            notes.append({"track": track, "channel": message.channel, "pitch": message.note,
                          "velocity": message.velocity, "onset_tick": tick,
                          "onset_sec": float(seconds), "offset_tick": None,
                          "offset_sec": None, "source_order": order})
            active[(track, message.channel, message.note)].append(index)
        elif message.type == "note_off" or (message.type == "note_on" and not message.velocity):
            key = (track, message.channel, message.note)
            if active[key]:
                index = active[key].pop(0)
                notes[index]["offset_tick"], notes[index]["offset_sec"] = tick, float(seconds)
            else:
                unmatched_off += 1
    _admit(bool(notes), "empty_midi_performance")
    summary = {
        "midi_sha256": sha256(raw), "midi_bytes": len(raw), "mido_version": MIDO_VERSION,
        "format": midi.type, "tracks": len(midi.tracks), "ticks_per_quarter": midi.ticks_per_beat,
        "source_end_s": float(seconds), "source_note_on_count": len(notes),
        "source_controller_count": len(controls), "source_tempo_event_count": len(tempos),
        "source_tempo_unique_count": len({t for _, t in tempos}),
        "single_encoding_tempo_us_per_quarter": tempos[0][1] if len(tempos) == 1 else None,
        "source_raw_pitch_counts": _counts(n["pitch"] for n in notes),
        "source_velocity": _velocity([n["velocity"] for n in notes]),
        "source_note_events_sha256": fingerprint(notes),
        "source_controllers_sha256": fingerprint(controls),
        "source_tempo_events_sha256": fingerprint(tempos),
        "unmatched_note_off_count": unmatched_off,
        "missing_key_release_count": sum(n["offset_sec"] is None for n in notes),
        "zero_key_duration_count": sum(n["offset_sec"] == n["onset_sec"] for n in notes),
        "midi_tempo_used_as_musical_score_clock": False,
    }
    return notes, controls, summary


def parse_annotations(raw):
    """Supplied 4/4 pulse clock, rooted at its first annotated downbeat."""
    _admit(isinstance(raw, bytes) and len(raw) <= MAX_FILE_BYTES, "annotation_byte_budget")
    times, labels, signatures = [], [], []
    try:
        lines = raw.decode("utf-8-sig").splitlines()
        _admit(2 <= len(lines) <= MAX_ROWS, "annotation_row_budget")
        for line in lines:
            fields = line.split("\t")
            _admit(len(fields) == 3, "annotation_schema")
            t, other = float(fields[0]), float(fields[1])
            tag = fields[2].split(",")
            _admit(math.isfinite(t) and t >= 0 and t == other, "invalid_annotation_time")
            _admit(tag[0] in ("b", "db"), "irregular_or_unknown_beat_annotation")
            times.append(t)
            labels.append(tag[0])
            if len(tag) > 1 and tag[1]:
                signatures.append((len(times) - 1, tag[1]))
    except (UnicodeError, ValueError) as exc:
        if isinstance(exc, AdmissionError):
            raise
        raise AdmissionError("malformed_annotation") from exc
    _admit(all(b > a for a, b in zip(times, times[1:])), "nonmonotone_annotation_clock")
    _admit("db" in labels, "missing_annotated_downbeat")
    origin_index = labels.index("db")
    _admit(origin_index + int(LENGTH_Q) < len(times), "insufficient_fixed_window_clock")
    _admit(signatures and all(s == "4/4" for _, s in signatures)
           and signatures[0][0] <= origin_index, "unsupported_annotation_meter")
    _admit(all((i - origin_index) % 4 == 0 for i, tag in enumerate(labels) if tag == "db")
           and all(labels[i] == "db" for i in range(origin_index, len(labels), 4)),
           "downbeat_phase_inconsistency")
    return {"times": tuple(times), "labels": tuple(labels), "origin_index": origin_index,
            "start_s": times[origin_index], "end_s": times[origin_index + int(LENGTH_Q)]}


def _clock_q(seconds, clock):
    times = clock["times"]
    _admit(times[0] <= seconds <= times[-1], "clock_extrapolation_refused")
    i = min(len(times) - 2, max(0, bisect.bisect_right(times, seconds) - 1))
    return i - clock["origin_index"] + (seconds - times[i]) / (times[i + 1] - times[i])


def parse_input(raw_midi, raw_annotations):
    from scripts.same_score_phase import OnsetEvent

    notes, controls, midi_summary = parse_midi(raw_midi)
    clock = parse_annotations(raw_annotations)
    selected = [i for i, n in enumerate(notes) if clock["start_s"] <= n["onset_sec"] < clock["end_s"]]
    _admit(bool(selected), "empty_fixed_window")
    events = tuple(OnsetEvent(f"e{i + 1:06d}", notes[index]["pitch"],
                             _clock_q(notes[index]["onset_sec"], clock),
                             notes[index]["velocity"]) for i, index in enumerate(selected))
    _admit(all(0 <= e.onset_q < LENGTH_Q for e in events), "input_window_arithmetic")
    receipt = {
        "status": "complete", **midi_summary, "selected_note_on_count": len(events),
        "excluded_before_window": sum(n["onset_sec"] < clock["start_s"] for n in notes),
        "excluded_at_or_after_window": sum(n["onset_sec"] >= clock["end_s"] for n in notes),
        "selected_velocity": _velocity([e.velocity for e in events]),
        "selected_source_note_events_sha256": fingerprint([notes[i] for i in selected]),
        "input_events_sha256": fingerprint([asdict(e) for e in events]),
        "performance_annotations_sha256": sha256(raw_annotations),
        "supplied_clock": {"kind": "author_performance_beat_annotations", "meter": "4/4",
                           "beat_count": len(clock["times"]),
                           "downbeat_count": clock["labels"].count("db"),
                           "first_downbeat_index": clock["origin_index"],
                           "origin_time_s": clock["start_s"], "window_end_time_s": clock["end_s"],
                           "length_q": LENGTH_Q, "extrapolation": False},
        "original_timing_velocity_retained": True, "performance_export_verified": False,
        "score_or_alignment_opened": False, "raw_arrays_exported": False,
    }
    state = {"notes": notes, "controls": controls, "clock": clock, "selected": selected,
             "events": events, "source_index_to_event": dict(zip(selected, (e.event_id for e in events)))}
    return events, state, receipt


def _failed(case_id, error):
    return {"id": case_id, "status": "failed", "scope": "real_same_score",
            "length_q": LENGTH_Q, "events": (),
            "receipt": {"status": "failed", "failure": error.code,
                        "diagnostics": error.diagnostics}}


def prepare_inputs(work):
    """No score, metadata CSV, alignment or score-aware CSV is opened here."""
    manifest = load_manifest()
    reader, cases = SourceReader(work, manifest), []
    for case in manifest["cases"]:
        try:
            raw_midi = reader.get(case["midi"])
            raw_annotations = reader.get(case["performance_annotations"])
            events, _, receipt = parse_input(raw_midi, raw_annotations)
            cases.append({"id": case["id"], "status": "complete", "scope": "real_same_score",
                          "events": events, "length_q": LENGTH_Q, "receipt": receipt})
        except AdmissionError as exc:
            cases.append(_failed(case["id"], exc))
    return {"cases": cases, "source_receipt": reader.receipt("inputs", cases)}


def _rows(raw, fields, delimiter=","):
    _admit(len(raw) <= MAX_FILE_BYTES, "csv_byte_budget")
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")), delimiter=delimiter)
        _admit(tuple(reader.fieldnames or ()) == fields, "csv_header_mismatch")
        rows = list(reader)
        _admit(len(rows) <= MAX_ROWS and all(None not in r for r in rows), "csv_row_budget_or_schema")
        return rows
    except (UnicodeError, csv.Error) as exc:
        raise AdmissionError("malformed_csv") from exc


def _verify_metadata(raw, manifest):
    _require(sha256(raw) == METADATA_SHA256, "metadata digest mismatch")
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    rows = list(reader)
    _require(len(rows) == 1066, "metadata population changed")
    index = {r["midi_performance"]: r for r in rows}
    _require(len(index) == len(rows), "duplicate metadata performances")
    for case in manifest["cases"]:
        _require(index.get(case["midi"]) == case["metadata_row"], "metadata case substitution")
    groups = defaultdict(set)
    for row in rows:
        if (row.get("robust_note_alignment") in ("1", "1.0")
                and row.get("xml_score", "").startswith("Bach/Fugue/")
                and row.get("note_alignments") and row.get("parangonada_data_folder")
                and row.get("performance_annotations")):
            groups[row["xml_score"]].add(row["midi_performance"])
    mandatory = "Bach/Fugue/bwv_848/xml_score.musicxml"
    eligible = sorted(p for p, takes in groups.items() if p > mandatory and len(takes) >= 2)
    _require(bool(eligible) and eligible[0] == manifest["cases"][2]["xml"]
             and sorted(groups[eligible[0]])[:2] == [c["midi"] for c in manifest["cases"][2:]],
             "deterministic different-score selection changed")


def _parser(manifest):
    root = Path(__file__).resolve().parents[1]
    for path, digest in manifest["parser_dependencies"].items():
        _require(sha256((root / path).read_bytes()) == digest, "frozen XML parser dependency changed")
    from scripts.nasap_joint_rhythm import parse_score
    return parse_score


def canonical_score(raw_xml, part_rows, parser):
    """Bind every ordinary and grace score row to its unchanged XML occurrence."""
    try:
        parsed = parser(raw_xml)
        root = ET.fromstring(raw_xml)
        grace_nodes = [n for n in root.findall(".//note") if n.find("grace") is not None]
        _admit(len(grace_nodes) == len(parsed["grace"]), "grace_identity_count_mismatch")
        ordinary = parsed["notes"]
        expected = {}
        for nid, n in ordinary.items():
            expected[nid] = {"onset": n["start"], "duration": n["end"] - n["start"],
                             "pitch": n["pitch"], "grace": False}
        for node, (_, onset) in zip(grace_nodes, parsed["grace"]):
            nid, pitch = node.get("id"), node.find("pitch")
            _admit(bool(nid) and nid not in expected and pitch is not None,
                   "invalid_grace_identity")
            semitone = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
            midi = (12 * (int(pitch.findtext("octave")) + 1)
                    + semitone[pitch.findtext("step")] + int(pitch.findtext("alter", "0")))
            expected[nid] = {"onset": Fraction(str(onset)), "duration": Fraction(0),
                             "pitch": midi, "grace": True}
        _admit(not root.findall(".//repeat"), "repeat_occurrences_not_supported")
        _admit(all(m["simple_full"] and m["nominal"] == 4 for m in parsed["measures"]),
               "unsupported_score_meter_or_pickup")
        canonical = {}
        for row in part_rows:
            nid, suffix = row["id"].rsplit("-", 1)
            _admit(suffix == "1" and nid in expected and row["id"] not in canonical,
                   "unsupported_or_duplicate_score_occurrence")
            n = expected[nid]
            _admit(Fraction(row["onset_quarter"]) == n["onset"]
                   and Fraction(row["duration_quarter"]) == n["duration"]
                   and Fraction(row["onset_beat"]) == n["onset"]
                   and Fraction(row["duration_beat"]) == n["duration"]
                   and int(row["pitch"]) == n["pitch"], "xml_csv_canonical_mismatch")
            canonical[row["id"]] = dict(n)
        _admit(len(canonical) == len(expected), "incomplete_canonical_score_map")
        _admit(any(m["start"] == SCORE_ORIGIN_Q for m in parsed["measures"]),
               "canonical_bar_origin_not_structural")
        return canonical
    except (ValueError, TypeError, KeyError, ET.ParseError) as exc:
        if isinstance(exc, AdmissionError):
            raise
        raise AdmissionError("unsupported_xml_or_canonical_schema") from exc


def _author_origin(clock, score_annotations, part_rows, performance_rows):
    score_clock = parse_annotations(score_annotations)
    _admit(score_clock["labels"] == clock["labels"], "score_performance_beat_labels_disagree")
    times, verified = clock["times"], 0
    for rows, time_key, q_key in ((performance_rows, "last_beat", "last_beat_ref"),
                                  (part_rows, "last_beat_ref", "last_beat")):
        row_count = 0
        for row in rows:
            try:
                t, q = float(row[time_key]), float(row[q_key])
            except (ValueError, TypeError) as exc:
                raise AdmissionError("invalid_author_beat_reference") from exc
            _admit(math.isfinite(t) and math.isfinite(q), "invalid_author_beat_reference")
            if t == q == -10:
                continue
            _admit(t >= 0 and q >= 0, "invalid_author_beat_reference")
            index = min(range(len(times)), key=lambda i: abs(times[i] - t))
            _admit(abs(times[index] - t) <= AUTHOR_BEAT_TOLERANCE_S,
                   "author_beat_time_not_in_tsv")
            _admit(abs(q - (index - clock["origin_index"]) - float(SCORE_ORIGIN_Q)) <= 1e-8,
                   "author_score_origin_not_four_quarters")
            row_count += 1
        _admit(row_count > 0, "missing_author_score_origin_evidence")
        verified += row_count
    return verified


def evaluate_source(case, state, canonical, part_rows, performance_rows, alignment_rows,
                    score_annotations):
    """Private source correspondences only; no estimator prediction is inspected."""
    verified_origin_rows = _author_origin(state["clock"], score_annotations,
                                          part_rows, performance_rows)
    notes, selected_map = state["notes"], state["source_index_to_event"]
    pp = {r["id"]: r for r in performance_rows}
    _admit(len(pp) == len(performance_rows) == len(notes), "performance_row_inventory_mismatch")
    raw_by_key = defaultdict(list)
    for i, note in enumerate(notes):
        raw_by_key[(note["track"], note["channel"], note["pitch"])].append(i)
    by_score, by_source, row_binding = defaultdict(list), defaultdict(list), {}
    unsupported_rows = set()
    for ri, row in enumerate(alignment_rows):
        xid, mid = row["xml_id"], row["midi_id"]
        if xid != "insertion":
            by_score[xid].append(ri)
        if mid == "deletion":
            if xid == "insertion" or xid not in canonical:
                unsupported_rows.add(ri)
            continue
        try:
            key = (int(row["track"]), int(row["channel"]), int(row["pitch"]))
            onset = float(row["onset"])
            p = pp[mid]
            _admit(math.isfinite(onset) and onset >= 0
                   and key == (int(p["track"]), int(p["channel"]), int(p["pitch"]))
                   and abs(float(p["onset_sec"]) - onset) <= AUTHOR_BEAT_TOLERANCE_S,
                   "alignment_performance_identity_mismatch")
            matches = [i for i in raw_by_key[key]
                       if abs(notes[i]["onset_sec"] - onset) <= MIDI_ONSET_TOLERANCE_S]
            if len(matches) != 1:
                unsupported_rows.add(ri)
                continue
            index = matches[0]
            _admit(int(p["velocity"]) == notes[index]["velocity"],
                   "performance_velocity_identity_mismatch")
            row_binding[ri] = index
            by_source[index].append(ri)
            if xid != "insertion" and xid not in canonical:
                unsupported_rows.add(ri)
        except (ValueError, KeyError, TypeError):
            unsupported_rows.add(ri)
    for indices in by_source.values():
        if len(indices) > 1:
            unsupported_rows.update(indices)
    for indices in by_score.values():
        if len(indices) > 1:
            unsupported_rows.update(indices)

    def in_window(n):
        return SCORE_ORIGIN_Q <= n["onset"] < SCORE_ORIGIN_Q + Fraction(int(LENGTH_Q))

    targets = []
    for sid, note in sorted(canonical.items(), key=lambda x: (x[1]["onset"], x[0])):
        if not in_window(note):
            continue
        rows = by_score.get(sid, [])
        event_id, coverage = None, "unsupported_alignment"
        if len(rows) > 1:
            coverage = "ambiguous"
        elif len(rows) == 1:
            ri, row = rows[0], alignment_rows[rows[0]]
            if ri in unsupported_rows:
                coverage = "ambiguous" if ri in row_binding else "unsupported_alignment"
            elif row["midi_id"] == "deletion":
                coverage = "deletion"
            elif ri in row_binding:
                event_id = selected_map.get(row_binding[ri])
                coverage = "observed" if event_id is not None else "outside_input_window"
        targets.append({"score_id": sid, "pitch": note["pitch"],
                        "onset_q": float(note["onset"] - SCORE_ORIGIN_Q),
                        "duration_q": float(note["duration"]), "grace": note["grace"],
                        "event_id": event_id, "coverage": coverage})
    input_links = []
    for index in state["selected"]:
        event_id, classification, sid = selected_map[index], "unsupported", None
        rows = by_source.get(index, [])
        if len(rows) == 1 and rows[0] not in unsupported_rows:
            row = alignment_rows[rows[0]]
            if row["xml_id"] == "insertion":
                classification = "insertion"
            elif row["xml_id"] in canonical:
                sid, n = row["xml_id"], canonical[row["xml_id"]]
                if not in_window(n):
                    classification = "matched_outside_target_window"
                else:
                    classification = "grace_target" if n["grace"] else "ordinary_target"
        input_links.append({"event_id": event_id, "classification": classification, "score_id": sid})
    serial = [[sid, str(n["onset"]), str(n["duration"]), n["pitch"], n["grace"]]
              for sid, n in sorted(canonical.items())]
    ordinary = [n for n in targets if not n["grace"]]
    note_by_event = {selected_map[i]: notes[i] for i in state["selected"]}
    receipt = {
        "status": "complete", "full_score_attacks": len(canonical),
        "ordinary_score_attacks": sum(not n["grace"] for n in canonical.values()),
        "grace_score_attacks": sum(n["grace"] for n in canonical.values()),
        "target_notes": len(targets), "target_ordinary": len(ordinary),
        "target_grace": len(targets) - len(ordinary),
        "non_target_score_attacks": len(canonical) - len(targets),
        "target_coverage_counts": {k: sum(t["coverage"] == k for t in targets) for k in COVERAGE_CLASSES},
        "ordinary_target_coverage_counts": {k: sum(t["coverage"] == k for t in ordinary)
                                            for k in COVERAGE_CLASSES},
        "input_classification_counts": {k: sum(r["classification"] == k for r in input_links)
                                         for k in INPUT_CLASSES},
        "source_performance_note_count": len(notes), "selected_note_on_count": len(input_links),
        "source_alignment_rows": len(alignment_rows),
        "source_deletion_rows": sum(r["midi_id"] == "deletion" for r in alignment_rows),
        "source_insertion_rows": sum(r["xml_id"] == "insertion" for r in alignment_rows),
        "unsupported_alignment_rows": len(unsupported_rows),
        "source_uniquely_bound_performance_notes": sum(len(v) == 1 and v[0] not in unsupported_rows
                                                       for v in by_source.values()),
        "observed_target_wrong_pitch_count": sum(t["event_id"] is not None
            and note_by_event[t["event_id"]]["pitch"] != t["pitch"] for t in targets),
        "author_score_origin_verified_rows": verified_origin_rows,
        "score_window_start_q": float(SCORE_ORIGIN_Q), "score_window_end_q": 36.0,
        "canonical_score_map_sha256": fingerprint(serial),
        "input_links_sha256": fingerprint(input_links), "target_notes_sha256": fingerprint(targets),
        "raw_arrays_exported": False, "source_admission_only": True,
    }
    return {"id": case["id"], "status": "complete", "score_id": case["score_id"],
            "performance_id": case["performance_id"], "score_sha256": case["xml_sha256"],
            "score_window_start_q": float(SCORE_ORIGIN_Q), "length_q": LENGTH_Q,
            "target_notes": targets, "input_links": input_links, "receipt": receipt}


def load_evaluation(work, cases):
    """Caller must invoke only after saving all predictions; returns private maps."""
    manifest = load_manifest()
    _require([c.get("id") for c in cases] == [c["id"] for c in manifest["cases"]],
             "evaluation input population changed")
    reader = SourceReader(work, manifest)
    payloads, unavailable = {}, set()
    for path in manifest["members"]:
        try:
            payloads[path] = reader.get(path)
        except AdmissionError:
            unavailable.add(path)
    if "metadata.csv" in payloads:
        _verify_metadata(payloads["metadata.csv"], manifest)
    parser = _parser(manifest)
    results, maps = {}, {}
    for case, original in zip(manifest["cases"], cases):
        try:
            _admit("metadata.csv" not in unavailable
                   and not any(case[k] in unavailable for k in PATH_FIELDS),
                   "evaluation_source_unavailable")
            _admit(original.get("status") == "complete", "input_admission_failed")
            events, state, receipt = parse_input(payloads[case["midi"]],
                                                  payloads[case["performance_annotations"]])
            _require(tuple(original["events"]) == events
                     and original["receipt"]["input_events_sha256"] == receipt["input_events_sha256"],
                     "saved inference inputs changed from original source")
            part_rows = _rows(payloads[case["part"]], PART_FIELDS)
            performance_rows = _rows(payloads[case["ppart"]], PPART_FIELDS)
            alignment_rows = _rows(payloads[case["alignment"]], ALIGNMENT_FIELDS, "\t")
            canonical = canonical_score(payloads[case["xml"]], part_rows, parser)
            result = evaluate_source({**case, "xml_sha256": sha256(payloads[case["xml"]])},
                                     state, canonical, part_rows, performance_rows, alignment_rows,
                                     payloads[case["score_annotations"]])
            maps[case["id"]] = canonical
            results[case["id"]] = result
        except AdmissionError as exc:
            results[case["id"]] = {"id": case["id"], "status": "failed",
                                    "score_id": case["score_id"], "performance_id": case["performance_id"],
                                    "receipt": {"status": "failed", "failure": exc.code,
                                                "diagnostics": exc.diagnostics}}
    verified_pairs = 0
    for a, b in (("nasap001", "nasap002"), ("nasap003", "nasap004")):
        if a in maps and b in maps:
            if maps[a] != maps[b]:
                for cid in (a, b):
                    results[cid] = {"id": cid, "status": "failed", "receipt": {
                        "status": "failed", "failure": "paired_canonical_maps_disagree"}}
            else:
                verified_pairs += 1
    source_receipt = reader.receipt("evaluation", list(results.values()))
    source_receipt.update({"same_score_canonical_pairs_verified": verified_pairs,
                           "parser_dependencies": dict(manifest["parser_dependencies"]),
                           "metadata_selection_verified": "metadata.csv" not in unavailable})
    return {"cases": results, "source_receipt": source_receipt}

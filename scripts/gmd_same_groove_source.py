"""Frozen, bounded GMD MIDI admission for same-groove research.

The public records contain derived summaries only. The original ZIP and MIDI
remain in the caller's private work directory. This module neither infers rhythm
nor exports/replays a performance, and its provided MIDI clock is privileged
context. Real groove identities are evaluation labels, not written-score truth.
"""
from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import io
import json
import math
import re
import struct
import urllib.request
import zipfile
from collections import Counter
from dataclasses import asdict
from pathlib import Path, PurePosixPath

MANIFEST_PATH = Path(__file__).with_name("gmd_same_groove_manifest.json")
ARCHIVE_NAME = "groove-v1.0.0-midionly.zip"
ARCHIVE_URL = "https://storage.googleapis.com/magentadata/datasets/groove/" + ARCHIVE_NAME
ARCHIVE_BYTES = 3_260_318
ARCHIVE_SHA256 = "651cbc524ffb891be1a3e46d89dc82a1cecb09a57c748c7b45b844c4841dcc1e"
METADATA_SHA256 = "3e17eef2f18012c0160c183ad5b106964eb429876cceb1eee1b746def4e6b11b"
MAX_MANIFEST_BYTES = 100_000
MAX_MIDI_BYTES = 256_000
MAX_MIDI_MESSAGES = 100_000
MIDO_VERSION = "1.3.3"
LENGTH_Q = 60.0
DRUMMERS = ("drummer1", "drummer5", "drummer7", "drummer8")
KIT_PITCHES = (36, 38, 42, 43, 46, 47, 49, 50, 51)
PAPER_MAPPING = {
    36: 36, 38: 38, 40: 38, 37: 38, 48: 50, 50: 50, 45: 47, 47: 47,
    43: 43, 58: 43, 46: 46, 26: 46, 42: 42, 22: 42, 44: 42,
    49: 49, 55: 49, 57: 49, 52: 49, 51: 51, 59: 51, 53: 51,
}
METADATA_FIELDS = (
    "drummer", "session", "id", "style", "bpm", "beat_type",
    "time_signature", "midi_filename", "audio_filename", "duration", "split",
)


class AdmissionError(ValueError):
    """A stable, path-free case failure with optional derived diagnostics."""

    def __init__(self, code, diagnostics=None):
        super().__init__(code)
        self.code = code
        self.diagnostics = {} if diagnostics is None else diagnostics


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def _fingerprint(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                            allow_nan=False).encode())


def _safe_member(path):
    _require(isinstance(path, str) and path.startswith("groove/")
             and "\\" not in path and not any(ord(c) < 32 for c in path)
             and all(p not in ("", ".", "..") for p in path.split("/"))
             and not PurePosixPath(path).is_absolute(), "unsafe member path")


def _member_contract(member):
    _require(set(member) == {"path", "bytes", "sha256", "crc32"},
             "unexpected member schema")
    _safe_member(member["path"])
    _require(type(member["bytes"]) is int and 0 < member["bytes"] <= MAX_MIDI_BYTES,
             "member exceeds byte budget")
    _require(isinstance(member["sha256"], str)
             and re.fullmatch(r"[0-9a-f]{64}", member["sha256"]), "invalid member digest")
    _require(isinstance(member["crc32"], str)
             and re.fullmatch(r"[0-9a-f]{8}", member["crc32"]), "invalid member CRC")


def validate_manifest(manifest):
    _require(manifest.get("schema_version") == 1, "unsupported manifest version")
    _require(manifest.get("archive") == {
        "url": ARCHIVE_URL, "bytes": ARCHIVE_BYTES, "sha256": ARCHIVE_SHA256,
    }, "archive identity changed")
    _require(manifest.get("license") == "CC-BY-4.0", "source license changed")
    _require(manifest.get("kit_pitches") == list(KIT_PITCHES)
             and manifest.get("paper_mapping") == {str(k): v for k, v in PAPER_MAPPING.items()},
             "official paper mapping changed")
    selected = manifest.get("selection", {})
    _require(selected.get("planned_recordings") == 40
             and selected.get("drummers") == list(DRUMMERS)
             and selected.get("grooves") == [f"groove{i}" for i in range(1, 11)]
             and selected.get("window_onset_q") == [0, 60]
             and selected.get("minimum_source_end_q") == 60
             and selected.get("supplied_meter") == "4/4"
             and selected.get("split") == "test", "cohort or window changed")
    metadata = manifest.get("metadata_member", {})
    _member_contract(metadata)
    _require(metadata["path"] == "groove/info.csv"
             and metadata["sha256"] == METADATA_SHA256, "metadata identity changed")
    cases = manifest.get("cases", [])
    _require(len(cases) == 40, "all forty recordings required")
    paths = set()
    for number, case in enumerate(cases):
        groove, drummer = f"groove{number // 4 + 1}", DRUMMERS[number % 4]
        _require(case.get("id") == f"gmd{number + 1:03d}"
                 and case.get("evaluation") == {"groove": groove, "drummer": drummer},
                 "case identity or ordering changed")
        row = case.get("metadata", {})
        _require(set(row) == set(METADATA_FIELDS) and all(isinstance(v, str) for v in row.values()),
                 "metadata row schema changed")
        _require(row["drummer"] == drummer and row["session"] == drummer + "/eval_session"
                 and row["style"].split("/")[-1] == groove and row["split"] == "test"
                 and row["beat_type"] == "beat" and row["time_signature"] == "4-4",
                 "metadata cohort identity changed")
        _require(row["bpm"].isdigit() and 0 < int(row["bpm"]) <= 1000,
                 "invalid metadata tempo")
        _require(math.isfinite(float(row["duration"])) and float(row["duration"]) > 0,
                 "invalid metadata duration")
        member = case.get("member", {})
        _member_contract(member)
        _require(member["path"] == "groove/" + row["midi_filename"]
                 and row["midi_filename"].startswith(row["session"] + "/")
                 and member["path"].endswith(".mid") and member["path"] not in paths,
                 "duplicate or substituted MIDI member")
        paths.add(member["path"])


def load_manifest(path=None):
    raw = (MANIFEST_PATH if path is None else Path(path)).read_bytes()
    _require(len(raw) <= MAX_MANIFEST_BYTES, "manifest exceeds byte budget")
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


def _store_verified(path, raw):
    _safe_directory(path.parent)
    _require(not path.is_symlink(), "linked cache refused")
    if path.exists():
        _require(path.is_file() and path.stat().st_size == len(raw)
                 and path.read_bytes() == raw, "cached member digest mismatch")
        return True
    with path.open("xb") as handle:
        handle.write(raw)
    return False


def _archive(work):
    path = work / ARCHIVE_NAME
    _require(not path.is_symlink(), "linked archive cache refused")
    if path.exists():
        _require(path.is_file() and path.stat().st_size == ARCHIVE_BYTES,
                 "cached archive size mismatch")
        raw = path.read_bytes()
        _require(sha256(raw) == ARCHIVE_SHA256, "cached archive digest mismatch")
        return raw, True
    request = urllib.request.Request(ARCHIVE_URL, headers={
        "User-Agent": "audio-score-research/1.0", "Accept-Encoding": "identity",
    })
    with urllib.request.urlopen(request, timeout=45) as response:
        _require(response.status == 200 and response.url == ARCHIVE_URL,
                 "unexpected archive response or redirect")
        length = response.headers.get("Content-Length")
        _require(length is None or length == str(ARCHIVE_BYTES), "archive Content-Length mismatch")
        _require(response.headers.get("Content-Encoding", "identity") == "identity",
                 "encoded archive response refused")
        raw = response.read(ARCHIVE_BYTES + 1)
    _require(len(raw) == ARCHIVE_BYTES and sha256(raw) == ARCHIVE_SHA256,
             "downloaded archive identity mismatch")
    _store_verified(path, raw)
    return raw, False


def acquire_sources(work):
    """Return private payloads plus a JSON-safe identity receipt; no inference."""
    raw_manifest = MANIFEST_PATH.read_bytes()
    manifest = load_manifest()
    destination = _safe_directory(work)
    raw_archive, archive_hit = _archive(destination)
    payloads, identities, member_hits = {}, {}, 0
    with zipfile.ZipFile(io.BytesIO(raw_archive)) as archive:
        names = archive.namelist()
        _require(len(names) == len(set(names)), "duplicate ZIP members")
        members = [manifest["metadata_member"], *(c["member"] for c in manifest["cases"])]
        for member in members:
            info = archive.getinfo(member["path"])
            _require(not info.is_dir() and not info.flag_bits & 1
                     and info.file_size == member["bytes"]
                     and f"{info.CRC:08x}" == member["crc32"], "ZIP member identity mismatch")
            raw = archive.read(info)
            _require(len(raw) == member["bytes"] and sha256(raw) == member["sha256"],
                     "member digest mismatch")
            member_hits += _store_verified(destination / member["path"], raw)
            payloads[member["path"]] = raw
            identities[member["path"]] = dict(member)
    reader = csv.DictReader(io.StringIO(payloads["groove/info.csv"].decode("utf-8")))
    _require(tuple(reader.fieldnames or ()) == METADATA_FIELDS, "metadata CSV header changed")
    rows = list(reader)
    _require(len(rows) == 1150, "metadata population changed")
    selected = [r for r in rows if r["session"].endswith("/eval_session")]
    selected.sort(key=lambda r: (int(r["style"].rsplit("groove", 1)[1]), r["drummer"]))
    _require(selected == [c["metadata"] for c in manifest["cases"]],
             "frozen forty-row selection does not match original metadata")
    receipt = {
        "dataset": manifest["dataset"], "license": manifest["license"],
        "official_source": manifest["official_source"], "archive": dict(manifest["archive"]),
        "manifest_sha256": sha256(raw_manifest), "metadata_sha256": METADATA_SHA256,
        "verified_member_count": len(identities), "members": identities,
        "archive_cache_hit": archive_hit, "member_cache_hits": member_hits,
        "http_requests": 0 if archive_hit else 1,
        "downloaded_bytes": 0 if archive_hit else len(raw_archive),
        "planned_recordings": 40, "midi_member_bytes": sum(c["member"]["bytes"] for c in manifest["cases"]),
        "audio_acquired": False, "midi_only": True, "canonical_written_score_provided": False,
        "real_identity_basis": "Four drummers instructed to perform the same ten grooves; official eval_session labels.",
    }
    return manifest, payloads, receipt


def _counts(values):
    return {str(k): v for k, v in sorted(Counter(values).items())}


def _velocity_summary(values):
    return {"count": len(values), "min": min(values) if values else None,
            "max": max(values) if values else None, "sum": sum(values),
            "unique_count": len(set(values))}


def parse_midi(raw, metadata_bpm):
    """Read unquantized positive note-on events; supplied PPQN defines quarters.

    Only source clock/schema admission happens here. All source pitches are
    counted, including attacks outside the fixed first-fifteen-bar window.
    """
    if importlib.metadata.version("mido") != MIDO_VERSION:
        raise RuntimeError("mido 1.3.3 is required")
    import mido

    from scripts.performed_rhythm_invariance import Event

    if not isinstance(raw, bytes) or not 14 <= len(raw) <= MAX_MIDI_BYTES:
        raise AdmissionError("midi_byte_budget")
    if raw[:8] != b"MThd\x00\x00\x00\x06":
        raise AdmissionError("malformed_midi_header")
    track_count = int.from_bytes(raw[10:12], "big")
    position = 14
    for _ in range(track_count):
        if position + 8 > len(raw) or raw[position:position + 4] != b"MTrk":
            raise AdmissionError("malformed_midi_track")
        position += 8 + int.from_bytes(raw[position + 4:position + 8], "big")
        if position > len(raw):
            raise AdmissionError("malformed_midi_track")
    if position != len(raw):
        raise AdmissionError("trailing_midi_bytes")
    try:
        midi = mido.MidiFile(file=io.BytesIO(raw))
    except (EOFError, OSError, ValueError, TypeError, KeyError, struct.error) as exc:
        raise AdmissionError("malformed_midi") from exc
    if midi.type not in (0, 1) or not 1 <= len(midi.tracks) <= 16:
        raise AdmissionError("unsupported_midi_format")
    ppqn = midi.ticks_per_beat
    if type(ppqn) is not int or not 1 <= ppqn < 32768:
        raise AdmissionError("unsupported_midi_clock")
    timeline, ends = [], []
    for track_index, track in enumerate(midi.tracks):
        if not track or track[-1].type != "end_of_track" or sum(
                msg.type == "end_of_track" for msg in track) != 1:
            raise AdmissionError("missing_or_multiple_track_end")
        tick = 0
        for order, message in enumerate(track):
            if type(message.time) is not int or message.time < 0:
                raise AdmissionError("invalid_delta_tick")
            tick += message.time
            timeline.append((tick, track_index, order, message))
            if len(timeline) > MAX_MIDI_MESSAGES:
                raise AdmissionError("midi_message_budget")
        ends.append(tick)
    timeline.sort(key=lambda r: r[:3])
    attacks = [(tick, tr, order, msg.note, msg.velocity, msg.channel)
               for tick, tr, order, msg in timeline if msg.type == "note_on" and msg.velocity > 0]
    tempos = [(tick, msg.tempo) for tick, _, _, msg in timeline if msg.type == "set_tempo"]
    meters = [(tick, msg.numerator, msg.denominator) for tick, _, _, msg in timeline
              if msg.type == "time_signature"]
    summary = {
        "midi_sha256": sha256(raw), "midi_bytes": len(raw), "mido_version": MIDO_VERSION,
        "format": midi.type, "tracks": len(midi.tracks), "ticks_per_quarter": ppqn,
        "source_end_tick": max(ends), "source_end_q": max(ends) / ppqn,
        "source_note_on_count": len(attacks), "source_raw_pitch_counts": _counts(a[3] for a in attacks),
        "source_channel_counts": _counts(a[5] for a in attacks),
        "source_velocity": _velocity_summary([a[4] for a in attacks]),
        "tempo_events": len(tempos), "meter_events": len(meters),
        "controller_count": sum(msg.type == "control_change" for _, _, _, msg in timeline),
        "note_off_count": sum(msg.type == "note_off" for _, _, _, msg in timeline),
        "zero_velocity_note_on_count": sum(msg.type == "note_on" and msg.velocity == 0
                                           for _, _, _, msg in timeline),
        "source_attack_sha256": _fingerprint(attacks),
    }

    def admit(condition, code):
        if not condition:
            raise AdmissionError(code, summary)

    admit(bool(tempos) and tempos[0][0] == 0 and all(t[1] > 0 for t in tempos),
          "missing_explicit_initial_tempo")
    admit(len({t[1] for t in tempos}) == 1, "nonconstant_supplied_tempo")
    admit(bool(meters) and meters[0][0] == 0 and all(m[1:] == (4, 4) for m in meters),
          "unsupported_or_missing_4_4_meter")
    admit(type(metadata_bpm) is int and metadata_bpm > 0, "invalid_metadata_bpm")
    # MIDI's tempo is an integral microsecond value; allow only that rounding.
    admit(abs(tempos[0][1] - 60_000_000 / metadata_bpm) <= 1,
          "metadata_midi_tempo_mismatch")
    summary["supplied_tempo_microseconds_per_quarter"] = tempos[0][1]
    summary["supplied_meter"] = "4/4"
    summary["unknown_pitch_counts"] = _counts(a[3] for a in attacks if a[3] not in PAPER_MAPPING)
    admit(not summary["unknown_pitch_counts"], "unknown_raw_drum_pitch")
    admit(all(a[5] == 9 for a in attacks), "nonpercussion_note_channel")
    admit(max(ends) >= 60 * ppqn, "source_shorter_than_fifteen_bars")
    selected = [a for a in attacks if 0 <= a[0] < 60 * ppqn]
    admit(bool(selected), "no_attacks_in_fixed_window")
    events = tuple(Event(f"e{i:06d}", KIT_PITCHES.index(PAPER_MAPPING[a[3]]),
                         a[0] / ppqn, a[4]) for i, a in enumerate(selected, 1))
    before = [(f"e{i:06d}", a[0] / ppqn, a[4]) for i, a in enumerate(selected, 1)]
    after = [(e.event_id, e.onset_q, e.velocity) for e in events]
    admit(before == after, "input_timing_or_velocity_changed")
    summary.update({
        "status": "complete", "window_start_q": 0.0, "window_end_q": LENGTH_Q,
        "window_note_on_count": len(selected), "excluded_note_on_count": len(attacks) - len(selected),
        "excluded_at_or_after_window_end": sum(a[0] >= 60 * ppqn for a in attacks),
        "window_raw_pitch_counts": _counts(a[3] for a in selected),
        "window_instrument_counts": _counts(e.instrument for e in events),
        "window_velocity": _velocity_summary([e.velocity for e in events]),
        "window_onset_range_q": [min(e.onset_q for e in events), max(e.onset_q for e in events)],
        "selected_source_attack_sha256": _fingerprint(selected),
        "input_events_sha256": _fingerprint([asdict(e) for e in events]),
        "timing_velocity_before_sha256": _fingerprint(before),
        "timing_velocity_after_sha256": _fingerprint(after),
        "performed_onsets_and_velocities_unchanged": True,
        "attack_count_preserved_within_window": len(events) == len(selected),
        "supplied_clock_used": True, "onset_quantization_applied": False,
        "seconds_bpm_or_labels_passed_to_predictor": False,
        "replay_or_export_preservation_test": False,
        "raw_controllers_preserved_in_private_source_midi": True,
    })
    return events, summary


def prepare_real(work):
    """Keep all forty planned rows, including per-recording admission failures."""
    manifest, payloads, source_receipt = acquire_sources(work)
    cases = []
    for entry in manifest["cases"]:
        raw = payloads[entry["member"]["path"]]
        try:
            events, receipt = parse_midi(raw, int(entry["metadata"]["bpm"]))
        except AdmissionError as exc:
            events = ()
            receipt = {**exc.diagnostics, "status": "failed", "failure_code": exc.code,
                       "midi_sha256": sha256(raw), "midi_bytes": len(raw)}
        receipt["source_member"] = dict(entry["member"])
        cases.append({"id": entry["id"], "scope": "real_same_groove", "events": events,
                      "length_q": LENGTH_Q, "evaluation": dict(entry["evaluation"]),
                      "receipt": receipt})
    complete = sum(c["receipt"]["status"] == "complete" for c in cases)
    source_receipt.update({"complete_recordings": complete, "failed_recordings": 40 - complete,
                           "all_planned_recordings_retained": len(cases) == 40})
    return {"cases": cases, "source_receipt": source_receipt}

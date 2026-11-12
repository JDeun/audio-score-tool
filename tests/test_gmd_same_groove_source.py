"""Source-integrity and MIDI-admission contracts; no real groove inference."""
from __future__ import annotations

import copy
import csv
import io
import json
import struct
import zipfile
from dataclasses import asdict

import mido
import pytest

from scripts import gmd_same_groove_source as source


def midi_bytes(attacks=((1, 36, 91, 9), (479, 38, 127, 9)), *, end=64 * 480,
               ppqn=480, tempo=500000, meter=(4, 4), format_type=0,
               extra=()):
    midi = mido.MidiFile(type=format_type, ticks_per_beat=ppqn)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    timeline = []
    if tempo is not None:
        timeline.append((0, mido.MetaMessage("set_tempo", tempo=tempo)))
    if meter is not None:
        timeline.append((0, mido.MetaMessage("time_signature", numerator=meter[0], denominator=meter[1])))
    for tick, pitch, velocity, channel in attacks:
        timeline.append((tick, mido.Message("note_on", note=pitch, velocity=velocity, channel=channel)))
        timeline.append((tick + 1, mido.Message("note_off", note=pitch, velocity=0, channel=channel)))
    timeline.extend(extra)
    timeline.append((end, mido.MetaMessage("end_of_track")))
    before = 0
    for tick, message in sorted(timeline, key=lambda row: row[0]):
        track.append(message.copy(time=tick - before))
        before = tick
    stream = io.BytesIO()
    midi.save(file=stream)
    return stream.getvalue()


def install_archive(monkeypatch):
    """A complete invented 40-row cohort, with no original performance notes."""
    manifest = source.load_manifest()
    rows = [c["metadata"] for c in manifest["cases"]]
    rows = [*rows, *[{**rows[0], "session": "drummer1/session1", "id": str(i)}
                    for i in range(1110)]]
    csv_stream = io.StringIO(newline="")
    writer = csv.DictWriter(csv_stream, fieldnames=source.METADATA_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    metadata = csv_stream.getvalue().encode()
    payloads = {"groove/info.csv": metadata}
    for entry in manifest["cases"]:
        bpm = int(entry["metadata"]["bpm"])
        payloads[entry["member"]["path"]] = midi_bytes(tempo=round(60_000_000 / bpm))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, raw in payloads.items():
            archive.writestr(path, raw)
    raw_archive = buffer.getvalue()
    with zipfile.ZipFile(io.BytesIO(raw_archive)) as archive:
        for member in [manifest["metadata_member"], *(c["member"] for c in manifest["cases"])]:
            info = archive.getinfo(member["path"])
            member.update(bytes=info.file_size, crc32=f"{info.CRC:08x}",
                          sha256=source.sha256(payloads[info.filename]))
    digest = source.sha256(raw_archive)
    manifest["archive"].update(bytes=len(raw_archive), sha256=digest)
    monkeypatch.setattr(source, "ARCHIVE_BYTES", len(raw_archive))
    monkeypatch.setattr(source, "ARCHIVE_SHA256", digest)
    monkeypatch.setattr(source, "METADATA_SHA256", source.sha256(metadata))
    monkeypatch.setattr(source, "load_manifest", lambda path=None: copy.deepcopy(manifest))
    return raw_archive, manifest


class Response:
    status = 200
    url = source.ARCHIVE_URL

    def __init__(self, raw):
        self.raw = raw
        self.headers = {"Content-Length": str(len(raw))}
        self.read_limit = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit):
        self.read_limit = limit
        return self.raw[:limit]


def forbid_network(*args, **kwargs):
    raise AssertionError("unexpected network request")


def test_manifest_pins_all_40_official_eval_rows_and_mapping():
    manifest = source.load_manifest()
    assert [c["id"] for c in manifest["cases"]] == [f"gmd{i:03d}" for i in range(1, 41)]
    assert len({(c["evaluation"]["groove"], c["evaluation"]["drummer"])
                for c in manifest["cases"]}) == 40
    assert sum(c["member"]["bytes"] for c in manifest["cases"]) == 120381
    assert manifest["archive"]["sha256"] == "651cbc524ffb891be1a3e46d89dc82a1cecb09a57c748c7b45b844c4841dcc1e"
    assert source.PAPER_MAPPING[22] == 42 and source.PAPER_MAPPING[53] == 51


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "reordered", "label", "window",
                                     "mapping", "archive", "traversal", "audio", "metadata"])
def test_changed_manifest_cannot_change_cohort_or_observation_contract(mutation):
    manifest = copy.deepcopy(source.load_manifest())
    first = manifest["cases"][0]
    if mutation == "missing":
        manifest["cases"].pop()
    elif mutation == "duplicate":
        manifest["cases"][-1] = first
    elif mutation == "reordered":
        manifest["cases"].reverse()
    elif mutation == "label":
        first["evaluation"]["groove"] = "groove2"
    elif mutation == "window":
        manifest["selection"]["window_onset_q"] = [4, 64]
    elif mutation == "mapping":
        manifest["paper_mapping"]["22"] = 46
    elif mutation == "archive":
        manifest["archive"]["sha256"] = "0" * 64
    elif mutation == "traversal":
        first["member"]["path"] = "groove/../private.mid"
    elif mutation == "audio":
        first["member"]["path"] = first["member"]["path"].replace(".mid", ".wav")
    else:
        first["metadata"]["drummer"] = "drummer5"
    with pytest.raises(ValueError):
        source.validate_manifest(manifest)


def test_one_bounded_download_and_network_free_verified_cache(monkeypatch, tmp_path):
    raw, manifest = install_archive(monkeypatch)
    response = Response(raw)
    calls = []

    def fetch(request, timeout):
        assert request.full_url == source.ARCHIVE_URL and timeout == 45
        calls.append(request)
        return response

    monkeypatch.setattr(source.urllib.request, "urlopen", fetch)
    result = source.prepare_real(tmp_path)
    assert len(calls) == 1 and response.read_limit == len(raw) + 1
    assert len(result["cases"]) == 40 and result["source_receipt"]["complete_recordings"] == 40
    assert result["source_receipt"]["verified_member_count"] == 41
    assert result["source_receipt"]["downloaded_bytes"] == len(raw)
    for entry in manifest["cases"]:
        path = tmp_path / entry["member"]["path"]
        assert source.sha256(path.read_bytes()) == entry["member"]["sha256"]
    monkeypatch.setattr(source.urllib.request, "urlopen", forbid_network)
    second = source.prepare_real(tmp_path)
    assert second["source_receipt"]["archive_cache_hit"] is True
    assert second["source_receipt"]["member_cache_hits"] == 41
    assert second["source_receipt"]["downloaded_bytes"] == 0
    assert second["cases"] == result["cases"]
    public = json.dumps({"source_receipt": second["source_receipt"],
                         "cases": [c["receipt"] for c in second["cases"]]})
    assert str(tmp_path) not in public and "note_on\"" not in public


@pytest.mark.parametrize("target", ["archive", "member"])
def test_tampered_cache_is_rejected_without_repair(monkeypatch, tmp_path, target):
    raw, manifest = install_archive(monkeypatch)
    (tmp_path / source.ARCHIVE_NAME).write_bytes(raw)
    monkeypatch.setattr(source.urllib.request, "urlopen", forbid_network)
    source.acquire_sources(tmp_path)
    path = tmp_path / (source.ARCHIVE_NAME if target == "archive" else manifest["cases"][0]["member"]["path"])
    changed = bytearray(path.read_bytes())
    changed[-1] ^= 1
    path.write_bytes(changed)
    with pytest.raises(ValueError, match="digest mismatch"):
        source.acquire_sources(tmp_path)
    assert path.read_bytes() == bytes(changed)


@pytest.mark.parametrize("problem", ["status", "redirect", "length", "encoding", "oversize", "digest"])
def test_download_contract_refuses_wrong_or_unbounded_input(monkeypatch, tmp_path, problem):
    raw, _ = install_archive(monkeypatch)
    response = Response(raw)
    if problem == "status":
        response.status = 206
    elif problem == "redirect":
        response.url = "https://example.invalid/unapproved.zip"
    elif problem == "length":
        response.headers["Content-Length"] = str(len(raw) + 1)
    elif problem == "encoding":
        response.headers["Content-Encoding"] = "gzip"
    elif problem == "oversize":
        response.raw += b"!"
    else:
        response.raw = bytes([raw[0] ^ 1]) + raw[1:]
    monkeypatch.setattr(source.urllib.request, "urlopen", lambda *a, **k: response)
    with pytest.raises(ValueError):
        source.acquire_sources(tmp_path)
    assert not (tmp_path / source.ARCHIVE_NAME).exists()


def test_forged_member_crc_cannot_bypass_archive_identity(monkeypatch, tmp_path):
    raw, manifest = install_archive(monkeypatch)
    manifest["cases"][0]["member"]["crc32"] = "00000000"
    (tmp_path / source.ARCHIVE_NAME).write_bytes(raw)
    with pytest.raises(ValueError, match="ZIP member identity"):
        source.acquire_sources(tmp_path)


@pytest.mark.parametrize("target", ["work", "archive", "member_parent"])
def test_symlinked_work_or_cache_is_rejected(monkeypatch, tmp_path, target):
    raw, manifest = install_archive(monkeypatch)
    outside = tmp_path / "outside"
    outside.mkdir()
    work = tmp_path / "work"
    if target == "work":
        work.symlink_to(outside, target_is_directory=True)
    else:
        work.mkdir()
        if target == "archive":
            archive = outside / source.ARCHIVE_NAME
            archive.write_bytes(raw)
            (work / source.ARCHIVE_NAME).symlink_to(archive)
        else:
            (work / source.ARCHIVE_NAME).write_bytes(raw)
            (work / "groove").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(source.urllib.request, "urlopen", forbid_network)
    with pytest.raises(ValueError, match="linked"):
        source.acquire_sources(work)
    assert len(manifest["cases"]) == 40


def test_event_adapter_preserves_exact_attack_times_velocity_and_window_boundary():
    raw = midi_bytes(((1, 22, 1, 9), (479, 40, 127, 9), (60 * 480, 36, 75, 9)))
    events, receipt = source.parse_midi(raw, 120)
    assert [asdict(e) for e in events] == [
        {"event_id": "e000001", "instrument": 2, "onset_q": 1 / 480, "velocity": 1},
        {"event_id": "e000002", "instrument": 1, "onset_q": 479 / 480, "velocity": 127},
    ]
    assert receipt["source_note_on_count"] == 3
    assert receipt["window_note_on_count"] == 2 and receipt["excluded_at_or_after_window_end"] == 1
    assert receipt["timing_velocity_before_sha256"] == receipt["timing_velocity_after_sha256"]
    assert receipt["replay_or_export_preservation_test"] is False
    assert set(asdict(events[0])) == {"event_id", "instrument", "onset_q", "velocity"}


def test_ppqn_changes_do_not_change_quarter_positions():
    left, _ = source.parse_midi(midi_bytes(((30, 36, 90, 9),), ppqn=480), 120)
    right, _ = source.parse_midi(midi_bytes(((60, 36, 90, 9),), ppqn=960, end=64 * 960), 120)
    assert left == right and left[0].onset_q == .0625


def test_every_official_raw_pitch_maps_without_deleting_colliding_hits():
    pitches = list(source.PAPER_MAPPING)
    raw = midi_bytes(tuple((0, p, 50 + i, 9) for i, p in enumerate(pitches)))
    events, receipt = source.parse_midi(raw, 120)
    assert len(events) == len(pitches) == sum(receipt["window_raw_pitch_counts"].values())
    assert len({e.event_id for e in events}) == len(events)
    assert [source.KIT_PITCHES[e.instrument] for e in events] == [source.PAPER_MAPPING[p] for p in pitches]


@pytest.mark.parametrize("change,expected", [
    ("short", "source_shorter_than_fifteen_bars"),
    ("unknown", "unknown_raw_drum_pitch"),
    ("unknown_outside", "unknown_raw_drum_pitch"),
    ("channel", "nonpercussion_note_channel"),
    ("missing_tempo", "missing_explicit_initial_tempo"),
    ("changing_tempo", "nonconstant_supplied_tempo"),
    ("wrong_tempo", "metadata_midi_tempo_mismatch"),
    ("meter", "unsupported_or_missing_4_4_meter"),
    ("missing_meter", "unsupported_or_missing_4_4_meter"),
    ("empty_window", "no_attacks_in_fixed_window"),
    ("format2", "unsupported_midi_format"),
    ("smpte", "unsupported_midi_clock"),
    ("trailing", "trailing_midi_bytes"),
    ("truncated", "malformed_midi_track"),
])
def test_midi_admission_fails_explicitly_without_deleting_observations(change, expected):
    kwargs = {}
    if change == "short":
        kwargs["end"] = 60 * 480 - 1
    elif change in ("unknown", "unknown_outside"):
        kwargs["attacks"] = ((0, 36, 90, 9), (0 if change == "unknown" else 61 * 480, 60, 90, 9))
    elif change == "channel":
        kwargs["attacks"] = ((0, 36, 90, 0),)
    elif change == "missing_tempo":
        kwargs["tempo"] = None
    elif change == "changing_tempo":
        kwargs["extra"] = ((480, mido.MetaMessage("set_tempo", tempo=400000)),)
    elif change == "wrong_tempo":
        kwargs["tempo"] = 400000
    elif change == "meter":
        kwargs["meter"] = (3, 4)
    elif change == "missing_meter":
        kwargs["meter"] = None
    elif change == "empty_window":
        kwargs["attacks"] = ((60 * 480, 36, 90, 9),)
    elif change == "format2":
        kwargs["format_type"] = 2
    raw = midi_bytes(**kwargs)
    if change == "smpte":
        raw = raw[:12] + struct.pack(">H", 0xE728) + raw[14:]
    elif change == "trailing":
        raw += b"not a MIDI track"
    elif change == "truncated":
        raw = raw[:-1]
    with pytest.raises(source.AdmissionError) as error:
        source.parse_midi(raw, 120)
    assert error.value.code == expected
    if change in ("unknown", "unknown_outside"):
        assert error.value.diagnostics["unknown_pitch_counts"] == {"60": 1}
        assert error.value.diagnostics["source_note_on_count"] == 2


def test_integral_microsecond_tempo_rounding_is_accepted():
    _, receipt = source.parse_midi(midi_bytes(tempo=round(60_000_000 / 138)), 138)
    assert receipt["status"] == "complete"


def test_one_failed_recording_stays_in_40_case_denominator(monkeypatch, tmp_path):
    raw, _ = install_archive(monkeypatch)
    (tmp_path / source.ARCHIVE_NAME).write_bytes(raw)
    original = source.parse_midi
    calls = []

    def parse(raw, bpm):
        calls.append(bpm)
        if len(calls) == 17:
            raise source.AdmissionError("invented_schema_failure", {"source_note_on_count": 12})
        return original(raw, bpm)

    monkeypatch.setattr(source, "parse_midi", parse)
    result = source.prepare_real(tmp_path)
    assert len(calls) == len(result["cases"]) == 40
    assert result["source_receipt"]["complete_recordings"] == 39
    assert result["source_receipt"]["failed_recordings"] == 1
    failed = result["cases"][16]
    assert failed["id"] == "gmd017" and failed["events"] == ()
    assert failed["receipt"]["status"] == "failed"
    assert failed["receipt"]["failure_code"] == "invented_schema_failure"
    assert failed["receipt"]["source_note_on_count"] == 12


def test_mido_version_must_match_pinned_parser(monkeypatch):
    monkeypatch.setattr(source.importlib.metadata, "version", lambda name: "0.0.0")
    with pytest.raises(RuntimeError, match="1.3.3"):
        source.parse_midi(midi_bytes(), 120)

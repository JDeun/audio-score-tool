"""Orchestration and source admission checks; detectors and network are mocked.

No study WAV or authored control bank is evaluated here. Tiny owned arrays and
MIDI messages test artifact ordering, identity, admission and failure receipts.
"""
from __future__ import annotations

import copy
import hashlib
import io
import json
import struct
import zipfile

import numpy as np
import pytest

from scripts import drum_lane_source as source
from scripts import run_drum_event_lanes as runner


def forbidden(*args, **kwargs):
    pytest.fail("unexpected detector, network, or reference access")


@pytest.fixture(autouse=True)
def no_real_detector_or_network(monkeypatch):
    monkeypatch.setattr(runner, "detect_all_arms", forbidden)
    monkeypatch.setattr(runner, "RangeZipReader", forbidden)


def empty_arms():
    return {arm: [] for arm in runner.ARMS}


def ready_input(work, identity="fixture", index=0, cohort="authored_controls"):
    return runner.save_input(work, index, np.array([0, .25, -.5, .125], dtype="<f4"), {
        "id": identity, "cohort": cohort, "duration_seconds": .25,
    })


def prediction_receipt(planned):
    return {
        "schema": runner.SCHEMA, "arms": list(runner.ARMS), "preflight_sha256": "f" * 64,
        "reference_calls_before_freeze": 0,
        "cases": [{"id": row["id"], "cohort": row["cohort"], "status": "predicted",
                   "input_sha256": row["input_sha256"], "arms": empty_arms()}
                  for row in planned],
    }


def test_saved_input_hashes_canonical_little_endian_float32_and_never_overwrites(tmp_path):
    samples = np.array([[.25, 8.], [-.5, 9.], [.125, 10.]], dtype=">f8")[:, 0]
    assert not samples.flags.c_contiguous
    row = runner.save_input(tmp_path, 0, samples, {"id": "tiny", "cohort": "new_waveform"})
    expected = hashlib.sha256(struct.pack("<3f", .25, -.5, .125)).hexdigest()
    assert row["input_sha256"] == expected
    assert row["input_dtype"] == "<f4" and row["input_shape"] == [3]
    assert row["sample_rate"] == 16000
    path = tmp_path / row["input_path"]
    saved = np.load(path, allow_pickle=False)
    assert saved.dtype.str == "<f4" and saved.shape == (3,)
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        runner.save_input(tmp_path, 0, np.ones(3), {"id": "replacement"})
    assert path.read_bytes() == before


@pytest.mark.parametrize("samples", [np.array([[0., 1.]]), np.array([np.nan]), np.array([np.inf])])
def test_nonfinite_or_nonmono_input_is_rejected_before_save(tmp_path, samples):
    with pytest.raises(ValueError, match="finite_mono"):
        runner.save_input(tmp_path, 0, samples, {})
    assert not (tmp_path / "inputs/000.npy").exists()


def test_json_identity_is_exact_bytes_and_existing_artifact_is_preserved(tmp_path):
    path = tmp_path / "receipt.json"
    digest = runner.write_json(path, {"id": "owned", "times": [.25, .34]})
    before = path.read_bytes()
    assert digest == hashlib.sha256(before).hexdigest()
    with pytest.raises(FileExistsError):
        runner.write_json(path, {"id": "replacement"})
    assert path.read_bytes() == before
    invalid = tmp_path / "invalid.json"
    with pytest.raises(ValueError):
        runner.write_json(invalid, {"time": float("nan")})
    assert not invalid.exists()


def test_prediction_input_is_read_only_and_all_arms_keep_event_multiplicity(tmp_path, monkeypatch):
    row = ready_input(tmp_path)

    def detector(samples, sr):
        assert samples.dtype.str == "<f4" and not samples.flags.writeable and sr == 16000
        return {arm: [(.1, "backbeat", .3), (.1, "kick", .9), (.115, "backbeat", .2)]
                for arm in runner.ARMS}

    monkeypatch.setattr(runner, "detect_all_arms", detector)
    monkeypatch.setattr(runner, "control_reference", forbidden)
    monkeypatch.setattr(runner, "midi_reference", forbidden)
    result = runner.predict_frozen_inputs(tmp_path, [row], "f" * 64)
    case = result["cases"][0]
    assert case["status"] == "predicted" and tuple(case["arms"]) == runner.ARMS
    assert result["reference_calls_before_freeze"] == 0
    for arm, events in case["arms"].items():
        assert [(event["time"], event["role"]) for event in events] == [
            (.1, "backbeat"), (.1, "kick"), (.115, "backbeat"),
        ]
        assert len({event["event_id"] for event in events}) == 3
        assert all(event["event_id"].startswith(arm + ":") and event["velocity"] is None
                   for event in events)


def test_changed_samples_fail_before_detector(tmp_path):
    row = ready_input(tmp_path)
    np.save(tmp_path / row["input_path"], np.array([0., .5, -.5, .125], dtype="<f4"))
    case = runner.predict_frozen_inputs(tmp_path, [row], "f" * 64)["cases"][0]
    assert case["status"] == "prediction_failed"
    assert "input_identity_before_prediction" in case["reason"]
    assert "arms" not in case


def test_equal_canonical_hash_cannot_admit_changed_float64_predictor_input(tmp_path):
    row = ready_input(tmp_path)
    altered = np.load(tmp_path / row["input_path"]).astype("<f8")
    altered[1] += 1e-10
    assert runner.sample_sha(altered) == row["input_sha256"]
    np.save(tmp_path / row["input_path"], altered)
    case = runner.predict_frozen_inputs(tmp_path, [row], "f" * 64)["cases"][0]
    assert case["status"] == "prediction_failed" and "arms" not in case


@pytest.mark.parametrize("corruption", ["mutated_input", "missing_arm", "reordered_arms"])
def test_corrupt_prediction_is_a_recorded_failure_not_a_partial_arm_result(tmp_path, monkeypatch, corruption):
    row = ready_input(tmp_path)

    def detector(samples, sr):
        output = empty_arms()
        if corruption == "mutated_input":
            samples.flags.writeable = True
            samples[0] = 1
        elif corruption == "missing_arm":
            output.pop(runner.ARMS[-1])
        else:
            output = dict(reversed(list(output.items())))
        return output

    monkeypatch.setattr(runner, "detect_all_arms", detector)
    case = runner.predict_frozen_inputs(tmp_path, [row], "f" * 64)["cases"][0]
    assert case["status"] == "prediction_failed"
    assert "prediction_inventory_or_input_mutation" in case["reason"]
    assert "arms" not in case


@pytest.mark.parametrize("corruption,error", [
    ("changed_bytes", "byte_identity"), ("reordered_cases", "complete_population"),
    ("missing_case", "complete_population"), ("missing_arm", "all_four_arms"),
    ("reordered_arms", "all_four_arms"),
])
def test_entire_prediction_barrier_is_checked_before_first_reference(tmp_path, monkeypatch, corruption, error):
    planned = [ready_input(tmp_path, "first", 0), ready_input(tmp_path, "last", 1)]
    prediction = prediction_receipt(planned)
    if corruption == "reordered_cases":
        prediction["cases"].reverse()
    elif corruption == "missing_case":
        prediction["cases"].pop()
    elif corruption == "missing_arm":
        prediction["cases"][-1]["arms"].pop(runner.ARMS[-1])
    elif corruption == "reordered_arms":
        prediction["cases"][-1]["arms"] = dict(reversed(list(empty_arms().items())))
    path = tmp_path / "predictions.json"
    expected = runner.write_json(path, prediction)
    if corruption == "changed_bytes":
        path.write_bytes(path.read_bytes() + b" ")
    monkeypatch.setattr(runner, "control_reference", forbidden)
    monkeypatch.setattr(runner, "midi_reference", forbidden)
    monkeypatch.setattr(runner, "safe_member", forbidden)
    with pytest.raises(ValueError, match="prediction_barrier_" + error):
        runner.freeze_references(None, "groove/", planned, planned, path, expected)


def test_full_run_freezes_all_predictions_before_references_and_keeps_failure(tmp_path, monkeypatch):
    archive_path = tmp_path / "owned.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("owned.txt", "orchestration fixture")
    monkeypatch.setattr(runner, "ARCHIVE_SHA256", hashlib.sha256(archive_path.read_bytes()).hexdigest())
    monkeypatch.setattr(runner, "source_contract", lambda: {"all_equal": True})
    monkeypatch.setattr(runner, "qualify", lambda: {"status": "compatible"})
    monkeypatch.setattr(runner, "exclusion_inventory", lambda: [])
    for name in ("NPY_DISABLE_CPU_FEATURES", "HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    calls = []
    work, output = tmp_path / "work", tmp_path / "output"

    def collect(archive, directory):
        controls = [{"id": "owned0"}, {"id": "owned1"}]
        planned = [ready_input(directory, case["id"], i) for i, case in enumerate(controls)]
        planned.append({"id": "unavailable", "cohort": "new_waveform", "status": "unavailable",
                        "reason": "owned acquisition failure"})
        return "groove/", [], controls, planned, {"failure": "owned acquisition failure"}

    def detector(samples, sr):
        assert (output / "preflight.json").is_file()
        assert not (output / "references.json").exists()
        assert "reference" not in calls
        calls.append("prediction")
        return empty_arms()

    def reference(case):
        assert calls.count("prediction") == 2
        path = output / "predictions.json"
        frozen = json.loads(path.read_bytes())
        assert [row["status"] for row in frozen["cases"]] == ["predicted", "predicted", "unavailable"]
        assert all(tuple(row["arms"]) == runner.ARMS for row in frozen["cases"][:2])
        assert path.stat().st_mode & 0o222 == 0
        calls.append("reference")
        return []

    monkeypatch.setattr(runner, "collect_inputs", collect)
    monkeypatch.setattr(runner, "detect_all_arms", detector)
    monkeypatch.setattr(runner, "control_reference", reference)
    monkeypatch.setattr(runner, "midi_reference", forbidden)
    report = runner.run(archive_path, work, output)
    assert calls == ["prediction", "prediction", "reference", "reference"]
    assert report["status"] == "incomplete"
    assert report["decision"]["outcome"] == "inconclusive_incomplete"
    assert report["aggregates"]["new_waveform"]["planned"] == 1
    assert report["aggregates"]["new_waveform"]["scored"] == 0
    assert [row["id"] for row in report["case_metrics"]] == ["owned0", "owned1", "unavailable"]
    for name in ("preflight", "predictions", "references"):
        receipt = json.loads((output / f"{name}.json").read_bytes())
        key = "planned_cases" if name == "preflight" else "cases"
        assert receipt[key][-1]["reason"] == "owned acquisition failure"
    assert report["hashes"]["predictions.json"] == hashlib.sha256(
        (output / "predictions.json").read_bytes()).hexdigest()
    before = {path.name: path.read_bytes() for path in output.iterdir()}
    with pytest.raises(ValueError, match="new_work_and_output"):
        runner.run(archive_path, work, output)
    assert before == {path.name: path.read_bytes() for path in output.iterdir()}


def bind_mock_population(monkeypatch, tmp_path):
    selection = [{"id": f"wave{i}", "cohort": "new_waveform" if i < 6 else "development_replay"}
                 for i in range(10)]
    controls = [{"id": f"owned{i:03d}"} for i in range(100)]
    samples = np.array([0., .25], dtype="<f4")
    digest = hashlib.sha256(struct.pack("<2f", 0., .25)).hexdigest()
    binding = {"cases": [{"id": case["id"], "sha256": digest, "shape": [2], "dtype": "<f4"}
                          for case in controls]}
    path = tmp_path / "owned-binding.json"
    path.write_text(json.dumps(binding))
    monkeypatch.setattr(runner, "CONTROL_INPUTS", path)
    monkeypatch.setattr(runner, "read_metadata", lambda archive: ("groove/", selection))
    monkeypatch.setattr(runner, "select_rows", lambda rows: rows)
    monkeypatch.setattr(runner, "control_inventory", lambda: controls)
    monkeypatch.setattr(runner, "synthesize_input", lambda case: (samples, digest))
    monkeypatch.setattr(runner, "exclusion_inventory", lambda: [])
    monkeypatch.setattr(runner, "control_reference", forbidden)
    monkeypatch.setattr(runner, "midi_reference", forbidden)

    def unavailable():
        raise runner.RangeNotSupported("owned range-access failure")

    monkeypatch.setattr(runner, "RangeZipReader", unavailable)
    return selection, controls, path, binding


def test_acquisition_failure_preserves_all_ten_planned_waves_and_control_input_identities(tmp_path, monkeypatch):
    selection, controls, _, _ = bind_mock_population(monkeypatch, tmp_path)
    base, chosen, authored, planned, access = runner.collect_inputs(None, tmp_path / "work")
    assert base == "groove/" and chosen == selection and authored == controls
    assert len(planned) == 110
    assert [row["id"] for row in planned] == [row["id"] for row in selection + controls]
    assert all(row["status"] == "unavailable" for row in planned[:10])
    assert all(row["status"] == "ready" for row in planned[10:])
    assert "owned range-access failure" in access["failure"]
    assert access["range_bytes_fetched"] == access["range_requests"] == 0
    assert len({row["input_sha256"] for row in planned[10:]}) == 1


@pytest.mark.parametrize("field,value", [("sha256", "0" * 64), ("shape", [3]), ("dtype", "<f8")])
def test_authored_input_binding_failure_is_not_silently_replaced(tmp_path, monkeypatch, field, value):
    _, _, path, binding = bind_mock_population(monkeypatch, tmp_path)
    binding["cases"][0][field] = value
    path.write_text(json.dumps(binding))
    with pytest.raises(ValueError, match="authored_input_byte_identity"):
        runner.collect_inputs(None, tmp_path / "work")
    assert not (tmp_path / "work/inputs/010.npy").exists()


def metadata_row(identity, kind="beat", duration="10", **overrides):
    return {"id": identity, "split": "test", "time_signature": "4-4", "beat_type": kind,
            "duration": duration, "audio_filename": identity + ".wav", "midi_filename": identity + ".mid",
            **overrides}


def metadata_population():
    excluded = [metadata_row(row["id"]) for row in source.exclusion_inventory()]
    beats = [metadata_row(f"owned/beat/{i}") for i in range(7)]
    fills = [metadata_row(f"owned/fill/{i}", "fill") for i in range(4)]
    return excluded + beats + fills, beats, fills


def test_metadata_only_admission_excludes_known_sixteen_and_keeps_exact_six_plus_four(monkeypatch):
    rows, beats, fills = metadata_population()
    rows += [metadata_row("owned/train", split="train"), metadata_row("owned/meter", time_signature="3-4"),
             metadata_row("owned/short", duration="3.999"), metadata_row("owned/long", duration="28.001"),
             metadata_row("owned/filllong", "fill", "15.001"), metadata_row("owned/nan", duration="nan")]
    before = copy.deepcopy(rows)
    monkeypatch.setattr(source, "midi_reference", forbidden)
    result = source.select_rows(list(reversed(rows)))
    def order(row):
        return hashlib.sha256(row["id"].encode()).hexdigest()
    expected = [row["id"] for row in sorted(beats, key=order)[:4] + sorted(fills, key=order)[:2]]
    assert [row["id"] for row in result[:6]] == expected
    assert [row["id"] for row in result[6:]] == list(source.OLD_IDS)
    assert [row["cohort"] for row in result] == ["new_waveform"] * 6 + ["development_replay"] * 4
    excluded = {row["id"] for row in source.exclusion_inventory()}
    assert len(excluded) == 16 and not excluded.intersection(expected)
    assert rows == before
    assert source.select_rows(rows) == result


@pytest.mark.parametrize("corruption", ["duplicate", "missing_old", "insufficient_fills"])
def test_metadata_admission_rejects_changed_population(corruption):
    rows, _, fills = metadata_population()
    if corruption == "duplicate":
        rows.append(dict(rows[0]))
    elif corruption == "missing_old":
        rows = [row for row in rows if row["id"] != source.OLD_IDS[0]]
    else:
        rows = [row for row in rows if row["id"] not in {row["id"] for row in fills[1:]}]
    with pytest.raises(ValueError, match="metadata_unique|insufficient_predeclared"):
        source.select_rows(rows)


def midi_bytes(mido, tracks, midi_type=1):
    midi = mido.MidiFile(type=midi_type, ticks_per_beat=480)
    for messages in tracks:
        midi.tracks.append(mido.MidiTrack(messages))
    stream = io.BytesIO()
    midi.save(file=stream)
    return stream.getvalue()


def test_midi_reference_preserves_tempo_silence_simultaneous_hits_and_unsupported_truth():
    mido = pytest.importorskip("mido")
    tempo = [mido.MetaMessage("set_tempo", tempo=500000, time=0),
             mido.MetaMessage("set_tempo", tempo=1000000, time=480),
             mido.MetaMessage("set_tempo", tempo=250000, time=480)]
    notes = [mido.Message("note_on", channel=9, note=pitch, velocity=velocity, time=delta)
             for pitch, velocity, delta in [(35, 1, 240), (42, 127, 0), (40, 90, 240),
                                            (60, 100, 480), (58, 2, 240), (36, 0, 0), (36, 64, 120)]]
    raw = midi_bytes(mido, [tempo, notes])
    result = source.midi_reference(raw, 2.)
    assert [row["time"] for row in result] == pytest.approx([.25, .25, .5, 1.5, 1.625, 1.6875])
    assert [row["role"] for row in result] == ["kick", "hat_closed", "backbeat", "unsupported_pitch_60", "tom_low", "kick"]
    assert [row["velocity"] for row in result] == [1, 127, 90, 100, 2, 64]
    assert [row["event_id"] for row in result] == [f"r{i:05d}" for i in range(6)]
    assert source.midi_reference(raw, 1.625) == result[:4]
    # The source retains every kit/unknown onset. Orchestration filters only
    # the separate supported-role view, never the all-kit denominator.
    planned = [{"id": "owned", "cohort": "new_waveform"}]
    predictions = {"cases": [{"id": "owned", "status": "predicted", "arms": empty_arms()}]}
    references = {"cases": [{"id": "owned", "status": "ready", "events": result}]}
    measured = runner.case_metrics(planned, predictions, references)[0]["arms"][runner.ARMS[0]]
    assert measured["all_kit_50ms"]["reference"] == measured["all_kit_50ms"]["false_negatives"] == 6
    assert measured["supported_50ms"]["reference"] == 3
    assert measured["all_kit_50ms"]["per_role"]["unsupported_pitch_60"]["false_negatives"] == 1


def test_midi_reference_rejects_nonpercussion_note_on_but_ignores_velocity_zero():
    mido = pytest.importorskip("mido")
    raw = midi_bytes(mido, [[mido.Message("note_on", channel=0, note=36, velocity=1, time=240)]])
    with pytest.raises(ValueError, match="nonpercussion_reference_channel"):
        source.midi_reference(raw, 1.)
    raw = midi_bytes(mido, [[mido.Message("note_on", channel=0, note=36, velocity=0, time=240)]])
    assert source.midi_reference(raw, 1.) == []


@pytest.mark.parametrize("duration", [0., -1., float("nan"), float("inf")])
def test_midi_reference_rejects_invalid_excerpt_duration(duration):
    pytest.importorskip("mido")
    with pytest.raises(ValueError, match="excerpt_duration"):
        source.midi_reference(b"", duration)


def test_midi_reference_rejects_independent_track_clocks_and_zero_tempo():
    mido = pytest.importorskip("mido")
    raw = midi_bytes(mido, [[mido.Message("note_on", channel=9, note=36, velocity=1)]], midi_type=2)
    with pytest.raises(ValueError, match="unsupported_reference_midi_clock"):
        source.midi_reference(raw, 1.)
    raw = midi_bytes(mido, [[mido.MetaMessage("set_tempo", tempo=0)]])
    with pytest.raises(ValueError, match="reference_tempo"):
        source.midi_reference(raw, 1.)

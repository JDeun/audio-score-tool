"""Boundary evidence contracts on hand-authored miniatures; no model execution."""
from __future__ import annotations

import copy
import hashlib
import json

import numpy as np
import pytest

from scripts import note_boundary_synthetic as diagnostic


def note(pitch, onset, offset):
    return {"pitch": pitch, "onset": onset, "offset": offset, "is_drum": False}


def case_fixture(kind="change"):
    spec = {"id": "change_195", "kind": kind, "pitch": 45, "frames": 12,
            "context": "interior", "gap": 0, "interval": 1}
    hz = np.zeros(85, dtype=np.float64)
    hz[30:42] = 440 * 2 ** ((45 - 69) / 12)
    hz[42:54] = 440 * 2 ** ((46 - 69) / 12)
    path = np.full(85, 110, dtype=np.int16)
    path[30] = 108
    path[31:54] = 109
    paths = {arm: path.copy() for arm in diagnostic.PATH_ARMS}
    truth = [note(45, .30, .42), note(46, .42, .54)]
    events = [note(46, .30, .54)]
    row = {"id": spec["id"], "spec": spec, "duration_seconds": .84,
           "accuracy_eligible": True, "observation": diagnostic.identity(hz),
           "truth": truth, "alternative_truth": [], "arms": {}}
    for arm in diagnostic.ARMS:
        predicted = truth if arm == "pitch_runs" else events
        raw = json.dumps(predicted, indent=2, allow_nan=False) + "\n"
        row["arms"][arm] = {"count": len(predicted), "events": copy.deepcopy(predicted),
                            "event_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                            "diagnostics": {}, "metrics": {"onset_f1": 0., "onset_offset_f1": 0.}}
        if arm != "pitch_runs":
            row["arms"][arm]["state_path"] = diagnostic.identity(paths[arm])
    return row, hz, paths


def joined_boundary(result):
    return next(boundary for boundary in result["boundaries"]["truth"] if boundary["frame"] == 42)


def test_full_population_preserves_every_grid_and_ambiguity():
    specs = diagnostic.planned_specs()
    assert len(specs) == len({spec["id"] for spec in specs}) == 245
    assert sum(spec["kind"] == "single" for spec in specs) == 140
    assert sum(spec["kind"] == "repeat" for spec in specs) == 54
    assert sum(spec["kind"] == "change" for spec in specs) == 36
    assert sum(spec["kind"] == "silence" for spec in specs) == 3
    assert sum(spec["kind"] == "dropout" for spec in specs) == 6
    assert sum(spec["kind"] == "repeat" and spec["gap"] == 0 for spec in specs) == 9
    assert [spec["id"] for spec in specs if spec["kind"] == "change" and spec["interval"] == 1
            and spec["gap"] == 0] == [
                "change_195", "change_197", "change_207", "change_209", "change_219", "change_221"]


def test_joined_pitch_change_can_be_observed_without_a_decoded_boundary():
    row, hz, paths = case_fixture()
    result = diagnostic.diagnose_case(row, hz, paths)
    boundary = joined_boundary(result)
    assert boundary["onset_reference_ids"] == [1]
    assert boundary["offset_reference_ids"] == [0]
    assert boundary["raw_midi_step"] == pytest.approx(1)
    g = boundary["arms"]["gaussian_exponent_1"]
    assert g["decoded_label_changed"] is False
    assert g["state_changed"] is False
    assert g["emitted_events_spanning_frame"] == 1
    assert g["emitted_onsets_at_frame"] == g["emitted_offsets_at_frame"] == 0
    assert g["nearest_label_change_delta_frames"] == -12  # Equal distance: earlier edge.
    assert boundary["arms"]["pitch_runs"] == {
        "emitted_onsets_at_frame": 1, "emitted_offsets_at_frame": 1, "emitted_events_spanning_frame": 0}


def test_phase_transition_is_not_automatically_a_note_boundary():
    row, hz, paths = case_fixture()
    for arm in diagnostic.PATH_ARMS:
        paths[arm][30:42] = 108  # Attack continues until authored pitch step.
        row["arms"][arm]["state_path"] = diagnostic.identity(paths[arm])
    g = joined_boundary(diagnostic.diagnose_case(row, hz, paths))["arms"]["gaussian_exponent_1"]
    assert g["state_changed"] is True
    assert (g["phase_before"], g["phase_after"]) == (0, 1)
    assert g["decoded_label_changed"] is False
    assert g["nearest_phase_change_delta_frames"] == 0
    assert g["emitted_events_spanning_frame"] == 1


def test_clip_ending_is_emitted_even_when_retained_terminal_state_is_voiced():
    hz = np.full(9, 220.)
    path = np.full(9, 217, dtype=np.int16)
    paths = {arm: path for arm in diagnostic.PATH_ARMS}
    reference = [note(57, 0., .08)]
    events = {arm: reference for arm in diagnostic.ARMS}
    boundaries = diagnostic.boundary_rows(reference, events, hz, paths, .08)
    first, last = boundaries
    assert first["at_audio_start"] is True
    assert first["raw_before_hz"] is None
    assert first["arms"]["note_state_hmm"]["state_changed"] is None
    assert last["at_audio_end"] is True
    assert last["raw_before_hz"] == last["raw_after_hz"] == 220.
    g = last["arms"]["gaussian_exponent_1"]
    assert g["emitted_offsets_at_frame"] == 1
    assert g["emitted_events_spanning_frame"] == 0
    assert g["decoded_label_changed"] is False
    assert g["nearest_label_change_delta_frames"] is None


def test_both_same_pitch_interpretations_remain_unscored():
    row, hz, paths = case_fixture()
    row["spec"].update(kind="repeat", interval=0)
    row["accuracy_eligible"] = False
    row["alternative_truth"] = [note(45, .30, .54)]
    row["truth"][1]["pitch"] = 45
    hz[42:54] = hz[30]
    row["observation"] = diagnostic.identity(hz)
    for arm in diagnostic.ARMS:
        row["arms"][arm]["metrics"] = None
    result = diagnostic.diagnose_case(row, hz, paths)
    assert result["ambiguous"] is True
    assert result["accuracy_eligible"] is False
    assert result["truth_note_count"] == 2
    assert result["alternative_truth_note_count"] == 1
    assert [b["frame"] for b in result["boundaries"]["truth"]] == [30, 42, 54]
    assert [b["frame"] for b in result["boundaries"]["alternative_truth"]] == [30, 54]
    row["arms"]["pitch_runs"]["metrics"] = {"onset_f1": 1., "onset_offset_f1": 1.}
    with pytest.raises(ValueError, match="cannot acquire a score"):
        diagnostic.diagnose_case(row, hz, paths)


@pytest.mark.parametrize("mutation", ["hz", "path", "path_inventory", "event_count", "eligibility", "score"])
def test_mutations_cannot_enter_diagnostics(mutation):
    row, hz, paths = case_fixture()
    if mutation == "hz":
        hz[42] += 1e-9
    elif mutation == "path":
        paths["gaussian_exponent_1"][42] += 1
    elif mutation == "path_inventory":
        paths["extra"] = paths["note_state_hmm"]
    elif mutation == "event_count":
        row["arms"]["pitch_runs"]["count"] += 1
    elif mutation == "eligibility":
        row["accuracy_eligible"] = False
    elif mutation == "score":
        row["arms"]["pitch_runs"]["metrics"]["onset_f1"] = float("nan")
    with pytest.raises(ValueError):
        diagnostic.diagnose_case(row, hz, paths)


@pytest.mark.parametrize("mutation", ["missing_terminal", "negative_hz", "bad_state", "fractional_state", "off_clock", "reverse_event"])
def test_clock_and_domain_contracts(mutation):
    row, hz, paths = case_fixture()
    events = {arm: row["arms"][arm]["events"] for arm in diagnostic.ARMS}
    if mutation == "missing_terminal":
        hz = hz[:-1]
    elif mutation == "negative_hz":
        hz[0] = -1
    elif mutation == "bad_state":
        paths["note_state_hmm"][0] = 435
    elif mutation == "fractional_state":
        paths["note_state_hmm"] = paths["note_state_hmm"].astype(float)
    elif mutation == "off_clock":
        events["pitch_runs"][0]["offset"] += .001
    elif mutation == "reverse_event":
        events["pitch_runs"][0]["offset"] = .2
    with pytest.raises(ValueError):
        diagnostic.boundary_rows(row["truth"], events, hz, paths, .84)


def test_incomplete_study_cannot_produce_a_complete_summary(tmp_path):
    row, hz, paths = case_fixture()
    diagnosed = diagnostic.diagnose_case(row, hz, paths)
    with pytest.raises(ValueError, match="population"):
        diagnostic.summarize([diagnosed])
    with pytest.raises(ValueError, match="complete frozen"):
        diagnostic.diagnose_report(tmp_path, {"status": "failed", "cases": [row]})


@pytest.mark.parametrize("mutation", ["event_bytes", "extra_array", "manifest"])
def test_private_identity_mutation_is_rejected_before_aggregation(tmp_path, monkeypatch, mutation):
    row, hz, paths = case_fixture()
    # Shrink only the diagnostic inventory contract for this I/O test; no model
    # is run and no complete-study summary is manufactured.
    monkeypatch.setattr(diagnostic, "planned_specs", lambda: [row["spec"]])
    directory = tmp_path / row["id"]
    directory.mkdir()
    for arm in diagnostic.ARMS:
        (directory / f"{arm}.json").write_text(json.dumps(row["arms"][arm]["events"], indent=2) + "\n")
    arrays = {"hz": hz, **paths}
    if mutation == "event_bytes":
        path = directory / "pitch_runs.json"
        path.write_text(path.read_text() + " ")  # Same parsed notes, different frozen bytes.
    elif mutation == "extra_array":
        arrays["extra"] = hz
    np.savez_compressed(directory / "observations.npz", **arrays)
    replay = {"status": "complete", "planned_cases": 245, "planned_arms": list(diagnostic.ARMS),
              "all_predictions_saved_before_scoring": True, "cases": [row],
              "predictions_manifest_sha256": "wrong"}
    message = {"event_bytes": "event identity", "extra_array": "array inventory", "manifest": "manifest"}[mutation]
    with pytest.raises(ValueError, match=message):
        diagnostic.diagnose_report(tmp_path, replay)


def test_no_inference_dependency_is_imported():
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(diagnostic))
    imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
    assert all(not isinstance(node, ast.ImportFrom) or not (node.module or "").startswith("scripts") for node in imports)

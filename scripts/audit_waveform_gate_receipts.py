"""Audit archived waveform-gate evidence offline; never repeat source inference."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import zipfile
from pathlib import Path

from scripts.audio_gate_rest import ARMS, MODES, SETTINGS, gains_and_damage
from scripts.run_audio_gate_rest import BASES, EXPECTED, summarize

RECEIPTS = (
    {
        "filename": "basic-pitch-decode-42954128502.zip",
        "member": "basic_pitch_decode.json",
        "zip_bytes": 41870,
        "report_bytes": 290670,
        "zip_sha256": "6dc61e728c749ebfe8a51b3d4eea94026d18ca2cb6ec59c4e4ff734894cda3b0",
        "report_sha256": "dff293dc36a6642141cd235d8d958770e01d4bcd90f6f67c2ae0f82ae465309c",
        "run_id": 42954128502,
        "artifact_id": 13825524844,
    },
    {
        "filename": "waveform-gate-rest-43172631193.zip",
        "member": "report.json",
        "zip_bytes": 85041,
        "report_bytes": 1295758,
        "zip_sha256": "ce7fb57fa4da65ee320f5c5e14e58d61d6a19bbccedd303143540de239a56325",
        "report_sha256": "e807cee43b21425738ae1fea206f61c86eeb4cbbfd4cfd113c4bb226cdf2461d",
        "run_id": 43172631193,
        "artifact_id": 13922463947,
    },
)
CASE_IDS = tuple(f"vocadito_{i}" for i in range(1, 41))
ANNOTATORS = ("A1", "A2")
METRICS = ("onset", "onset_offset")
SOURCE_SHA256 = {
    "scripts/audio_gate_rest.py": "05f239835c2bee14e40cb059b68bad35c7c5a79f247c3d616677c501161fff73",
    "scripts/run_audio_gate_rest.py": "ed34357e1fcb0d63ab0be7ed226b91d5bf6fb438231b4d956aac678bfaab2ef4",
    "tests/test_audio_gate_rest.py": "36abe55b0b378da02d2a44b3342b646b00a6ae04daf15b387d255a1d707838b0",
    "docs/research/AUDIO_GATE_REST_PROTOCOL_2026-11-12.md":
        "2bead50724ea9bcb2578ca49ea47e24085bf071b19bdb0cd3c387cff89a80913",
    "scripts/run_cpu_vocadito_candidates.py": "0265be97c1f891816da30e75fa145a58a1972636a5729fcb1ccc761665c52465",
    "scripts/vocadito_reference.py": "2ee6f18518e0f4887b9f0c163fff6cfcb964a05d21da1eddd6fcf8e031259194",
    "scripts/run_offset_tail_probe.py": "44730f903b4e8eddc1755ff0ae89793052c43abc129f15028b91b0d16562939e",
    "scripts/vocal_recovery.py": "9cbc4c1e635b78263c46473d357fa928350fabdf3efcab79ec44a42e00fa246b",
}
TOLERANCE = 1e-12


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _same(actual, expected, path):
    """Compare nested arithmetic with absolute tolerance only; types stay meaningful."""
    if isinstance(expected, dict):
        _require(isinstance(actual, dict) and actual.keys() == expected.keys(),
                 f"{path}: field mismatch")
        for key, value in expected.items():
            _same(actual[key], value, f"{path}.{key}")
    elif isinstance(expected, (list, tuple)):
        _require(isinstance(actual, (list, tuple)) and len(actual) == len(expected),
                 f"{path}: length mismatch")
        for i, value in enumerate(expected):
            _same(actual[i], value, f"{path}[{i}]")
    elif type(expected) is float:
        _require(type(actual) in (int, float) and math.isfinite(actual)
                 and abs(actual - expected) <= TOLERANCE, f"{path}: numeric mismatch")
    else:
        _require(type(actual) is type(expected) and actual == expected, f"{path}: mismatch")


def _integer(value, path, maximum=None):
    _require(type(value) is int and value >= 0
             and (maximum is None or value <= maximum), f"{path}: invalid count")
    return value


def _finite(value, path):
    _require(type(value) in (int, float) and math.isfinite(value),
             f"{path}: nonfinite or nonnumeric value")
    return value


def _hash(value, path):
    _require(isinstance(value, str) and len(value) == 64
             and set(value) <= set("0123456789abcdef"), f"{path}: invalid SHA256")


def _read_receipt(root, spec):
    path = root / "docs/research/receipts" / spec["filename"]
    _require(path.is_file() and not path.is_symlink(), f"{path.name}: regular file required")
    _require(path.stat().st_size == spec["zip_bytes"], f"{path.name}: archive size mismatch")
    data = path.read_bytes()
    _same(hashlib.sha256(data).hexdigest(), spec["zip_sha256"], f"{path.name}: ZIP digest")
    # Check before decompression. No member is extracted to the filesystem.
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        _same(archive.namelist(), [spec["member"]], f"{path.name}: allowed JSON member")
        info = archive.getinfo(spec["member"])
        _require(not info.is_dir() and info.file_size == spec["report_bytes"]
                 and not info.flag_bits & 1, f"{path.name}: invalid member metadata")
        raw = archive.read(spec["member"])
    _same(hashlib.sha256(raw).hexdigest(), spec["report_sha256"], f"{path.name}: report digest")
    report = json.loads(raw)
    _require(isinstance(report, dict), f"{path.name}: report must be an object")
    return report


def load_receipts(root: Path) -> tuple[dict, dict]:
    """Return the exact checksum-verified baseline and gate JSON receipts.

    ``root`` is the repository root. This performs no network or model access.
    Use ``validate_receipts`` or ``audit`` for the separate arithmetic checks.
    """
    return tuple(_read_receipt(Path(root), spec) for spec in RECEIPTS)


def _cases(report, planned_key, label):
    planned = report[planned_key]
    _require(len(planned) == 40 and set(planned) == set(CASE_IDS),
             f"{label}: planned forty-source identities mismatch")
    rows = report["cases"]
    ids = [row["id"] for row in rows]
    _require(len(ids) == 40 and len(set(ids)) == 40 and set(ids) == set(CASE_IDS),
             f"{label}: missing or duplicate source identity")
    _require(all(row["status"] == "scored" for row in rows), f"{label}: incomplete case")
    return {row["id"]: row for row in rows}


def _occupancy(value, scope, path):
    expected_keys = {"reference_note_s", "reference_gap_s", "correct_gap_s", "lost_note_s",
                     "filled_reference_gap_s", "gap_precision", "gap_recall", "gap_f1"}
    _require(set(value) == expected_keys, f"{path}: occupancy field mismatch")
    for key in expected_keys - {"gap_precision", "gap_recall", "gap_f1"}:
        _require(_finite(value[key], path + key) >= 0, f"{path}: negative occupancy")
    for key in ("reference_note_s", "reference_gap_s"):
        _same(value[key], scope[key], path + key)
    tp, fp, fn = (value[k] for k in ("correct_gap_s", "lost_note_s", "filled_reference_gap_s"))
    _same(tp + fn, value["reference_gap_s"], path + "gap conservation")
    _require(fp <= value["reference_note_s"] + TOLERANCE, f"{path}: note occupancy exceeds scope")
    for key, expected in {
        "gap_precision": tp / (tp + fp) if tp + fp else None,
        "gap_recall": tp / (tp + fn) if tp + fn else None,
        "gap_f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
    }.items():
        _same(value[key], expected, path + key)


def _provenance(baseline, gate, root):
    for label, report in (("baseline", baseline), ("gate", gate)):
        _same(report["status"], "complete", label + " status")
        _same(report["quality_approved"], False, label + " quality flag")
        _same(report["archive_sha256"],
              "e0d6b99d3f9c594afe5ae5c4d7bdacebe569e53b809e90b89d1c771c4f9990e3",
              label + " corpus digest")
    _same(baseline["all_cases_complete"], True, "baseline completeness")
    _same(baseline["source_revision"], "c4ea6148b38cb65b5e714cf984b23121246a09df", "baseline checkout")
    _same(gate["source_revision"], "d6bd1d761d5edc993d1166c5630bcca1c80ef5bb", "gate checkout")
    _same(gate["source_head"], "451f4dc616dabb60499298a0d733c351be405a2a", "gate head")
    _same(gate["baseline_zip_sha256"], RECEIPTS[0]["zip_sha256"], "baseline provenance")
    _same(gate["settings"], SETTINGS, "frozen gate settings")
    _same(gate["runtime"], EXPECTED, "frozen numeric runtime")
    _same(gate["source_sha256"], SOURCE_SHA256, "historical source digests")
    for key, expected in {"model_inference_repeated": True, "explicit_notated_rest_reference": False,
                          "joint_bar_decoder_evaluated": False, "reused_development_corpus": True,
                          "gate_used_reference": False,
                          "gain_tests_are_unclipped_float_amplitude_changes": True}.items():
        _same(gate[key], expected, key)
    _same(gate["model_identity"], baseline["model_identity"], "shared model identity")
    identity = gate["model_identity"]
    _same(identity["weights"], {
        "git_blob": "c30e5f9438e798604b7177aa26be1fe64482f767",
        "sha256": "2c3c1d144bfa61ad236e92e169c13535c880469a12a047d4e73451f2c059a0ec",
        "bytes": 230444}, "pinned weights")
    _same(identity["backend"], "onnx-cpu", "CPU backend")
    _same(identity["weights_source_revision"], "fa5997af0a8210982619003269994a1be25eddf3",
          "model source revision")
    _same(identity["intra_threads"], 2, "intra threads")
    _same(identity["inter_threads"], 1, "inter threads")
    _same(identity["thresholds"], {"onset": 0.5, "frame": 0.3, "minimum_note_ms": 127.7},
          "original model decoder thresholds")
    _same(identity["pitch_bends_scored"], False, "pitch-bend scope")
    _same(identity["instrument_identity_predicted"], False, "instrument scope")
    for path, expected in SOURCE_SHA256.items():
        if path in baseline["source_sha256"]:
            _same(baseline["source_sha256"][path], expected, "shared source " + path)
        if root is not None:
            source = Path(root) / path
            _require(source.is_file() and not source.is_symlink(), "missing frozen source " + path)
            _same(hashlib.sha256(source.read_bytes()).hexdigest(), expected, "current frozen source " + path)


def validate_receipts(baseline: dict, gate: dict, root: Path | None = None) -> dict:
    """Check receipt semantics and arithmetic, independently of ZIP byte identity.

    This can diagnose copied in-memory reports, but only ``load_receipts`` verifies
    their historical origin. Counts/masks cannot independently prove audio accuracy.
    """
    _provenance(baseline, gate, root)
    prior = _cases(baseline, "planned_case_ids", "baseline")
    current = _cases(gate, "planned_ids", "gate")
    checks = 0
    for case_id in CASE_IDS:
        row, old = current[case_id], prior[case_id]
        _require(set(row) == {"id", "status", "audio_sha256", "reference_sha256", "duration_s",
                             "gain_checks", "source_prediction_receipt", "gates", "bases",
                             "elapsed_seconds"}, case_id + " metadata-only case fields")
        _same(row["audio_sha256"], old["audio_sha256"], case_id + " audio hash")
        _same(row["reference_sha256"], old["reference_sha256"], case_id + " reference hashes")
        _hash(row["audio_sha256"], case_id)
        _require(set(row["reference_sha256"]) == set(ANNOTATORS), case_id + " annotations")
        for value in row["reference_sha256"].values():
            _hash(value, case_id)
        _require(set(row["bases"]) == set(BASES), case_id + " decoder coverage")
        _require(set(row["gates"]) == set(MODES), case_id + " gate coverage")
        prediction = row["source_prediction_receipt"]
        _require(set(prediction) == {"prediction_midi_sha256", "raw_output_sha256",
                                    "predicted_note_count", "empty_prediction"},
                 case_id + " metadata-only prediction receipt")
        _same(prediction["prediction_midi_sha256"], old["prediction_receipt"]["prediction_midi_sha256"],
              case_id + " replayed prediction MIDI hash")
        for key in ("prediction_midi_sha256", "raw_output_sha256"):
            _hash(prediction[key], case_id)
        _same(prediction["predicted_note_count"], row["bases"]["default"]["arms"]["raw"]["count"],
              case_id + " raw prediction count")
        _same(prediction["empty_prediction"], prediction["predicted_note_count"] == 0,
              case_id + " empty prediction flag")
        duration = _finite(row["duration_s"], case_id + " duration")
        _require(duration > 0, case_id + " positive duration required")
        frame_count = math.ceil(duration / SETTINGS["hop_seconds"])
        for mode in MODES:
            evidence = row["gates"][mode]
            _same(evidence["total_frames"], frame_count, case_id + " frame count")
            _integer(evidence["quiet_frames"], case_id + " quiet frames", frame_count)
            expected_close = (-45. if mode == "absolute" else evidence["reference_db"] - 30.)
            _same(evidence["close_db"], expected_close, case_id + " gate threshold")
            _same(evidence["open_db"], expected_close + 6., case_id + " gate hysteresis")
            _require(set(evidence["annotators"]) == set(ANNOTATORS), case_id + " gate annotations")
        _require(set(row["gain_checks"]) == {"-12", "12"}, case_id + " gain controls")
        for gain in row["gain_checks"].values():
            _require(set(gain) == {"absolute_changed_frames", "relative_changed_frames"},
                     case_id + " gain fields")
            _integer(gain["absolute_changed_frames"], case_id + " absolute gain", frame_count)
            _same(gain["relative_changed_frames"], 0, case_id + " relative gain invariance")
        for base, old_arm in BASES.items():
            arms = row["bases"][base]["arms"]
            _require(set(arms) == set(ARMS), case_id + " arm coverage")
            raw = arms["raw"]
            _same(raw["event_sha256"], old["arms"][old_arm]["event_sha256"], case_id + " raw events")
            _same(raw["count"], old["arms"][old_arm]["count"], case_id + " raw count")
            for arm_name, arm in arms.items():
                context = f"{case_id}/{base}/{arm_name}/"
                _require(set(arm) == {"count", "event_sha256", "edits", "annotators"},
                         context + "metadata-only fields")
                count = _integer(arm["count"], context + "output count")
                _hash(arm["event_sha256"], context)
                _require(set(arm["annotators"]) == set(ANNOTATORS), context + "annotator coverage")
                edits = arm["edits"]
                if arm_name == "raw":
                    _same(edits, {"changed_parents": 0}, context + "raw edits")
                else:
                    for name in ("changed_parents", "deleted", "split_parents", "out_of_audio_unchanged"):
                        _integer(edits[name], context + name, raw["count"])
                    _integer(edits["extra_fragments"], context + "extra fragments")
                    _same(edits["output_count"], count, context + "edit output count")
                    _same(count, raw["count"] - edits["deleted"] + edits["extra_fragments"],
                          context + "note count conservation")
                    _require(edits["deleted"] + edits["split_parents"] <= edits["changed_parents"],
                             context + "invalid changed-parent count")
                    _require(edits["extra_fragments"] >= edits["split_parents"], context + "split count")
                    _require(_finite(edits["removed_seconds"], context) >= 0, context + "negative removal")
                for annotator in ANNOTATORS:
                    metric = arm["annotators"][annotator]
                    original = raw["annotators"][annotator]
                    _require(set(metric) == {"reference_note_count", "onset_f1", "onset_offset_f1",
                                             "onset_reference_mask", "onset_offset_reference_mask",
                                             "occupancy", "transition"}, context + "metric fields")
                    ref_count = _integer(metric["reference_note_count"], context + "reference count")
                    _same(ref_count, old["arms"][old_arm]["annotators"][annotator]["reference_note_count"],
                          context + "reference replay")
                    for name in METRICS:
                        mask = metric[name + "_reference_mask"]
                        _require(isinstance(mask, str) and len(mask) == ref_count
                                 and set(mask) <= {"0", "1"}, context + "invalid reference mask")
                        matches = mask.count("1")
                        _require(matches <= min(ref_count, count), context + "invalid matching cardinality")
                        expected_f1 = round(2 * matches / (ref_count + count), 8) if count else 0.
                        _same(metric[name + "_f1"], expected_f1, context + name + " F1 from mask")
                        _same(metric["transition"][name],
                              gains_and_damage(original[name + "_reference_mask"], mask),
                              context + name + " gain/damage")
                        if arm_name == "raw":
                            _same(metric[name + "_f1"], old["arms"][old_arm]["annotators"][annotator][name + "_f1"],
                                  context + name + " baseline score replay")
                        checks += 1
                    occupancy = metric["occupancy"]
                    scope = original["occupancy"]
                    _occupancy(occupancy, scope, context + annotator)
                    _require(scope["reference_note_s"] + scope["reference_gap_s"] <= duration + TOLERANCE,
                             context + "scope exceeds audio")
                    if arm_name == "raw":
                        for mode in MODES:
                            _occupancy(row["gates"][mode]["annotators"][annotator], scope,
                                       context + mode + annotator)
                    else:
                        _require(occupancy["lost_note_s"] + TOLERANCE >= scope["lost_note_s"]
                                 and occupancy["filled_reference_gap_s"] <= scope["filled_reference_gap_s"] + TOLERANCE,
                                 context + "intersection occupancy monotonicity")
            for mode in MODES:
                hard, soft = arms[mode + "_hard"], arms[mode + "_soft"]
                _require(soft["edits"]["changed_parents"] <= hard["edits"]["changed_parents"],
                         case_id + "soft change subset")
                _require(soft["edits"]["removed_seconds"] <= hard["edits"]["removed_seconds"] + TOLERANCE,
                         case_id + "soft removal subset")
                for annotator in ANNOTATORS:
                    h, s = (v["annotators"][annotator]["occupancy"] for v in (hard, soft))
                    _require(s["lost_note_s"] <= h["lost_note_s"] + TOLERANCE
                             and s["filled_reference_gap_s"] + TOLERANCE >= h["filled_reference_gap_s"],
                             case_id + "hard/soft occupancy containment")
    _same(gate["summary"], summarize(gate["cases"], CASE_IDS), "recomputed frozen summary")
    return {"status": "verified", "recordings": 40, "decoders": 2, "arms": 5, "annotators": 2,
            "metric_mask_checks": checks, "raw_prediction_replays": 80,
            "baseline_metric_replays": 320, "new_source_inference": False,
            "quality_approved": False}


def audit(root: Path) -> dict:
    """Verify archived bytes, frozen code identities and receipt arithmetic."""
    baseline, gate = load_receipts(root)
    return validate_receipts(baseline, gate, root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    print(json.dumps(audit(args.root), sort_keys=True))


if __name__ == "__main__":
    main()

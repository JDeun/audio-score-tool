"""Historical receipt integrity/coverage checks; no source audio or model runtime."""
from __future__ import annotations

import copy
import shutil
from pathlib import Path

import pytest

from scripts import audit_waveform_gate_receipts as receipts

ROOT = Path(receipts.__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def archived():
    return receipts.load_receipts(ROOT)


def test_exact_historical_archives_and_all_arithmetic_pass():
    result = receipts.audit(ROOT)
    assert result["status"] == "verified"
    assert result["recordings"] == 40
    assert result["metric_mask_checks"] == 1600
    assert result["baseline_metric_replays"] == 320
    assert result["new_source_inference"] is False
    assert result["quality_approved"] is False


@pytest.mark.parametrize("change", ["same_size_corruption", "append", "symlink"])
def test_archive_tampering_fails_before_report_use(tmp_path, change):
    destination = tmp_path / "docs/research/receipts"
    destination.mkdir(parents=True)
    for spec in receipts.RECEIPTS:
        shutil.copyfile(ROOT / "docs/research/receipts" / spec["filename"],
                        destination / spec["filename"])
    target = destination / receipts.RECEIPTS[0]["filename"]
    if change == "symlink":
        target.unlink()
        target.symlink_to(ROOT / "docs/research/receipts" / target.name)
    else:
        data = bytearray(target.read_bytes())
        if change == "append":
            data.append(0)
        else:
            data[len(data) // 2] ^= 1
        target.write_bytes(data)
    with pytest.raises(ValueError, match="digest|size mismatch|regular file"):
        receipts.load_receipts(tmp_path)


@pytest.mark.parametrize("change", ["missing", "duplicate", "failed", "missing_arm", "missing_annotator"])
def test_incomplete_coverage_cannot_become_complete(archived, change):
    baseline, gate = copy.deepcopy(archived)
    first = gate["cases"][0]
    if change == "missing":
        gate["cases"].pop()
    elif change == "duplicate":
        gate["cases"][-1] = copy.deepcopy(first)
    elif change == "failed":
        first["status"] = "failed"
    elif change == "missing_arm":
        del first["bases"]["default"]["arms"]["relative_soft"]
    else:
        del first["bases"]["default"]["arms"]["raw"]["annotators"]["A2"]
    with pytest.raises(ValueError, match="identity|incomplete|coverage"):
        receipts.validate_receipts(baseline, gate)


@pytest.mark.parametrize("change", ["mask", "f1", "gain", "note_count", "occupancy", "summary"])
def test_corrupted_scientific_bookkeeping_is_rejected(archived, change):
    baseline, gate = copy.deepcopy(archived)
    arm = gate["cases"][0]["bases"]["onset065"]["arms"]["relative_soft"]
    metric = arm["annotators"]["A1"]
    if change == "mask":
        metric["onset_reference_mask"] = "x" + metric["onset_reference_mask"][1:]
    elif change == "f1":
        metric["onset_offset_f1"] += 0.01
    elif change == "gain":
        metric["transition"]["onset_offset"]["gained"] += 1
    elif change == "note_count":
        arm["edits"]["output_count"] += 1
    elif change == "occupancy":
        metric["occupancy"]["correct_gap_s"] += 0.01
    else:
        gate["summary"]["bases"]["onset065"]["relative_soft"]["onset_offset_f1"] += 1e-8
    with pytest.raises(ValueError):
        receipts.validate_receipts(baseline, gate)


@pytest.mark.parametrize("change", ["model", "source", "baseline", "raw_payload"])
def test_changed_provenance_or_raw_payload_is_rejected(archived, change):
    baseline, gate = copy.deepcopy(archived)
    if change == "model":
        gate["model_identity"]["backend"] = "different-backend"
    elif change == "source":
        gate["source_sha256"]["scripts/audio_gate_rest.py"] = "0" * 64
    elif change == "baseline":
        baseline["cases"][0]["arms"]["raw"]["event_sha256"] = "0" * 64
    else:
        gate["cases"][0]["events"] = [{"pitch": 60, "onset": 0, "offset": 1}]
    with pytest.raises(ValueError):
        receipts.validate_receipts(baseline, gate)


def test_nonfinite_occupancy_cannot_pass_numeric_comparison(archived):
    baseline, gate = copy.deepcopy(archived)
    gate["cases"][0]["gates"]["relative"]["annotators"]["A1"]["lost_note_s"] = float("nan")
    with pytest.raises(ValueError, match="nonfinite"):
        receipts.validate_receipts(baseline, gate)

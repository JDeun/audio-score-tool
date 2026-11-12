"""Exercise the real expressive runner with entirely invented dependency data."""
from __future__ import annotations

import copy
import dataclasses
import json
import zipfile

import pytest

from scripts import run_kraisler_expressive as runner


def dependencies(tmp_path, monkeypatch):
    timeline, source_cases, alignment_cases, gate_cases = [], [], [], []
    private = tmp_path / "invented-members"
    private.mkdir()
    baseline = {"reference_count": 1, "beat_alignment": {"status": "unavailable"}}
    for tid in runner.PLANNED_IDS:
        paths, hashes = {}, {}
        for role, (_, _, path_key) in runner.source.ROLES.items():
            path = private / (tid + "-" + role)
            raw = (role + " " + tid).encode()
            path.write_bytes(raw)
            paths[path_key] = str(path)
            hashes[role] = runner.inherited.digest(raw)
        source_cases.append({"id": tid, "source_id": "kraisler_" + tid,
                             **paths, "member_sha256": hashes})
        alignment_cases.append({"id": tid, "status": "analyzed", "analysis": copy.deepcopy(baseline),
                                "source_member_sha256": hashes, "source_audio_duration_s": 42.0})
        gate_cases.append({"id": tid, "status": "scored", "source_member_sha256": hashes})

    def make_receipt(name, cases):
        path = tmp_path / (name + ".zip")
        report = {"status": "complete", "source_head": name + "-head",
                  "source_revision": name + "-checkout", "cases": cases}
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("report.json", json.dumps(report))
        return path, runner.inherited.digest(path.read_bytes())

    alignment_path, alignment_sha = make_receipt("alignment", alignment_cases)
    gate_path, gate_sha = make_receipt("gate", gate_cases)
    monkeypatch.setattr(runner, "ALIGNMENT_RECEIPT", alignment_path)
    monkeypatch.setattr(runner, "ALIGNMENT_ZIP_SHA256", alignment_sha)
    monkeypatch.setattr(runner, "GATE_RECEIPT", gate_path)
    monkeypatch.setattr(runner, "GATE_ZIP_SHA256", gate_sha)
    monkeypatch.setattr(runner, "collect_provenance", lambda: {
        "source_sha256": {"invented-contract": "0" * 64},
        "runtime": {"standard_library_only": True},
        "checkout_revision": "actual-checkout", "checkout_tree": "actual-tree",
    })

    def controls():
        timeline.append("controls")
        return {"status": "completed", "illustrative_only": True}

    def acquire(destination):
        timeline.append("acquire")
        return {"status": "verified", "network_bytes": 0, "http_range_requests": 0,
                "verified_member_count": 30, "media_acquired": False, "cases": source_cases}

    def analyze(score, piano_score, match_audit, raw_beats, raw_notes, audio_duration_s, *, raw_score):
        tid = raw_notes.decode().split()[-1]
        timeline.append("analysis:" + tid)
        assert raw_score == score == ("score " + tid).encode()
        assert audio_duration_s == 42.0
        return {"reference_count": 1, "frozen_baseline": copy.deepcopy(baseline),
                "local_support": {"status": "unavailable"}}

    def read_receipt(path, kind):
        timeline.append(kind)
        with zipfile.ZipFile(path) as archive:
            return json.loads(archive.read("report.json"))

    def verify(old, analysis):
        timeline.append("verify:" + old["id"])
        if old["analysis"] != analysis["frozen_baseline"]:
            raise ValueError("invented baseline mismatch")

    def attribute(previous, analysis):
        timeline.append("attribute:" + previous["id"])
        return {"class_counts": {"unresolved": 1}}

    def summarize(cases, planned_ids):
        timeline.append("summary")
        assert tuple(row["id"] for row in cases) == planned_ids == runner.PLANNED_IDS
        assert all(row["status"] == "analyzed" and row["attribution"] is not None for row in cases)
        return {"recordings": 6, "admitted_recordings": 0}

    deps = runner.Dependencies(
        acquire_sources=acquire,
        load_gate_manifest=lambda: {"sources": [{"id": tid, "audio": {"duration_seconds": 42.0}}
                                                for tid in runner.PLANNED_IDS]},
        parse_score=lambda raw: raw,
        parse_piano_match=lambda raw, piano_score: raw,
        synthetic_controls=controls,
        analyze_expressive=analyze,
        read_alignment_baseline=lambda path: read_receipt(path, "alignment"),
        verify_baseline_case=verify,
        read_previous_receipt=lambda path: read_receipt(path, "gate"),
        attribute_expressive=attribute,
        summarize_expressive=summarize,
    )
    return deps, timeline


def execute(tmp_path, deps):
    work, output = tmp_path / "work", tmp_path / "public" / "report.json"
    status = runner.run(work, output, deps=deps)
    return status, json.loads(output.read_bytes()), work, output


def test_six_analyses_precede_both_receipts_and_all_baselines_precede_attribution(tmp_path, monkeypatch):
    deps, timeline = dependencies(tmp_path, monkeypatch)
    status, report, _, output = execute(tmp_path, deps)
    assert status == 0 and report["status"] == "complete"
    assert report["summary"]["admitted_recordings"] == 0
    assert timeline == ["controls", "acquire", *["analysis:" + tid for tid in runner.PLANNED_IDS],
                        "alignment", "gate", *["verify:" + tid for tid in runner.PLANNED_IDS],
                        *["attribute:" + tid for tid in runner.PLANNED_IDS], "summary"]
    assert report["completed_analyses"] == report["completed_baseline_verifications"] == 6
    assert report["completed_attributions"] == 6
    assert report["analysis_phase_completed_before_prior_receipts"] is True
    assert report["alignment_baseline_loaded"] is True and report["gate_receipt_loaded"] is True
    assert report["synthetic_controls"] == {"status": "completed", "illustrative_only": True}
    assert str(tmp_path) not in output.read_text() and "score 02" not in output.read_text()


@pytest.mark.parametrize("stage", ["provenance", "synthetic_controls", "source_acquisition"])
def test_preparation_failure_preserves_redacted_receipt_without_historical_reads(tmp_path, monkeypatch, stage):
    deps, timeline = dependencies(tmp_path, monkeypatch)

    def fail(*args):
        raise ValueError("private-source-content " + str(tmp_path / "source.xml"))

    if stage == "provenance":
        monkeypatch.setattr(runner, "collect_provenance", fail)
    elif stage == "synthetic_controls":
        deps = dataclasses.replace(deps, synthetic_controls=fail)
    else:
        deps = dataclasses.replace(deps, acquire_sources=fail)
    status, report, work, output = execute(tmp_path, deps)
    assert status == 1 and report["status"] == "preparation_failed"
    assert report["failure_stage"] == stage and report["summary"] is None
    assert report["cases"] == [] and "alignment" not in timeline and "gate" not in timeline
    assert "private-source-content" not in output.read_text() and str(tmp_path) not in output.read_text()
    assert "private-source-content" in (work / "failure.log").read_text()


def test_failed_source_keeps_six_diagnostics_and_prevents_both_historical_reads(tmp_path, monkeypatch):
    deps, timeline = dependencies(tmp_path, monkeypatch)
    original = deps.analyze_expressive

    def fail_one(*args, **kwargs):
        result = original(*args, **kwargs)
        if args[4] == b"notes 08":
            raise ValueError("invented unsupported source")
        return result

    deps = dataclasses.replace(deps, analyze_expressive=fail_one)
    status, report, _, _ = execute(tmp_path, deps)
    assert status == 1 and report["status"] == "incomplete" and report["summary"] is None
    assert len(report["cases"]) == 6 and report["completed_analyses"] == 5
    assert [row["id"] for row in report["cases"] if row["status"] == "failed"] == ["08"]
    assert "alignment" not in timeline and "gate" not in timeline and "summary" not in timeline
    assert timeline.count("controls") == 1


@pytest.mark.parametrize("receipt", ["alignment", "gate"])
def test_receipt_digest_mismatch_is_detected_after_analysis_before_attribution(tmp_path, monkeypatch, receipt):
    deps, timeline = dependencies(tmp_path, monkeypatch)
    monkeypatch.setattr(runner, receipt.upper() + "_ZIP_SHA256", "0" * 64)
    status, report, _, _ = execute(tmp_path, deps)
    assert status == 1 and report["status"] == "historical_receipt_failed"
    assert report["completed_analyses"] == 6 and report["summary"] is None
    assert all(row["analysis"] is not None for row in report["cases"])
    assert not any(item.startswith("attribute:") for item in timeline)
    assert report["completed_baseline_verifications"] == 0


@pytest.mark.parametrize("receipt,role", [("alignment", "piano_match"), ("gate", "notes")])
def test_changed_historical_source_identity_prevents_conditional_attribution(
        tmp_path, monkeypatch, receipt, role):
    deps, timeline = dependencies(tmp_path, monkeypatch)
    original = deps.read_alignment_baseline if receipt == "alignment" else deps.read_previous_receipt

    def changed_identity(path):
        report = original(path)
        report["cases"][0]["source_member_sha256"][role] = "0" * 64
        return report

    field = "read_alignment_baseline" if receipt == "alignment" else "read_previous_receipt"
    deps = dataclasses.replace(deps, **{field: changed_identity})
    status, report, _, _ = execute(tmp_path, deps)
    assert status == 1 and report["status"] == "baseline_verification_failed"
    assert report["completed_analyses"] == 6 and report["summary"] is None
    assert not any(item.startswith("attribute:") for item in timeline)


def test_frozen_baseline_disagreement_prevents_all_attribution(tmp_path, monkeypatch):
    deps, timeline = dependencies(tmp_path, monkeypatch)

    def reject(old, analysis):
        timeline.append("verify:" + old["id"])
        raise ValueError("invented regenerated baseline disagreement")

    deps = dataclasses.replace(deps, verify_baseline_case=reject)
    status, report, _, _ = execute(tmp_path, deps)
    assert status == 1 and report["status"] == "baseline_verification_failed"
    assert report["completed_analyses"] == 6 and report["completed_attributions"] == 0
    assert report["summary"] is None and not any(item.startswith("attribute:") for item in timeline)


@pytest.mark.parametrize("stage", ["verification", "attribution"])
def test_historical_helpers_cannot_modify_saved_analysis(tmp_path, monkeypatch, stage):
    deps, _ = dependencies(tmp_path, monkeypatch)

    def mutate(previous, analysis):
        analysis["frozen_baseline"]["reference_count"] = 99
        return {"class_counts": {"unresolved": 1}}

    field = "verify_baseline_case" if stage == "verification" else "attribute_expressive"
    deps = dataclasses.replace(deps, **{field: mutate})
    status, report, _, _ = execute(tmp_path, deps)
    assert status == 1 and report["summary"] is None
    assert report["completed_analyses"] == 6 and report["completed_attributions"] == 0
    assert all(row["analysis"]["frozen_baseline"]["reference_count"] == 1 for row in report["cases"])


def test_aggregation_exception_preserves_all_completed_case_receipts(tmp_path, monkeypatch):
    deps, _ = dependencies(tmp_path, monkeypatch)

    def fail(cases, planned_ids):
        assert len(cases) == 6 and all(row["attribution"] is not None for row in cases)
        cases[0]["analysis"]["raw_notes"] = "private-source-content"
        raise RuntimeError("private-source-content")

    deps = dataclasses.replace(deps, summarize_expressive=fail)
    status, report, _, output = execute(tmp_path, deps)
    assert status == 1 and report["status"] == "aggregation_failed" and report["summary"] is None
    assert report["completed_analyses"] == report["completed_attributions"] == 6
    assert all(row["status"] == "analyzed" for row in report["cases"])
    assert "private-source-content" not in output.read_text() and "raw_notes" not in output.read_text()


def test_combined_report_budget_keeps_bounded_failure_receipt(tmp_path, monkeypatch):
    deps, _ = dependencies(tmp_path, monkeypatch)
    monkeypatch.setattr(runner, "MAX_REPORT_BYTES", 25_000)
    deps = dataclasses.replace(deps, attribute_expressive=lambda *args: {"diagnostic": "x" * 5000})
    status, report, _, output = execute(tmp_path, deps)
    assert status == 1 and report["status"] == "incomplete" and report["summary"] is None
    assert report["completed_analyses"] == 6 and 0 < report["completed_attributions"] < 6
    assert len(report["cases"]) == 6 and output.stat().st_size <= runner.MAX_REPORT_BYTES
    assert any(row["status"] == "attribution_failed" for row in report["cases"])


def test_private_analysis_fields_are_not_published(tmp_path, monkeypatch):
    deps, timeline = dependencies(tmp_path, monkeypatch)
    deps = dataclasses.replace(deps, analyze_expressive=lambda *args, **kwargs: {
        "frozen_baseline": {}, "raw_notes": "private-source-content",
        "score_path": str(tmp_path / "source.xml"),
    })
    status, report, _, output = execute(tmp_path, deps)
    assert status == 1 and report["completed_analyses"] == 0 and report["summary"] is None
    assert "alignment" not in timeline and "gate" not in timeline
    assert "private-source-content" not in output.read_text() and "score_path" not in output.read_text()


@pytest.mark.parametrize("unsafe", ["existing_output", "nested_report"])
def test_unsafe_output_is_rejected_before_controls_or_acquisition(tmp_path, monkeypatch, unsafe):
    deps, timeline = dependencies(tmp_path, monkeypatch)
    work, output = tmp_path / "work", tmp_path / "report.json"
    if unsafe == "existing_output":
        output.write_text("preserve this")
    else:
        output = work / "report.json"
    with pytest.raises(ValueError, match="fresh separate"):
        runner.run(work, output, deps=deps)
    assert timeline == [] and not work.exists()
    if unsafe == "existing_output":
        assert output.read_text() == "preserve this"

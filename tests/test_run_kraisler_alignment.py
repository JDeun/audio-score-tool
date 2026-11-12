"""Exercise the actual runner with injected metadata analysis dependencies."""
from __future__ import annotations

import dataclasses
import json

import pytest

from scripts import run_kraisler_alignment as runner


def dependencies(tmp_path, monkeypatch):
    """Invented private members; no original source, model, or network access."""
    timeline, source_cases, previous_cases = [], [], []
    private = tmp_path / "invented-private-members"
    private.mkdir()
    for tid in runner.PLANNED_IDS:
        paths, hashes = {}, {}
        for role, (_, _, path_key) in runner.source.ROLES.items():
            path = private / (tid + "-" + role)
            raw = (role + " " + tid).encode()
            path.write_bytes(raw)
            paths[path_key] = str(path)
            hashes[role] = runner.digest(raw)
        source_cases.append({"id": tid, "source_id": "kraisler_" + tid, **paths,
                             "member_sha256": hashes})
        previous_cases.append({"id": tid, "status": "scored", "source_member_sha256": hashes})

    def acquire(destination):
        timeline.append("acquire")
        return {"status": "verified", "network_bytes": 0, "http_range_requests": 0,
                "verified_member_count": 30, "media_acquired": False, "cases": source_cases}

    def analyze(score, piano_score, match_audit, raw_beats, raw_notes, audio_duration_s):
        tid = raw_notes.decode().split()[-1]
        timeline.append("analysis:" + tid)
        assert audio_duration_s == 42.0
        return {
            "reference_count": 1,
            "beat_alignment": {"status": "unavailable"},
            "correspondence": {"primary_window_ms": 100, "windows": {
                str(window): {"matched_pairs": 0, "memberships": {"unresolved": "1"}}
                for window in (50, 100, 200)
            }},
            "rest_context": {"projected_count": 0},
        }

    def read_previous(path):
        timeline.append("prior")
        assert path == runner.PREVIOUS_RECEIPT
        return {"status": "complete", "source_head": "prior-head", "source_revision": "prior-merge",
                "cases": previous_cases}

    def attribute(prior_case, analysis):
        timeline.append("attribute:" + prior_case["id"])
        return {"reference_count": 1, "class_counts": {"unresolved": 1}}

    def summarize(cases, planned_ids):
        timeline.append("summary")
        assert tuple(row["id"] for row in cases) == planned_ids == runner.PLANNED_IDS
        assert all(row["status"] == "analyzed" and row["attribution"] is not None for row in cases)
        return {"recordings": 6, "reference_count": 6, "admitted_recordings": 0}

    monkeypatch.setattr(runner, "collect_provenance", lambda: {
        "source_sha256": {"invented-contract": "0" * 64},
        "runtime": {"standard_library_only": True},
        "checkout_revision": "actual-checkout", "checkout_tree": "actual-tree",
    })
    deps = runner.Dependencies(
        acquire_sources=acquire,
        load_gate_manifest=lambda: {"sources": [{"id": tid, "audio": {"duration_seconds": 42.0}}
                                                for tid in runner.PLANNED_IDS]},
        parse_score=lambda raw: raw,
        parse_piano_match=lambda raw, piano_score: raw,
        analyze_correspondence=analyze,
        read_previous_receipt=read_previous,
        attribute_previous_case=attribute,
        summarize_cases=summarize,
    )
    return deps, timeline


def execute(tmp_path, deps):
    work, output = tmp_path / "work", tmp_path / "public" / "report.json"
    status = runner.run(work, output, deps=deps)
    return status, json.loads(output.read_bytes()), work, output


def test_all_six_analyses_precede_prior_read_and_unadmitted_sources_can_complete(tmp_path, monkeypatch):
    deps, timeline = dependencies(tmp_path, monkeypatch)
    status, report, _, output = execute(tmp_path, deps)
    assert status == 0 and report["status"] == "complete"
    assert report["completed_analyses"] == report["completed_attributions"] == 6
    assert report["summary"]["admitted_recordings"] == 0
    assert timeline[1:7] == ["analysis:" + tid for tid in runner.PLANNED_IDS]
    assert timeline[7] == "prior" and timeline[-1] == "summary"
    assert report["analysis_phase_completed_before_prior_receipt"] is True
    assert report["previous_receipt_loaded"] is True
    assert all(row["analysis"]["beat_alignment"]["status"] == "unavailable"
               for row in report["cases"])
    public = output.read_text()
    assert str(tmp_path) not in public and "notes 02" not in public
    assert "notes_path" not in public and "quality_approved" not in public


@pytest.mark.parametrize("stage", ["provenance", "source_acquisition"])
def test_preparation_failure_preserves_bounded_redacted_receipt(tmp_path, monkeypatch, stage):
    deps, timeline = dependencies(tmp_path, monkeypatch)

    def fail(*args):
        raise ValueError("private-source-content " + str(tmp_path / "private.xml"))

    if stage == "provenance":
        monkeypatch.setattr(runner, "collect_provenance", fail)
    else:
        deps = dataclasses.replace(deps, acquire_sources=fail)
    status, report, work, output = execute(tmp_path, deps)
    assert status == 1 and report["status"] == "preparation_failed"
    assert report["failure_stage"] == stage and report["error_type"] == "ValueError"
    assert report["summary"] is None and report["cases"] == []
    assert "prior" not in timeline and report["previous_receipt_loaded"] is False
    assert "private-source-content" not in output.read_text()
    assert str(tmp_path) not in output.read_text()
    assert "private-source-content" in (work / "failure.log").read_text()
    assert output.stat().st_size < runner.MAX_REPORT_BYTES


def test_one_failed_analysis_keeps_all_six_diagnostics_and_never_reads_prior(tmp_path, monkeypatch):
    deps, timeline = dependencies(tmp_path, monkeypatch)
    original = deps.analyze_correspondence

    def fail_one(*args):
        result = original(*args)
        if args[4] == b"notes 08":
            raise ValueError("invented malformed annotation")
        return result

    deps = dataclasses.replace(deps, analyze_correspondence=fail_one)
    status, report, _, _ = execute(tmp_path, deps)
    assert status == 1 and report["status"] == "incomplete" and report["summary"] is None
    assert len(report["cases"]) == 6 and report["completed_analyses"] == 5
    assert [row["id"] for row in report["cases"] if row["status"] == "failed"] == ["08"]
    assert "prior" not in timeline and "summary" not in timeline
    assert report["completed_attributions"] == 0


def test_previous_receipt_failure_occurs_after_all_analyses_and_keeps_them(tmp_path, monkeypatch):
    deps, timeline = dependencies(tmp_path, monkeypatch)

    def fail_receipt(path):
        timeline.append("prior")
        raise ValueError("invented prior receipt corruption")

    deps = dataclasses.replace(deps, read_previous_receipt=fail_receipt)
    status, report, _, _ = execute(tmp_path, deps)
    assert status == 1 and report["status"] == "previous_receipt_failed"
    assert report["summary"] is None and report["completed_analyses"] == 6
    assert all(row["status"] == "analyzed" for row in report["cases"])
    assert timeline[7] == "prior" and not any(item.startswith("attribute:") for item in timeline)


def test_outcome_attribution_cannot_mutate_frozen_analysis(tmp_path, monkeypatch):
    deps, timeline = dependencies(tmp_path, monkeypatch)
    original = deps.attribute_previous_case

    def change_analysis(prior_case, analysis):
        result = original(prior_case, analysis)
        if prior_case["id"] == "02":
            analysis["beat_alignment"]["status"] = "admitted"
        return result

    deps = dataclasses.replace(deps, attribute_previous_case=change_analysis)
    status, report, _, _ = execute(tmp_path, deps)
    assert status == 1 and report["status"] == "incomplete" and report["summary"] is None
    assert report["completed_attributions"] == 5 and "summary" not in timeline
    first = report["cases"][0]
    assert first["status"] == "attribution_failed" and first["attribution"] is None
    assert first["analysis"]["beat_alignment"]["status"] == "unavailable"


def test_aggregation_exception_preserves_complete_case_receipts_with_null_summary(tmp_path, monkeypatch):
    deps, _ = dependencies(tmp_path, monkeypatch)

    def fail_summary(cases, planned_ids):
        assert len(cases) == 6 and all(row["attribution"] is not None for row in cases)
        # The failing helper cannot corrupt already preserved case diagnostics.
        cases[0]["analysis"]["raw_notes"] = "private-source-content"
        raise RuntimeError("private-source-content")

    deps = dataclasses.replace(deps, summarize_cases=fail_summary)
    status, report, _, output = execute(tmp_path, deps)
    assert status == 1 and report["status"] == "aggregation_failed" and report["summary"] is None
    assert report["completed_analyses"] == report["completed_attributions"] == 6
    assert all(row["status"] == "analyzed" for row in report["cases"])
    assert "private-source-content" not in output.read_text() and "raw_notes" not in output.read_text()


def test_private_analysis_payload_is_rejected_before_publication_or_prior_read(tmp_path, monkeypatch):
    deps, timeline = dependencies(tmp_path, monkeypatch)
    deps = dataclasses.replace(deps, analyze_correspondence=lambda *args: {
        "raw_notes": "private-source-content", "notes_path": str(tmp_path / "private.csv")
    })
    status, report, _, output = execute(tmp_path, deps)
    assert status == 1 and report["summary"] is None and report["completed_analyses"] == 0
    assert "prior" not in timeline
    assert all(row["analysis"] is None for row in report["cases"])
    assert "private-source-content" not in output.read_text() and "notes_path" not in output.read_text()


@pytest.mark.parametrize("unsafe", ["existing_work", "existing_output", "linked_parent", "nested_report"])
def test_unsafe_work_or_output_is_rejected_before_execution(tmp_path, monkeypatch, unsafe):
    deps, timeline = dependencies(tmp_path, monkeypatch)
    work, output = tmp_path / "work", tmp_path / "report.json"
    if unsafe == "existing_work":
        work.mkdir()
    elif unsafe == "existing_output":
        output.write_text("preserve this")
    elif unsafe == "linked_parent":
        original = tmp_path / "original"
        original.mkdir()
        link = tmp_path / "link"
        link.symlink_to(original, target_is_directory=True)
        work = link / "work"
    else:
        output = work / "report.json"
    with pytest.raises(ValueError, match="fresh separate|symlinks"):
        runner.run(work, output, deps=deps)
    assert timeline == []
    if unsafe == "existing_output":
        assert output.read_text() == "preserve this"

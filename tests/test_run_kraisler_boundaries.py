"""Exercise the acoustic runner using authored PCM and invented source receipts."""
from __future__ import annotations

import copy
import dataclasses
import io
import json
import wave
import zipfile
from types import SimpleNamespace

import numpy as np
import pytest

from scripts import run_kraisler_boundaries as runner


def pcm_wav(*, channels=1, sample_rate=44100, sample_width=2):
    stream = io.BytesIO()
    pcm = np.array([-32768, 32767, 0, 16384], dtype="<i2").tobytes()
    with wave.open(stream, "wb") as recording:
        recording.setnchannels(channels)
        recording.setsampwidth(sample_width)
        recording.setframerate(sample_rate)
        recording.writeframes(pcm)
    return stream.getvalue()


def audio_shape():
    return {"channels": 1, "sample_rate": 44100, "sample_width": 2,
            "frames": 4, "duration_seconds": 4 / 44100}


def dependencies(tmp_path, monkeypatch):
    timeline, originals, declared, old_expressive, old_gate = [], {}, [], [], []
    expressive = {}
    gate = {"reference_db": -20.0, "close_db": -50.0, "open_db": -44.0,
            "frame_count": 1, "quiet_frame_count": 0, "mask_sha256": "a" * 64}
    for tid in runner.PLANNED_IDS:
        raws = {role: (role + " " + tid).encode() for role in runner.metadata_source.ROLES}
        raws["audio"] = pcm_wav()
        originals[tid] = raws
        hashes = {role: runner.inherited.digest(raw) for role, raw in raws.items()}
        declared.append({"id": tid, "source_id": "kraisler_" + tid, "audio": audio_shape(),
                         "members": {role: {"sha256": hashes[role]} for role in runner.audio_source.ROLES}})
        expressive[tid] = {"reference_count": 300, "frozen_baseline": {"source": tid},
                           "local_support": {"status": "unavailable"}}
        old_expressive.append({"id": tid, "status": "analyzed", "analysis": expressive[tid],
                               "source_member_sha256": {role: hashes[role] for role in runner.metadata_source.ROLES},
                               "source_audio_duration_s": 4 / 44100})
        bases = {}
        for base in runner.BASES:
            arms = {}
            for arm in runner.ARMS:
                masks = {metric + "_reference_mask": "0" * 300 for metric in runner.METRICS}
                if base == "default" and arm == "relative_soft" and runner.WATCHLIST[tid]:
                    index = runner.WATCHLIST[tid][0]
                    masks["onset_offset_reference_mask"] = "0" * index + "1" + "0" * (299 - index)
                arms[arm] = {"metrics": {"reference_note_count": 300, **masks}}
            bases[base] = {"arms": arms}
        old_gate.append({"id": tid, "status": "scored", "gate": copy.deepcopy(gate),
                         "source_member_sha256": {role: hashes[role] for role in runner.audio_source.ROLES},
                         "duration_s": 4 / 44100, "bases": bases})

    def make_receipt(kind, cases):
        path = tmp_path / (kind.lower() + ".zip")
        report = {"status": "complete", "source_head": "invented-head",
                  "source_revision": "invented-checkout", "cases": cases,
                  "planned_ids": list(runner.PLANNED_IDS), "summary": {"recordings": 6}}
        if kind == "GATE":
            report.update(planned_bases=list(runner.BASES), planned_arms=list(runner.ARMS),
                          summary={"scored_conditions": 48})
        payload = runner.inherited._encoded(report)
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("report.json", payload)
        monkeypatch.setattr(runner, kind + "_RECEIPT", path)
        monkeypatch.setattr(runner, kind + "_ZIP_BYTES", path.stat().st_size)
        monkeypatch.setattr(runner, kind + "_ZIP_SHA256", runner.inherited.digest(path.read_bytes()))
        monkeypatch.setattr(runner, kind + "_REPORT_BYTES", len(payload))
        monkeypatch.setattr(runner, kind + "_REPORT_SHA256", runner.inherited.digest(payload))

    make_receipt("EXPRESSIVE", old_expressive)
    make_receipt("GATE", old_gate)
    monkeypatch.setattr(runner, "collect_provenance", lambda: {
        "source_sha256": {"invented-contract": "0" * 64},
        "runtime": {"numpy": "1.26.4", "inference_device": "none"},
        "checkout_revision": "actual-checkout", "checkout_tree": "actual-tree",
    })

    def controls():
        timeline.append("controls")
        return {"status": "passed", "checks": {"authored_example": True}, "source_audio_used": False}

    def acquire(destination, metadata):
        kind = "metadata" if metadata else "audio"
        timeline.append("acquire:" + kind)
        destination.mkdir(parents=True)
        roles = runner.metadata_source.ROLES if metadata else runner.audio_source.ROLES
        rows = []
        for tid in runner.PLANNED_IDS:
            paths, hashes = {}, {}
            for role in roles:
                path = destination / (tid + "-" + role)
                path.write_bytes(originals[tid][role])
                path_key = runner.metadata_source.ROLES[role][2] if metadata else role + "_path"
                paths[path_key] = str(path)
                hashes[role] = runner.inherited.digest(originals[tid][role])
            row = {"id": tid, "source_id": "kraisler_" + tid, **paths, "member_sha256": hashes}
            if not metadata:
                row["audio"] = audio_shape()
            rows.append(row)
        receipt = {"status": "verified", "cases": rows, "network_bytes": 0,
                   "http_range_requests": 0, "cache_hits": 0,
                   "full_archive_downloaded": False, "full_archive_md5_verified": False}
        if metadata:
            receipt.update(verified_member_count=30, media_acquired=False)
        return receipt

    def analyze(case_id, samples, sr, score, piano_score, match_audit, raw_beats, raw_notes, *, raw_score):
        timeline.append("analysis:" + case_id)
        assert samples.tolist() == [-1.0, 32767 / 32768, 0.0, 0.5]
        assert not samples.flags.writeable and sr == 44100
        assert score == raw_score == originals[case_id]["score"]
        assert raw_notes == originals[case_id]["notes"]
        baseline = copy.deepcopy(expressive[case_id])
        public = {"reference_count": 300, "duration_s": len(samples) / sr,
                  "gate": copy.deepcopy(gate),
                  "expressive_analysis_sha256": runner.inherited.digest(runner.inherited._encoded(baseline)),
                  "boundaries": {"onset": {"count": 300}, "offset": {"count": 300}, "midpoint": {"count": 300}},
                  "watchlist": {str(index): {"probe": "invented"} for index in runner.WATCHLIST[case_id]}}
        return SimpleNamespace(public=public, expressive_analysis=baseline)

    def read(path, kind):
        timeline.append(kind)
        saved = json.loads((tmp_path / "public" / "report.json").read_bytes())
        assert saved["completed_analyses"] == 6
        assert saved["analysis_phase_completed_before_prior_receipts"] is True
        assert all(row["analysis_sha256"] for row in saved["cases"])
        for tid in runner.PLANNED_IDS:
            assert (tmp_path / "work" / (tid + "-expressive-baseline.json")).is_file()
        return runner.read_expressive_receipt(path) if kind == "expressive" else runner.read_gate_receipt(path)

    def summarize(cases):
        timeline.append("summary")
        assert tuple(row["id"] for row in cases) == runner.PLANNED_IDS
        assert all(row["status"] == "complete" and row["historical_watchlist_transitions"] is not None for row in cases)
        return {"recordings": 6, "new_model_inferences": 0}

    deps = runner.Dependencies(
        acquire_audio_sources=lambda destination: acquire(destination, False),
        acquire_metadata_sources=lambda destination: acquire(destination, True),
        load_gate_manifest=lambda: {"sources": copy.deepcopy(declared)},
        parse_score=lambda raw: raw, parse_piano_match=lambda raw, piano_score: raw,
        synthetic_controls=controls, analyze_boundaries=analyze,
        read_expressive_receipt=lambda path: read(path, "expressive"),
        read_gate_receipt=lambda path: read(path, "gate"), summarize_boundaries=summarize,
    )
    return deps, timeline


def execute(tmp_path, deps):
    work, output = tmp_path / "work", tmp_path / "public" / "report.json"
    status = runner.run(work, output, deps=deps)
    return status, json.loads(output.read_bytes()), work, output


def test_pcm16_scaling_is_exact_and_original_samples_are_readonly():
    samples, sr = runner.decode_audio(pcm_wav(), audio_shape())
    assert samples.dtype == np.float64 and samples.tolist() == [-1.0, 32767 / 32768, 0.0, 0.5]
    assert sr == 44100 and not samples.flags.writeable


@pytest.mark.parametrize("shape", [{"channels": 2}, {"sample_rate": 48000}, {"sample_width": 1}])
def test_nonoriginal_waveform_shapes_are_rejected(shape):
    with pytest.raises(ValueError, match="original mono PCM16"):
        runner.decode_audio(pcm_wav(**shape), audio_shape())


def test_six_saved_analyses_precede_receipts_and_all_baselines_precede_watchlists(tmp_path, monkeypatch):
    deps, timeline = dependencies(tmp_path, monkeypatch)
    original_verify, original_watch = runner._verify_baseline, runner.historical_watchlist_transitions

    def verify(old, *args):
        timeline.append("verify:" + old["id"])
        return original_verify(old, *args)

    def watch(previous, *args):
        saved = json.loads((tmp_path / "public" / "report.json").read_bytes())
        assert saved["completed_baseline_verifications"] == 6
        timeline.append("watch:" + previous["id"])
        return original_watch(previous, *args)

    monkeypatch.setattr(runner, "_verify_baseline", verify)
    monkeypatch.setattr(runner, "historical_watchlist_transitions", watch)
    status, report, _, output = execute(tmp_path, deps)
    assert status == 0 and report["status"] == "complete"
    assert timeline == ["controls", "acquire:audio", "acquire:metadata",
                        *["analysis:" + tid for tid in runner.PLANNED_IDS], "expressive", "gate",
                        *["verify:" + tid for tid in runner.PLANNED_IDS],
                        *["watch:" + tid for tid in runner.PLANNED_IDS], "summary"]
    assert report["completed_analyses"] == report["completed_baseline_verifications"] == 6
    assert report["completed_historical_watchlists"] == 6
    assert report["completed_audio_decodes"] == 6
    assert report["source_acquisition"]["unique_verified_members"] == 36
    for row in report["cases"]:
        transitions = row["historical_watchlist_transitions"]
        assert transitions["changed_reference_indices"] == list(runner.WATCHLIST[row["id"]])
        assert transitions["causal_endpoint_attribution"] is False
        assert len(row["source_member_sha256"]) == 6
    assert str(tmp_path) not in output.read_text() and "notes 02" not in output.read_text()


@pytest.mark.parametrize("stage", ["provenance", "synthetic_controls", "audio", "metadata"])
def test_preparation_failure_keeps_redacted_receipt_without_reading_outcomes(tmp_path, monkeypatch, stage):
    deps, timeline = dependencies(tmp_path, monkeypatch)

    def fail(*args):
        raise RuntimeError("private-source-content " + str(tmp_path / "original.wav"))

    if stage == "provenance":
        monkeypatch.setattr(runner, "collect_provenance", fail)
    else:
        field = {"synthetic_controls": "synthetic_controls", "audio": "acquire_audio_sources",
                 "metadata": "acquire_metadata_sources"}[stage]
        deps = dataclasses.replace(deps, **{field: fail})
    status, report, work, output = execute(tmp_path, deps)
    assert status == 1 and report["status"] == "preparation_failed" and report["summary"] is None
    assert report["cases"] == [] and "expressive" not in timeline and "gate" not in timeline
    assert report["completed_audio_decodes"] == 0
    assert "private-source-content" in (work / "failure.log").read_text()
    assert "private-source-content" not in output.read_text() and str(tmp_path) not in output.read_text()


def test_one_failed_analysis_retains_other_cases_and_blocks_all_historical_reads(tmp_path, monkeypatch):
    deps, timeline = dependencies(tmp_path, monkeypatch)
    original = deps.analyze_boundaries

    def fail_one(case_id, *args, **kwargs):
        result = original(case_id, *args, **kwargs)
        if case_id == "08":
            raise ValueError("invented unsupported analysis")
        return result

    status, report, _, _ = execute(tmp_path, dataclasses.replace(deps, analyze_boundaries=fail_one))
    assert status == 1 and report["status"] == "incomplete" and report["summary"] is None
    assert len(report["cases"]) == 6 and report["completed_analyses"] == 5
    assert [row["id"] for row in report["cases"] if row["status"] == "failed"] == ["08"]
    assert "expressive" not in timeline and "gate" not in timeline and "summary" not in timeline


def test_analysis_that_changes_an_original_member_is_not_accepted(tmp_path, monkeypatch):
    deps, timeline = dependencies(tmp_path, monkeypatch)
    original = deps.analyze_boundaries

    def mutate_source(case_id, *args, **kwargs):
        result = original(case_id, *args, **kwargs)
        if case_id == "02":
            (tmp_path / "work" / "audio-sources" / "02-audio").write_bytes(b"changed original")
        return result

    status, report, _, output = execute(tmp_path, dataclasses.replace(deps, analyze_boundaries=mutate_source))
    assert status == 1 and report["completed_analyses"] == 5 and report["summary"] is None
    assert report["cases"][0]["analysis"] is None and "expressive" not in timeline
    assert "changed original" not in output.read_text()


@pytest.mark.parametrize("receipt", ["EXPRESSIVE", "GATE"])
def test_exact_receipt_digest_failure_happens_after_all_analyses(tmp_path, monkeypatch, receipt):
    deps, timeline = dependencies(tmp_path, monkeypatch)
    monkeypatch.setattr(runner, receipt + "_ZIP_SHA256", "0" * 64)
    status, report, _, _ = execute(tmp_path, deps)
    assert status == 1 and report["status"] == "historical_receipt_failed"
    assert report["completed_analyses"] == 6 and report["completed_baseline_verifications"] == 0
    assert report["completed_historical_watchlists"] == 0 and report["summary"] is None
    assert "summary" not in timeline


@pytest.mark.parametrize("change", ["expressive", "audio_sha256", "gate_count", "gate_mask", "gate_level"])
def test_mismatched_frozen_baseline_blocks_every_historical_attachment(tmp_path, monkeypatch, change):
    deps, timeline = dependencies(tmp_path, monkeypatch)
    field = "read_expressive_receipt" if change == "expressive" else "read_gate_receipt"
    original = getattr(deps, field)

    def mismatch(path):
        report = original(path)
        row = report["cases"][2]
        if change == "expressive":
            row["analysis"]["reference_count"] += 1
        elif change == "audio_sha256":
            row["source_member_sha256"]["audio"] = "0" * 64
        elif change == "gate_count":
            row["gate"]["quiet_frame_count"] += 1
        elif change == "gate_mask":
            row["gate"]["mask_sha256"] = "0" * 64
        else:
            row["gate"]["close_db"] += 0.001
        return report

    status, report, _, _ = execute(tmp_path, dataclasses.replace(deps, **{field: mismatch}))
    assert status == 1 and report["status"] == "baseline_verification_failed" and report["summary"] is None
    assert report["completed_analyses"] == 6 and report["completed_historical_watchlists"] == 0
    assert all(row["historical_watchlist_transitions"] is None for row in report["cases"])
    assert "summary" not in timeline


@pytest.mark.parametrize("change", ["extra", "missing", "malformed"])
def test_changed_reference_union_and_mask_integrity_are_required(tmp_path, monkeypatch, change):
    deps, timeline = dependencies(tmp_path, monkeypatch)
    original = deps.read_gate_receipt

    def changed(path):
        report = original(path)
        metrics = report["cases"][0]["bases"]["default"]["arms"]["relative_soft"]["metrics"]
        old = metrics["onset_offset_reference_mask"]
        metrics["onset_offset_reference_mask"] = (
            "1" + old[1:] if change == "extra" else "0" * 300 if change == "missing" else old[:-1]
        )
        return report

    status, report, _, _ = execute(tmp_path, dataclasses.replace(deps, read_gate_receipt=changed))
    assert status == 1 and report["status"] == "incomplete" and report["summary"] is None
    assert report["completed_baseline_verifications"] == 6 and report["completed_historical_watchlists"] == 5
    assert report["cases"][0]["status"] == "historical_watchlist_failed" and "summary" not in timeline


def test_private_source_fields_are_rejected_before_publication(tmp_path, monkeypatch):
    deps, timeline = dependencies(tmp_path, monkeypatch)
    original = deps.analyze_boundaries

    def private_data(*args, **kwargs):
        result = original(*args, **kwargs)
        result.public["raw_notes"] = "private-source-content"
        return result

    status, report, _, output = execute(tmp_path, dataclasses.replace(deps, analyze_boundaries=private_data))
    assert status == 1 and report["completed_analyses"] == 0 and report["summary"] is None
    assert "raw_notes" not in output.read_text() and "private-source-content" not in output.read_text()
    assert "expressive" not in timeline


def test_combined_metadata_budget_leaves_room_for_a_failure_receipt(tmp_path, monkeypatch):
    deps, timeline = dependencies(tmp_path, monkeypatch)
    original = deps.analyze_boundaries
    monkeypatch.setattr(runner, "MAX_REPORT_BYTES", 40_000)

    def large_metadata(*args, **kwargs):
        result = original(*args, **kwargs)
        result.public["invented_diagnostic"] = "x" * 7000
        return result

    status, report, _, output = execute(tmp_path, dataclasses.replace(deps, analyze_boundaries=large_metadata))
    assert status == 1 and report["status"] == "incomplete" and report["summary"] is None
    assert len(report["cases"]) == 6 and 0 < report["completed_analyses"] < 6
    assert output.stat().st_size <= runner.MAX_REPORT_BYTES and "expressive" not in timeline


def test_aggregation_failure_preserves_all_six_frozen_case_receipts(tmp_path, monkeypatch):
    deps, _ = dependencies(tmp_path, monkeypatch)

    def fail(cases):
        assert len(cases) == 6 and all(row["historical_watchlist_transitions"] is not None for row in cases)
        cases[0]["analysis"]["raw_notes"] = "private-source-content"
        raise ValueError("private-source-content")

    status, report, _, output = execute(tmp_path, dataclasses.replace(deps, summarize_boundaries=fail))
    assert status == 1 and report["status"] == "aggregation_failed" and report["summary"] is None
    assert report["completed_analyses"] == report["completed_baseline_verifications"] == 6
    assert report["completed_historical_watchlists"] == 6
    assert all(row["status"] == "complete" for row in report["cases"])
    assert "raw_notes" not in output.read_text() and "private-source-content" not in output.read_text()


def test_existing_report_is_preserved_before_any_source_or_controls(tmp_path, monkeypatch):
    deps, timeline = dependencies(tmp_path, monkeypatch)
    output = tmp_path / "report.json"
    output.write_text("keep this")
    with pytest.raises(ValueError, match="fresh separate"):
        runner.run(tmp_path / "work", output, deps=deps)
    assert output.read_text() == "keep this" and timeline == [] and not (tmp_path / "work").exists()

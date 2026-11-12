"""Freeze six acoustic boundary diagnostics before opening historical outcomes.

The originals and private baselines remain outside the repository. Completion
means the predeclared diagnostics and provenance checks completed; it does not
establish an acoustic release, a written rest, or the cause of an old gate edit.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import io
import json
import os
import platform
import subprocess
import time
import wave
import zipfile
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Callable

import numpy as np

from scripts import kraisler_alignment_source as metadata_source
from scripts import kraisler_source as audio_source
from scripts import run_kraisler_alignment as inherited

ROOT = Path(__file__).resolve().parents[1]
PLANNED_IDS = ("02", "19", "08", "12", "05", "06")
BASES = ("default", "onset065")
ARMS = ("raw", "relative_soft", "tail_only", "non_tail_only")
METRICS = ("onset", "onset_offset")
WATCHLIST = {"02": (14,), "19": (294,), "08": (), "12": (16,), "05": (), "06": (159,)}
EXPRESSIVE_RECEIPT = ROOT / "docs/research/receipts/kraisler-expressive-43210425240.zip"
EXPRESSIVE_ZIP_SHA256 = "e51fae082cf3c97240a9746cf2ba2214923ce30555ae2f70130f6043cffd478f"
EXPRESSIVE_ZIP_BYTES = 72_066
EXPRESSIVE_REPORT_SHA256 = "32005007594058ee941fd367aab5cd0ad093cef130fc38a23f47912e36f580bc"
EXPRESSIVE_REPORT_BYTES = 1_546_689
GATE_RECEIPT = ROOT / "docs/research/receipts/kraisler-gate-43184102838.zip"
GATE_ZIP_SHA256 = "ba88b9bda70d4a560a3d05c85ea5301d2e8ff98ea81746d676a1c6695898e10e"
GATE_ZIP_BYTES = 16_111
GATE_REPORT_SHA256 = "e79ff94736b471da64638a93456ef4f1510750c843960ae924fc1f488ad2f754"
GATE_REPORT_BYTES = 155_591
MAX_COMPONENT_BYTES = 1_000_000
MAX_REPORT_BYTES = 8_000_000
MAX_AUDIO_NETWORK_BYTES = 28_339_853
MAX_NETWORK_BYTES = 29_116_178
MAX_HTTP_REQUESTS = 14
NEW_SOURCE_PATHS = (
    "scripts/run_kraisler_boundaries.py",
    "tests/test_run_kraisler_boundaries.py",
    ".github/workflows/cpu-kraisler-boundaries.yml",
    "scripts/kraisler_waveform_features.py",
    "tests/test_kraisler_waveform_features.py",
    "scripts/kraisler_rest_acoustics.py",
    "tests/test_kraisler_rest_acoustics.py",
    "scripts/kraisler_boundary_audit.py",
    "tests/test_kraisler_boundary_audit.py",
    "docs/research/KRAISLER_BOUNDARY_PROTOCOL_2026-11-12.md",
    "scripts/research_test_manifest.json",
)
# Literal byte pins from committed main 84fade231ebc89fefcb3f6a60f284b1e5a6cd575.
# Historical outcomes are not opened to derive runtime provenance.
FROZEN_SOURCE_SHA256 = {
    '.github/workflows/cpu-kraisler-alignment.yml':
        'd94b6841b12507491df7f58c595084d22b238de7a550e70328725b0353ce64f3',
    '.github/workflows/cpu-kraisler-expressive.yml':
        '34d5212a28a3f6ee7ea2755f2adfc1a63a22051345aa49a52d6f4259d59151b2',
    '.github/workflows/cpu-kraisler-gate.yml':
        '15a408d208567cb4c9ff272460ab2dfc0d937730741e61b8efb061ec12cec705',
    'docs/research/KRAISLER_ALIGNMENT_PROTOCOL_2026-11-12.md':
        '49d9cc04e08b03afd22201a5a4541336f1fe294d57167ed968476b196d126a28',
    'docs/research/KRAISLER_EXPRESSIVE_PROTOCOL_2026-11-12.md':
        '3ad6dc012ff934c92779bb4fc1c7a46cebb14d1b4821a8764b5f5b4271e4f94f',
    'docs/research/KRAISLER_GATE_PROTOCOL_2026-11-12.md':
        'bfbe4bce2335f1b942f7f55a9c855c8f87657ba4ec8efa5f4ac040981b0e0c1d',
    'scripts/audio_gate_attribution.py': '99b3c494b59fbb0725cc9dd4cd25665a777c93d1516ba6e5a13eb238ddf65cea',
    'scripts/audio_gate_rest.py': '05f239835c2bee14e40cb059b68bad35c7c5a79f247c3d616677c501161fff73',
    'scripts/kraisler_alignment_manifest.json':
        'ba062dc673f0ebb64c12a95c096144b3efb0975ab7e7be34be645359c3d6503d',
    'scripts/kraisler_alignment_source.py': '25e0ed3327facffdd0f1dcf1a34134176673f9012f2c9f318d2b32ce288642f5',
    'scripts/kraisler_correspondence.py': 'c3046d387ba83c7a97c2eb2d16d7f609ecd71c6708ec45d25f5aec9238198efb',
    'scripts/kraisler_expressive.py': 'f34fdca98c388d3b4f7e27bacfce319f0cee91b289b37a6d2d17355b233b0b1f',
    'scripts/kraisler_gate_eval.py': 'ea664ad392d61a12a52b98dcb3987d4bad62ad8d2dbd2aa34301b669434695bf',
    'scripts/kraisler_gate_manifest.json': 'a18857a4b7a2025ea327f9a03855ca02dca0964110d973d5224b85dfbb258c60',
    'scripts/kraisler_local_clock.py': 'a3af99572ed39c87d1c64311a6c537d1275f8e47a8b8914286e7c8a3637ce2c0',
    'scripts/kraisler_match.py': '3fbf1c07783bfa9205eb152e553032e5922018c3c1c7d673b524d2a7632a373c',
    'scripts/kraisler_rhythm_ranges.py': '7083a1a4bde6195ef56662a4a62ddd95aaf944e6d723efeb1108d4f757f5cbeb',
    'scripts/kraisler_score.py': '515f7f06579e9ee590f4a17147993d496d0b4040e9f60574eb82377c7ac3c431',
    'scripts/kraisler_source.py': '94ba9c30adfd60dfc518a371a53b6fdaa722a44352a019311582b8125423e2bd',
    'scripts/offset_tail_evidence.py': '5adb61edca4b68deac9a0f9f6f619009d8295f006a5913b9f14c6a30f6ce0b4c',
    'scripts/run_cpu_vocadito_candidates.py':
        '0265be97c1f891816da30e75fa145a58a1972636a5729fcb1ccc761665c52465',
    'scripts/run_kraisler_alignment.py': 'fb5a1682ead8d5416143228a9ff845006ccfd1672d700b277f5f41a0eaea4847',
    'scripts/run_kraisler_expressive.py': '774826f48f4abc430924db5f8593f6ed0ad68eb2d6095645aecaeb75221c3ab0',
    'scripts/run_kraisler_gate.py': '57b23a975bb8f4a64858c8f034c8a66c50def91053a72004717b815114fe700a',
    'scripts/run_offset_tail_probe.py': '44730f903b4e8eddc1755ff0ae89793052c43abc129f15028b91b0d16562939e',
    'scripts/vocadito_reference.py': '2ee6f18518e0f4887b9f0c163fff6cfcb964a05d21da1eddd6fcf8e031259194',
    'scripts/vocal_recovery.py': '9cbc4c1e635b78263c46473d357fa928350fabdf3efcab79ec44a42e00fa246b',
    'src/audio_score_tool/metrics.py': '476fdb3dcebf8660a83b258263a2719193590eee5135d40f79b87ceab313df4f',
    'tests/test_kraisler_alignment_source.py':
        'f53aab084da20bb60333e6a7205c74e0476806b9a2309fcc9c299dd76700167f',
    'tests/test_kraisler_correspondence.py':
        '82f4f6226c2e1e3f9a21a30cfca7a58019f8853666d406fa5316882fa156cf7e',
    'tests/test_kraisler_expressive.py': '20a68d1bb6ad48f7dbe2dcd1ce1886bef709afaedbd68d996df9814f1430d7ad',
    'tests/test_kraisler_local_clock.py': '6e71e19a1d6798fcea9a63e51a750616bf264b3c8608fa3c4a8410a6a053b57c',
    'tests/test_kraisler_match.py': 'e630f244d1c526325954dba12a467eee6668a52dfa05a789105b57d93114b9ca',
    'tests/test_kraisler_rhythm_ranges.py': 'f2f6e4153cae65e0e67071f44f1db00d670767b738bdfc7b7bdf6568afd407e7',
    'tests/test_kraisler_score.py': 'e1e8f40144d37936bfe505b866a72326fbfb3709b1adb864482c1afaf31661c4',
    'tests/test_run_kraisler_alignment.py': '3bfa6640ef4be15f4cd62bbc82c7fbe88801f35f26741d016ea46c5c84c00c48',
    'tests/test_run_kraisler_expressive.py':
        '100d8b7bd8f582a3b09a67a0caebfa52d4e055002f30e4501f4a72278fd527af',
}


@dataclass(frozen=True)
class Dependencies:
    acquire_audio_sources: Callable
    acquire_metadata_sources: Callable
    load_gate_manifest: Callable
    parse_score: Callable
    parse_piano_match: Callable
    synthetic_controls: Callable
    analyze_boundaries: Callable
    read_expressive_receipt: Callable
    read_gate_receipt: Callable
    summarize_boundaries: Callable


def _dependencies():
    from scripts.kraisler_boundary_audit import analyze_boundaries, summarize_boundaries
    from scripts.kraisler_match import parse_piano_match
    from scripts.kraisler_score import parse_score
    from scripts.kraisler_waveform_features import synthetic_controls

    return Dependencies(
        audio_source.acquire_sources, metadata_source.acquire_alignment_sources,
        audio_source.load_manifest, parse_score, parse_piano_match, synthetic_controls,
        analyze_boundaries, read_expressive_receipt, read_gate_receipt, summarize_boundaries,
    )


def validate_frozen_sources():
    if len(FROZEN_SOURCE_SHA256) != 37:
        raise ValueError("inherited source inventory changed")
    for relative, expected in FROZEN_SOURCE_SHA256.items():
        path = ROOT / relative
        if (path.is_symlink() or not path.is_file() or path.stat().st_size > 1_000_000
                or inherited.digest(path.read_bytes()) != expected):
            raise ValueError("inherited source digest changed: " + relative)


def collect_provenance():
    validate_frozen_sources()
    if os.getenv("HF_TOKEN") or os.getenv("HUGGING_FACE_HUB_TOKEN"):
        raise ValueError("external model credentials are not permitted")
    if np.__version__ != "1.26.4" or version("numpy") != "1.26.4":
        raise ValueError("the pinned NumPy 1.26.4 CPU runtime is required")
    hashes = {}
    for relative in NEW_SOURCE_PATHS:
        path = ROOT / relative
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1_000_000:
            raise ValueError("missing or invalid predeclared source: " + relative)
        hashes[relative] = inherited.digest(path.read_bytes())
    revisions = subprocess.run(
        ["git", "rev-parse", "HEAD", "HEAD^{tree}"], cwd=ROOT, text=True,
        capture_output=True, check=True, timeout=10,
    ).stdout.splitlines()
    if len(revisions) != 2:
        raise ValueError("checkout identity unavailable")
    expected_checkout = os.getenv("GITHUB_SHA")
    if expected_checkout and expected_checkout != revisions[0]:
        raise ValueError("actual checkout differs from GITHUB_SHA")
    dirty = bool(subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, text=True,
        capture_output=True, check=True, timeout=10,
    ).stdout)
    contract_tools = {}
    for name in ("pytest", "ruff"):
        try:
            contract_tools[name] = version(name)
        except PackageNotFoundError:
            contract_tools[name] = None
    return {
        "source_sha256": hashes,
        "source_head": os.getenv("EXPERIMENT_HEAD", "local-uncommitted" if dirty else revisions[0]),
        "source_revision": expected_checkout or revisions[0],
        "checkout_revision": revisions[0], "checkout_tree": revisions[1],
        "workspace_dirty": dirty,
        "runtime": {"implementation": platform.python_implementation(),
                    "python": platform.python_version(), "numpy": np.__version__,
                    "inference_device": "none", "contract_tools": contract_tools},
    }


def _public_component(value, private_roots):
    if len(inherited._encoded(value)) > MAX_COMPONENT_BYTES:
        raise ValueError("public component exceeds bounded metadata budget")
    return inherited._public_component(value, private_roots)


def _check_report_budget(report):
    reserve = min(32_000, MAX_REPORT_BYTES // 10)
    if len(inherited._encoded(report)) > MAX_REPORT_BYTES - reserve:
        raise ValueError("combined public metadata exceeds report budget")


def save(path, report):
    raw = inherited._encoded(report)
    if len(raw) > MAX_REPORT_BYTES:
        raise ValueError("public report exceeds bounded metadata budget")
    audio_source._write_atomic(path, raw)


def _finish(output, report, started, status):
    report["status"] = status
    report["elapsed_seconds"] = time.monotonic() - started
    save(output, report)
    return 0 if status == "complete" else 1


def _read_receipt(path, zip_sha256, zip_bytes, report_sha256, report_bytes):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size != zip_bytes:
        raise ValueError("exact historical receipt ZIP required")
    raw = path.read_bytes()
    if inherited.digest(raw) != zip_sha256:
        raise ValueError("historical receipt ZIP digest mismatch")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if (archive.namelist() != ["report.json"]
                or archive.getinfo("report.json").file_size != report_bytes
                or not 0 < report_bytes <= MAX_REPORT_BYTES):
            raise ValueError("historical report coverage or bounded size changed")
        payload = archive.read("report.json")
    if inherited.digest(payload) != report_sha256:
        raise ValueError("historical report digest mismatch")
    report = json.loads(payload)
    if (report.get("status") != "complete" or report.get("planned_ids") != list(PLANNED_IDS)
            or [row.get("id") for row in report.get("cases", [])] != list(PLANNED_IDS)
            or not isinstance(report.get("summary"), dict)):
        raise ValueError("historical study incomplete or changed")
    return report


def read_expressive_receipt(path):
    return _read_receipt(path, EXPRESSIVE_ZIP_SHA256, EXPRESSIVE_ZIP_BYTES,
                         EXPRESSIVE_REPORT_SHA256, EXPRESSIVE_REPORT_BYTES)


def read_gate_receipt(path):
    report = _read_receipt(path, GATE_ZIP_SHA256, GATE_ZIP_BYTES,
                           GATE_REPORT_SHA256, GATE_REPORT_BYTES)
    if (report.get("planned_bases") != list(BASES) or report.get("planned_arms") != list(ARMS)
            or report["summary"].get("scored_conditions") != 48):
        raise ValueError("historical gate conditions changed")
    return report


def _receipt_identity(report, zip_sha256, zip_bytes, report_sha256, report_bytes):
    return {"archive_sha256": zip_sha256, "archive_bytes": zip_bytes,
            "report_sha256": report_sha256, "report_bytes": report_bytes,
            "source_head": report["source_head"], "source_revision": report["source_revision"],
            "status": report["status"], "case_count": len(report["cases"])}


def _validate_acquisition(audio, metadata, manifest):
    if any(tuple(row["id"] for row in items) != PLANNED_IDS
           for items in (audio["cases"], metadata["cases"], manifest["sources"])):
        raise ValueError("source cohort differs from the six predeclared IDs")
    for receipt, max_bytes, max_requests in ((audio, MAX_AUDIO_NETWORK_BYTES, 7),
                                            (metadata, metadata_source.MAX_NETWORK_BYTES, 7)):
        if (receipt["status"] != "verified"
                or type(receipt["network_bytes"]) is not int
                or type(receipt["http_range_requests"]) is not int
                or not 0 <= receipt["network_bytes"] <= max_bytes
                or not 0 <= receipt["http_range_requests"] <= max_requests
                or receipt["full_archive_downloaded"] is not False
                or receipt["full_archive_md5_verified"] is not False):
            raise ValueError("source acquisition exceeded its bounded contract")
    if metadata["verified_member_count"] != 30 or metadata["media_acquired"] is not False:
        raise ValueError("metadata acquisition population changed")
    for recording, extra, declared in zip(audio["cases"], metadata["cases"], manifest["sources"], strict=True):
        if (set(recording["member_sha256"]) != set(audio_source.ROLES)
                or set(extra["member_sha256"]) != set(metadata_source.ROLES)
                or recording["source_id"] != extra["source_id"]
                or recording["source_id"] != declared["source_id"]
                or recording["audio"] != declared["audio"]
                or any(recording["member_sha256"][role] != declared["members"][role]["sha256"]
                       for role in audio_source.ROLES)
                or any(recording["member_sha256"][role] != extra["member_sha256"][role]
                       for role in ("notes", "beats", "score"))):
            raise ValueError("source member coverage or shared identity changed")
    fields = inherited.ACQUISITION_FIELDS
    return {
        "audio_and_shared_metadata": {key: audio[key] for key in fields if key in audio},
        "alignment_metadata": {key: metadata[key] for key in fields if key in metadata},
        "unique_verified_members": 36,
        "network_bytes": audio["network_bytes"] + metadata["network_bytes"],
        "http_range_requests": audio["http_range_requests"] + metadata["http_range_requests"],
        "cache_hits": audio["cache_hits"] + metadata["cache_hits"],
        "full_archive_downloaded": False, "full_archive_md5_verified": False,
        "duplicate_metadata_suffix_requests_allowed": True,
    }


def _read_member(path, expected_sha256, limit, directory):
    path = inherited._safe_path(path)
    if (not path.is_relative_to(directory) or not path.is_file()
            or not 0 < path.stat().st_size <= limit):
        raise ValueError("source member escaped acquisition directory or size bound")
    raw = path.read_bytes()
    if inherited.digest(raw) != expected_sha256:
        raise ValueError("source member changed after acquisition")
    return raw


def _read_sources(recording, metadata, audio_directory, metadata_directory):
    raw = {}
    for role in audio_source.ROLES:
        raw[role] = _read_member(recording[role + "_path"], recording["member_sha256"][role],
                                 audio_source.MAX_MEMBER_BYTES, audio_directory)
    for role, (_, _, path_key) in metadata_source.ROLES.items():
        value = _read_member(metadata[path_key], metadata["member_sha256"][role],
                             metadata_source.MAX_MEMBER_BYTES, metadata_directory)
        if role in raw and raw[role] != value:
            raise ValueError("overlapping source members differ")
        raw[role] = value
    return raw


def decode_audio(raw, expected):
    """Decode the frozen mono PCM16 representation without resampling or cropping."""
    with wave.open(io.BytesIO(raw)) as recording:
        shape = (recording.getnchannels(), recording.getframerate(), recording.getsampwidth(),
                 recording.getnframes(), recording.getcomptype())
        if (shape != (1, 44100, 2, expected["frames"], "NONE")
                or expected["channels"] != 1 or expected["sample_rate"] != 44100
                or expected["sample_width"] != 2 or not 0 < shape[3] <= 44100 * 150):
            raise ValueError("invalid original mono PCM16 recording")
        pcm = recording.readframes(shape[3] + 1)
    if len(pcm) != shape[3] * 2:
        raise ValueError("truncated original PCM samples")
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float64) / 32768.0
    if len(samples) / 44100 != expected["duration_seconds"]:
        raise ValueError("original duration differs from frozen manifest")
    samples.flags.writeable = False
    return samples, 44100


def historical_watchlist_transitions(previous, case_id, count):
    """Describe only saved reference-mask transitions, never prediction endpoints."""
    if previous["id"] != case_id or previous["status"] != "scored" or set(previous["bases"]) != set(BASES):
        raise ValueError("historical gate case changed")
    records = {str(index): [] for index in WATCHLIST[case_id]}
    changed = set()
    for base in BASES:
        arms = previous["bases"][base]["arms"]
        if set(arms) != set(ARMS):
            raise ValueError("historical gate arm coverage changed")
        for arm in ARMS:
            metrics = arms[arm]["metrics"]
            if metrics["reference_note_count"] != count:
                raise ValueError("historical reference population changed")
            for metric in METRICS:
                before = arms["raw"]["metrics"][metric + "_reference_mask"]
                after = metrics[metric + "_reference_mask"]
                if any(not isinstance(mask, str) or len(mask) != count or set(mask) - {"0", "1"}
                       for mask in (before, after)):
                    raise ValueError("historical reference mask is invalid")
                changed.update(index for index, (left, right) in enumerate(zip(before, after, strict=True))
                               if left != right)
                for index in WATCHLIST[case_id]:
                    raw_matched, arm_matched = before[index] == "1", after[index] == "1"
                    label = ("gained" if arm_matched else "lost") if raw_matched != arm_matched else "unchanged"
                    records[str(index)].append({"base": base, "arm": arm, "metric": metric,
                                                "raw_matched": raw_matched, "arm_matched": arm_matched,
                                                "transition": label})
    if changed != set(WATCHLIST[case_id]):
        raise ValueError("changed-reference union differs from the frozen watchlist")
    return {"source": "immutable prior reference match masks", "new_predictions_computed": False,
            "causal_endpoint_attribution": False, "changed_reference_indices": sorted(changed),
            "references": records}


def _verify_baseline(old, previous, row, expressive, private_roots):
    hashes, analysis = row["source_member_sha256"], row["analysis"]
    if (old["status"] != "analyzed" or previous["status"] != "scored"
            or old["id"] != previous["id"] or old["id"] != row["id"]
            or set(old["source_member_sha256"]) != set(metadata_source.ROLES)
            or set(previous["source_member_sha256"]) != set(audio_source.ROLES)
            or any(old["source_member_sha256"][role] != hashes[role] for role in metadata_source.ROLES)
            or any(previous["source_member_sha256"][role] != hashes[role] for role in audio_source.ROLES)
            or old["source_audio_duration_s"] != row["source_audio_duration_s"]
            or previous["duration_s"] != row["source_audio_duration_s"]
            or previous["gate"] != analysis["gate"]
            or old["analysis"] != expressive
            or _public_component(expressive, private_roots) != analysis["expressive_analysis_sha256"]
            or _public_component(analysis, private_roots) != row["analysis_sha256"]):
        raise ValueError("frozen source, waveform gate or expressive baseline differs")


def run(work, output, *, deps=None):
    work, output, _ = inherited._prepare_paths(work, output, None)
    started = time.monotonic()
    private_roots = (ROOT, work, output)
    report = {
        "schema_version": 1, "status": "running", "cases": [], "summary": None,
        "synthetic_controls": None, "planned_ids": list(PLANNED_IDS),
        "planned_analyses": 6, "completed_analyses": 0,
        "planned_audio_decodes": 6, "completed_audio_decodes": 0,
        "completed_baseline_verifications": 0, "completed_historical_watchlists": 0,
        "source_head": os.getenv("EXPERIMENT_HEAD", "local"),
        "source_revision": os.getenv("GITHUB_SHA", "local"),
        "source_sha256": {}, "frozen_source_sha256": dict(FROZEN_SOURCE_SHA256), "runtime": {},
        "expressive_baseline_loaded": False, "gate_receipt_loaded": False,
        "analysis_phase_completed_before_prior_receipts": False,
        "workflow_run_id": os.getenv("GITHUB_RUN_ID"),
        "workflow_run_attempt": os.getenv("GITHUB_RUN_ATTEMPT"),
        "policy": {
            "analysis_type": "reference-assisted acoustic boundary and written-rest diagnostics",
            "cohort": "same six previously observed recordings; outcome-informed development follow-up",
            "original_audio_in_scope": True, "new_model_inferences": 0, "training": False,
            "threshold_tuning": False, "original_samples_or_events_changed": False,
            "release_ground_truth_measured": False, "human_acceptability_measured": False,
            "prediction_endpoint_recovery": False, "causal_gate_edit_attribution": False,
            "automatic_correction_enabled": False, "source_media_or_event_arrays_published": False,
            "synthetic_controls_are_separate_authored_examples": True,
            "maximum_network_bytes": MAX_NETWORK_BYTES, "maximum_http_range_requests": MAX_HTTP_REQUESTS,
            "completion_definition": "six diagnostics, baseline checks and historical watchlists processed",
        },
    }
    save(output, report)
    stage = "provenance"
    audio_directory, metadata_directory = work / "audio-sources", work / "metadata-sources"
    try:
        report.update(collect_provenance())
        save(output, report)
        deps = deps if deps is not None else _dependencies()
        stage = "synthetic_controls"
        with (work / "synthetic-controls.log").open("w") as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            controls = deps.synthetic_controls()
        if (not isinstance(controls, dict) or controls.get("status") != "passed"
                or not controls.get("checks") or not all(value is True for value in controls["checks"].values())):
            raise ValueError("predeclared synthetic acoustic controls failed")
        _public_component(controls, private_roots)
        _check_report_budget({**report, "synthetic_controls": controls})
        report["synthetic_controls"] = copy.deepcopy(controls)
        save(output, report)
        stage = "source_acquisition"
        with (work / "preparation.log").open("w") as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            manifest = deps.load_gate_manifest()
            audio = deps.acquire_audio_sources(audio_directory)
            metadata = deps.acquire_metadata_sources(metadata_directory)
        acquisition = _validate_acquisition(audio, metadata, manifest)
        _public_component(acquisition, private_roots)
        _check_report_budget({**report, "source_acquisition": acquisition})
        report["source_acquisition"] = acquisition
        report["preparation_seconds"] = time.monotonic() - started
        save(output, report)
    except Exception as exc:
        inherited._failure(report, "preparation_failed", stage, work, exc)
        return _finish(output, report, started, "preparation_failed")

    baselines = {}
    analysis_tick = time.monotonic()
    for recording, extra in zip(audio["cases"], metadata["cases"], strict=True):
        tick = time.monotonic()
        case_id = recording["id"]
        row = {"id": case_id, "status": "started", "analysis": None,
               "historical_watchlist_transitions": None}
        try:
            raw = _read_sources(recording, extra, audio_directory, metadata_directory)
            samples, sample_rate = decode_audio(raw["audio"], recording["audio"])
            report["completed_audio_decodes"] += 1
            with (work / (case_id + "-analysis.log")).open("w") as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                score, piano_score = deps.parse_score(raw["score"]), deps.parse_score(raw["piano_score"])
                match_audit = deps.parse_piano_match(raw["piano_match"], piano_score)
                result = deps.analyze_boundaries(case_id, samples, sample_rate, score, piano_score,
                                                match_audit, raw["beats"], raw["notes"], raw_score=raw["score"])
            analysis, expressive = result.public, result.expressive_analysis
            if (not isinstance(analysis, dict) or not isinstance(expressive, dict)
                    or type(analysis["reference_count"]) is not int or analysis["reference_count"] <= 0
                    or analysis["reference_count"] != expressive["reference_count"]
                    or analysis["duration_s"] != len(samples) / sample_rate
                    or set(analysis["watchlist"]) != {str(index) for index in WATCHLIST[case_id]}):
                raise ValueError("boundary analysis coverage or original duration changed")
            analysis_hash = _public_component(analysis, private_roots)
            expressive_hash = _public_component(expressive, private_roots)
            if analysis["expressive_analysis_sha256"] != expressive_hash:
                raise ValueError("boundary analysis lost its frozen expressive identity")
            _read_sources(recording, extra, audio_directory, metadata_directory)
            candidate = {**row, "status": "analyzed", "analysis": copy.deepcopy(analysis),
                         "analysis_sha256": analysis_hash,
                         "source_member_sha256": {**recording["member_sha256"], **extra["member_sha256"]},
                         "source_audio_duration_s": len(samples) / sample_rate}
            _check_report_budget({**report, "cases": [*report["cases"], candidate]})
            audio_source._write_atomic(work / (case_id + "-expressive-baseline.json"), inherited._encoded(expressive))
            baselines[case_id] = copy.deepcopy(expressive)
            row = candidate
            report["completed_analyses"] += 1
        except Exception as exc:
            inherited._failure(row, "failed", "analysis", work, exc)
        row["analysis_seconds"] = time.monotonic() - tick
        report["cases"].append(row)
        save(output, report)
        print(case_id, row["status"], flush=True)
    report["analysis_seconds"] = time.monotonic() - analysis_tick
    if report["completed_analyses"] != len(PLANNED_IDS):
        return _finish(output, report, started, "incomplete")
    report["analysis_phase_completed_before_prior_receipts"] = True
    save(output, report)

    stage = "expressive_baseline"
    try:
        # The runner first opens historical outcomes only after saving all six analyses.
        with (work / "historical-receipts.log").open("w") as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            expressive = deps.read_expressive_receipt(EXPRESSIVE_RECEIPT)
            report["expressive_baseline_loaded"] = True
            stage = "gate_receipt"
            gate = deps.read_gate_receipt(GATE_RECEIPT)
            report["gate_receipt_loaded"] = True
        if any(tuple(row["id"] for row in previous["cases"]) != PLANNED_IDS for previous in (expressive, gate)):
            raise ValueError("historical receipt cohort changed")
        report["historical_receipts"] = {
            "expressive": _receipt_identity(expressive, EXPRESSIVE_ZIP_SHA256, EXPRESSIVE_ZIP_BYTES,
                                              EXPRESSIVE_REPORT_SHA256, EXPRESSIVE_REPORT_BYTES),
            "gate": _receipt_identity(gate, GATE_ZIP_SHA256, GATE_ZIP_BYTES, GATE_REPORT_SHA256, GATE_REPORT_BYTES),
        }
        _public_component(report["historical_receipts"], private_roots)
        save(output, report)
        stage = "baseline_verification"
        for old, previous, row in zip(expressive["cases"], gate["cases"], report["cases"], strict=True):
            _verify_baseline(old, previous, row, baselines[row["id"]], private_roots)
            report["completed_baseline_verifications"] += 1
        save(output, report)
    except Exception as exc:
        status = "baseline_verification_failed" if stage == "baseline_verification" else "historical_receipt_failed"
        inherited._failure(report, status, stage, work, exc)
        return _finish(output, report, started, status)

    for index, (previous, row) in enumerate(zip(gate["cases"], report["cases"], strict=True)):
        try:
            transitions = historical_watchlist_transitions(copy.deepcopy(previous), row["id"], row["analysis"]["reference_count"])
            _public_component(transitions, private_roots)
            candidates = list(report["cases"])
            candidates[index] = {**row, "status": "complete", "historical_watchlist_transitions": transitions}
            _check_report_budget({**report, "cases": candidates})
            row["historical_watchlist_transitions"] = transitions
            row["status"] = "complete"
            report["completed_historical_watchlists"] += 1
        except Exception as exc:
            inherited._failure(row, "historical_watchlist_failed", "historical_watchlist", work, exc)
        save(output, report)
    if report["completed_historical_watchlists"] != len(PLANNED_IDS):
        return _finish(output, report, started, "incomplete")
    try:
        summary = deps.summarize_boundaries(copy.deepcopy(report["cases"]))
        if summary is not None and not isinstance(summary, dict):
            raise ValueError("aggregate summary must be a metadata object or unavailable")
        _public_component(summary, private_roots)
        _check_report_budget({**report, "summary": summary})
        report["summary"] = copy.deepcopy(summary)
        status = "complete" if summary is not None else "incomplete"
    except Exception as exc:
        inherited._failure(report, "aggregation_failed", "aggregation", work, exc)
        report["summary"] = None
        status = "aggregation_failed"
    return _finish(output, report, started, status)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    return run(args.work, args.output)


if __name__ == "__main__":
    raise SystemExit(main())

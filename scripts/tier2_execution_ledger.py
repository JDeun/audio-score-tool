"""Build a private-run, metadata-only Tier 2 execution and retest receipt.

Receipt generation does not run models. Completed stages are accepted only
after checking their recorded provenance and artifact/report SHA-256. Private
audio paths and raw exception messages are intentionally *not* copied into the
receipt or uploaded to public Actions artifacts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEX32 = re.compile(r"^[0-9a-f]{32}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
STAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+_-]{0,79}$")
STATUSES = frozenset({"planned", "blocked", "failed", "completed"})
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(data)
    return digest.hexdigest()


def _load_json(path: Path) -> dict:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"missing or unsafe JSON input: {path.name}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("JSON input must be an object")
    return data


def _environment(device: str) -> dict[str, Any]:
    lock = PROJECT_ROOT / "uv.lock"
    commit = os.getenv("GITHUB_SHA", "").lower()
    return {
        "python": platform.python_version(),
        "platform": platform.system(),
        "platform_release": platform.release(),
        "machine": platform.machine(),
        "cpu_logical_count": os.cpu_count(),
        "inference_device_requested": device,
        "git_commit": commit if HEX40.fullmatch(commit) else None,
        "uv_lock_sha256": sha256(lock) if lock.is_file() else None,
        "hardware_acceleration_measured": False,
    }


def _manifest_info(path: Path) -> dict:
    from audio_score_tool.tier2_benchmark import load_manifest

    version, cases = load_manifest(path)
    raw = _load_json(path)
    by_id = {entry.get("id"): entry for entry in raw.get("cases", [])
             if isinstance(entry, dict)}
    rights = []
    for case in cases:
        source = by_id.get(case.id, {}).get("audio", {})
        if not isinstance(source, dict):
            source = {}
        rights.append({
            "case_id": case.id,
            "ownership": str(source.get("ownership") or "unverified"),
            "redistributable": source.get("redistributable") is True,
            "rights_independently_verified": False,
        })
    ids = [case.id for case in cases]
    fingerprint = hashlib.sha256(
        json.dumps(ids, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "corpus_version": version,
        "manifest_sha256": sha256(path),
        "ordered_case_fingerprint": fingerprint,
        "cases": rights,
    }


def _previous_receipt(path: Path, *, manifest_sha: str | None, matrix_sha: str) -> dict:
    previous = _load_json(path)
    old_id = previous.get("run_id")
    if previous.get("schema_version") != 1 or not isinstance(old_id, str) or not HEX32.fullmatch(old_id):
        raise ValueError("retest source has invalid run identity")
    if previous.get("matrix_sha256") != matrix_sha:
        raise ValueError("retest source matrix hash differs")
    old_manifest = (previous.get("corpus") or {}).get("manifest_sha256")
    if old_manifest != manifest_sha:
        raise ValueError("retest source corpus manifest hash differs")
    if not any(
        isinstance(item, dict) and item.get("status") in {"blocked", "failed"}
        for item in previous.get("stages", [])
    ):
        raise ValueError("retest source has no blocked or failed stage")
    return {"run_id": old_id, "receipt_sha256": sha256(path)}


def build_receipt(
    *,
    summary: dict, matrix_path: Path, output_root: Path,
    manifest_path: Path | None = None, device: str = "cpu",
    retest_of: Path | None = None,
) -> dict:
    """Fail closed on forged completed stages or stale runtime artifacts."""
    matrix = _load_json(matrix_path)
    declared = matrix.get("stages")
    if matrix.get("schema_version") != 1 or not isinstance(declared, list):
        raise ValueError("invalid experiment matrix")
    ids = {
        item.get("id") for item in declared
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    if len(ids) != len(declared):
        raise ValueError("matrix contains duplicate or invalid stages")
    stages = summary.get("results")
    if summary.get("schema_version") != 1 or not isinstance(stages, list) or not stages:
        raise ValueError("summary requires ordered stage results")
    if not isinstance(device, str) or device not in {"cpu", "cuda", "mps"}:
        raise ValueError("unknown inference device")
    corpus = _manifest_info(manifest_path) if manifest_path is not None else None
    if corpus is None and any(item.get("status") not in {"planned", "blocked"} for item in stages):
        raise ValueError("non-dry-run execution receipt requires a corpus manifest")
    matrix_digest = sha256(matrix_path)
    output = output_root.expanduser().resolve()
    ledger: list[dict] = []
    seen: set[str] = set()
    for stage in stages:
        if not isinstance(stage, dict):
            raise ValueError("result stages must be objects")
        name, status = stage.get("id"), stage.get("status")
        if name == "comparison" and status == "failed":
            if "comparison" in seen:
                raise ValueError("duplicate comparison result")
            seen.add("comparison")
            ledger.append({
                "id": "comparison", "kind": "comparison", "status": "failed",
                "error_or_blocker_recorded": True, "report_verified": False,
                "failure_reason_sha256": hashlib.sha256(
                    b"comparison command failed; details retained in private job logs"
                ).hexdigest(),
            })
            continue
        if (not isinstance(name, str) or not STAGE.fullmatch(name)
                or name not in ids or name in seen or status not in STATUSES):
            raise ValueError("unknown, duplicate or invalid stage result")
        seen.add(name)
        kind = next(item["kind"] for item in declared if item["id"] == name)
        item: dict[str, Any] = {"id": name, "kind": kind, "status": status}
        seconds = stage.get("elapsed_seconds")
        if seconds is not None:
            if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not 0 <= seconds < 1e9:
                raise ValueError("stage elapsed_seconds invalid")
            item["elapsed_seconds"] = seconds
        if status == "completed":
            if corpus is None or not stage.get("report") or not stage.get("report_sha256"):
                raise ValueError("completed stage must have corpus, report and checksum")
            raw_report = Path(stage["report"])
            candidate = raw_report.resolve()
            if raw_report.is_symlink() or not candidate.is_relative_to(output) or not candidate.is_file():
                raise ValueError("completed report is missing or outside its private output root")
            report_sha = stage["report_sha256"]
            if not isinstance(report_sha, str) or not HEX64.fullmatch(report_sha):
                raise ValueError("completed report SHA-256 is invalid")
            if sha256(candidate) != report_sha:
                raise ValueError("completed report SHA-256 mismatch")
            from audio_score_tool.tier2_experiment_record import validate_tier2_experiment_record

            model_dir = output / name
            receipt = validate_tier2_experiment_record(
                model_dir,
                manifest_path=manifest_path,
                events_root=(output / "sheetsage2") if kind == "hybrid" else None,
            )
            if receipt["stage_id"] != name:
                raise ValueError("completed report identity differs from stage")
            item["prediction_run_id"] = receipt["run_id"]
            item["validated_artifact_count"] = receipt["verified_artifacts"]
            item["report_sha256"] = report_sha
            item["prediction_provenance_sha256"] = sha256(
                model_dir / "tier2-prediction-provenance.json"
            )
            item["report_verified"] = True
        elif status in {"blocked", "failed"}:
            reason = stage.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError("blocked/failed stage requires a recorded reason")
            # May contain confidential private paths or CLI tokens: hash only.
            item["failure_reason_sha256"] = hashlib.sha256(reason.encode("utf-8")).hexdigest()
            item["error_or_blocker_recorded"] = True
            item["report_verified"] = False
        else:
            item["report_verified"] = False
        ledger.append(item)
    if seen - {"comparison"} != ids:
        raise ValueError("summary must cover every declared experiment stage exactly once")
    if (summary.get("completed") != sum(i["status"] == "completed" for i in ledger)
            or summary.get("blocked") != sum(i["status"] == "blocked" for i in ledger)):
        raise ValueError("summary status counters are inconsistent")
    previous = (_previous_receipt(
        retest_of, manifest_sha=corpus["manifest_sha256"] if corpus else None,
        matrix_sha=matrix_digest,
    ) if retest_of is not None else None)
    return {
        "schema_version": 1,
        "run_id": uuid.uuid4().hex,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "matrix_sha256": matrix_digest,
        "corpus": corpus,
        "environment": _environment(device),
        "stages": ledger,
        "completed": summary["completed"],
        "blocked": summary["blocked"],
        "failed": sum(i["status"] == "failed" for i in ledger),
        "retest_of": previous,
        "source_audio_copied_to_receipt": False,
        "raw_exception_messages_copied_to_receipt": False,
        "commercial_approval": False,
    }


def save_receipt(path: Path, content: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit a Tier 2 run summary without inference")
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--device", choices=("cpu", "cuda", "mps"), default="cpu")
    parser.add_argument("--retest-of", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = build_receipt(
        summary=_load_json(args.summary),
        matrix_path=args.matrix,
        manifest_path=args.manifest,
        output_root=args.output_root,
        device=args.device,
        retest_of=args.retest_of,
    )
    save_receipt(args.output, receipt)
    print(json.dumps({
        "run_id": receipt["run_id"], "completed": receipt["completed"],
        "blocked": receipt["blocked"], "failed": receipt["failed"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

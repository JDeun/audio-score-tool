"""Run the five private WAVs through real upload -> job -> Song -> explicit PDF.

This records execution, never approves musical quality without reference scores
and measured human correction. No audio, lyrics or scores belong in public CI.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio-root", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--runtime-python", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    if args.output.exists() or args.output.is_symlink() or args.output.resolve().is_relative_to(project):
        raise ValueError("Use a new private output directory outside the repository")
    manifest_path = project / "benchmarks/tier2/user-acceptance.manifest.json"
    manifest = json.loads(manifest_path.read_text())
    sources = [(case, args.audio_root / f"{case['id']}.wav") for case in manifest["cases"]]
    if len(sources) != 5 or any(not p.is_file() or p.is_symlink() for _, p in sources):
        raise ValueError("All five original private WAVs are required")
    args.output.mkdir(parents=True)
    # Environment must be set before API modules create their SQLite stores.
    import shlex

    os.environ.update(
        AST_DATA_DIR=str(args.output / "app"), AST_USAGE_MODE="personal",
        AST_TRANSCRIPTION_ENGINE="sheetsage2", AST_SHEETSAGE2_SNAPSHOT=str(args.snapshot),
        AST_SHEETSAGE2_CMD=shlex.join([str(args.runtime_python), str(project / "scripts/sheetsage2_infer_adapter.py")]),
        AST_WHISPERX_CMD=str(args.output / "unavailable-whisperx"),
        AST_DEMUCS_CMD=str(args.output / "unavailable-demucs"),
        HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
    )
    from fastapi.testclient import TestClient

    from audio_score_tool.api import app
    from audio_score_tool.sheetsage2_score import BASE_REVISION, CHECKPOINT_SHA256, MODEL_REVISION

    report = dict(
        schema_version=1, model="sheetsage2", model_revision=MODEL_REVISION,
        checkpoint_sha256=CHECKPOINT_SHA256, base_model_revision=BASE_REVISION,
        device="cpu", dtype="fp32", threads=4, preset="default", window_seconds=300,
        model_selection="frozen_diagnostic_candidate_not_quality_approved",
        manifest_sha256=sha256(manifest_path),
        source_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=project, text=True).strip(),
        source_sha256={str(p.relative_to(project)): sha256(p) for p in [
            Path(__file__), project / "scripts/sheetsage2_infer_adapter.py",
            project / "src/audio_score_tool/sheetsage2_score.py",
            project / "src/audio_score_tool/transcription_engine.py",
            project / "src/audio_score_tool/pipeline_v2.py"]},
        source_kind="prepared_youtube_wav_uploaded_to_real_product_api",
        live_youtube_ingestion_retested=False, lyrics_tested=False,
        gold_reference_available=False, human_correction_measured=False,
        commercial_release_quality_approved=False, cases=[],
    )
    receipt = args.output / "report.json"
    receipt.write_text(json.dumps(report, indent=2) + "\n")
    with TestClient(app) as client:
        for case, source in sources:
            started = time.perf_counter()
            row = dict(id=case["id"], audio_sha256=sha256(source), status="starting")
            report["cases"].append(row)
            try:
                with source.open("rb") as audio:
                    reply = client.post("/api/jobs", files={"file": (case["title"] + ".wav", audio, "audio/wav")},
                                        data={"score_mode": "lead_sheet", "skip_lyrics": "true", "auto_enrich": "false"})
                reply.raise_for_status()
                job_id = reply.json()["job_id"]
                row.update(job_id=job_id, status="running")
                receipt.write_text(json.dumps(report, indent=2) + "\n")
                last_stage = None
                while time.perf_counter() - started < 7500:
                    reply = client.get(f"/api/jobs/{job_id}")
                    reply.raise_for_status()
                    job = reply.json()
                    if job.get("stage") != last_stage:
                        print(f"{case['id']}: {job.get('stage')}", flush=True)
                        last_stage = job.get("stage")
                    if job["status"] in {"done", "failed", "cancelled"}:
                        break
                    time.sleep(5)
                else:
                    client.post(f"/api/jobs/{job_id}/cancel")
                    raise RuntimeError("Product job timed out")
                (args.output / f"{case['id']}-job.json").write_text(json.dumps(job, indent=2))
                if job["status"] != "done":
                    raise RuntimeError(job.get("error") or job["status"])
                reply = client.get("/api/songs")
                reply.raise_for_status()
                songs = [s for s in reply.json()["songs"] if s.get("job_id") == job_id]
                if len(songs) != 1:
                    raise RuntimeError("Completed job did not reconcile to exactly one Song")
                song = songs[0]
                reply = client.post(f"/api/songs/{song['song_id']}/export-to", json={
                    "destination_dir": str(args.output / "exports" / case["id"]),
                    "formats": ["musicxml", "midi", "pdf"], "expected_revision": song["revision"]})
                reply.raise_for_status()
                (args.output / f"{case['id']}-export.json").write_text(json.dumps(reply.json(), indent=2))
                files = list((args.output / "exports" / case["id"]).rglob("score.*"))
                if not {".pdf", ".mid", ".musicxml"}.issubset({p.suffix for p in files}):
                    raise RuntimeError("Explicit export omitted PDF/MIDI/MusicXML")
                row.update(status="exported", song_id=song["song_id"], revision=song["revision"],
                           outputs={p.suffix: {"bytes": p.stat().st_size, "sha256": sha256(p)} for p in files})
            except Exception as exc:
                row.update(status="failed", error_type=type(exc).__name__)
                response = getattr(exc, "response", None)
                detail = str(exc) + ("\n" + response.text if response is not None else "")
                (args.output / f"{case['id']}-failure.txt").write_text(detail)
            row["elapsed_seconds"] = round(time.perf_counter() - started, 3)
            receipt.write_text(json.dumps(report, indent=2) + "\n")
            print(f"{case['id']}: {row['status']} ({row['elapsed_seconds']}s)", flush=True)
    return 0 if all(c["status"] == "exported" for c in report["cases"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())

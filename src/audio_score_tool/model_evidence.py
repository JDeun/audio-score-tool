"""Immutable, bounded model observations owned by a Song, not its temporary Job."""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path

MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024
SCORE_FILES = {"score.mid", "score.musicxml", "analysis.json", "notation-report.json",
               "recipe.json", "interpretation.json"}
NATIVE_FILES = {
    "score.abc", "playback.json", "result.json", "events.json", "events.tsv",
    "tokens.json", "tokens.txt", "transcription.mid", "melody.mid", "chords.mid",
    "melody_vocal.mid", "melody_instrumental.mid", "melody_vocal.lab",
    "melody_instrumental.lab", "melody_full.lab", "key.lab", "chord.lab",
    "rhythm_events.lab", "downbeat.lab", "beat.lab", "structure.lab",
    "notation/song_beats.txt", "notation/song_keys.txt", "notation/song_structures.txt",
    "notation/song_melody.mid", "notation/song_chords.txt",
}


def _owned(path: Path, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    return not root.is_symlink() and all(
        not (root / Path(*relative.parts[:i])).is_symlink()
        for i in range(1, len(relative.parts) + 1)
    ) and path.resolve().is_relative_to(root.resolve())


def _digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def preserve_model_evidence(job: dict, *, jobs_root: Path, asset_root: Path) -> dict:
    """Refuse cleanup on incomplete/corrupt evidence; never copy arbitrary job paths."""
    song_id = str(job.get("job_id") or "")
    if not song_id or Path(song_id).name != song_id or song_id in {".", ".."}:
        raise ValueError("Invalid evidence owner")
    song_dir = asset_root / song_id
    if not _owned(song_dir, asset_root):
        raise ValueError("Model evidence destination is not owned by this Song")
    final = song_dir / "model-evidence"
    if final.exists() or final.is_symlink():
        if not _owned(final, asset_root):
            raise ValueError("Unsafe model evidence directory")
        if not _owned(final / "manifest.json", final):
            raise ValueError("Unsafe model evidence manifest")
        receipt = final / "manifest.json"
        if receipt.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("Oversized model evidence manifest")
        manifest = json.loads(receipt.read_text())
        if (not isinstance(manifest, dict) or manifest.get("schema_version") != 1
                or manifest.get("job_id") != song_id):
            raise ValueError("Invalid model evidence manifest")
        files = manifest.get("files")
        if not isinstance(files, list) or not files:
            raise ValueError("Model evidence manifest has no files")
        for entry in files:
            if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                raise ValueError("Invalid model evidence file entry")
            path = final / entry["path"]
            if (not _owned(path, final) or not path.is_file()
                    or path.stat().st_size != entry["bytes"] or _digest(path) != entry["sha256"]):
                raise ValueError("Stored model evidence failed integrity validation")
        return manifest

    result = job.get("result") or {}
    score_value = result.get("score_dir")
    if not score_value:
        # Legacy/direct notation jobs did not declare raw model outputs.
        return {"status": "unavailable", "reason": "job_has_no_model_output_directory"}
    job_root = jobs_root / song_id
    score_dir = Path(score_value)
    if (not _owned(job_root, jobs_root) or not _owned(score_dir, job_root)
            or not score_dir.is_dir()):
        raise ValueError("Model output directory is missing or outside its Job")
    candidates = [score_dir / name for name in sorted(SCORE_FILES)]
    candidates += [score_dir / "native" / name for name in sorted(NATIVE_FILES)]
    if job.get("transcription_engine") == "vocal_lead_v1":
        candidates += [score_dir / "structure" / name for name in sorted(SCORE_FILES)]
        candidates += [score_dir / "structure/native" / name for name in sorted(NATIVE_FILES)]
    candidates += [score_dir.parent / name for name in ("music_structure.json", "chords.json")]
    for role in ("vocal", "guitar", "accompaniment"):
        candidates += [score_dir / role / name for name in (
            "score.mid", "score.musicxml", "part-selection.json", "selected.mid",
            "selected.musicxml", "score.runtime.json", "pitch.npz", "pitch.runtime.json")]
    files = []
    total = 0
    for path in candidates:
        if path.is_symlink() or not _owned(path, job_root):
            raise ValueError("Symlinked or foreign model evidence")
        if not path.exists():
            continue
        size = path.stat().st_size
        if not path.is_file() or size > MAX_FILE_BYTES:
            raise ValueError("Invalid or oversized model evidence file")
        total += size
        if total > MAX_TOTAL_BYTES:
            raise ValueError("Model evidence exceeds storage limit")
        files.append(path)
    if score_dir / "score.mid" not in files:
        raise ValueError("Model evidence has no original MIDI")
    if job.get("transcription_engine") == "sheetsage2" and not {
        score_dir / "native" / "score.abc", score_dir / "native" / "melody_vocal.mid",
        score_dir / "native" / "playback.json", score_dir / "analysis.json",
    }.issubset(files):
        raise ValueError("Incomplete SheetSage2 source observations")
    if job.get("transcription_engine") == "vocal_lead_v1" and not {
        score_dir / "recipe.json", score_dir / "interpretation.json",
        score_dir / "vocal/score.mid", score_dir / "vocal/score.runtime.json",
        score_dir / "vocal/selected.mid", score_dir / "native/score.abc",
        score_dir / "native/playback.json", score_dir / "structure/analysis.json",
        score_dir / "structure/native/score.abc", score_dir / "structure/native/melody_vocal.mid",
    }.issubset(files):
        raise ValueError("Incomplete fixed vocal recipe source observations")
    if job.get("transcription_engine") == "vocal_lead_v1":
        recipe_path = score_dir / "recipe.json"
        recipe = json.loads(recipe_path.read_text())
        if not isinstance(recipe, dict) or type(recipe.get("recipe_version", 1)) is not int or recipe.get("recipe_version", 1) not in (1, 2):
            raise ValueError("Invalid fixed vocal recipe version")
        if recipe.get("recipe_version", 1) == 2:
            if not {score_dir / "vocal/pitch.npz", score_dir / "vocal/pitch.runtime.json"}.issubset(files):
                raise ValueError("Incomplete fixed vocal pitch evidence")
            pitch_receipt = json.loads((score_dir / "vocal/pitch.runtime.json").read_text())
            if not isinstance(pitch_receipt, dict) or pitch_receipt.get("prediction_sha256") != _digest(score_dir / "vocal/pitch.npz"):
                raise ValueError("Fixed vocal pitch evidence SHA mismatch")
    inputs = [p for p in job_root.glob("input.*") if p.is_file() and _owned(p, job_root)]
    manifest = {
        "schema_version": 1, "status": "preserved", "job_id": song_id,
        "selection": {k: job.get(k) for k in (
            "transcription_engine", "transcription_selection_version", "mt3_model",
            "native_checkpoint_sha256", "muscriptor_model", "score_mode",
        )},
        "source_audio_sha256": _digest(inputs[0]) if len(inputs) == 1 else None,
        "files": [],
        "policy": {"immutable_model_observations": True, "independent_ground_truth": False},
    }
    song_dir.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".model-evidence-", dir=song_dir))
    try:
        copied_bytes = 0
        for source in files:
            name = (source.relative_to(score_dir).as_posix() if source.is_relative_to(score_dir)
                    else f"context/{source.name}")
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open("rb") as src, target.open("xb") as dst:
                remaining = MAX_FILE_BYTES + 1
                while remaining:
                    chunk = src.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    dst.write(chunk)
                    remaining -= len(chunk)
            if target.stat().st_size != source.stat().st_size or remaining == 0:
                raise ValueError("Model evidence changed or exceeded limit during copy")
            copied_bytes += target.stat().st_size
            if copied_bytes > MAX_TOTAL_BYTES:
                raise ValueError("Model evidence exceeds storage limit during copy")
            digest = _digest(target)
            if digest != _digest(source):
                raise ValueError("Model evidence changed during copy")
            manifest["files"].append({"path": name, "bytes": target.stat().st_size, "sha256": digest})
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        stage.rename(final)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return manifest

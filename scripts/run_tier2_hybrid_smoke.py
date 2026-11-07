"""Verify actual AMT artifacts and bind SheetSage2 fusion to the same audio bytes.

This runner never creates model predictions. Failure remains failure; a valid XML
file without performed notes and a changed/re-downloaded YouTube source cannot
become a successful hybrid result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from audio_score_tool.sheetsage_hybrid import (
    SheetSageError,
    load_sheetsage_events,
    merge_sheetsage_musicxml,
)
from scripts.run_tier2_model_smoke import verify_model_outputs

_MODELS = frozenset({"yourmt3", "mr_mt3"})


def _sha256_file(path: Path) -> str:
    if path.is_symlink() or not path.is_file() or path.stat().st_size <= 0:
        raise ValueError(f"Missing, empty or symlinked inference artifact: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _receipt(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 256 * 1024:
        raise ValueError("AMT result receipt is absent or too large")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError, UnicodeError) as exc:
        raise ValueError("AMT result receipt is malformed") from exc
    if not isinstance(payload, dict):
        raise ValueError("AMT result receipt must be a JSON object")
    return payload


def _version(package: str) -> str | None:
    try:
        return version(package)
    except PackageNotFoundError:
        return None


def verify_base(audio: Path, base_dir: Path, *, model: str) -> dict:
    """Revalidate detached CI artifacts, never trust claimed success or paths."""
    if model not in _MODELS:
        raise ValueError(f"Unsupported AMT variant: {model}")
    if base_dir.is_symlink() or not base_dir.is_dir():
        raise ValueError("AMT model artifact directory is missing")
    payload = _receipt(base_dir / "smoke-result.json")
    if payload.get("model") != model or payload.get("note_events_detected") is not True:
        raise ValueError("AMT receipt model identity or note-success flag is invalid")
    ci_sha = os.environ.get("GITHUB_SHA")
    if ci_sha and payload.get("source_commit") != ci_sha:
        raise ValueError("AMT result originated from a different source commit")

    file_map = (
        ("audio_sha256", audio),
        ("midi_sha256", base_dir / "score.mid"),
        ("musicxml_sha256", base_dir / "score.musicxml"),
    )
    for field, path in file_map:
        actual = _sha256_file(path)
        if payload.get(field) != actual:
            raise ValueError(f"AMT {field} mismatch: source or artifact bytes changed")

    counts = verify_model_outputs(base_dir / "score.mid", base_dir / "score.musicxml")
    for field in ("notes", "midi_notes", "parts"):
        if (
            isinstance(payload.get(field), bool)
            or not isinstance(payload.get(field), int)
            or payload[field] <= 0
            or counts[field] != payload[field]
        ):
            raise ValueError(f"AMT receipt {field} does not match real score")
    return payload


def merge_verified(
    audio: Path, base_dir: Path, *,
    model: str, events_file: Path, destination: Path,
) -> dict:
    """Only persist a hybrid receipt after actual model outputs and merge pass."""
    base = verify_base(audio, base_dir, model=model)
    if events_file.is_symlink() or not events_file.is_file():
        raise ValueError("SheetSage2 events file is missing or symlinked")
    events = load_sheetsage_events(events_file)
    if events.get("model") != "sheetsage2" or events.get("schema_version") != 1:
        raise ValueError("SheetSage2 output lacks actual model/schema identity")
    if not (
        any(e["label"].strip() not in {"", "N", "N.C.", "no_chord"} for e in events.get("chords", []))
        or events.get("keys")
        or events.get("meter")
    ):
        raise ValueError("SheetSage2 produced no usable harmony, key or meter for fusion")
    if destination.exists() or destination.is_symlink():
        raise ValueError("Hybrid MusicXML destination must not preexist")

    try:
        report = merge_sheetsage_musicxml(
            base_dir / "score.musicxml", events_file, destination,
        )
        counts = verify_model_outputs(base_dir / "score.mid", destination)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    if counts["notes"] != base["notes"]:
        destination.unlink(missing_ok=True)
        raise ValueError("Hybrid conversion changed AMT performed-note count")
    if not any(report["added"].values()):
        destination.unlink(missing_ok=True)
        raise SheetSageError("No SheetSage2 annotations were merged")

    result = {
        "schema_version": 1,
        "model": f"{model}+sheetsage2",
        "inference_engine": "mt3-infer",
        "analysis_model": "sheetsage2",
        "commercial_approval": False,
        "license_review_required": True,
        "source_commit": base.get("source_commit"),
        "audio_sha256": base["audio_sha256"],
        "amt_result_sha256": _sha256_file(base_dir / "smoke-result.json"),
        "amt_midi_sha256": base["midi_sha256"],
        "amt_musicxml_sha256": base["musicxml_sha256"],
        "sheetsage_events_sha256": _sha256_file(events_file),
        "hybrid_musicxml_sha256": _sha256_file(destination),
        "performed_notes_preserved": counts["notes"],
        "added": report["added"],
        "alignment": report["alignment"],
        "runtime": {
            "python": platform.python_version(),
            "mt3_infer": (base.get("runtime") or {}).get("mt3_infer"),
            "sheetsage_infer": _version("sheetsage-infer"),
            "sheetsage_source_revision": os.environ.get("SHEETSAGE_RUNTIME_REVISION"),
            "requested_device": "cpu",
        },
        "checkpoint": {
            "mt3_verified": bool((base.get("checkpoint") or {}).get("verified", False)),
            # The Python package pin is NOT evidence of the SheetSage2 model weights.
            "sheetsage_verified": False,
        },
    }
    evidence = base_dir / "hybrid-result.json"
    if evidence.exists() or evidence.is_symlink():
        raise ValueError("Hybrid receipt already exists")
    with evidence.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify AMT audio identity and real SheetSage2 fusion.")
    parser.add_argument("audio", type=Path)
    parser.add_argument("base_dir", type=Path)
    parser.add_argument("--model", required=True, choices=sorted(_MODELS))
    parser.add_argument("--phase", required=True, choices=("verify-base", "merge"))
    parser.add_argument("--events", type=Path)
    parser.add_argument("--merged", type=Path)
    args = parser.parse_args()
    if args.phase == "verify-base":
        base = verify_base(args.audio, args.base_dir, model=args.model)
        print(json.dumps({"base_verified": True, "model": args.model,
                          "audio_sha256": base["audio_sha256"], "notes": base["notes"]}))
    else:
        if args.events is None or args.merged is None:
            parser.error("--events and --merged are required for --phase merge")
        result = merge_verified(
            args.audio, args.base_dir, model=args.model,
            events_file=args.events, destination=args.merged,
        )
        print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

import json
from pathlib import Path

import pytest

from training.train_native import load_manifest


def _row(license_name: str) -> str:
    return json.dumps(
        {
            "audio": "song.wav",
            "midi": "song.mid",
            "license": license_name,
            "split": "train",
        }
    ) + "\n"


def test_native_training_manifest_accepts_commercial_compatible_license(tmp_path: Path):
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(_row("CC-BY-4.0"), encoding="utf-8")
    rows = load_manifest(manifest, "train")
    assert len(rows) == 1


def test_native_training_manifest_rejects_unapproved_license(tmp_path: Path):
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(_row("CC-BY-NC-4.0"), encoding="utf-8")
    with pytest.raises(ValueError, match="Refusing training asset"):
        load_manifest(manifest, "train")

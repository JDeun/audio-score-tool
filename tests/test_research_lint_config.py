"""Nested archival lint settings must retain root import classification and error checks."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import tomllib

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("directory", "archived_file"),
    [("scripts", "nasap_joint_rhythm.py"), ("tests", "test_nasap_joint_rhythm.py")],
)
def test_nested_lint_config_preserves_source_roots_and_narrow_exception(directory, archived_file):
    config_path = ROOT / directory / "ruff.toml"
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert (config_path.parent / config["extend"]).resolve() == ROOT / "pyproject.toml"
    assert {(config_path.parent / item).resolve() for item in config["src"]} == {
        ROOT, ROOT / "src",
    }
    assert config["lint"] == {"extend-per-file-ignores": {archived_file: ["I001"]}}


def lint_stdin(path, source):
    return subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--no-cache", "--stdin-filename", str(path), "-"],
        input=source,
        text=True,
        capture_output=True,
        cwd=ROOT,
        timeout=20,
        check=False,
    )


@pytest.mark.parametrize("directory", ["scripts", "tests"])
def test_nested_lint_keeps_internal_imports_separate_from_dependencies(directory):
    source = (
        "import numpy as np\n\n"
        "from audio_score_tool.metrics import midi_notes\n"
        "from scripts.run_ci_test_scope import scopes\n\n"
        '__all__ = ["np", "midi_notes", "scopes"]\n'
    )
    result = lint_stdin(ROOT / directory / "_import_classification_probe.py", source)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "relative", ["scripts/nasap_joint_rhythm.py", "tests/test_nasap_joint_rhythm.py"],
)
def test_archival_import_exception_does_not_suppress_undefined_names(relative):
    result = lint_stdin(ROOT / relative, "print(undefined_archival_probe_name)\n")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "F821" in result.stdout

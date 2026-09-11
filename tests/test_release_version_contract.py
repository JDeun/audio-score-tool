from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_release_versions.py"
spec = importlib.util.spec_from_file_location("verify_release_versions", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_release_versions_are_consistent():
    versions = module.release_versions(ROOT)
    assert set(versions.values()) == {"0.8.0"}
    assert module.verify_versions(root=ROOT) == "0.8.0"


def test_release_tag_must_match_package_version():
    assert module.verify_versions(tag="v0.8.0", root=ROOT) == "0.8.0"
    with pytest.raises(ValueError, match="tag/version mismatch"):
        module.verify_versions(tag="v9.9.9", root=ROOT)

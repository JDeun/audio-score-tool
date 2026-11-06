"""Manually gated packaged-runtime acceptance must fail closed without a catalog."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from audio_score_tool.managed_publication_readiness import _REQUIRED_TOOLS, CORE_COMPONENTS
from scripts import smoke_packaged_sidecar as smoke


def _catalog(*, published: bool = True) -> dict[str, dict]:
    return {
        name: {
            "key": name,
            "auto_install": published,
            "catalog": {
                "published": published,
                "publication_reason": None if published else "artifact-not-published",
            },
            "managed_status": {"ready": False, "integrity": "not-installed"},
        }
        for name in CORE_COMPONENTS
    }


def test_no_published_managed_runtime_fails_before_any_download(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(smoke, "_component_index", lambda *_: _catalog(published=False))
    monkeypatch.setattr(
        smoke, "_post_json", lambda *_: (_ for _ in ()).throw(
            AssertionError("Unpublished components must not be installed")
        ),
    )
    with pytest.raises(RuntimeError, match="no approved platform artifact"):
        smoke._verify_managed_delivery("http://127.0.0.1:9999", "test-token", tmp_path)


def test_approved_catalog_installs_verified_tools_in_temp_managed_root(
    tmp_path: Path, monkeypatch
):
    root = tmp_path / "managed"
    root.mkdir()
    installed_paths: dict[str, dict[str, str]] = {}
    for component in CORE_COMPONENTS:
        paths = {}
        for name in sorted(_REQUIRED_TOOLS[component]):
            path = root / "installed" / component / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"CI fixture:{component}:{name}".encode())
            paths[name] = str(path)
        installed_paths[component] = paths

    calls: list[tuple[str, str]] = []
    indexes = 0

    def index(_base: str, _token: str):
        nonlocal indexes
        indexes += 1
        values = _catalog()
        if indexes >= 2:
            for item in values.values():
                item["managed_status"] = {"ready": True, "integrity": "verified"}
        return values

    def install(url: str, token: str, body: dict):
        component = body["component"]
        calls.append((url, token))
        return (
            200,
            json.dumps({
                "installed": {
                    "ready": True, "integrity": "verified",
                    "tools": installed_paths[component],
                }
            }).encode(),
        )

    monkeypatch.setattr(smoke, "_component_index", index)
    monkeypatch.setattr(smoke, "_post_json", install)
    smoke._verify_managed_delivery("http://127.0.0.1:9999", "test-token", root)
    assert indexes == 2
    assert len(calls) == len(CORE_COMPONENTS)
    assert all(url.endswith("/api/setup/install") and token == "test-token" for url, token in calls)


def test_missing_tool_in_installer_result_blocks_release(tmp_path: Path, monkeypatch):
    root = tmp_path / "managed"
    root.mkdir()
    monkeypatch.setattr(smoke, "_component_index", lambda *_: _catalog())

    def install(_url: str, _token: str, body: dict):
        name = body["component"]
        paths = {
            tool: str(root / f"{name}-{tool}")
            for tool in sorted(_REQUIRED_TOOLS[name])[:-1]
        }
        return (200, json.dumps({
            "installed": {"ready": True, "integrity": "verified", "tools": paths}
        }).encode())

    monkeypatch.setattr(smoke, "_post_json", install)
    with pytest.raises(RuntimeError, match="required installed tools missing"):
        smoke._verify_managed_delivery("http://127.0.0.1:9999", "token", root)


def test_verifier_rejects_installed_tool_escaping_managed_root(
    tmp_path: Path, monkeypatch,
):
    root = tmp_path / "managed"
    root.mkdir()
    outside = tmp_path / "foreign-tool"
    outside.write_bytes(b"foreign executable")
    monkeypatch.setattr(smoke, "_component_index", lambda *_: _catalog())

    def install(_url: str, _token: str, body: dict):
        component = body["component"]
        return (200, json.dumps({
            "installed": {
                "ready": True, "integrity": "verified",
                "tools": {tool: str(outside) for tool in _REQUIRED_TOOLS[component]},
            }
        }).encode())

    monkeypatch.setattr(smoke, "_post_json", install)
    with pytest.raises(RuntimeError, match="escapes the managed root"):
        smoke._verify_managed_delivery("http://127.0.0.1:9999", "token", root)


def test_failed_remote_install_stops_acceptance(tmp_path: Path, monkeypatch):
    root = tmp_path / "managed"
    root.mkdir()
    monkeypatch.setattr(smoke, "_component_index", lambda *_: _catalog())
    monkeypatch.setattr(
        smoke, "_post_json",
        lambda *_: (409, b'{"detail":"checksum mismatch"}'),
    )
    with pytest.raises(RuntimeError, match="managed installation failed \(409\)"):
        smoke._verify_managed_delivery("http://127.0.0.1:9999", "token", root)


def test_managed_delivery_check_is_manual_or_v1_tag_only():
    workflow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/desktop-packages.yml"
    ).read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "require_managed_delivery:" in workflow
    assert "pull_request:" not in workflow.split("on:\n", 1)[1].split("jobs:", 1)[0]
    assert "matrix.name != 'linux'" in workflow
    assert "startsWith(github.ref, 'refs/tags/v1')" in workflow
    assert "--require-managed-delivery" in workflow

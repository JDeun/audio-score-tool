"""Protect the fast PR check and independent release/package CI boundaries."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def _read(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def _events(content: str) -> str:
    return content.split("\non:\n", 1)[1].split("\njobs:\n", 1)[0]


def test_regular_pull_requests_do_not_build_three_os_installers():
    pkg = _read("desktop-packages.yml")
    events = _events(pkg)
    assert "workflow_dispatch:" in events
    assert 'tags:\n      - "v*"' in events
    assert "pull_request:" not in events
    assert "push:\n    branches:" not in events
    # Full sidecar/bundle builds must remain available as an explicit QA gate.
    assert "Build packaged sidecar" in pkg
    assert "Smoke packaged sidecar" in pkg
    assert "Build desktop package" in pkg


def test_ci_keeps_required_verify_context_and_fails_for_upstream_errors():
    ci = _read("ci.yml")
    assert "pull_request:" in _events(ci)
    assert "name: verify" in ci
    assert "needs: [changes, python, frontend, tauri]" in ci
    assert "if: ${{ always() }}" in ci
    assert 'test "$PYTHON_RESULT" = success' in ci
    assert 'test "$FRONTEND_RESULT" = success' in ci
    assert 'test "$TAURI_RESULT" = success' in ci
    assert 'test "$TAURI_RESULT" = skipped' in ci
    assert 'test "$CHANGES_RESULT" = success' in ci
    assert "git diff --name-only" in ci


def test_code_ci_runs_real_tests_but_not_packaging_or_duplicated_audits():
    ci = _read("ci.yml")
    assert "uv run --frozen pytest -q" in ci
    assert "ruff check src tests training scripts" in ci
    assert "npm run build" in ci
    assert "npm run test:e2e" in ci
    assert "cargo check --locked" in ci
    assert "cargo clippy --locked" in ci
    assert "if: github.event_name != 'pull_request'" in ci
    for expensive in ("cargo install cargo-audit", "pip-audit", "npm audit", "Build desktop package"):
        assert expensive not in ci


def test_registry_and_lock_audits_have_independent_triggers():
    audit = _read("dependency-security.yml")
    events = _events(audit)
    assert "schedule:" in events
    assert "workflow_dispatch:" in events
    assert "pull_request:" in events
    assert "push:\n    branches: [\"main\"]" in events
    assert '"desktop/package-lock.json"' in events
    assert '"desktop/src-tauri/Cargo.lock"' in events
    assert "npm audit --audit-level=high" in audit
    assert "cargo audit --file desktop/src-tauri/Cargo.lock" in audit

    python = _read("python-compatibility-audit.yml")
    python_events = _events(python)
    assert "schedule:" in python_events
    assert "pull_request:" in python_events
    assert "pyproject.toml" in python_events
    assert "uv.lock" in python_events
    assert ".github/workflows/ci.yml" not in python_events
    assert "pip-audit --strict" in python


def test_official_youtube_source_review_is_separate_and_never_redistributes_binaries():
    review = _read("youtube-official-native-review.yml")
    events = _events(review)
    assert "workflow_dispatch:" in events
    assert "review/youtube-official-native-smoke" in events
    assert "pull_request:" not in events
    assert "windows-2025" in review
    assert "macos-15" in review
    assert "--execute-native" in review
    assert "fetch_youtube_official_assets.py" in review
    assert "DOWNLOAD-EVIDENCE.pending.json" in review
    assert "SOURCE-EVIDENCE.pending.json" in review
    assert "upload-artifact" in review
    assert "Desktop Packages" not in review
    assert "tauri build" not in review
    assert "desktop-packages.yml" not in review
    assert "verified/*.exe" not in review
    assert "verified/*.zip" not in review

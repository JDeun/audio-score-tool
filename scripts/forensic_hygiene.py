from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_TRACKED_FILE_BYTES = 5 * 1024 * 1024

FORBIDDEN_TRACKED_PARTS = {
    ".DS_Store",
    "Thumbs.db",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".venv",
    "node_modules",
    "dist",
    "build",
    "work",
    "outputs",
    "target",
    ".coverage",
}
FORBIDDEN_TRACKED_SUFFIXES = {
    ".pyc", ".pyo", ".log", ".sqlite", ".sqlite3", ".db",
    ".pem", ".key", ".p12", ".pfx",
    ".wav", ".mp3", ".flac", ".m4a",
}
FORBIDDEN_SECRET_FILENAMES = {
    ".env",
    "id_rsa",
    "id_ed25519",
    "credentials.json",
    "service-account.json",
}
TEXT_SUFFIXES = {
    ".py", ".pyi", ".ts", ".tsx", ".js", ".jsx", ".json", ".toml", ".yml", ".yaml",
    ".md", ".txt", ".css", ".html", ".rs", ".sh", ".ps1", ".xml", ".svg", ".example",
}
MARKER_RE = re.compile(r"^(?:<{7}|={7}|>{7})(?:\s|$)", re.MULTILINE)
DEBT_RE = re.compile(r"\b(?:TODO|FIXME|HACK|XXX)\b", re.IGNORECASE)
ACTION_RE = re.compile(r"^\s*-?\s*uses:\s*([^\s#]+)", re.MULTILINE)
PINNED_ACTION_RE = re.compile(r"^[^@]+@[0-9a-fA-F]{40}$")
SECRET_PATTERNS = {
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "github-token": re.compile(r"\bgh[opusr]_[A-Za-z0-9]{30,}\b"),
    "aws-access-key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "slack-token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    "google-api-key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
}

CONTENT_SCAN_EXCLUDES = {
    "uv.lock",
    "desktop/package-lock.json",
    "desktop/src-tauri/Cargo.lock",
    "scripts/forensic_hygiene.py",
}
DEBT_SCAN_PREFIXES = ("src/", "scripts/", "training/", "desktop/src/", "desktop/src-tauri/src/")


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True, errors="replace")


def _tracked_files() -> list[str]:
    return [line for line in _git("ls-files").splitlines() if line]


def _is_text_candidate(path: str) -> bool:
    p = Path(path)
    return p.suffix.lower() in TEXT_SUFFIXES or p.name in {"Dockerfile", "Makefile"}


def audit_repository() -> list[str]:
    failures: list[str] = []
    tracked = _tracked_files()

    for path in tracked:
        p = Path(path)
        parts = set(p.parts)
        if parts & FORBIDDEN_TRACKED_PARTS or p.suffix.lower() in FORBIDDEN_TRACKED_SUFFIXES:
            failures.append(f"generated/runtime/credential artifact is tracked: {path}")
        if p.name in FORBIDDEN_SECRET_FILENAMES and p.name != ".env.example":
            failures.append(f"secret-bearing filename is tracked: {path}")
        try:
            size = (ROOT / path).stat().st_size
        except OSError:
            continue
        if size > MAX_TRACKED_FILE_BYTES:
            failures.append(f"oversized tracked file ({size} bytes > {MAX_TRACKED_FILE_BYTES}): {path}")

    for row in _git("ls-files", "-s").splitlines():
        fields = row.split(maxsplit=3)
        if len(fields) == 4 and fields[0] == "120000":
            failures.append(f"symlink is tracked (forbidden for release reproducibility): {fields[3]}")

    for path in tracked:
        if path in CONTENT_SCAN_EXCLUDES or not _is_text_candidate(path):
            continue
        file_path = ROOT / path
        try:
            text = file_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if MARKER_RE.search(text):
            failures.append(f"unresolved merge-conflict marker: {path}")
        if path.startswith(DEBT_SCAN_PREFIXES) and DEBT_RE.search(text):
            failures.append(f"unresolved debt marker (TODO/FIXME/HACK/XXX): {path}")
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                failures.append(f"secret-shaped content ({label}): {path}")
        if path.startswith(".github/workflows/"):
            for action in ACTION_RE.findall(text):
                if action.startswith("./"):
                    continue
                if not PINNED_ACTION_RE.fullmatch(action):
                    failures.append(f"GitHub Action is not pinned to a full commit SHA: {path}: {action}")

    history = _git(
        "log", "--all", "-p", "--no-ext-diff", "--", ".",
        ":(exclude)uv.lock",
        ":(exclude)desktop/package-lock.json",
        ":(exclude)desktop/src-tauri/Cargo.lock",
    )
    for label, pattern in SECRET_PATTERNS.items():
        if pattern.search(history):
            failures.append(f"secret-shaped content ({label}) exists in git history")

    return sorted(set(failures))


def main() -> int:
    failures = audit_repository()
    if failures:
        print("Repository forensic hygiene gate FAILED:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("Repository forensic hygiene gate passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

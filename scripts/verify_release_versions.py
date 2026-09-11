from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[1]


def release_versions(root: Path = ROOT) -> dict[str, str]:
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    cargo = tomllib.loads((root / "desktop/src-tauri/Cargo.toml").read_text(encoding="utf-8"))
    package = json.loads((root / "desktop/package.json").read_text(encoding="utf-8"))
    tauri = json.loads((root / "desktop/src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
    return {
        "python": str(pyproject["project"]["version"]),
        "npm": str(package["version"]),
        "cargo": str(cargo["package"]["version"]),
        "tauri": str(tauri["version"]),
    }


def verify_versions(*, tag: str | None = None, root: Path = ROOT) -> str:
    versions = release_versions(root)
    unique = set(versions.values())
    if len(unique) != 1:
        detail = ", ".join(f"{name}={version}" for name, version in versions.items())
        raise ValueError(f"release versions disagree: {detail}")
    version = next(iter(unique))
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", version):
        raise ValueError(f"unsupported release version: {version}")
    if tag is not None:
        expected = tag.removeprefix("v")
        if expected != version:
            raise ValueError(f"release tag/version mismatch: tag={tag}, version={version}")
    return version


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify AudioScoreTool release versions.")
    parser.add_argument("--tag", help="Optional release tag, for example v0.8.0")
    args = parser.parse_args()
    version = verify_versions(tag=args.tag)
    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

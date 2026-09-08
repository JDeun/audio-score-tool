from __future__ import annotations

import json
from pathlib import Path

ALLOWED_TRAINING_LICENSES = {
    "CC-BY-4.0",
    "CC0-1.0",
    "MIT",
    "Apache-2.0",
    "project-owned",
}


def load_manifest(path: Path, split: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            license_name = row.get("license", "")
            if license_name not in ALLOWED_TRAINING_LICENSES:
                raise ValueError(
                    f"Refusing training asset at line {line_number}: license={license_name!r}. "
                    "Only explicitly approved commercial-compatible assets may enter Native training."
                )
            if not row.get("audio") or not row.get("midi"):
                raise ValueError(f"Manifest line {line_number} must include audio and midi paths.")
            if row.get("split", "train") == split:
                rows.append(row)
    return rows

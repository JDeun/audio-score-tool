from __future__ import annotations

import json
import shutil
from pathlib import Path
from threading import Lock
from typing import Any

from .paths import app_data_dir
from .publication_layout import merged_publication_settings


class PublicationStore:
    def __init__(self, root: Path | None = None):
        self.root = root or (app_data_dir() / "songs")
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def path(self, song_id: str) -> Path:
        return self.root / song_id / "publication.json"

    def exists(self, song_id: str) -> bool:
        return self.path(song_id).exists()

    def read(self, song_id: str) -> dict[str, Any]:
        path = self.path(song_id)
        if not path.exists():
            return merged_publication_settings(None)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        return merged_publication_settings(payload if isinstance(payload, dict) else {})

    def write(self, song_id: str, settings: dict[str, Any]) -> dict[str, Any]:
        merged = merged_publication_settings(settings)
        path = self.path(song_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        with self._lock:
            temp.write_text(
                json.dumps(merged, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temp.replace(path)
        return merged

    def snapshot(self, song_id: str, revisions_dir: Path, revision: int) -> Path:
        revisions_dir.mkdir(parents=True, exist_ok=True)
        source = self.path(song_id)
        if not source.exists():
            self.write(song_id, self.read(song_id))
        target = revisions_dir / f"rev-{revision:04d}.publication.json"
        shutil.copy2(self.path(song_id), target)
        return target

    def restore_snapshot(
        self,
        song_id: str,
        revisions_dir: Path,
        revision: int,
    ) -> bool:
        source = revisions_dir / f"rev-{revision:04d}.publication.json"
        if not source.exists():
            return False
        target = self.path(song_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        source.unlink(missing_ok=True)
        return True

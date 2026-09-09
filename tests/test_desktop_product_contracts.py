from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "desktop"


def test_score_renderer_is_lazy_loaded_outside_initial_desktop_bundle():
    source = (DESKTOP / "src" / "SongWorkspace.tsx").read_text(encoding="utf-8")
    assert 'import { OpenSheetMusicDisplay } from "opensheetmusicdisplay"' not in source
    assert 'await import("opensheetmusicdisplay")' in source


def test_vector_app_icon_is_authoritative_for_local_and_ci_builds():
    icon = DESKTOP / "src-tauri" / "app-icon.svg"
    assert icon.is_file()
    assert "<svg" in icon.read_text(encoding="utf-8")

    package = json.loads((DESKTOP / "package.json").read_text(encoding="utf-8"))
    assert "tauri icon src-tauri/app-icon.svg" in package["scripts"]["desktop:build"]

    for workflow_name in ("desktop-packages.yml", "desktop-release.yml"):
        workflow = (ROOT / ".github" / "workflows" / workflow_name).read_text(encoding="utf-8")
        assert "tauri icon src-tauri/app-icon.svg" in workflow

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
    icon_text = icon.read_text(encoding="utf-8")
    assert "<svg" in icon_text
    assert "Audio waveform flowing into score lines" in icon_text
    assert "#1673F9" in icon_text

    package = json.loads((DESKTOP / "package.json").read_text(encoding="utf-8"))
    assert "tauri icon src-tauri/app-icon.svg" in package["scripts"]["desktop:build"]

    for workflow_name in ("desktop-packages.yml", "desktop-release.yml"):
        workflow = (ROOT / ".github" / "workflows" / workflow_name).read_text(encoding="utf-8")
        assert "tauri icon src-tauri/app-icon.svg" in workflow


def test_brand_mark_is_shared_by_product_shell_and_github_readme():
    mark = DESKTOP / "public" / "brand-mark.svg"
    assert mark.is_file()
    mark_text = mark.read_text(encoding="utf-8")
    assert "audio waveform flowing into three score lines" in mark_text.lower()
    assert "#1673F9" in mark_text
    assert "#4F5964" in mark_text

    aesthetic = (DESKTOP / "src" / "aesthetic-system.css").read_text(encoding="utf-8")
    assert 'background-image: url("/brand-mark.svg")' in aesthetic

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert 'docs/assets/audioscoretool-logo.svg' in readme
    assert (ROOT / "docs" / "assets" / "audioscoretool-logo.svg").is_file()

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_apache_notice_present_and_attributed():
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    notice = (ROOT / "NOTICE").read_text(encoding="utf-8")
    assert "Apache License" in license_text
    assert "Version 2.0" in license_text
    assert notice.startswith("AudioScoreTool\n")
    assert "JDeun and AudioScoreTool contributors" in notice
    assert "https://github.com/JDeun/audio-score-tool" in notice


def test_desktop_bundle_ships_original_license_and_notice():
    config = json.loads((ROOT / "desktop/src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
    bundle = config["bundle"]
    assert bundle["licenseFile"] == "../../LICENSE"
    assert bundle["resources"]["../../LICENSE"] == "legal/LICENSE"
    assert bundle["resources"]["../../NOTICE"] == "legal/NOTICE"
    for source in ("../../LICENSE", "../../NOTICE"):
        assert (ROOT / "desktop/src-tauri" / source).is_file()


def test_offline_notice_view_is_wired_into_settings():
    component = (ROOT / "desktop/src/LegalNotices.tsx").read_text(encoding="utf-8")
    workspace = (ROOT / "desktop/src/OperationsWorkspace.tsx").read_text(encoding="utf-8")
    assert 'from "../../LICENSE?raw"' in component
    assert 'from "../../NOTICE?raw"' in component
    assert "라이선스 및 출처 표시" in component
    assert 'import LegalNotices from "./LegalNotices";' in workspace
    assert "<LegalNotices />" in workspace

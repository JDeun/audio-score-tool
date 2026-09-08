from __future__ import annotations

from audio_score_tool import api_ext


def test_startup_diagnostics_exposes_latest_recovery_result():
    recovery = {
        "restored_exports": 1,
        "removed_export_backups": 2,
        "removed_staged_exports": 3,
        "removed_partial_uploads": 4,
        "removed_score_work_dirs": 5,
        "restored_staged_job_deletions": 6,
        "removed_staged_job_deletions": 7,
        "recovery_errors": 0,
    }

    with api_ext._startup_lock:
        previous = dict(api_ext._startup_diagnostics)
        api_ext._startup_diagnostics["recovery_completed"] = True
        api_ext._startup_diagnostics["recovery"] = recovery

    try:
        diagnostics = api_ext.startup_diagnostics()
        assert diagnostics["app_version"] == "0.8.0"
        assert diagnostics["recovery_completed"] is True
        assert diagnostics["recovery"] == recovery
    finally:
        with api_ext._startup_lock:
            api_ext._startup_diagnostics.clear()
            api_ext._startup_diagnostics.update(previous)

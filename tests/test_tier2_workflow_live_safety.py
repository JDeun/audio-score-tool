"""Protect the actual-model GitHub Actions workflow from non-starting jobs and media leaks.

These contracts complement live GitHub Actions validation: a successful code CI
alone does not prove the workflow was parsed, scheduled or ran a real model.
"""
from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/tier2-actual-models.yml")


def _read() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_gated_muscriptor_job_uses_runner_temp_only_inside_steps():
    content = _read().split("\n  muscriptor:\n", 1)[1]
    before_steps, step_body = content.split("\n    steps:\n", 1)
    # Runner context is unavailable at jobs.<job_id>.env evaluation time.
    # Referencing it there invalidates the *entire* workflow before any jobs.
    assert "runner.temp" not in before_steps
    assert "HF_TOKEN: ${{ secrets.HF_TOKEN }}" in before_steps
    assert "github.event_name == 'workflow_dispatch'" in before_steps
    assert "vars.ENABLE_MUSCRIPTOR == 'true'" in before_steps
    assert "inputs.youtube_url != ''" in before_steps
    assert 'echo "HF_HOME=$RUNNER_TEMP/ast-muscriptor-hf" >> "$GITHUB_ENV"' in step_body
    assert step_body.index("Isolate the Hugging Face cache") < step_body.index(
        "Explicitly fetch approved private weights"
    )


def test_external_user_audio_never_enters_public_amtscore_artifact():
    content = _read()
    amt = content.split("\n  amt:\n", 1)[1].split("\n  hybrid:\n", 1)[0]
    hybrid = content.split("\n  hybrid:\n", 1)[1].split("\n  muscriptor:\n", 1)[0]
    synthetic_upload = amt.split(
        "- name: Upload synthetic-only model output to the hybrid job", 1
    )[1].split("- name: Keep real-source inference evidence metadata-only", 1)[0]
    real_upload = amt.split(
        "- name: Keep real-source inference evidence metadata-only", 1
    )[1]
    assert "always() && inputs.youtube_url == ''" in synthetic_upload
    assert "out/**/*.mid" in synthetic_upload
    assert "out/**/*.musicxml" in synthetic_upload
    assert "always() && inputs.youtube_url != ''" in real_upload
    assert "out/${{ matrix.model }}/smoke-result.json" in real_upload
    assert "out/${{ matrix.model }}/managed-real-checkpoint.pending.json" in real_upload
    for forbidden in (".mid\n", ".musicxml\n", "out/**/*.json", "out/chords.wav"):
        assert forbidden not in real_upload
    # Hybrid needs detached MIDI/MusicXML and is consequently synthetic-only.
    assert "inputs.youtube_url == ''" in hybrid.split("\n    needs:", 1)[0]


def test_real_gated_muscriptor_only_uploads_metadata_evidence():
    content = _read().split("\n  muscriptor:\n", 1)[1]
    upload = content.split(
        "- name: Upload metadata-only MuScriptor research evidence", 1
    )[1]
    assert "out/muscriptor/verification.pending.json" in upload
    for disallowed in ("out/**/*.mid", "out/**/*.musicxml", "out/muscriptor/score"):
        assert disallowed not in upload
    assert "HF_TOKEN: ''" in content
    assert "scripts.run_muscriptor_source_qa" in content
    product_runner = Path("scripts/run_muscriptor_source_qa.py").read_text(encoding="utf-8")
    assert "MuScriptorEngine" in product_runner

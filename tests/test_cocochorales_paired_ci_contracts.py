"""Two actual MT3 models must share source pairs but not contaminated runtimes."""
from __future__ import annotations

from pathlib import Path

from scripts.fetch_pinned_mrmt3_checkpoint import CHECKPOINT_SHA256 as MR_SHA
from scripts.fetch_pinned_yourmt3_checkpoint import CHECKPOINT_SHA256 as YOUR_SHA

_WORKFLOW = Path(".github/workflows/cocochorales-real-mt3-benchmark.yml")


def test_paired_workflow_runs_both_models_on_identical_real_audio_and_midi_sources():
    text = _WORKFLOW.read_text(encoding="utf-8")
    assert "model: [mr_mt3, yourmt3]" in text
    assert "fail-fast: false" in text
    assert "ubuntu-24.04" in text
    assert "scripts.prepare_cocochorales_official_sample" in text
    assert "scripts.score_cocochorales_tiny" in text
    assert "scripts.aggregate_cocochorales_author_samples" in text
    assert "scripts.compare_cocochorales_models" in text
    assert "needs: real-model-reference" in text
    assert "four-ensemble-score.pending.json" in text
    assert text.count("string_track001010 brass_track049013 woodwind_track097010 random_track145011") == 2


def test_yourmt3_uses_pinned_space_digest_and_isolated_t5_dependencies():
    text = _WORKFLOW.read_text(encoding="utf-8")
    assert "scripts.fetch_pinned_yourmt3_checkpoint" in text
    assert "scripts.fetch_pinned_mrmt3_checkpoint" in text
    assert MR_SHA in text
    assert YOUR_SHA in text
    assert "TRANSFORMERS_VERSION=4.44.2" in text
    assert "TRANSFORMERS_VERSION=4.57.6" in text
    assert "AST_MT3_INFER_CMD: audio-score-mt3" in text
    assert "HF_HUB_OFFLINE: '1'" in text
    assert "TRANSFORMERS_OFFLINE: '1'" in text
    assert "--model \"$MT3_MODEL\"" in text
    assert "--device cpu" in text


def test_metadata_only_upload_stays_separate_from_private_models_and_scores():
    text = _WORKFLOW.read_text(encoding="utf-8")
    upload = text.split(
        "      - name: Upload metadata only, never music/MIDI/checkpoint/score/source ZIP",
        1,
    )[1].split("  pair-and-compare:", 1)[0]
    assert "coco-real-${{ matrix.model }}-evidence-pending" in upload
    for extension in (".zip", ".wav", ".mid", ".musicxml", ".pth", ".ckpt"):
        assert extension not in upload
    assert "model-source.pending.json" in upload
    assert "mt3-real-score.pending.json" in upload
    assert "four-ensemble-score.pending.json" in upload
    compare = text.split("  pair-and-compare:", 1)[1]
    assert "coco-real-mr_mt3-evidence-pending" in compare
    assert "coco-real-yourmt3-evidence-pending" in compare
    assert "head-to-head.pending.json" in compare
    assert "coco-mrmt3-yourmt3-same-source-comparison-pending" in compare

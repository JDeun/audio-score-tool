from pathlib import Path

from audio_score_tool.benchmark import (
    BenchmarkResult,
    configs_for_profile,
    write_reports,
)


def test_benchmark_profiles_are_stable():
    score = configs_for_profile("score")
    lyrics = configs_for_profile("lyrics")
    native = configs_for_profile("native")
    assert [c.muscriptor_model for c in score] == ["small", "medium", "large"]
    assert [c.whisperx_model for c in lyrics] == ["small", "medium", "large-v3"]
    assert [c.transcription_engine for c in score] == ["muscriptor"] * 3
    assert native[0].transcription_engine == "native"


def test_write_benchmark_reports(tmp_path: Path):
    rows = [
        BenchmarkResult(
            config="balanced",
            engine="muscriptor",
            muscriptor_model="medium",
            whisperx_model="small",
            skip_lyrics=False,
            wall_seconds=1.25,
            success=True,
            attached_ratio=0.95,
        )
    ]
    write_reports(tmp_path, rows)
    assert (tmp_path / "benchmark.json").exists()
    text = (tmp_path / "benchmark.csv").read_text(encoding="utf-8")
    assert "balanced" in text
    assert "muscriptor" in text
    assert "0.95" in text

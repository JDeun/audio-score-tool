from pathlib import Path

from audio_score_tool.benchmark import (
    BenchmarkResult,
    configs_for_profile,
    write_reports,
)


def test_benchmark_profiles_are_stable():
    score = configs_for_profile("score")
    lyrics = configs_for_profile("lyrics")
    yourmt3 = configs_for_profile("yourmt3")
    native = configs_for_profile("native")
    all_configs = configs_for_profile("all")

    assert [c.muscriptor_model for c in score] == ["small", "medium", "large"]
    assert [c.whisperx_model for c in lyrics] == ["small", "medium", "large-v3"]
    assert [c.transcription_engine for c in score] == ["muscriptor"] * 3
    assert {c.transcription_engine for c in yourmt3} == {"yourmt3"}
    assert native[0].transcription_engine == "native"
    assert any(c.transcription_engine == "yourmt3" for c in all_configs)


def test_write_benchmark_reports(tmp_path: Path):
    rows = [
        BenchmarkResult(
            config="yourmt3-score",
            engine="yourmt3",
            muscriptor_model="n/a",
            whisperx_model="small",
            skip_lyrics=True,
            wall_seconds=1.25,
            success=True,
            attached_ratio=None,
        )
    ]
    write_reports(tmp_path, rows)
    assert (tmp_path / "benchmark.json").exists()
    text = (tmp_path / "benchmark.csv").read_text(encoding="utf-8")
    assert "yourmt3-score" in text
    assert "yourmt3" in text

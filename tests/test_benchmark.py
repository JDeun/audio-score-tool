from pathlib import Path

from audio_score_tool.benchmark import (
    BenchmarkResult,
    configs_for_profile,
    write_reports,
)


def test_benchmark_profiles_are_stable():
    score = configs_for_profile("score")
    lyrics = configs_for_profile("lyrics")
    mt3 = configs_for_profile("mt3")
    mr_mt3 = configs_for_profile("mr_mt3")
    yourmt3 = configs_for_profile("yourmt3")
    native = configs_for_profile("native")
    all_configs = configs_for_profile("all")

    assert score[0].transcription_engine == "mt3_infer"
    assert score[0].mt3_model == "mr_mt3"
    assert any(c.transcription_engine == "muscriptor" for c in score)
    assert lyrics[0].mt3_model == "mr_mt3"
    assert {c.mt3_model for c in mt3} == {"mr_mt3", "yourmt3"}
    assert {c.mt3_model for c in mr_mt3} == {"mr_mt3"}
    assert {c.mt3_model for c in yourmt3} == {"yourmt3"}
    assert native[0].transcription_engine == "native"
    assert any(c.mt3_model == "mr_mt3" for c in all_configs)
    assert any(c.mt3_model == "yourmt3" for c in all_configs)


def test_write_benchmark_reports(tmp_path: Path):
    rows = [
        BenchmarkResult(
            config="mr-mt3-score",
            engine="mt3_infer",
            mt3_model="mr_mt3",
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
    assert "mr-mt3-score" in text
    assert "mt3_infer" in text
    assert "mr_mt3" in text

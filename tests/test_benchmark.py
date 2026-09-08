from pathlib import Path
from types import SimpleNamespace

import audio_score_tool.benchmark as benchmark_module
from audio_score_tool.benchmark import (
    BenchmarkResult,
    configs_for_profile,
    run_benchmark_matrix,
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


def test_benchmark_disables_canonical_source_asset_preservation(tmp_path: Path, monkeypatch):
    audio = tmp_path / "input.wav"
    audio.write_bytes(b"audio")
    captured: dict[str, object] = {}

    def fake_transcribe(_audio, output_root, **kwargs):
        captured.update(kwargs)
        work_dir = Path(output_root) / "input"
        work_dir.mkdir(parents=True)
        return SimpleNamespace(work_dir=work_dir, midi_path=work_dir / "score.mid")

    monkeypatch.setattr(benchmark_module, "transcribe", fake_transcribe)
    results = run_benchmark_matrix(
        audio,
        tmp_path / "benchmark",
        language=None,
        configs=[configs_for_profile("score")[0]],
    )

    assert results[0].success is True
    assert captured["preserve_source_audio"] is False

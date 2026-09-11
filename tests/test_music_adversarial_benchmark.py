from __future__ import annotations

from audio_score_tool.music_adversarial_benchmark import run_music_adversarial_benchmark


def test_music_adversarial_benchmark_meets_release_thresholds() -> None:
    report = run_music_adversarial_benchmark()
    failures = [case for case in report.cases if not case.passed]
    assert not failures, [(case.name, case.details) for case in failures]
    assert report.category_scores["music_start"] >= report.thresholds["music_start"]
    assert report.category_scores["meter_pickup"] >= report.thresholds["meter_pickup"]
    assert report.category_scores["choir"] >= report.thresholds["choir"]
    assert report.overall_score >= report.thresholds["overall"]
    assert report.passed


def test_music_adversarial_benchmark_is_deterministic() -> None:
    first = run_music_adversarial_benchmark().as_dict()
    second = run_music_adversarial_benchmark().as_dict()
    assert first == second

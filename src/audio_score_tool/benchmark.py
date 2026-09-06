from __future__ import annotations

import csv
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import Settings
from .pipeline import PipelineError, transcribe


@dataclass(frozen=True, slots=True)
class BenchmarkConfig:
    name: str
    muscriptor_model: str
    whisperx_model: str = "small"
    skip_lyrics: bool = False


@dataclass(slots=True)
class BenchmarkResult:
    config: str
    muscriptor_model: str
    whisperx_model: str
    skip_lyrics: bool
    wall_seconds: float
    success: bool
    attached_ratio: float | None = None
    error: str | None = None


SCORE_CONFIGS = [
    BenchmarkConfig("score-small", "small", skip_lyrics=True),
    BenchmarkConfig("score-medium", "medium", skip_lyrics=True),
    BenchmarkConfig("score-large", "large", skip_lyrics=True),
]

LYRICS_CONFIGS = [
    BenchmarkConfig("balanced", "medium", "small"),
    BenchmarkConfig("lyrics-medium", "medium", "medium"),
    BenchmarkConfig("quality", "large", "large-v3"),
]


def configs_for_profile(profile: str) -> list[BenchmarkConfig]:
    if profile == "score":
        return SCORE_CONFIGS
    if profile == "lyrics":
        return LYRICS_CONFIGS
    if profile == "all":
        return [*SCORE_CONFIGS, *LYRICS_CONFIGS]
    raise ValueError(f"Unknown benchmark profile: {profile}")


def _alignment_ratio(work_dir: Path) -> float | None:
    path = work_dir / "alignment.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    total = int(payload.get("lyric_token_count") or 0)
    attached = int(payload.get("attached_token_count") or 0)
    return attached / total if total else None


def run_benchmark_matrix(
    audio: Path,
    output_root: Path,
    *,
    language: str | None,
    configs: list[BenchmarkConfig],
) -> list[BenchmarkResult]:
    output_root.mkdir(parents=True, exist_ok=True)
    results: list[BenchmarkResult] = []

    for config in configs:
        started = time.perf_counter()
        target = output_root / config.name
        try:
            result = transcribe(
                audio,
                target,
                language=language,
                skip_lyrics=config.skip_lyrics,
                settings=Settings(
                    muscriptor_model=config.muscriptor_model,
                    whisperx_model=config.whisperx_model,
                ),
            )
            results.append(
                BenchmarkResult(
                    config=config.name,
                    muscriptor_model=config.muscriptor_model,
                    whisperx_model=config.whisperx_model,
                    skip_lyrics=config.skip_lyrics,
                    wall_seconds=time.perf_counter() - started,
                    success=True,
                    attached_ratio=_alignment_ratio(result.work_dir),
                )
            )
        except (PipelineError, OSError, ValueError) as exc:
            results.append(
                BenchmarkResult(
                    config=config.name,
                    muscriptor_model=config.muscriptor_model,
                    whisperx_model=config.whisperx_model,
                    skip_lyrics=config.skip_lyrics,
                    wall_seconds=time.perf_counter() - started,
                    success=False,
                    error=str(exc),
                )
            )

    write_reports(output_root, results)
    return results


def write_reports(output_root: Path, results: list[BenchmarkResult]) -> None:
    json_path = output_root / "benchmark.json"
    csv_path = output_root / "benchmark.csv"
    json_path.write_text(
        json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(results[0]).keys()) if results else [
            "config",
            "muscriptor_model",
            "whisperx_model",
            "skip_lyrics",
            "wall_seconds",
            "success",
            "attached_ratio",
            "error",
        ])
        writer.writeheader()
        for result in results:
            writer.writerow(asdict(result))

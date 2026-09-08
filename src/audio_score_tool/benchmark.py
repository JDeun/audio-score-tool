from __future__ import annotations

import csv
import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from threading import Event

from .config import Settings
from .metrics import evaluate_midi_files
from .pipeline import PipelineError, transcribe


@dataclass(frozen=True, slots=True)
class BenchmarkConfig:
    name: str
    transcription_engine: str = "mt3_infer"
    mt3_model: str = "mr_mt3"
    muscriptor_model: str = "medium"
    whisperx_model: str = "small"
    skip_lyrics: bool = False


@dataclass(slots=True)
class BenchmarkResult:
    config: str
    engine: str
    mt3_model: str
    muscriptor_model: str
    whisperx_model: str
    skip_lyrics: bool
    wall_seconds: float
    success: bool
    attached_ratio: float | None = None
    error: str | None = None
    note_precision: float | None = None
    note_recall: float | None = None
    note_f1: float | None = None
    onset_mae_ms: float | None = None
    offset_mae_ms: float | None = None
    instrument_precision: float | None = None
    instrument_recall: float | None = None
    instrument_f1: float | None = None


MR_MT3_CONFIGS = [
    BenchmarkConfig(name="mr-mt3-score", mt3_model="mr_mt3", skip_lyrics=True),
    BenchmarkConfig(name="mr-mt3-lyrics", mt3_model="mr_mt3", skip_lyrics=False),
]

YOURMT3_CONFIGS = [
    BenchmarkConfig(name="yourmt3-score", mt3_model="yourmt3", skip_lyrics=True),
    BenchmarkConfig(name="yourmt3-lyrics", mt3_model="yourmt3", skip_lyrics=False),
]

MUSCRIPTOR_SCORE_CONFIGS = [
    BenchmarkConfig(
        name="muscriptor-small",
        transcription_engine="muscriptor",
        muscriptor_model="small",
        skip_lyrics=True,
    ),
    BenchmarkConfig(
        name="muscriptor-medium",
        transcription_engine="muscriptor",
        muscriptor_model="medium",
        skip_lyrics=True,
    ),
    BenchmarkConfig(
        name="muscriptor-large",
        transcription_engine="muscriptor",
        muscriptor_model="large",
        skip_lyrics=True,
    ),
]

MUSCRIPTOR_LYRICS_CONFIGS = [
    BenchmarkConfig(
        name="muscriptor-balanced",
        transcription_engine="muscriptor",
        muscriptor_model="medium",
        whisperx_model="small",
    ),
    BenchmarkConfig(
        name="muscriptor-lyrics-medium",
        transcription_engine="muscriptor",
        muscriptor_model="medium",
        whisperx_model="medium",
    ),
    BenchmarkConfig(
        name="muscriptor-quality",
        transcription_engine="muscriptor",
        muscriptor_model="large",
        whisperx_model="large-v3",
    ),
]

NATIVE_CONFIGS = [
    BenchmarkConfig(
        name="native-score",
        transcription_engine="native",
        mt3_model="n/a",
        muscriptor_model="n/a",
        skip_lyrics=True,
    ),
]


def configs_for_profile(profile: str) -> list[BenchmarkConfig]:
    normalized = profile.strip().lower()
    if normalized == "score":
        return [MR_MT3_CONFIGS[0], YOURMT3_CONFIGS[0], *MUSCRIPTOR_SCORE_CONFIGS]
    if normalized == "lyrics":
        return [MR_MT3_CONFIGS[1], YOURMT3_CONFIGS[1], *MUSCRIPTOR_LYRICS_CONFIGS]
    if normalized in {"mt3", "mt3_infer"}:
        return [*MR_MT3_CONFIGS, *YOURMT3_CONFIGS]
    if normalized == "mr_mt3":
        return MR_MT3_CONFIGS
    if normalized == "yourmt3":
        return YOURMT3_CONFIGS
    if normalized == "muscriptor":
        return [*MUSCRIPTOR_SCORE_CONFIGS, *MUSCRIPTOR_LYRICS_CONFIGS]
    if normalized == "native":
        return NATIVE_CONFIGS
    if normalized == "all":
        return [
            *MR_MT3_CONFIGS,
            *YOURMT3_CONFIGS,
            *MUSCRIPTOR_SCORE_CONFIGS,
            *MUSCRIPTOR_LYRICS_CONFIGS,
        ]
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
    reference_midi: Path | None = None,
    base_settings: Settings | None = None,
    progress: Callable[[str, int], None] | None = None,
    cancel_event: Event | None = None,
) -> list[BenchmarkResult]:
    output_root.mkdir(parents=True, exist_ok=True)
    results: list[BenchmarkResult] = []

    total = max(1, len(configs))
    base = base_settings or Settings()

    for index, config in enumerate(configs):
        if cancel_event is not None and cancel_event.is_set():
            break
        if progress is not None:
            progress(f"benchmark:{config.name}", int(index / total * 100))
        started = time.perf_counter()
        target = output_root / config.name
        try:
            result = transcribe(
                audio,
                target,
                language=language,
                skip_lyrics=config.skip_lyrics,
                settings=replace(
                    base,
                    transcription_engine=config.transcription_engine,
                    mt3_model=config.mt3_model,
                    muscriptor_model=config.muscriptor_model,
                    whisperx_model=config.whisperx_model,
                ),
                cancel_event=cancel_event,
                progress=(
                    (
                        lambda stage, percent, i=index, name=config.name: progress(
                            f"benchmark:{name}:{stage}",
                            min(99, int((i + percent / 100) / total * 100)),
                        )
                    )
                    if progress is not None
                    else None
                ),
            )
            metrics = (
                evaluate_midi_files(result.midi_path, reference_midi)
                if reference_midi is not None
                else None
            )
            results.append(
                BenchmarkResult(
                    config=config.name,
                    engine=config.transcription_engine,
                    mt3_model=config.mt3_model,
                    muscriptor_model=config.muscriptor_model,
                    whisperx_model=config.whisperx_model,
                    skip_lyrics=config.skip_lyrics,
                    wall_seconds=time.perf_counter() - started,
                    success=True,
                    attached_ratio=_alignment_ratio(result.work_dir),
                    note_precision=metrics.precision if metrics else None,
                    note_recall=metrics.recall if metrics else None,
                    note_f1=metrics.f1 if metrics else None,
                    onset_mae_ms=metrics.onset_mae_ms if metrics else None,
                    offset_mae_ms=metrics.offset_mae_ms if metrics else None,
                    instrument_precision=metrics.instrument_precision if metrics else None,
                    instrument_recall=metrics.instrument_recall if metrics else None,
                    instrument_f1=metrics.instrument_f1 if metrics else None,
                )
            )
        except (PipelineError, OSError, ValueError) as exc:
            results.append(
                BenchmarkResult(
                    config=config.name,
                    engine=config.transcription_engine,
                    mt3_model=config.mt3_model,
                    muscriptor_model=config.muscriptor_model,
                    whisperx_model=config.whisperx_model,
                    skip_lyrics=config.skip_lyrics,
                    wall_seconds=time.perf_counter() - started,
                    success=False,
                    error=str(exc),
                )
            )
            if cancel_event is not None and cancel_event.is_set():
                break

    if progress is not None:
        progress("benchmark:complete", 100)
    write_reports(output_root, results)
    return results


def write_reports(output_root: Path, results: list[BenchmarkResult]) -> None:
    json_path = output_root / "benchmark.json"
    csv_path = output_root / "benchmark.csv"
    json_path.write_text(
        json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    fallback_fields = [
        "config",
        "engine",
        "mt3_model",
        "muscriptor_model",
        "whisperx_model",
        "skip_lyrics",
        "wall_seconds",
        "success",
        "attached_ratio",
        "error",
        "note_precision",
        "note_recall",
        "note_f1",
        "onset_mae_ms",
        "offset_mae_ms",
        "instrument_precision",
        "instrument_recall",
        "instrument_f1",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(asdict(results[0]).keys()) if results else fallback_fields,
        )
        writer.writeheader()
        for result in results:
            writer.writerow(asdict(result))

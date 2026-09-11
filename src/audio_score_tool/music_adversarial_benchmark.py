from __future__ import annotations

import json
import math
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

import mido
import numpy as np
from music21 import chord, meter, note, stream

from .choir_postprocess import reconstruct_satb
from .music_structure import (
    MusicStructureAnalysis,
    analyze_midi_meter_and_pickup,
    estimate_music_start,
)


@dataclass(frozen=True, slots=True)
class AdversarialCaseResult:
    name: str
    category: str
    passed: bool
    score: float
    details: dict[str, object]


@dataclass(frozen=True, slots=True)
class AdversarialBenchmarkReport:
    schema_version: int
    cases: tuple[AdversarialCaseResult, ...]
    category_scores: dict[str, float]
    overall_score: float
    passed: bool
    thresholds: dict[str, float]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "cases": [asdict(case) for case in self.cases],
            "category_scores": self.category_scores,
            "overall_score": self.overall_score,
            "passed": self.passed,
            "thresholds": self.thresholds,
        }


_DEFAULT_THRESHOLDS = {
    "music_start": 0.75,
    "meter_pickup": 0.80,
    "choir": 0.80,
    "overall": 0.82,
}


def _tone(
    sample_rate: int,
    seconds: float,
    frequencies: tuple[float, ...],
    amplitude: float = 0.35,
) -> np.ndarray:
    count = max(1, int(round(sample_rate * seconds)))
    time = np.arange(count, dtype=np.float64) / sample_rate
    value = np.zeros(count, dtype=np.float64)
    for frequency in frequencies:
        value += np.sin(2.0 * math.pi * frequency * time)
    value /= max(1, len(frequencies))
    pulse = 0.62 + 0.38 * (np.sin(2.0 * math.pi * 2.0 * time) ** 2)
    fade = np.minimum(
        1.0,
        np.arange(count, dtype=np.float64) / max(1.0, sample_rate * 0.08),
    )
    return (value * pulse * fade * amplitude).astype(np.float32)


def _speech_like(sample_rate: int, seconds: float) -> np.ndarray:
    """Deterministic, non-periodic intro used to test conservative trimming."""

    count = max(1, int(round(sample_rate * seconds)))
    rng = np.random.default_rng(20260911)
    noise = rng.normal(0.0, 0.055, count)
    time = np.arange(count, dtype=np.float64) / sample_rate
    envelope = 0.25 + 0.75 * (np.sin(2.0 * math.pi * 1.7 * time) ** 8)
    return (noise * envelope).astype(np.float32)


def _score_timing(expected: float, actual: float, tolerance: float) -> float:
    error = abs(expected - actual)
    return max(0.0, 1.0 - error / max(tolerance, 1e-9))


def _music_start_cases() -> list[AdversarialCaseResult]:
    rate = 22_050
    music = _tone(rate, 9.0, (220.0, 329.63, 440.0))
    cases: list[AdversarialCaseResult] = []

    immediate, confidence = estimate_music_start(music, rate)
    score = _score_timing(0.0, immediate, 1.5)
    cases.append(
        AdversarialCaseResult(
            name="immediate-music-no-false-trim",
            category="music_start",
            passed=immediate <= 1.5,
            score=score,
            details={
                "expected_seconds": 0.0,
                "actual_seconds": round(immediate, 3),
                "confidence": round(confidence, 3),
            },
        )
    )

    delayed = np.concatenate([np.zeros(rate * 5, dtype=np.float32), music])
    detected, confidence = estimate_music_start(delayed, rate)
    score = _score_timing(5.0, detected, 2.0)
    cases.append(
        AdversarialCaseResult(
            name="five-second-silent-intro",
            category="music_start",
            passed=abs(detected - 5.0) <= 2.0 and confidence >= 0.55,
            score=score,
            details={
                "expected_seconds": 5.0,
                "actual_seconds": round(detected, 3),
                "confidence": round(confidence, 3),
            },
        )
    )

    ambiguous = np.concatenate([_speech_like(rate, 4.0), music])
    detected, confidence = estimate_music_start(ambiguous, rate)
    safe = detected == 0.0 or detected >= 2.8
    transition_score = 1.0 if detected == 0.0 else _score_timing(4.0, detected, 2.0)
    cases.append(
        AdversarialCaseResult(
            name="speech-like-intro-fail-safe",
            category="music_start",
            passed=safe,
            score=transition_score if safe else 0.0,
            details={
                "expected_transition_seconds": 4.0,
                "actual_seconds": round(detected, 3),
                "confidence": round(confidence, 3),
            },
        )
    )
    return cases


def _simple_midi(
    path: Path,
    *,
    numerator: int,
    denominator: int,
    pickup_quarters: float,
) -> None:
    """Create accent-heavy MIDI with a predictable metrical phase."""

    mid = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(
        mido.MetaMessage(
            "time_signature",
            numerator=numerator,
            denominator=denominator,
            time=0,
        )
    )
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(120), time=0))
    beat_ticks = int(round(mid.ticks_per_beat * 4.0 / denominator))
    pickup_ticks = int(round(pickup_quarters * mid.ticks_per_beat))
    if pickup_ticks:
        track.append(mido.Message("note_on", note=69, velocity=42, time=0))
        elapsed_to_downbeat = pickup_ticks
    else:
        elapsed_to_downbeat = 0

    for _bar in range(8):
        track.append(
            mido.Message(
                "note_on",
                note=60,
                velocity=124,
                time=elapsed_to_downbeat,
            )
        )
        for beat in range(1, numerator):
            track.append(
                mido.Message(
                    "note_on",
                    note=64 + beat,
                    velocity=54,
                    time=beat_ticks,
                )
            )
        elapsed_to_downbeat = beat_ticks
    mid.save(path)


def _meter_pickup_cases(root: Path) -> list[AdversarialCaseResult]:
    definitions = (
        ("four-four-no-pickup", 4, 4, 0.0, 0.45),
        ("four-four-quarter-pickup", 4, 4, 1.0, 0.55),
        ("three-four-no-pickup", 3, 4, 0.0, 0.45),
        ("three-four-eighth-pickup", 3, 4, 0.5, 0.55),
    )
    results: list[AdversarialCaseResult] = []
    for name, numerator, denominator, pickup, tolerance in definitions:
        midi_path = root / f"{name}.mid"
        _simple_midi(
            midi_path,
            numerator=numerator,
            denominator=denominator,
            pickup_quarters=pickup,
        )
        analysis = analyze_midi_meter_and_pickup(
            midi_path,
            MusicStructureAnalysis(),
        )
        pickup_score = _score_timing(
            pickup,
            analysis.pickup_quarters,
            tolerance,
        )
        meter_ok = (
            analysis.meter_numerator == numerator
            and analysis.meter_denominator == denominator
        )
        passed = meter_ok and abs(analysis.pickup_quarters - pickup) <= tolerance
        results.append(
            AdversarialCaseResult(
                name=name,
                category="meter_pickup",
                passed=passed,
                score=(pickup_score * 0.75 + (0.25 if meter_ok else 0.0)),
                details={
                    "expected_meter": f"{numerator}/{denominator}",
                    "actual_meter": (
                        f"{analysis.meter_numerator}/{analysis.meter_denominator}"
                    ),
                    "expected_pickup_quarters": pickup,
                    "actual_pickup_quarters": analysis.pickup_quarters,
                    "confidence": analysis.pickup_confidence,
                },
            )
        )
    return results


def _write_four_part_score(path: Path) -> None:
    score = stream.Score()
    voice_pitches = ((76, 79), (67, 69), (57, 60), (43, 48))
    for index, pair in enumerate(voice_pitches):
        part = stream.Part(id=f"voice-{index}")
        measure = stream.Measure(number=1)
        measure.insert(0, meter.TimeSignature("4/4"))
        for offset in range(4):
            created = note.Note(pair[offset % 2], quarterLength=1)
            measure.insert(offset, created)
        part.append(measure)
        score.append(part)
    score.write("musicxml", fp=str(path))


def _write_chordal_score(path: Path, *, monophonic: bool = False) -> None:
    score = stream.Score()
    part = stream.Part(id="mixed-choir")
    for measure_number in range(1, 5):
        measure = stream.Measure(number=measure_number)
        if measure_number == 1:
            measure.insert(0, meter.TimeSignature("4/4"))
        for offset in range(4):
            if monophonic:
                item = note.Note(64 + offset % 2, quarterLength=1)
            else:
                item = chord.Chord([48, 57, 64, 72], quarterLength=1)
            measure.insert(offset, item)
        part.append(measure)
    score.append(part)
    score.write("musicxml", fp=str(path))


def _stable_choir_details(result: object) -> dict[str, object]:
    """Keep benchmark output deterministic by excluding ephemeral filesystem paths."""

    payload = result.as_dict()  # type: ignore[attr-defined]
    payload.pop("output_path", None)
    return payload


def _choir_cases(root: Path) -> list[AdversarialCaseResult]:
    results: list[AdversarialCaseResult] = []

    source = root / "four-parts.musicxml"
    output = root / "four-parts-satb.musicxml"
    _write_four_part_score(source)
    result = reconstruct_satb(source, output, mode="auto")
    passed = (
        result.applied
        and result.source_parts == 4
        and result.confidence >= 0.80
        and output.exists()
    )
    results.append(
        AdversarialCaseResult(
            name="four-part-range-ordering",
            category="choir",
            passed=passed,
            score=min(1.0, result.confidence) if passed else 0.0,
            details=_stable_choir_details(result),
        )
    )

    source = root / "chordal.musicxml"
    output = root / "chordal-satb.musicxml"
    _write_chordal_score(source)
    result = reconstruct_satb(source, output, mode="auto")
    passed = (
        result.applied
        and result.target_parts == 4
        and result.confidence >= 0.72
        and output.exists()
    )
    results.append(
        AdversarialCaseResult(
            name="single-part-dense-polyphony",
            category="choir",
            passed=passed,
            score=min(1.0, result.confidence) if passed else 0.0,
            details=_stable_choir_details(result),
        )
    )

    source = root / "monophonic.musicxml"
    output = root / "monophonic-satb.musicxml"
    _write_chordal_score(source, monophonic=True)
    result = reconstruct_satb(source, output, mode="auto")
    passed = not result.applied and result.confidence < 0.45
    results.append(
        AdversarialCaseResult(
            name="monophonic-fail-open",
            category="choir",
            passed=passed,
            score=1.0 if passed else 0.0,
            details=_stable_choir_details(result),
        )
    )
    return results


def run_music_adversarial_benchmark(
    *,
    thresholds: dict[str, float] | None = None,
) -> AdversarialBenchmarkReport:
    limits = {**_DEFAULT_THRESHOLDS, **(thresholds or {})}
    with tempfile.TemporaryDirectory(prefix="ast-music-adversarial-") as temp:
        root = Path(temp)
        cases = [
            *_music_start_cases(),
            *_meter_pickup_cases(root),
            *_choir_cases(root),
        ]

    category_scores: dict[str, float] = {}
    for category in ("music_start", "meter_pickup", "choir"):
        selected = [case.score for case in cases if case.category == category]
        category_scores[category] = round(sum(selected) / max(1, len(selected)), 4)
    overall = round(sum(case.score for case in cases) / max(1, len(cases)), 4)
    passed = all(case.passed for case in cases)
    passed = passed and all(
        category_scores[name] >= limits[name] for name in category_scores
    )
    passed = passed and overall >= limits["overall"]
    return AdversarialBenchmarkReport(
        schema_version=1,
        cases=tuple(cases),
        category_scores=category_scores,
        overall_score=overall,
        passed=passed,
        thresholds=limits,
    )


def write_music_adversarial_report(
    path: Path,
    report: AdversarialBenchmarkReport,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.as_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

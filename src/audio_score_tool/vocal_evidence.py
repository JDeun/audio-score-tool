"""Octave-sensitive observations from a vocal waveform; never a score editor."""
from __future__ import annotations

import math
import tempfile
from pathlib import Path

import numpy as np

from .audio_symbol_validation import AudioSymbolValidationError, _decode_to_wav, _read_pcm16
from .score_timing import score_time_clocks


def pitch_track(audio: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray]:
    """YIN difference minima, with silence/aperiodicity and stable-note abstention.

    shortcut: monophonic vocal evidence can confuse bleed/harmonies; never certify
    full-mix transcription or automatically change octaves from these observations.
    """
    if sr <= 0 or audio.ndim != 1 or not np.all(np.isfinite(audio)):
        raise ValueError("Invalid vocal waveform")
    size, hop = 2048, 256
    low, high = max(2, math.floor(sr / 880)), min(size // 2, math.ceil(sr / 55))
    times, pitches = [], []
    for start in range(0, len(audio) - size + 1, hop):
        x = audio[start:start + size].astype(np.float64)
        x -= x.mean()
        times.append((start + size / 2) / sr)
        pitches.append(float("nan"))
        if np.sqrt(np.mean(x * x)) < 0.01:
            continue
        spectrum = np.fft.rfft(x, n=2 * size)
        corr = np.fft.irfft(spectrum * spectrum.conj(), n=2 * size)[:high + 1]
        energy = np.concatenate(([0.0], np.cumsum(x * x)))
        lags = np.arange(1, high + 1)
        difference = np.maximum(0, energy[size - lags] + energy[size] - energy[lags] - 2 * corr[1:])
        normalized = np.ones(high + 1)
        normalized[1:] = difference * lags / np.maximum(np.cumsum(difference), 1e-15)
        candidates = np.flatnonzero(normalized[low:high] < 0.1) + low
        if not len(candidates):
            continue
        lag = int(candidates[0])
        while lag + 1 <= high and normalized[lag + 1] < normalized[lag]:
            lag += 1
        refined = float(lag)
        if 1 <= lag < high:
            left, mid, right = normalized[lag - 1:lag + 2]
            curvature = left - 2 * mid + right
            if curvature > 1e-12:
                refined += float(np.clip(0.5 * (left - right) / curvature, -0.5, 0.5))
        pitches[-1] = 69 + 12 * math.log2(sr / refined / 440)
    return np.asarray(times), np.asarray(pitches)


def vocal_pitch_track(source: Path, *, ffmpeg_cmd: str) -> tuple[np.ndarray, np.ndarray]:
    with tempfile.TemporaryDirectory(prefix="ast-vocal-evidence-") as folder:
        wav = _decode_to_wav(source, Path(folder) / "vocal.wav", ffmpeg_cmd)
        audio, rate = _read_pcm16(wav)
    # The decoder fixes 22050Hz; pairwise averaging avoids an extra resampler dependency.
    usable = audio[:len(audio) // 2 * 2]
    return pitch_track(usable.reshape(-1, 2).mean(axis=1), rate // 2)


def part_notes(score, part, *, origin_seconds: float = 0.0) -> list[dict]:
    from music21 import note

    seconds, _ = score_time_clocks(score)
    merged = part.stripTies(inPlace=False)
    result = []
    for item in merged.recurse().notes:
        if not isinstance(item, note.Note) or item.duration.isGrace:
            continue
        at = float(item.getOffsetInHierarchy(merged))
        end = at + float(item.quarterLength)
        if end <= at:
            continue
        result.append({"pitch": int(item.pitch.midi), "start_seconds": origin_seconds + seconds(at),
                       "end_seconds": origin_seconds + seconds(end),
                       "measure": str(item.measureNumber) if item.measureNumber is not None else None})
    return result


def compare_notes(notes: list[dict], times: np.ndarray, pitches: np.ndarray) -> dict:
    """Count only stable, sufficiently covered note interiors; no octave folding."""
    if times.shape != pitches.shape or times.ndim != 1 or not np.all(np.isfinite(times)):
        raise ValueError("Invalid vocal pitch track")
    observations = []
    for event in notes:
        start, end = event["start_seconds"], event["end_seconds"]
        if (not math.isfinite(start) or not math.isfinite(end) or end <= start
                or type(event["pitch"]) is not int or not 0 <= event["pitch"] <= 127):
            raise ValueError("Invalid scored vocal event")
        inside = (times >= start + 0.025) & (times <= end - 0.025)
        selected = pitches[inside]
        finite = selected[np.isfinite(selected)]
        if len(finite) < 4 or len(finite) < 0.6 * len(selected):
            continue
        observed = float(np.median(finite))
        if float(np.median(np.abs(finite - observed))) > 0.35:
            continue
        difference = event["pitch"] - observed
        matched = abs(difference) <= 0.5
        octave = not matched and abs(difference) >= 11.5 and abs(difference - 12 * round(difference / 12)) <= 0.5
        observations.append({**event, "observed_midi": round(observed, 3),
                             "difference_semitones": round(difference, 3),
                             "category": "consistent" if matched else "octave" if octave else "pitch",
                             "frames": len(finite)})
    return {"predicted_notes": len(notes), "compared_notes": len(observations),
            "consistent_notes": sum(x["category"] == "consistent" for x in observations),
            "octave_suspects": sum(x["category"] == "octave" for x in observations),
            "pitch_suspects": sum(x["category"] == "pitch" for x in observations),
            "observations": observations, "whole_song_accuracy": None,
            "policy": {"advisory": True, "auto_edit": False, "reference_is_expert_ground_truth": False}}


def select_vocal_part(score_path: Path, vocal_audio: Path, *, ffmpeg_cmd: str) -> tuple[int, dict]:
    """Select by absolute acoustic pitch support; refuse unresolved competing parts."""
    from music21 import converter

    score = converter.parse(str(score_path))
    times, pitches = vocal_pitch_track(vocal_audio, ffmpeg_cmd=ffmpeg_cmd)
    finite = np.isfinite(pitches)
    if np.count_nonzero(finite) < 8:
        raise AudioSymbolValidationError("주선율을 고를 안정적인 보컬 음높이 근거가 부족합니다.")
    candidates = []
    for index, part in enumerate(score.parts):
        notes = part_notes(score, part)
        support = np.zeros(len(times), dtype=bool)
        for event in notes:
            support |= ((times >= event["start_seconds"]) & (times < event["end_seconds"])
                        & (np.abs(pitches - event["pitch"]) <= 0.5))
        candidates.append({"part_index": index, "support": float(support.sum() / finite.sum()),
                           **{k: v for k, v in compare_notes(notes, times, pitches).items()
                              if k not in {"observations", "policy"}}})
    ranked = sorted(candidates, key=lambda row: row["support"], reverse=True)
    if (not ranked or ranked[0]["support"] < 0.5 or ranked[0]["consistent_notes"] < 2
            or len(ranked) > 1 and ranked[0]["support"] - ranked[1]["support"] < 0.15):
        raise AudioSymbolValidationError("여러 파트 중 보컬 주선율을 확정할 근거가 부족합니다. 음표 수로 대체 선택하지 않았습니다.")
    return ranked[0]["part_index"], {
        "provider": "vocal_waveform_yin_v1", "candidates": candidates,
        "selected_part_index": ranked[0]["part_index"],
        "policy": {"octave_folding": False, "note_count_selection": False,
                   "ambiguous_selection": "refuse", "quality_approved": False},
    }

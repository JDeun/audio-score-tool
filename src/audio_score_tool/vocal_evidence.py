"""Octave-sensitive observations from a vocal waveform; never a score editor."""
from __future__ import annotations

import math
import tempfile
from pathlib import Path

import numpy as np

from .audio_symbol_validation import AudioSymbolValidationError, _decode_to_wav, _read_pcm16
from .midi_ties import prepare_score_for_midi
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

    performed = prepare_score_for_midi(score)
    seconds, _ = score_time_clocks(performed)
    merged = performed.parts[list(score.parts).index(part)]
    result = []
    for item in merged.recurse().notes:
        if (not isinstance(item, note.Note) or item.duration.isGrace
                or item.editorial.get("source_harmony", False)):
            continue
        at = float(item.getOffsetInHierarchy(merged))
        end = at + float(item.quarterLength)
        if end <= at:
            continue
        measure = item.editorial.get("source_measure")
        result.append({"pitch": int(item.pitch.midi), "start_seconds": origin_seconds + seconds(at),
                       "end_seconds": origin_seconds + seconds(end),
                       "measure": str(measure) if measure is not None else None})
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


def select_vocal_part(score_path: Path, vocal_audio: Path, *, ffmpeg_cmd: str, pitch_track=None) -> tuple[int, dict]:
    """Select by absolute acoustic pitch support; refuse unresolved competing parts."""
    from music21 import converter

    score = converter.parse(str(score_path))
    times, pitches = pitch_track if pitch_track is not None else vocal_pitch_track(vocal_audio, ffmpeg_cmd=ffmpeg_cmd)
    finite = np.isfinite(pitches)
    if np.count_nonzero(finite) < 8:
        raise AudioSymbolValidationError("주선율을 고를 안정적인 보컬 음높이 근거가 부족합니다.")
    candidates = []
    for index, part in enumerate(score.parts):
        notes = part_notes(score, part)
        support = np.zeros(len(times), dtype=bool)
        activity = np.zeros(len(times), dtype=np.int32)
        for event in notes:
            active = (times >= event["start_seconds"]) & (times < event["end_seconds"])
            activity += active
            support |= active & (np.abs(pitches - event["pitch"]) <= 0.5)
        coverage = float(support.sum() / finite.sum())
        precision = float(support.sum() / activity[finite].sum()) if activity[finite].sum() else 0.0
        fit = 2 * precision * coverage / (precision + coverage) if precision + coverage else 0.0
        candidates.append({"part_index": index, "support": fit,
                           "voiced_frame_coverage": coverage, "voiced_frame_precision": precision,
                           **{k: v for k, v in compare_notes(notes, times, pitches).items()
                              if k not in {"observations", "policy"}}})
    ranked = sorted(candidates, key=lambda row: row["support"], reverse=True)
    if (not ranked or ranked[0]["support"] < 0.5 or ranked[0]["consistent_notes"] < 2
            or len(ranked) > 1 and ranked[0]["support"] - ranked[1]["support"] < 0.15):
        raise AudioSymbolValidationError("여러 파트 중 보컬 주선율을 확정할 근거가 부족합니다. 음표 수로 대체 선택하지 않았습니다.")
    return ranked[0]["part_index"], {
        "provider": "vocal_waveform_torchcrepe_tiny_v1" if pitch_track is not None else "vocal_waveform_yin_v2", "candidates": candidates,
        "selected_part_index": ranked[0]["part_index"],
        "policy": {"octave_folding": False, "note_count_selection": False,
                   "ambiguous_selection": "refuse", "quality_approved": False,
                   "support_is_note_accuracy": False},
    }


def fixed_tiny_pitch_track(source: Path, output: Path, *, settings, cancel_event=None) -> tuple[tuple[np.ndarray, np.ndarray], dict]:
    """Run the pinned external verifier and validate its bounded observation."""
    import hashlib
    import json
    import zipfile

    from .runner import run_command

    run_command(settings.fixed_vocal_cmd, ['pitch', source, output, '--snapshot', settings.fixed_lead_snapshot],
                timeout_seconds=1800, cancel_event=cancel_event, env={'PYTHONHASHSEED': '0', 'OMP_NUM_THREADS': '2', 'MKL_NUM_THREADS': '2'})
    receipt_path = output.with_suffix('.runtime.json')
    if (output.is_symlink() or receipt_path.is_symlink() or not output.is_file() or not receipt_path.is_file()
            or output.stat().st_size > 16 * 1024 * 1024 or receipt_path.stat().st_size > 65536):
        raise ValueError('Missing or unsafe fixed pitch observation')
    receipt = json.loads(receipt_path.read_text())
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()
    if (not isinstance(receipt, dict) or not isinstance(receipt.get('runtime'), dict)
            or receipt.get('provider') != 'torchcrepe' or receipt.get('model') != 'tiny'
            or receipt.get('source_sha256') != digest(source) or receipt.get('prediction_sha256') != digest(output)
            or receipt.get('checkpoint_sha256') != 'd4993eea36ed1a0ad9ac549c740dae5265b049ce72004f00c2f59e01c0be8432'
            or any(receipt.get(k) != v for k, v in {'device': 'cpu', 'threads': 2, 'seed': 0,
                'sample_rate': 16000, 'hop': 160, 'fmin': 55, 'fmax': 880, 'decoder': 'viterbi',
                'batch_size': 128, 'pad': True, 'periodicity_threshold': .21, 'silence_db': -60}.items())
            or any(receipt.get('runtime', {}).get(k) != v for k, v in {
                'torchcrepe': '0.0.24', 'resampy': '0.4.3', 'librosa': '0.11.0'}.items())):
        raise ValueError('Fixed pitch observation provenance mismatch')
    try:
        with zipfile.ZipFile(output) as archive:
            members = archive.infolist()
            if sorted(x.filename for x in members) != ['hz.npy', 'times.npy'] or sum(x.file_size for x in members) > 32 * 1024 * 1024:
                raise ValueError('Invalid or oversized fixed pitch arrays')
        with np.load(output, allow_pickle=False) as data:
            times, hz = np.asarray(data['times']), np.asarray(data['hz'])
    except (OSError, EOFError, zipfile.BadZipFile) as exc:
        raise ValueError('Invalid fixed pitch archive') from exc
    if (times.ndim != 1 or hz.ndim != 1 or times.shape != hz.shape or not len(times)
            or times.dtype.kind not in 'fi' or hz.dtype.kind not in 'fi'
            or not np.isfinite(times).all() or not np.isfinite(hz).all()
            or times[0] < 0 or np.any(np.diff(times) <= 0) or np.any(hz < 0)
            or np.any((hz > 0) & ((hz < 55) | (hz > 880)))):
        raise ValueError('Invalid fixed pitch track')
    pitches = np.full(hz.shape, np.nan, dtype=float)
    voiced = hz > 0
    pitches[voiced] = 69 + 12 * np.log2(hz[voiced] / 440)
    return (times, pitches), receipt

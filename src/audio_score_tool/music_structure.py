from __future__ import annotations

import json
import math
import wave
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import Event

import mido
import numpy as np

from .config import Settings
from .runner import CommandCancelled, CommandError, command_exists, run_command


@dataclass(slots=True)
class MusicStructureAnalysis:
    media_start_seconds: float = 0.0
    music_start_seconds: float = 0.0
    first_downbeat_seconds: float | None = None
    pickup_quarters: float = 0.0
    meter_numerator: int = 4
    meter_denominator: int = 4
    tempo_bpm: float | None = None
    start_confidence: float = 0.0
    pickup_confidence: float = 0.0
    trimmed: bool = False
    method: str = "none"
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _decode_analysis_wav(
    audio_path: Path,
    output_path: Path,
    *,
    settings: Settings,
    cancel_event: Event | None,
) -> bool:
    if not command_exists(settings.ffmpeg_cmd):
        return audio_path.suffix.lower() == ".wav"
    try:
        run_command(
            settings.ffmpeg_cmd,
            [
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                audio_path,
                "-vn",
                "-ac",
                "1",
                "-ar",
                "22050",
                "-c:a",
                "pcm_s16le",
                output_path,
            ],
            cancel_event=cancel_event,
            timeout_seconds=600,
            max_output_bytes=2 * 1024 * 1024,
        )
        return output_path.is_file()
    except CommandCancelled:
        raise
    except CommandError:
        return False


def _read_mono_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as source:
        channels = source.getnchannels()
        sample_width = source.getsampwidth()
        sample_rate = source.getframerate()
        frame_count = source.getnframes()
        if sample_width != 2:
            raise ValueError("analysis WAV must use 16-bit PCM")
        raw = source.readframes(frame_count)
    samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples, sample_rate


def _frame_features(samples: np.ndarray, sample_rate: int) -> tuple[np.ndarray, np.ndarray, float]:
    frame_size = 2048
    hop = 512
    if samples.size < frame_size:
        return np.array([]), np.array([]), hop / sample_rate
    window = np.hanning(frame_size).astype(np.float32)
    rms_values: list[float] = []
    flux_values: list[float] = []
    previous: np.ndarray | None = None
    for start in range(0, samples.size - frame_size + 1, hop):
        frame = samples[start : start + frame_size]
        rms_values.append(float(np.sqrt(np.mean(np.square(frame), dtype=np.float64)) + 1e-9))
        spectrum = np.abs(np.fft.rfft(frame * window))
        norm = spectrum / max(float(np.linalg.norm(spectrum)), 1e-9)
        if previous is None:
            flux_values.append(0.0)
        else:
            delta = np.maximum(norm - previous, 0.0)
            flux_values.append(float(np.sum(delta)))
        previous = norm
    return np.asarray(rms_values), np.asarray(flux_values), hop / sample_rate


def _robust_scale(values: np.ndarray) -> np.ndarray:
    if values.size == 0:
        return values
    low, high = np.percentile(values, [10, 90])
    if high - low < 1e-9:
        return np.zeros_like(values)
    return np.clip((values - low) / (high - low), 0.0, 1.0)


def estimate_music_start(samples: np.ndarray, sample_rate: int) -> tuple[float, float]:
    """Conservatively find a sustained music-like region."""

    rms, flux, hop_seconds = _frame_features(samples, sample_rate)
    if rms.size < 32:
        return 0.0, 0.0
    energy = _robust_scale(np.log10(rms + 1e-9))
    activity = _robust_scale(flux)
    score = 0.58 * energy + 0.42 * activity

    window_frames = max(4, round(3.5 / hop_seconds))
    kernel = np.ones(window_frames, dtype=np.float64) / window_frames
    sustained = np.convolve(score, kernel, mode="same")
    threshold = max(0.52, float(np.percentile(sustained, 58)))

    for index in range(window_frames, len(sustained) - window_frames):
        future = sustained[index : index + window_frames]
        if float(np.mean(future)) < threshold or float(np.min(future)) < threshold * 0.62:
            continue
        before = sustained[max(0, index - window_frames) : index]
        contrast = float(np.mean(future) - np.mean(before)) if before.size else 0.0
        if index * hop_seconds < 1.5:
            return 0.0, min(1.0, float(np.mean(future)))
        if contrast >= 0.10 or float(np.mean(before)) < threshold * 0.68:
            confidence = min(1.0, 0.55 + contrast + float(np.mean(future)) * 0.3)
            return index * hop_seconds, confidence
    return 0.0, 0.0


def prepare_music_audio(
    audio_path: Path,
    work_dir: Path,
    *,
    settings: Settings,
    cancel_event: Event | None = None,
) -> tuple[Path, MusicStructureAnalysis]:
    analysis = MusicStructureAnalysis()
    analysis_dir = work_dir / "structure"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    decoded = analysis_dir / "analysis.wav"
    source_for_read = decoded
    if not _decode_analysis_wav(audio_path, decoded, settings=settings, cancel_event=cancel_event):
        if audio_path.suffix.lower() != ".wav":
            analysis.warnings.append("FFmpeg unavailable; music-start analysis was skipped.")
            return audio_path, analysis
        source_for_read = audio_path
    try:
        samples, sample_rate = _read_mono_wav(source_for_read)
        start_seconds, confidence = estimate_music_start(samples, sample_rate)
    except (OSError, ValueError, wave.Error) as exc:
        analysis.warnings.append(f"Music-start analysis was skipped: {exc}")
        return audio_path, analysis

    analysis.music_start_seconds = round(start_seconds, 3)
    analysis.start_confidence = round(confidence, 3)
    analysis.method = "pcm-energy-spectral-flux"
    if start_seconds < 1.5 or confidence < 0.72:
        return audio_path, analysis
    if not command_exists(settings.ffmpeg_cmd):
        analysis.warnings.append("Music start was detected but FFmpeg is unavailable for safe trimming.")
        return audio_path, analysis

    trimmed = analysis_dir / "music-region.wav"
    try:
        run_command(
            settings.ffmpeg_cmd,
            [
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{start_seconds:.3f}",
                "-i",
                audio_path,
                "-vn",
                "-ac",
                "1",
                "-ar",
                "44100",
                "-c:a",
                "pcm_s16le",
                trimmed,
            ],
            cancel_event=cancel_event,
            timeout_seconds=600,
            max_output_bytes=2 * 1024 * 1024,
        )
    except CommandCancelled:
        raise
    except CommandError as exc:
        analysis.warnings.append(f"Detected music start could not be trimmed safely: {exc}")
        return audio_path, analysis
    if trimmed.is_file():
        analysis.trimmed = True
        return trimmed, analysis
    return audio_path, analysis


def _tempo_seconds_per_beat(mid: mido.MidiFile) -> tuple[float, float | None]:
    tempo = 500_000
    for message in mido.merge_tracks(mid.tracks):
        if message.type == "set_tempo":
            tempo = int(message.tempo)
            break
    bpm = float(mido.tempo2bpm(tempo))
    return tempo / 1_000_000.0, bpm


def _phase_proximity(distance: float, radius: float) -> float:
    """Smoothly prefer exact metrical alignment over neighboring phase bins."""

    if radius <= 0 or distance >= radius:
        return 0.0
    ratio = distance / radius
    return (1.0 - ratio) ** 2


def analyze_midi_meter_and_pickup(
    midi_path: Path,
    analysis: MusicStructureAnalysis,
) -> MusicStructureAnalysis:
    try:
        mid = mido.MidiFile(midi_path)
    except (OSError, EOFError, ValueError) as exc:
        analysis.warnings.append(f"Pickup analysis was skipped: {exc}")
        return analysis

    numerator, denominator = 4, 4
    absolute = 0
    note_events: list[tuple[int, int]] = []
    for message in mido.merge_tracks(mid.tracks):
        absolute += int(message.time)
        if message.type == "time_signature":
            numerator, denominator = int(message.numerator), int(message.denominator)
        elif message.type == "note_on" and int(message.velocity) > 0:
            note_events.append((absolute, int(message.velocity)))
    if len(note_events) < 4:
        return analysis

    ticks_per_quarter = max(1, int(mid.ticks_per_beat))
    beat_ticks = ticks_per_quarter * 4.0 / max(1, denominator)
    bar_ticks = beat_ticks * max(1, numerator)
    step = max(1, int(round(beat_ticks / 4.0)))
    phases = range(0, max(1, int(round(bar_ticks))), step)

    best_phase = 0
    best_score = -math.inf
    second_score = -math.inf
    downbeat_radius = max(float(step) * 1.75, 1.0)
    beat_radius = max(float(step) * 1.5, 1.0)
    for phase in phases:
        score = 0.0
        for tick, velocity in note_events[:256]:
            rel = (tick - phase) % bar_ticks
            distance = min(rel, bar_ticks - rel)
            beat_mod = rel % beat_ticks
            beat_distance = min(beat_mod, beat_ticks - beat_mod)
            weight = 0.5 + velocity / 127.0
            downbeat_fit = _phase_proximity(distance, downbeat_radius)
            beat_fit = _phase_proximity(beat_distance, beat_radius)
            score += weight * (2.35 * downbeat_fit + 0.55 * beat_fit)
        if score > best_score:
            second_score = best_score
            best_score = score
            best_phase = phase
        elif score > second_score:
            second_score = score

    first_tick = note_events[0][0]
    downbeat_tick = best_phase
    while downbeat_tick <= first_tick + step:
        downbeat_tick += bar_ticks
    pickup_ticks = max(0.0, downbeat_tick - first_tick)
    if pickup_ticks >= bar_ticks - step:
        pickup_ticks = 0.0

    beat_seconds, bpm = _tempo_seconds_per_beat(mid)
    pickup_quarters = pickup_ticks / ticks_per_quarter
    confidence = 0.0
    if best_score > 0:
        confidence = max(
            0.0,
            min(1.0, (best_score - max(0.0, second_score)) / best_score * 2.5),
        )
    if pickup_quarters < 0.20:
        pickup_quarters = 0.0

    analysis.meter_numerator = numerator
    analysis.meter_denominator = denominator
    analysis.tempo_bpm = round(bpm, 2)
    analysis.pickup_quarters = round(pickup_quarters, 3)
    analysis.pickup_confidence = round(confidence, 3)
    if pickup_quarters > 0:
        analysis.first_downbeat_seconds = round(
            analysis.music_start_seconds + pickup_quarters * beat_seconds,
            3,
        )
    else:
        analysis.first_downbeat_seconds = analysis.music_start_seconds
    return analysis


def write_structure_report(
    path: Path,
    analysis: MusicStructureAnalysis,
    **extra: object,
) -> Path:
    payload = {**analysis.as_dict(), **extra}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path

from __future__ import annotations

import math
import tempfile
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .notation_backend import musicxml_to_midi
from .runner import CommandError, command_exists, run_command


class AudioSymbolValidationError(RuntimeError):
    pass


@dataclass(slots=True)
class AudioSymbolIssue:
    severity: str
    category: str
    message: str
    confidence: float
    start_seconds: float
    end_seconds: float
    measure: str | None = None
    suggested_action: str | None = None
    source: str = "audio_symbol"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _decode_to_wav(source: Path, target: Path, ffmpeg_cmd: str) -> Path:
    if not command_exists(ffmpeg_cmd):
        raise AudioSymbolValidationError("audio-symbol 검증에는 ffmpeg가 필요합니다.")
    try:
        run_command(
            ffmpeg_cmd,
            ["-y", "-i", source, "-ac", "1", "-ar", "22050", "-c:a", "pcm_s16le", target],
        )
    except CommandError as exc:
        raise AudioSymbolValidationError(f"오디오 정규화 실패: {exc}") from exc
    if not target.is_file():
        raise AudioSymbolValidationError("ffmpeg가 검증용 WAV를 생성하지 않았습니다.")
    return target


def _synthesize_midi(
    midi: Path,
    target: Path,
    *,
    fluidsynth_cmd: str,
    soundfont: Path,
) -> Path:
    if not command_exists(fluidsynth_cmd):
        raise AudioSymbolValidationError("audio-symbol 검증에는 FluidSynth가 필요합니다.")
    if not soundfont.is_file():
        raise AudioSymbolValidationError("검증용 SoundFont(.sf2/.sf3) 경로를 지정하세요.")
    try:
        run_command(
            fluidsynth_cmd,
            ["-ni", soundfont, midi, "-F", target, "-r", "22050"],
        )
    except CommandError as exc:
        raise AudioSymbolValidationError(f"악보 재합성 실패: {exc}") from exc
    if not target.is_file():
        raise AudioSymbolValidationError("FluidSynth가 검증용 오디오를 생성하지 않았습니다.")
    return target


def _read_pcm16(path: Path) -> tuple[np.ndarray, int]:
    try:
        with wave.open(str(path), "rb") as handle:
            sr = handle.getframerate()
            channels = handle.getnchannels()
            width = handle.getsampwidth()
            frames = handle.readframes(handle.getnframes())
    except (wave.Error, OSError) as exc:
        raise AudioSymbolValidationError(f"검증용 WAV를 읽지 못했습니다: {exc}") from exc
    if width != 2:
        raise AudioSymbolValidationError("검증용 WAV는 16-bit PCM이어야 합니다.")
    audio = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak > 1e-8:
        audio = audio / peak
    return audio, sr


def _chroma(audio: np.ndarray, sr: int, *, n_fft: int = 4096, hop: int = 1024) -> np.ndarray:
    if len(audio) < n_fft:
        return np.zeros((12, 0), dtype=np.float32)
    window = np.hanning(n_fft).astype(np.float32)
    bins = np.fft.rfftfreq(n_fft, d=1.0 / sr)
    midi = np.full_like(bins, -1.0, dtype=np.float64)
    valid = bins > 27.5
    midi[valid] = 69.0 + 12.0 * np.log2(bins[valid] / 440.0)
    pitch_class = np.mod(np.rint(midi).astype(np.int64), 12)
    frames: list[np.ndarray] = []
    for start in range(0, len(audio) - n_fft + 1, hop):
        spectrum = np.abs(np.fft.rfft(audio[start : start + n_fft] * window))
        frame = np.zeros(12, dtype=np.float64)
        for pc in range(12):
            mask = valid & (pitch_class == pc)
            frame[pc] = float(np.sum(spectrum[mask]))
        norm = float(np.linalg.norm(frame))
        if norm > 1e-10:
            frame /= norm
        frames.append(frame.astype(np.float32))
    return np.stack(frames, axis=1) if frames else np.zeros((12, 0), dtype=np.float32)


def _novelty(chroma: np.ndarray) -> np.ndarray:
    if chroma.shape[1] < 2:
        return np.zeros(chroma.shape[1], dtype=np.float32)
    diff = np.maximum(0.0, np.diff(chroma, axis=1))
    return np.concatenate([[0.0], np.linalg.norm(diff, axis=0)]).astype(np.float32)


def _best_shift(source: np.ndarray, synth: np.ndarray, max_shift: int) -> int:
    if source.size == 0 or synth.size == 0:
        return 0
    a = source - float(np.mean(source))
    b = synth - float(np.mean(synth))
    n = 1
    target = len(a) + len(b) - 1
    while n < target:
        n <<= 1
    corr = np.fft.irfft(np.fft.rfft(a, n) * np.conj(np.fft.rfft(b, n)), n)
    corr = np.concatenate([corr[-(len(b) - 1) :], corr[: len(a)]])
    lags = np.arange(-(len(b) - 1), len(a))
    mask = (lags >= -max_shift) & (lags <= max_shift)
    if not np.any(mask):
        return 0
    return int(lags[mask][int(np.argmax(corr[mask]))])


def _aligned_similarity(source: np.ndarray, synth: np.ndarray, shift: int) -> np.ndarray:
    if shift >= 0:
        a = source[:, shift:]
        b = synth[:, : a.shape[1]]
    else:
        b = synth[:, -shift:]
        a = source[:, : b.shape[1]]
    length = min(a.shape[1], b.shape[1])
    if length <= 0:
        return np.zeros(0, dtype=np.float32)
    a = a[:, :length]
    b = b[:, :length]
    return np.sum(a * b, axis=0).astype(np.float32)


def _measure_guess(seconds: float, xml_text: str) -> str | None:
    # Conservative estimate from the first explicit metronome/time signature. Exact
    # measure mapping belongs to a future tempo-map implementation.
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    beat = 120.0
    beats = 4
    beat_type = 4
    sound = root.find(".//sound[@tempo]")
    if sound is not None:
        try:
            beat = float(sound.get("tempo") or beat)
        except ValueError:
            pass
    time = root.find(".//time")
    if time is not None:
        try:
            beats = int(time.findtext("beats") or beats)
            beat_type = int(time.findtext("beat-type") or beat_type)
        except ValueError:
            pass
    quarter_per_measure = beats * 4.0 / max(1, beat_type)
    seconds_per_measure = quarter_per_measure * 60.0 / max(1.0, beat)
    return str(max(1, int(math.floor(seconds / seconds_per_measure)) + 1))


def validate_audio_symbol(
    *,
    source_audio: Path,
    xml_text: str,
    working_musicxml: Path,
    ffmpeg_cmd: str,
    fluidsynth_cmd: str,
    soundfont_path: Path,
    window_seconds: float = 2.5,
    threshold: float = 0.42,
) -> dict[str, Any]:
    """Compare original audio with a resynthesis of the current symbolic score.

    This is evidence generation, not an automatic correctness oracle. Chroma suppresses
    timbre differences so the result is useful for locating pitch/harmony/onset regions
    that deserve human inspection.
    """

    if not source_audio.is_file():
        raise AudioSymbolValidationError("보존된 원본 음원을 찾을 수 없습니다.")
    with tempfile.TemporaryDirectory(prefix="ast-audio-symbol-") as raw:
        root = Path(raw)
        midi = root / "current.mid"
        source_wav = root / "source.wav"
        synth_raw = root / "synth-raw.wav"
        synth_wav = root / "synth.wav"
        musicxml_to_midi(working_musicxml, midi)
        _synthesize_midi(
            midi,
            synth_raw,
            fluidsynth_cmd=fluidsynth_cmd,
            soundfont=soundfont_path,
        )
        _decode_to_wav(source_audio, source_wav, ffmpeg_cmd)
        _decode_to_wav(synth_raw, synth_wav, ffmpeg_cmd)
        source, sr = _read_pcm16(source_wav)
        synth, synth_sr = _read_pcm16(synth_wav)
        if sr != synth_sr:
            raise AudioSymbolValidationError("검증용 오디오 sample rate가 일치하지 않습니다.")
        hop = 1024
        src_chroma = _chroma(source, sr, hop=hop)
        syn_chroma = _chroma(synth, sr, hop=hop)
        if src_chroma.shape[1] < 8 or syn_chroma.shape[1] < 8:
            raise AudioSymbolValidationError("오디오가 너무 짧아 audio-symbol 검증을 수행할 수 없습니다.")
        max_shift_frames = int(12.0 * sr / hop)
        shift = _best_shift(_novelty(src_chroma), _novelty(syn_chroma), max_shift_frames)
        similarity = _aligned_similarity(src_chroma, syn_chroma, shift)
        frame_seconds = hop / sr
        window_frames = max(1, int(window_seconds / frame_seconds))
        issues: list[AudioSymbolIssue] = []
        window_scores: list[dict[str, float]] = []
        for start in range(0, len(similarity), window_frames):
            chunk = similarity[start : start + window_frames]
            if chunk.size == 0:
                continue
            score = float(np.mean(chunk))
            start_sec = start * frame_seconds
            end_sec = (start + len(chunk)) * frame_seconds
            window_scores.append(
                {"start_seconds": round(start_sec, 3), "end_seconds": round(end_sec, 3), "similarity": round(score, 4)}
            )
            if score >= threshold:
                continue
            confidence = min(0.98, max(0.5, (threshold - score) / max(threshold, 1e-6) + 0.55))
            issues.append(
                AudioSymbolIssue(
                    severity="warning" if score >= threshold * 0.55 else "error",
                    category="audio-symbol discrepancy",
                    message=f"원음과 현재 악보 재합성의 chroma 유사도가 낮습니다 ({score:.2f}).",
                    confidence=round(confidence, 3),
                    start_seconds=round(start_sec, 3),
                    end_seconds=round(end_sec, 3),
                    measure=_measure_guess(start_sec, xml_text),
                    suggested_action="해당 시간대의 누락/과잉 음표, 옥타브, 코드 또는 파트 배정을 원음과 대조하세요.",
                )
            )

    overall = float(np.mean(similarity)) if similarity.size else 0.0
    return {
        "provider": "chroma_resynthesis_v1",
        "evidence": "original_audio_vs_current_score_resynthesis",
        "overall_similarity": round(overall, 4),
        "alignment_shift_seconds": round(shift * frame_seconds, 3),
        "threshold": threshold,
        "issues": [issue.as_dict() for issue in issues],
        "windows": window_scores[:240],
        "policy": {"advisory": True, "auto_edit": False, "timbre_invariant_feature": "chroma"},
    }

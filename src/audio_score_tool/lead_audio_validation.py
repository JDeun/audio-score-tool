"""Independent vocal pitch and backing-harmony evidence for a current Lead Sheet."""
from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np

from .audio_symbol_validation import (
    AudioSymbolValidationError,
    _chroma,
    _decode_to_wav,
    _read_pcm16,
)
from .config import Settings
from .demucs_runtime import demucs_ready, demucs_repo_args
from .runner import CommandError, run_command
from .score_timing import score_time_clocks
from .selected_stem_score import SelectedScoreError, _stem
from .vocal_evidence import compare_notes, part_notes, vocal_pitch_track


def compare_lead_stems(*, vocal_audio: Path, backing_audio: Path, xml_text: str,
                       ffmpeg_cmd: str, origin_seconds: float = 0.0) -> dict:
    """Compare waveform observations with the CURRENT score, including user edits."""
    from music21 import converter, harmony

    score = converter.parseData(xml_text, format="musicxml")
    voices = [part for part in score.parts if str(part.partName).lower() in {"voice", "vocal", "vocals"}]
    if len(score.parts) == 1:
        voices = list(score.parts)
    if len(voices) != 1:
        raise AudioSymbolValidationError("독립 음향 대조에 사용할 보컬 파트를 하나로 식별하지 못했습니다.")
    part = voices[0]
    times, pitches = vocal_pitch_track(vocal_audio, ffmpeg_cmd=ffmpeg_cmd)
    report = compare_notes(part_notes(score, part, origin_seconds=origin_seconds), times, pitches)
    issues = []
    for observed in report.pop("observations"):
        if observed["category"] == "consistent":
            continue
        issues.append({
            "source": "vocal_acoustic", "severity": "warning",
            "category": "octave discrepancy" if observed["category"] == "octave" else "vocal pitch discrepancy",
            "message": (f"보컬 파형 기본음과 악보가 약 {observed['difference_semitones']:+.1f}반음 다릅니다. "
                        "분리음 누출·코러스·기본음 추정 오류도 가능하므로 원음 대조가 필요합니다."),
            "start_seconds": round(observed["start_seconds"], 3),
            "end_seconds": round(observed["end_seconds"], 3), "measure": observed["measure"],
            "suggested_action": "해당 구간의 원음과 보컬 음역을 확인하세요. 자동 수정하지 않았습니다.",
        })
    with tempfile.TemporaryDirectory(prefix="ast-chord-evidence-") as folder:
        wav = _decode_to_wav(backing_audio, Path(folder) / "backing.wav", ffmpeg_cmd)
        audio, sr = _read_pcm16(wav)
    chroma = _chroma(audio, sr)
    frame_times = (np.arange(chroma.shape[1]) * 1024 + 2048) / sr
    seconds, _ = score_time_clocks(score)
    symbols = list(part.recurse().getElementsByClass(harmony.ChordSymbol))
    symbols.sort(key=lambda h: float(h.getOffsetInHierarchy(part)))
    templates, labels = [], []
    for root in range(12):
        for quality, intervals in (("major", [0, 4, 7]), ("minor", [0, 3, 7])):
            template = np.zeros(12)
            template[[(root + step) % 12 for step in intervals]] = 1 / np.sqrt(3)
            templates.append(template)
            labels.append({"root_pitch_class": root, "quality": quality})
    compared, warnings = 0, 0
    for index, symbol in enumerate(symbols):
        pcs = {pitch.pitchClass for pitch in symbol.pitches}
        if not pcs:
            continue
        start = origin_seconds + seconds(float(symbol.getOffsetInHierarchy(part)))
        end_q = (float(symbols[index + 1].getOffsetInHierarchy(part))
                 if index + 1 < len(symbols) else float(part.highestTime))
        end = origin_seconds + seconds(end_q)
        selected = chroma[:, (frame_times >= start) & (frame_times < end)]
        if selected.shape[1] < 3:
            continue
        spectrum = selected.mean(axis=1)
        norm = float(np.linalg.norm(spectrum))
        if norm < 0.1:
            continue
        spectrum /= norm
        expected = np.zeros(12)
        expected[list(pcs)] = 1 / np.sqrt(len(pcs))
        support = float(expected @ spectrum)
        alternatives = np.asarray(templates) @ spectrum
        best = int(np.argmax(alternatives))
        compared += 1
        if float(alternatives[best]) - support <= 0.2:
            continue
        warnings += 1
        alternative = labels[best]
        issues.append({
            "source": "chord_acoustic", "severity": "warning", "category": "chord spectral discrepancy",
            "message": (f"코드 {symbol.figure}보다 다른 삼화음(근음 pitch class "
                        f"{alternative['root_pitch_class']}, {alternative['quality']})의 반주 스펙트럼 지지가 큽니다. "
                        "확장음·전위·분리 오류를 포함한 재검토 신호이며 코드 정답 판정은 아닙니다."),
            "start_seconds": round(start, 3), "end_seconds": round(end, 3),
            "measure": str(symbol.measureNumber),
            "suggested_action": "원음 반주와 코드 종류·변경 시점을 대조하세요. 자동 교체하지 않았습니다.",
        })
    return {
        "provider": "separated_waveform_yin_chroma_v1", "melody": report,
        "chords": {"compared_intervals": compared, "spectral_warnings": warnings, "wcsr": None},
        "issues": issues[:200], "total_issue_count": len(issues), "issues_truncated": len(issues) > 200,
        "policy": {"advisory": True, "auto_edit": False, "quality_approved": False,
                   "independent_ground_truth": False, "alignment": "score_tempo_map_plus_applied_crop"},
    }


def validate_lead_audio(*, source_audio: Path, xml_text: str, settings: Settings,
                        origin_seconds: float = 0.0) -> dict:
    if not demucs_ready(settings):
        raise AudioSymbolValidationError("보컬·반주 원음 대조에 사용할 검증된 Demucs 구성이 없습니다.")
    with tempfile.TemporaryDirectory(prefix="ast-lead-audio-") as folder:
        root = Path(folder)
        try:
            run_command(settings.demucs_cmd, ["-n", "htdemucs", *demucs_repo_args(settings),
                        "--two-stems", "vocals", "--shifts", "0", "-d", "cpu", "-o", root,
                        source_audio], timeout_seconds=1800)
            return compare_lead_stems(vocal_audio=_stem(root, "vocals"),
                                      backing_audio=_stem(root, "no_vocals"), xml_text=xml_text,
                                      ffmpeg_cmd=settings.ffmpeg_cmd, origin_seconds=origin_seconds)
        except (CommandError, SelectedScoreError, OSError, ValueError) as exc:
            raise AudioSymbolValidationError(f"독립 보컬·코드 대조 실패: {exc}") from exc

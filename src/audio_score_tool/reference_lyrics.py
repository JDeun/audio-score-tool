from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from .lyrics import expand_korean_syllables
from .models import WordTiming

_LRC_TAG = re.compile(r"\[(?:\d{1,2}:)?\d{1,2}(?:\.\d+)?\]")
_TOKEN = re.compile(r"[^\s]+")
_STRIP = re.compile(r"[^0-9A-Za-z가-힣]+")


def transcript_words(payload: Any) -> list[WordTiming]:
    if not isinstance(payload, dict):
        return []
    result: list[WordTiming] = []
    for segment in payload.get("segments", []) or []:
        if not isinstance(segment, dict):
            continue
        for item in segment.get("words", []) or []:
            if not isinstance(item, dict):
                continue
            text = str(item.get("word") or "").strip()
            start, end = item.get("start"), item.get("end")
            if not text or start is None or end is None:
                continue
            result.append(WordTiming(text=text, start=float(start), end=float(end), score=item.get("score")))
    return result


def reference_tokens(text: str) -> list[str]:
    clean = _LRC_TAG.sub(" ", text.replace("\r", "\n"))
    return [token.strip() for token in _TOKEN.findall(clean) if token.strip()]


def _norm(text: str) -> str:
    return _STRIP.sub("", text).lower()


def _distributed(tokens: list[str], start: float, end: float) -> list[WordTiming]:
    if not tokens:
        return []
    duration = max(0.01, end - start)
    step = duration / len(tokens)
    return [
        WordTiming(text=token, start=start + index * step, end=start + (index + 1) * step, score=None)
        for index, token in enumerate(tokens)
    ]


def align_reference_lyrics(
    transcript_payload: Any,
    reference_text: str,
    *,
    language: str | None = None,
) -> tuple[list[WordTiming], dict[str, Any]]:
    """Use clean lyrics text while retaining timing evidence from WhisperX.

    Equal spans keep exact ASR timings. Replaced/inserted spans are distributed over the
    corresponding ASR time range. This is deliberately conservative: it improves text
    correctness but does not pretend the external provider supplied acoustic timing.
    """
    asr = transcript_words(transcript_payload)
    refs = reference_tokens(reference_text)
    if not asr or not refs:
        return [], {"asr_words": len(asr), "reference_tokens": len(refs), "coverage": 0.0}

    matcher = SequenceMatcher(a=[_norm(item.text) for item in asr], b=[_norm(item) for item in refs], autojunk=False)
    aligned: list[WordTiming] = []
    exact = 0

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        ref_span = refs[j1:j2]
        asr_span = asr[i1:i2]
        if tag == "equal":
            for source, text in zip(asr_span, ref_span):
                aligned.append(WordTiming(text=text, start=source.start, end=source.end, score=source.score))
                exact += 1
            continue
        if not ref_span:
            continue
        if asr_span:
            aligned.extend(_distributed(ref_span, asr_span[0].start, asr_span[-1].end))
            continue
        # Pure insertion: borrow a narrow interval around the nearest known ASR boundary.
        if i1 > 0:
            anchor = asr[i1 - 1].end
        elif i1 < len(asr):
            anchor = asr[i1].start
        else:
            anchor = 0.0
        aligned.extend(_distributed(ref_span, anchor, anchor + max(0.08, 0.18 * len(ref_span))))

    aligned.sort(key=lambda item: (item.start, item.end))
    if language == "ko":
        aligned = expand_korean_syllables(aligned)
    return aligned, {
        "asr_words": len(asr),
        "reference_tokens": len(refs),
        "timed_tokens": len(aligned),
        "exact_token_matches": exact,
        "coverage": exact / max(1, len(refs)),
        "timing_source": "whisperx",
        "text_source": "external_reference",
    }

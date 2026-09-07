from __future__ import annotations

import base64
import json
import os
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from PIL import Image

from .notation_backend import render_pdf
from .paths import cache_dir, song_assets_dir
from .runner import CommandError, command_exists, run_command
from .runtime_settings import runtime_settings


class VisualValidationError(RuntimeError):
    pass


def _source_asset(song_id: str) -> Path:
    root = song_assets_dir() / song_id
    candidates = sorted(root.glob("original-score.*"))
    if not candidates:
        raise VisualValidationError("원본 PDF/이미지 asset이 없습니다. OMR로 가져온 악보만 시각 검증할 수 있습니다.")
    return candidates[0]


def _raster_pdf(source: Path, output_dir: Path, prefix: str, max_pages: int) -> list[Path]:
    if not command_exists("pdftoppm"):
        raise VisualValidationError(
            "PDF 페이지 비교에는 Poppler의 pdftoppm이 필요합니다. macOS는 `brew install poppler`로 설치할 수 있습니다."
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    target_prefix = output_dir / prefix
    try:
        run_command(
            "pdftoppm",
            ["-png", "-r", "150", "-f", "1", "-l", str(max_pages), source, target_prefix],
        )
    except CommandError as exc:
        raise VisualValidationError(f"PDF rasterize 실패: {exc}") from exc
    return sorted(output_dir.glob(f"{prefix}-*.png"))


def _normalize_image(source: Path, target: Path) -> Path:
    try:
        with Image.open(source) as image:
            image = image.convert("RGB")
            image.thumbnail((1800, 2400))
            target.parent.mkdir(parents=True, exist_ok=True)
            image.save(target, format="PNG", optimize=True)
    except Exception as exc:
        raise VisualValidationError(f"원본 악보 이미지를 읽지 못했습니다: {exc}") from exc
    return target


def _score_pages(song_id: str, xml_text: str, output_dir: Path, max_pages: int) -> list[Path]:
    settings = runtime_settings()
    source = output_dir / "recognized.musicxml"
    pdf = output_dir / "recognized.pdf"
    source.write_text(xml_text, encoding="utf-8")
    try:
        render_pdf(source, pdf, settings=settings)
    except Exception as exc:
        raise VisualValidationError(
            "인식 결과를 비교 이미지로 렌더링하지 못했습니다. LilyPond 또는 MuseScore fallback을 확인하세요. "
            f"({exc})"
        ) from exc
    return _raster_pdf(pdf, output_dir / "recognized-pages", "page", max_pages)


def _original_pages(song_id: str, output_dir: Path, max_pages: int) -> list[Path]:
    source = _source_asset(song_id)
    if source.suffix.lower() == ".pdf":
        return _raster_pdf(source, output_dir / "original-pages", "page", max_pages)
    return [_normalize_image(source, output_dir / "original-pages" / "page-1.png")]


def _data_url(path: Path) -> str:
    with Image.open(path) as image:
        image = image.convert("RGB")
        image.thumbnail((1600, 2200))
        temp = path.with_name(path.stem + "-vlm.jpg")
        image.save(temp, format="JPEG", quality=84, optimize=True)
    encoded = base64.b64encode(temp.read_bytes()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def _parse_json(text: str) -> dict[str, Any]:
    value = text.strip()
    if value.startswith("```"):
        value = value.split("\n", 1)[1] if "\n" in value else value
        if value.endswith("```"):
            value = value[:-3]
    start = value.find("{")
    end = value.rfind("}")
    if start < 0 or end <= start:
        raise VisualValidationError("Vision model이 JSON 보고서를 반환하지 않았습니다.")
    try:
        payload = json.loads(value[start : end + 1])
    except json.JSONDecodeError as exc:
        raise VisualValidationError("Vision model JSON 보고서를 해석하지 못했습니다.") from exc
    return payload if isinstance(payload, dict) else {}


def _call_vlm(
    *,
    original_pages: list[Path],
    recognized_pages: list[Path],
    base_url: str,
    model: str,
    api_key_env: str | None,
) -> dict[str, Any]:
    pair_count = min(len(original_pages), len(recognized_pages), 4)
    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                "You are a sheet-music OMR verification critic. Each page pair contains ORIGINAL first, "
                "then RECOGNIZED/RE-RENDERED. Identify only visually supported transcription discrepancies. "
                "Check pitches/accidentals, clefs, key/time signatures, note/rest durations, beams, ties/slurs, "
                "lyrics, repeats/endings, dynamics/text and missing/extra staves. Do not auto-correct. "
                "Return strict JSON: {summary:string, issues:[{page:int, measure:string|null, severity:'error'|'warning'|'info', "
                "category:string, message:string, confidence:number, suggested_action:string}], page_notes:[string]}. "
                "If uncertain, lower confidence and say what a human should inspect."
            ),
        }
    ]
    for index in range(pair_count):
        content.append({"type": "text", "text": f"PAGE {index + 1} ORIGINAL"})
        content.append({"type": "image_url", "image_url": {"url": _data_url(original_pages[index])}})
        content.append({"type": "text", "text": f"PAGE {index + 1} RECOGNIZED"})
        content.append({"type": "image_url", "image_url": {"url": _data_url(recognized_pages[index])}})

    headers = {"Content-Type": "application/json"}
    if api_key_env:
        token = os.getenv(api_key_env)
        if token:
            headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(
        {
            "model": model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": "Be conservative. Report evidence, not guesses."},
                {"role": "user", "content": content},
            ],
        }
    ).encode("utf-8")
    url = base_url.rstrip("/") + "/chat/completions"
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise VisualValidationError(f"Vision model 호출 실패: {exc}") from exc
    try:
        text = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise VisualValidationError("Vision model 응답 형식이 OpenAI-compatible chat/completions와 다릅니다.") from exc
    return _parse_json(str(text))


def validate_omr_visual(
    *,
    song_id: str,
    xml_text: str,
    base_url: str,
    model: str,
    api_key_env: str | None = None,
    max_pages: int = 4,
) -> dict[str, Any]:
    work_root = cache_dir() / "visual-validation"
    work_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"{song_id}-", dir=work_root) as raw:
        work = Path(raw)
        original = _original_pages(song_id, work, max_pages)
        recognized = _score_pages(song_id, xml_text, work, max_pages)
        if not original or not recognized:
            raise VisualValidationError("비교할 페이지 이미지를 만들지 못했습니다.")
        report = _call_vlm(
            original_pages=original,
            recognized_pages=recognized,
            base_url=base_url,
            model=model,
            api_key_env=api_key_env,
        )

    issues: list[dict[str, Any]] = []
    for raw_issue in report.get("issues", []) if isinstance(report.get("issues"), list) else []:
        if not isinstance(raw_issue, dict):
            continue
        severity = str(raw_issue.get("severity") or "warning").lower()
        if severity not in {"error", "warning", "info"}:
            severity = "warning"
        try:
            confidence = max(0.0, min(1.0, float(raw_issue.get("confidence", 0.5))))
        except (TypeError, ValueError):
            confidence = 0.5
        issues.append(
            {
                "severity": severity,
                "category": str(raw_issue.get("category") or "visual-omr"),
                "message": str(raw_issue.get("message") or "원본과 재렌더링 결과의 차이를 확인하세요."),
                "part": None,
                "measure": str(raw_issue.get("measure")) if raw_issue.get("measure") is not None else None,
                "page": int(raw_issue.get("page") or 1),
                "confidence": confidence,
                "suggested_action": str(raw_issue.get("suggested_action") or "원본 악보와 해당 구간을 직접 대조하세요."),
                "source": "vision",
            }
        )

    if len(original) != len(recognized):
        issues.insert(
            0,
            {
                "severity": "warning",
                "category": "page-structure",
                "message": f"원본과 재렌더링 페이지 수가 다릅니다: original={len(original)}, recognized={len(recognized)} (최대 {max_pages}페이지 비교).",
                "part": None,
                "measure": None,
                "page": 1,
                "confidence": 1.0,
                "suggested_action": "누락된 시스템/파트 또는 조판 차이인지 확인하세요.",
                "source": "vision",
            },
        )

    return {
        "summary": str(report.get("summary") or "시각 OMR 비교 완료"),
        "model": model,
        "pages_compared": min(len(original), len(recognized), 4),
        "original_pages": len(original),
        "recognized_pages": len(recognized),
        "issues": issues,
        "page_notes": report.get("page_notes") if isinstance(report.get("page_notes"), list) else [],
        "advisory": True,
        "auto_edit": False,
    }

from __future__ import annotations

import json
import os
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from typing import Any

from .safe_http import open_json


@dataclass(slots=True)
class ValidationIssue:
    severity: str
    category: str
    message: str
    part: str | None = None
    measure: str | None = None
    confidence: float = 1.0
    suggested_action: str | None = None
    source: str = "deterministic"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _namespace(root: ET.Element) -> str:
    if root.tag.startswith("{"):
        return root.tag.split("}", 1)[0] + "}"
    return ""


def _part_names(root: ET.Element, ns: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for score_part in root.findall(f".//{ns}score-part"):
        part_id = score_part.get("id") or ""
        result[part_id] = score_part.findtext(f"{ns}part-name") or part_id
    return result


def _pitch_midi(note: ET.Element, ns: str) -> int | None:
    pitch = note.find(f"{ns}pitch")
    if pitch is None:
        return None
    step = pitch.findtext(f"{ns}step")
    octave = pitch.findtext(f"{ns}octave")
    if not step or octave is None:
        return None
    base = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}.get(step.upper())
    if base is None:
        return None
    try:
        alter = int(float(pitch.findtext(f"{ns}alter") or "0"))
        return (int(octave) + 1) * 12 + base + alter
    except ValueError:
        return None


def _expected_range(part_name: str) -> tuple[int, int] | None:
    name = part_name.lower()
    if any(token in name for token in ("drum", "percussion", "kit")):
        return None
    if "bass" in name:
        return (28, 67)
    if any(token in name for token in ("guitar", "acoustic", "electric")):
        return (38, 88)
    if any(token in name for token in ("violin", "fiddle")):
        return (55, 103)
    if "viola" in name:
        return (48, 91)
    if any(token in name for token in ("cello", "violoncello")):
        return (36, 76)
    if any(token in name for token in ("vocal", "voice", "singer", "soprano", "alto", "tenor")):
        return (36, 88)
    if any(token in name for token in ("piano", "keyboard", "organ")):
        return (21, 108)
    return None


def _measure_duration_summary(measure: ET.Element, ns: str, divisions: float) -> tuple[float, bool]:
    cursor = 0.0
    max_cursor = 0.0
    previous_onset = 0.0
    has_voice_navigation = False
    for child in list(measure):
        kind = _local(child.tag)
        if kind == "backup":
            has_voice_navigation = True
            try:
                cursor -= float(child.findtext(f"{ns}duration") or "0") / divisions
            except ValueError:
                pass
            continue
        if kind == "forward":
            has_voice_navigation = True
            try:
                cursor += float(child.findtext(f"{ns}duration") or "0") / divisions
            except ValueError:
                pass
            max_cursor = max(max_cursor, cursor)
            continue
        if kind != "note":
            continue
        if child.find(f"{ns}grace") is not None:
            continue
        is_chord = child.find(f"{ns}chord") is not None
        try:
            duration = float(child.findtext(f"{ns}duration") or "0") / divisions
        except ValueError:
            duration = 0.0
        if is_chord:
            max_cursor = max(max_cursor, previous_onset + duration)
        else:
            previous_onset = cursor
            cursor += duration
            max_cursor = max(max_cursor, cursor)
    return max_cursor, has_voice_navigation


def deterministic_validate(xml_text: str) -> dict[str, Any]:
    root = ET.fromstring(xml_text)
    ns = _namespace(root)
    names = _part_names(root, ns)
    issues: list[ValidationIssue] = []
    compact_parts: list[dict[str, Any]] = []

    for part_index, part in enumerate(root.findall(f"{ns}part")):
        part_id = part.get("id") or f"P{part_index + 1}"
        part_name = names.get(part_id, part_id)
        pitch_range = _expected_range(part_name)
        divisions = 1.0
        beats = 4
        beat_type = 4
        note_count = 0
        rest_count = 0
        pitches: list[int] = []
        compact_measures: list[dict[str, Any]] = []

        for measure_index, measure in enumerate(part.findall(f"{ns}measure")):
            number = measure.get("number") or str(measure_index + 1)
            attributes = measure.find(f"{ns}attributes")
            if attributes is not None:
                try:
                    divisions = max(1.0, float(attributes.findtext(f"{ns}divisions") or divisions))
                except ValueError:
                    pass
                time = attributes.find(f"{ns}time")
                if time is not None:
                    try:
                        beats = int(time.findtext(f"{ns}beats") or beats)
                        beat_type = int(time.findtext(f"{ns}beat-type") or beat_type)
                    except ValueError:
                        pass

            measure_notes = measure.findall(f"{ns}note")
            sounding = 0
            for note in measure_notes:
                note_count += 1
                if note.find(f"{ns}rest") is not None:
                    rest_count += 1
                    if note.find(f"{ns}lyric") is not None:
                        issues.append(
                            ValidationIssue(
                                severity="warning",
                                category="notation",
                                message="쉼표에 가사가 연결되어 있습니다.",
                                part=part_name,
                                measure=number,
                                suggested_action="가사 anchor가 인접한 실제 음표인지 확인하세요.",
                            )
                        )
                    continue
                sounding += 1
                midi = _pitch_midi(note, ns)
                if midi is not None:
                    pitches.append(midi)
                    if pitch_range and (midi < pitch_range[0] - 5 or midi > pitch_range[1] + 5):
                        issues.append(
                            ValidationIssue(
                                severity="warning",
                                category="instrumentation",
                                message=f"{part_name}의 일반적인 음역에서 크게 벗어난 음({midi})이 감지되었습니다.",
                                part=part_name,
                                measure=number,
                                confidence=0.72,
                                suggested_action="악기 배정 오류 또는 옥타브 오류인지 원음을 확인하세요.",
                            )
                        )

                ties = [node.get("type") for node in note.findall(f"{ns}tie")]
                if ties.count("start") > 1 or ties.count("stop") > 1:
                    issues.append(
                        ValidationIssue(
                            severity="warning",
                            category="notation",
                            message="중복 tie 표시가 감지되었습니다.",
                            part=part_name,
                            measure=number,
                        )
                    )

            expected_quarters = beats * 4.0 / max(1, beat_type)
            actual_quarters, complex_voices = _measure_duration_summary(measure, ns, divisions)
            if not complex_voices and measure_index > 0 and abs(actual_quarters - expected_quarters) > 0.125:
                issues.append(
                    ValidationIssue(
                        severity="error" if abs(actual_quarters - expected_quarters) >= 1.0 else "warning",
                        category="rhythm",
                        message=(
                            f"마디 길이가 박자표와 다릅니다: {actual_quarters:.2f} quarter / "
                            f"expected {expected_quarters:.2f}."
                        ),
                        part=part_name,
                        measure=number,
                        suggested_action="누락/과잉 음표, 잘못된 duration 또는 pickup 마디인지 확인하세요.",
                    )
                )

            compact_measures.append(
                {
                    "measure": number,
                    "note_count": len(measure_notes),
                    "sounding_notes": sounding,
                    "duration_quarters": round(actual_quarters, 3),
                    "expected_quarters": round(expected_quarters, 3),
                }
            )

        if note_count == 0:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    category="instrumentation",
                    message="파트가 존재하지만 음표가 하나도 없습니다.",
                    part=part_name,
                    suggested_action="잘못 생성된 빈 파트인지 확인하세요.",
                )
            )

        compact_parts.append(
            {
                "part_id": part_id,
                "name": part_name,
                "notes": note_count,
                "rests": rest_count,
                "pitch_min": min(pitches) if pitches else None,
                "pitch_max": max(pitches) if pitches else None,
                "measures": compact_measures[:64],
            }
        )

    harmonies = root.findall(f".//{ns}harmony")
    summary = {
        "part_count": len(compact_parts),
        "harmony_count": len(harmonies),
        "parts": compact_parts,
    }
    severity_order = {"error": 0, "warning": 1, "info": 2}
    issue_dicts = [
        item.as_dict()
        for item in sorted(issues, key=lambda x: severity_order.get(x.severity, 9))
    ]
    return {
        "ok": not any(item["severity"] == "error" for item in issue_dicts),
        "issues": issue_dicts,
        "summary": summary,
    }


def _extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:].lstrip()
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("LLM did not return a JSON object") from None
        payload = json.loads(stripped[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("LLM response must be a JSON object")
    return payload


def llm_validate(
    *,
    deterministic_report: dict[str, Any],
    analyses: dict[str, Any],
    base_url: str,
    model: str,
    api_key_env: str | None = None,
    timeout_seconds: int = 90,
) -> dict[str, Any]:
    system = (
        "You are a conservative music transcription QA critic. Review structured MusicXML-derived "
        "facts and deterministic warnings. Find likely notation, rhythm, harmony, instrumentation, "
        "lyrics-alignment, and publishing anomalies. You do NOT have authoritative access to the "
        "original audio, so never assert that a note is acoustically wrong. Return JSON only with "
        "keys summary and issues. issues is an array of objects with severity(error|warning|info), "
        "category, message, part(optional), measure(optional), confidence(0..1), suggested_action. "
        "Prefer a small number of high-confidence actionable findings and explicitly mark hypotheses."
    )
    user = json.dumps(
        {
            "deterministic_report": deterministic_report,
            "analysis_context": analyses,
        },
        ensure_ascii=False,
    )
    endpoint = base_url.rstrip("/") + "/chat/completions"
    body = json.dumps(
        {
            "model": model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
    ).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key_env:
        token = os.getenv(api_key_env)
        if token:
            headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
    try:
        payload = open_json(request, timeout=timeout_seconds)
    except RuntimeError as exc:
        raise RuntimeError(f"LLM validation request failed: {exc}") from exc
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("LLM validation response has no assistant content") from exc
    parsed = _extract_json_object(str(content))
    normalized: list[dict[str, Any]] = []
    for raw in parsed.get("issues", []) if isinstance(parsed.get("issues"), list) else []:
        if not isinstance(raw, dict):
            continue
        severity = str(raw.get("severity") or "warning").lower()
        if severity not in {"error", "warning", "info"}:
            severity = "warning"
        try:
            confidence = max(0.0, min(1.0, float(raw.get("confidence", 0.5))))
        except (TypeError, ValueError):
            confidence = 0.5
        normalized.append(
            ValidationIssue(
                severity=severity,
                category=str(raw.get("category") or "musical_review")[:120],
                message=str(raw.get("message") or "LLM review finding")[:4000],
                part=str(raw["part"])[:200] if raw.get("part") else None,
                measure=str(raw["measure"])[:100] if raw.get("measure") else None,
                confidence=confidence,
                suggested_action=str(raw["suggested_action"])[:4000]
                if raw.get("suggested_action")
                else None,
                source="llm",
            ).as_dict()
        )
        if len(normalized) >= 200:
            break
    return {
        "summary": str(parsed.get("summary") or "LLM symbolic-score review completed.")[:4000],
        "issues": normalized,
        "model": model[:200],
        "advisory": True,
    }

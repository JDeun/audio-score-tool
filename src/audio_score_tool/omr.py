from __future__ import annotations

import shutil
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from threading import Event

from .runner import CommandCancelled, CommandError, command_exists, run_command


class OMRImportError(RuntimeError):
    pass


class OMRImportUnavailable(OMRImportError):
    pass


class OMRImportCancelled(OMRImportError):
    pass


@dataclass(slots=True)
class OMRArtifacts:
    musicxml_path: Path
    source_path: Path
    provider: str = "audiveris"


def _is_musicxml(text: str) -> bool:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return False
    return root.tag.rsplit("}", 1)[-1] in {"score-partwise", "score-timewise"}


def _musicxml_from_mxl(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            candidates: list[str] = []
            try:
                container = ET.fromstring(archive.read("META-INF/container.xml"))
                for node in container.iter():
                    if node.tag.rsplit("}", 1)[-1] == "rootfile":
                        full_path = node.attrib.get("full-path")
                        if full_path:
                            candidates.append(full_path)
            except (KeyError, ET.ParseError):
                pass
            candidates.extend(
                name
                for name in archive.namelist()
                if name.lower().endswith((".musicxml", ".xml"))
                and not name.startswith("META-INF/")
            )
            seen: set[str] = set()
            for name in candidates:
                if name in seen:
                    continue
                seen.add(name)
                try:
                    text = archive.read(name).decode("utf-8-sig")
                except (KeyError, UnicodeDecodeError):
                    continue
                if _is_musicxml(text):
                    return text
    except (OSError, zipfile.BadZipFile) as exc:
        raise OMRImportError(f"MXL 파일을 읽지 못했습니다: {exc}") from exc
    raise OMRImportError("MXL 안에서 유효한 MusicXML score를 찾지 못했습니다.")


def normalize_musicxml(source: Path, target: Path) -> Path:
    if source.suffix.lower() == ".mxl":
        text = _musicxml_from_mxl(source)
    else:
        try:
            text = source.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as exc:
            raise OMRImportError(f"MusicXML을 읽지 못했습니다: {exc}") from exc
        if not _is_musicxml(text):
            raise OMRImportError(f"OMR 결과가 유효한 MusicXML이 아닙니다: {source.name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(text, encoding="utf-8")
    temp.replace(target)
    return target


def _find_export(root: Path) -> Path | None:
    candidates = sorted(
        [*root.rglob("*.mxl"), *root.rglob("*.musicxml"), *root.rglob("*.xml")],
        key=lambda path: (path.suffix.lower() != ".mxl", len(path.parts), path.name),
    )
    for candidate in candidates:
        if candidate.name == "container.xml" or "META-INF" in candidate.parts:
            continue
        try:
            if candidate.suffix.lower() == ".mxl":
                _musicxml_from_mxl(candidate)
                return candidate
            if _is_musicxml(candidate.read_text(encoding="utf-8-sig")):
                return candidate
        except (OSError, UnicodeDecodeError, OMRImportError):
            continue
    return None


def audiveris_status(command: str) -> dict[str, object]:
    return {
        "provider": "audiveris",
        "ready": command_exists(command),
        "command": command,
        "accepted_inputs": ["pdf", "png", "jpg", "jpeg", "tif", "tiff", "bmp"],
        "output": "musicxml",
    }


def transcribe_score(
    source: Path,
    output_dir: Path,
    *,
    command: str,
    cancel_event: Event | None = None,
) -> OMRArtifacts:
    if not command_exists(command):
        raise OMRImportUnavailable(
            "Audiveris를 찾을 수 없습니다. Audiveris를 설치하거나 설정에서 실행 경로를 지정하세요."
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = output_dir / "audiveris"
    raw_dir.mkdir(parents=True, exist_ok=True)
    try:
        run_command(
            command,
            ["-batch", "-transcribe", "-export", "-output", raw_dir, "--", source],
            cancel_event=cancel_event,
        )
    except CommandCancelled as exc:
        raise OMRImportCancelled("악보 이미지 인식을 취소했습니다.") from exc
    except CommandError as exc:
        raise OMRImportError(f"Audiveris OMR 실행에 실패했습니다.\n{exc}") from exc

    exported = _find_export(raw_dir)
    if exported is None:
        raise OMRImportError(
            "Audiveris가 MusicXML을 생성하지 않았습니다. 원본 해상도/대비 또는 악보 구조를 확인하세요."
        )
    normalized = normalize_musicxml(exported, output_dir / "score.musicxml")
    return OMRArtifacts(musicxml_path=normalized, source_path=source)


def copy_source_asset(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination

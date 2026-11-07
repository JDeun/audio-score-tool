from __future__ import annotations

import re
import shutil
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path
from threading import Event

from .runner import CommandCancelled, CommandError, command_exists, run_command

_MAX_MXL_MEMBERS = 2048
_MAX_CONTAINER_BYTES = 1024 * 1024
_MAX_MUSICXML_BYTES = 64 * 1024 * 1024
_MAX_MXL_TOTAL_UNCOMPRESSED = 256 * 1024 * 1024
_MAX_MXL_COMPRESSION_RATIO = 200

# Audiveris emits an ordinary MusicXML PUBLIC DTD in its exported MXL. The
# internal renderer/parser never needs it: strip only this known header and
# never let a DTD or entity declaration reach ElementTree. A directly uploaded
# MusicXML/MXL still rejects *all* DOCTYPE declarations.
_AUDIVERIS_MUSICXML_DTD = re.compile(
    r'<!DOCTYPE\s+(?P<root>score-(?:partwise|timewise))\s+PUBLIC\s+'
    r'(?P<quote>["\'])-//Recordare//DTD MusicXML [1-4](?:\.\d+){1,2} '
    r'(?P<kind>Partwise|Timewise)//EN(?P=quote)\s+'
    r'(?P<url_quote>["\'])https?://(?:www\.)?musicxml\.org/dtds/'
    r'(?P<url_kind>partwise|timewise)\.dtd(?P=url_quote)\s*>',
    re.IGNORECASE,
)


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


def _xml_safety_check(text: str) -> None:
    # Scan the complete bounded payload. Restricting this check to a prefix lets a crafted
    # document hide a declaration behind comments/whitespace while still reaching the XML
    # parser. MusicXML does not require DTD/entity declarations for this application.
    probe = text.upper()
    if "<!DOCTYPE" in probe or "<!ENTITY" in probe:
        raise OMRImportError("DOCTYPE/ENTITY가 포함된 XML은 안전을 위해 처리하지 않습니다.")


def _strip_audiveris_musicxml_dtd(text: str) -> str:
    """Remove only Audiveris's conventional top-level public MusicXML DTD.

    Even an otherwise valid DTD is never parsed or resolved. Internal subsets,
    entity declarations, altered external identifiers, and non-header DTDs are
    rejected, including when the source is a managed native executable.
    """
    upper = text.upper()
    if "<!DOCTYPE" not in upper:
        _xml_safety_check(text)
        return text
    if "<!ENTITY" in upper:
        raise OMRImportError("ENTITY 선언이 포함된 OMR 결과는 처리하지 않습니다.")

    matches = list(_AUDIVERIS_MUSICXML_DTD.finditer(text))
    if len(matches) != 1:
        raise OMRImportError("OMR 결과의 DOCTYPE이 지원하는 MusicXML PUBLIC DTD가 아닙니다.")
    declaration = matches[0]
    kind = declaration.group("root").rsplit("-", 1)[-1].lower()
    if kind != declaration.group("kind").lower() or kind != declaration.group("url_kind").lower():
        raise OMRImportError("OMR 결과의 MusicXML DTD 유형이 일치하지 않습니다.")
    if re.fullmatch(r"\s*(?:<\?xml\s+[^>]*\?>\s*)?", text[:declaration.start()]) is None:
        raise OMRImportError("OMR MusicXML DTD는 문서 헤더에서만 허용합니다.")

    cleaned = text[:declaration.start()] + text[declaration.end():]
    _xml_safety_check(cleaned)
    return cleaned


def _parse_bounded_xml(payload: bytes, *, context: str) -> ET.Element:
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise OMRImportError(f"{context} XML 인코딩을 읽을 수 없습니다.") from exc
    _xml_safety_check(text)
    try:
        return ET.fromstring(text)
    except ET.ParseError as exc:
        raise OMRImportError(f"{context} XML을 파싱할 수 없습니다: {exc}") from exc


def _is_musicxml(text: str) -> bool:
    try:
        _xml_safety_check(text)
        root = ET.fromstring(text)
    except (ET.ParseError, OMRImportError):
        return False
    return root.tag.rsplit("}", 1)[-1] in {"score-partwise", "score-timewise"}


def _read_zip_member(archive: zipfile.ZipFile, name: str, *, max_bytes: int) -> bytes:
    info = archive.getinfo(name)
    if info.flag_bits & 0x1:
        raise OMRImportError(f"암호화된 MXL 항목은 처리하지 않습니다: {name}")
    if info.file_size < 0 or info.file_size > max_bytes:
        raise OMRImportError(f"MXL 항목이 허용 크기를 초과합니다: {name}")
    if info.compress_size > 0 and info.file_size / info.compress_size > _MAX_MXL_COMPRESSION_RATIO:
        raise OMRImportError(f"MXL 항목의 압축률이 비정상적으로 높습니다: {name}")
    with archive.open(info, "r") as handle:
        payload = handle.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise OMRImportError(f"MXL 항목이 허용 크기를 초과합니다: {name}")
    return payload


def _musicxml_from_mxl(path: Path, *, audiveris_output: bool = False) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > _MAX_MXL_MEMBERS:
                raise OMRImportError("MXL archive에 비정상적으로 많은 항목이 있습니다.")
            total_uncompressed = sum(max(0, info.file_size) for info in infos)
            if total_uncompressed > _MAX_MXL_TOTAL_UNCOMPRESSED:
                raise OMRImportError("MXL archive의 압축 해제 크기가 허용 한도를 초과합니다.")

            candidates: list[str] = []
            try:
                container_payload = _read_zip_member(
                    archive,
                    "META-INF/container.xml",
                    max_bytes=_MAX_CONTAINER_BYTES,
                )
                container = _parse_bounded_xml(container_payload, context="MXL container")
                for node in container.iter():
                    if node.tag.rsplit("}", 1)[-1] == "rootfile":
                        full_path = node.attrib.get("full-path")
                        if full_path:
                            candidates.append(full_path)
            except (KeyError, OMRImportError):
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
                    text = _read_zip_member(
                        archive,
                        name,
                        max_bytes=_MAX_MUSICXML_BYTES,
                    ).decode("utf-8-sig")
                except (KeyError, UnicodeDecodeError, OMRImportError, RuntimeError):
                    continue
                if audiveris_output:
                    try:
                        text = _strip_audiveris_musicxml_dtd(text)
                    except OMRImportError:
                        continue
                if _is_musicxml(text):
                    return text
    except OMRImportError:
        raise
    except (OSError, zipfile.BadZipFile) as exc:
        raise OMRImportError(f"MXL 파일을 읽지 못했습니다: {exc}") from exc
    raise OMRImportError("MXL 안에서 유효한 MusicXML score를 찾지 못했습니다.")


def normalize_musicxml(
    source: Path, target: Path, *, audiveris_output: bool = False
) -> Path:
    if source.suffix.lower() == ".mxl":
        text = _musicxml_from_mxl(source, audiveris_output=audiveris_output)
    else:
        try:
            if source.stat().st_size > _MAX_MUSICXML_BYTES:
                raise OMRImportError("MusicXML 파일이 허용 크기를 초과합니다.")
            text = source.read_text(encoding="utf-8-sig")
        except OMRImportError:
            raise
        except (OSError, UnicodeDecodeError) as exc:
            raise OMRImportError(f"MusicXML을 읽지 못했습니다: {exc}") from exc
        if audiveris_output:
            text = _strip_audiveris_musicxml_dtd(text)
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
                _musicxml_from_mxl(candidate, audiveris_output=True)
                return candidate
            if candidate.stat().st_size <= _MAX_MUSICXML_BYTES:
                text = _strip_audiveris_musicxml_dtd(
                    candidate.read_text(encoding="utf-8-sig")
                )
                if _is_musicxml(text):
                    return candidate
        except (OSError, UnicodeDecodeError, OMRImportError):
            continue
    return None


def _invalid_mxl_diagnostics(root: Path) -> list[dict[str, object]]:
    """Describe rejected Audiveris XML metadata, never store user score text.

    Some upstream Audiveris outputs are syntactically valid MXL archives but
    use a MusicXML header variant rejected by the strict importer. Diagnose
    that precisely without bypassing the XML/DOCTYPE/ENTITY safety boundary.
    """
    details: list[dict[str, object]] = []
    for source in sorted(root.rglob("*.mxl"))[:3]:
        if source.is_symlink() or not source.is_file():
            continue
        try:
            with zipfile.ZipFile(source) as archive:
                for info in archive.infolist()[:80]:
                    if not info.filename.lower().endswith((".xml", ".musicxml")):
                        continue
                    diagnostic: dict[str, object] = {
                        "member_basename": Path(info.filename).name[:90],
                        "member_bytes": info.file_size,
                        "compressed_bytes": info.compress_size,
                        "ratio": round(info.file_size / max(info.compress_size, 1), 1),
                    }
                    try:
                        xml = _read_zip_member(
                            archive, info.filename, max_bytes=_MAX_MUSICXML_BYTES
                        ).decode("utf-8-sig")
                        diagnostic["has_doctype"] = "<!DOCTYPE" in xml.upper()
                        diagnostic["has_entity"] = "<!ENTITY" in xml.upper()
                        if not diagnostic["has_doctype"] and not diagnostic["has_entity"]:
                            try:
                                candidate = ET.fromstring(xml)
                                diagnostic["root"] = candidate.tag.rsplit("}", 1)[-1][:60]
                            except ET.ParseError:
                                diagnostic["xml_parse_failed"] = True
                    except (OSError, UnicodeError, RuntimeError, OMRImportError) as exc:
                        diagnostic["rejected"] = type(exc).__name__
                        diagnostic["reason"] = str(exc)[:170]
                    details.append(diagnostic)
        except (OSError, zipfile.BadZipFile):
            details.append({"archive": source.name[:90], "rejected": "malformed-zip"})
    return details


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
            "OMR 구성요소를 찾을 수 없습니다. Setup Center에서 OMR 구성요소 상태를 확인하세요."
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = output_dir / "audiveris"
    raw_dir.mkdir(parents=True, exist_ok=True)
    try:
        completed = run_command(
            command,
            ["-batch", "-transcribe", "-export", "-output", raw_dir, "--", source],
            cancel_event=cancel_event,
        )
    except CommandCancelled as exc:
        raise OMRImportCancelled("악보 이미지 인식을 취소했습니다.") from exc
    except CommandError as exc:
        raise OMRImportError(f"OMR 실행에 실패했습니다.\n{exc}") from exc

    exported = _find_export(raw_dir)
    if exported is None:
        # Some Audiveris versions return process status 0 even when no score
        # reached the export step. Preserve a bounded diagnostic log tail and
        # filename-only output listing instead of reporting a false success
        # or losing the actual OMR recognition failure reason.
        generated = sorted(
            path.name for path in raw_dir.iterdir() if path.is_file() and not path.is_symlink()
        )[:24]
        output_tail = (completed.stdout or "")[-3500:]
        candidate_diagnostics = _invalid_mxl_diagnostics(raw_dir)
        raise OMRImportError(
            "OMR 구성요소에서 유효하게 정규화할 수 있는 MusicXML 결과를 찾지 못했습니다. "
            "원본 악보 및 결과 XML 형식/보안 선언을 확인하세요."
            f"\nAudiveris files: {generated}"
            f"\nAudiveris MXL validation diagnostics: {candidate_diagnostics}"
            f"\nAudiveris log tail (bounded):\n{output_tail}"
        )
    normalized = normalize_musicxml(
        exported, output_dir / "score.musicxml", audiveris_output=True
    )
    return OMRArtifacts(musicxml_path=normalized, source_path=source)


def copy_source_asset(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination

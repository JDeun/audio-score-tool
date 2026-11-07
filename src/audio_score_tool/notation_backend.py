from __future__ import annotations

import math
import shutil
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from xml.dom import minidom

from .config import Settings


class NotationBackendError(RuntimeError):
    pass


class NotationBackendUnavailable(NotationBackendError):
    pass


@dataclass(slots=True)
class NotationBackendStatus:
    music21: bool
    verovio: bool
    fpdf2: bool

    def as_dict(self) -> dict[str, bool]:
        return {
            "music21": self.music21,
            "verovio": self.verovio,
            "fpdf2": self.fpdf2,
        }


def music21_available() -> bool:
    try:
        import music21  # noqa: F401
    except ImportError:
        return False
    return True


def _verovio_resource_path() -> Path | None:
    try:
        import verovio
    except ImportError:
        return None
    module_file = getattr(verovio, "__file__", None)
    if not module_file:
        return None
    path = Path(module_file).resolve().parent / "data"
    return path if path.is_dir() else None


def verovio_available() -> bool:
    return _verovio_resource_path() is not None


def fpdf2_available() -> bool:
    try:
        from fpdf import FPDF  # noqa: F401
    except ImportError:
        return False
    return True


def backend_status(_settings: Settings | None = None) -> dict[str, bool]:
    return NotationBackendStatus(
        music21=music21_available(),
        verovio=verovio_available(),
        fpdf2=fpdf2_available(),
    ).as_dict()


def midi_to_musicxml(source: Path, target: Path) -> Path:
    if not music21_available():
        raise NotationBackendUnavailable("MIDI→MusicXML 변환에는 music21이 필요합니다.")
    try:
        from music21 import converter

        score = converter.parse(str(source))
        target.parent.mkdir(parents=True, exist_ok=True)
        written = score.write("musicxml", fp=str(target))
    except Exception as exc:
        raise NotationBackendError(f"music21 MIDI→MusicXML 변환 실패: {exc}") from exc
    result = Path(str(written)) if written else target
    if result.is_file() and not (target.is_file() and result.samefile(target)):
        shutil.copy2(result, target)
    if not target.is_file():
        raise NotationBackendError("music21이 MusicXML을 생성하지 않았습니다.")
    return target


def musicxml_to_midi(source: Path, target: Path) -> Path:
    if not music21_available():
        raise NotationBackendUnavailable("MusicXML→MIDI 변환에는 music21이 필요합니다.")
    try:
        from music21 import converter

        score = converter.parse(str(source))
        target.parent.mkdir(parents=True, exist_ok=True)
        written = score.write("midi", fp=str(target))
    except Exception as exc:
        raise NotationBackendError(f"music21 MusicXML→MIDI 변환 실패: {exc}") from exc
    result = Path(str(written)) if written else target
    if result.is_file() and not (target.is_file() and result.samefile(target)):
        shutil.copy2(result, target)
    if not target.is_file():
        raise NotationBackendError("music21이 MIDI를 생성하지 않았습니다.")
    return target


def _svg_dimensions_mm(svg_text: str) -> tuple[float, float]:
    try:
        root = ET.fromstring(svg_text)
    except ET.ParseError as exc:
        raise NotationBackendError(f"Verovio SVG 파싱 실패: {exc}") from exc

    view_box = (root.get("viewBox") or "").replace(",", " ").split()
    if len(view_box) == 4:
        try:
            width = float(view_box[2])
            height = float(view_box[3])
        except ValueError:
            width = height = 0.0
        if width > 0 and height > 0:
            page_width_mm = 210.0
            return page_width_mm, page_width_mm * height / width

    def _number(value: str | None) -> float | None:
        if not value:
            return None
        cleaned = value.strip().lower()
        for suffix in ("px", "pt", "mm", "cm", "in"):
            if cleaned.endswith(suffix):
                cleaned = cleaned[: -len(suffix)]
                break
        try:
            result = float(cleaned)
        except ValueError:
            return None
        return result if result > 0 else None

    width = _number(root.get("width"))
    height = _number(root.get("height"))
    if width and height:
        page_width_mm = 210.0
        return page_width_mm, page_width_mm * height / width
    return 210.0, 297.0


def _normalize_verovio_svg_for_fpdf2(svg_text: str) -> str:
    """Flatten Verovio's full-page nested SVG without rasterizing its paths.

    Verovio 6.3 emits an outer page SVG (viewBox 2100x2970) with a second,
    child SVG (viewBox 21000x29700). fpdf2 does not support nested <svg>:
    it silently drops ALL inner music content, yielding a valid but blank
    score PDF. Replace that single nested viewport with an ordinary SVG
    group carrying its exact viewBox coordinate transform, preserving
    original vector paths, glyph <defs>/<use>, styles and stroke widths.

    Fail closed if a future Verovio release changes this structure rather
    than silently issuing another blank PDF.
    """
    try:
        document = minidom.parseString(svg_text)
    except Exception as exc:
        raise NotationBackendError("Verovio SVG 구조를 읽지 못했습니다.") from exc
    root = document.documentElement
    if root.localName != "svg" or not root.namespaceURI:
        raise NotationBackendError("Verovio SVG root가 유효하지 않습니다.")
    embedded = [
        node
        for node in document.getElementsByTagNameNS(root.namespaceURI, "svg")
        if node is not root
    ]
    if not embedded:
        return svg_text
    if len(embedded) != 1 or embedded[0].parentNode is not root:
        raise NotationBackendError("지원되지 않는 중첩 Verovio SVG 구조입니다.")
    inner = embedded[0]
    # A nested 100%-size viewport without offsets is the only known
    # Verovio page output. Unsupported viewport layout is NOT guessed.
    if any(inner.hasAttribute(key) for key in ("x", "y", "width", "height")):
        raise NotationBackendError("지원되지 않는 중첩 SVG 위치·크기 속성입니다.")

    def parse_view_box(node) -> tuple[float, float, float, float]:
        try:
            values = [
                float(part)
                for part in node.getAttribute("viewBox").replace(",", " ").split()
            ]
        except ValueError as exc:
            raise NotationBackendError("Verovio SVG viewBox 값이 유효하지 않습니다.") from exc
        if (
            len(values) != 4
            or any(not math.isfinite(item) for item in values)
            or values[2] <= 0 or values[3] <= 0
        ):
            raise NotationBackendError("Verovio SVG viewBox의 크기가 유효하지 않습니다.")
        return values[0], values[1], values[2], values[3]

    outer_x, outer_y, outer_width, outer_height = parse_view_box(root)
    inner_x, inner_y, inner_width, inner_height = parse_view_box(inner)
    sx = outer_width / inner_width
    sy = outer_height / inner_height
    if not math.isclose(sx, sy, rel_tol=1e-7, abs_tol=1e-10):
        raise NotationBackendError(
            "중첩 SVG의 가로·세로 확대 비율이 달라 벡터 악보를 안전하게 변환할 수 없습니다."
        )
    tx = outer_x - inner_x * sx
    ty = outer_y - inner_y * sy
    group = document.createElementNS(root.namespaceURI, "g")
    group.setAttribute("transform", f"matrix({sx:.12g} 0 0 {sy:.12g} {tx:.12g} {ty:.12g})")
    while inner.firstChild is not None:
        group.appendChild(inner.firstChild)
    root.replaceChild(group, inner)
    return document.toxml()


def _verovio_toolkit():
    import verovio

    resource_path = _verovio_resource_path()
    if resource_path is None:
        raise NotationBackendUnavailable("Verovio font resource가 앱에 포함되지 않았습니다.")

    toolkit = verovio.toolkit(False)
    if toolkit.setResourcePath(str(resource_path)) is False:
        raise NotationBackendUnavailable(
            f"Verovio font resource를 초기화하지 못했습니다: {resource_path}"
        )
    return toolkit


def musicxml_to_pdf_embedded(
    source: Path,
    target: Path,
    *,
    cancel_event: Event | None = None,
) -> Path:
    if cancel_event is not None and cancel_event.is_set():
        raise NotationBackendError("PDF 생성이 취소되었습니다.")
    if not verovio_available() or not fpdf2_available():
        raise NotationBackendUnavailable(
            "내장 PDF renderer를 사용할 수 없습니다. verovio와 fpdf2가 앱에 포함되어야 합니다."
        )

    try:
        from fpdf import FPDF

        toolkit = _verovio_toolkit()
        toolkit.setOptions(
            {
                "inputFrom": "musicxml",
                "breaks": "encoded",
                "svgViewBox": True,
                "svgFormatRaw": True,
            }
        )
        loaded = toolkit.loadFile(str(source))
        if loaded is False:
            raise NotationBackendError("Verovio가 MusicXML을 읽지 못했습니다.")
        page_count = int(toolkit.getPageCount())
        if page_count < 1:
            raise NotationBackendError("Verovio가 렌더링할 페이지를 만들지 못했습니다.")

        target.parent.mkdir(parents=True, exist_ok=True)
        pdf = FPDF(unit="mm")
        pdf.set_auto_page_break(False)
        with tempfile.TemporaryDirectory(prefix="audioscore-verovio-") as raw_work:
            work = Path(raw_work)
            for page_number in range(1, page_count + 1):
                if cancel_event is not None and cancel_event.is_set():
                    raise NotationBackendError("PDF 생성이 취소되었습니다.")
                svg_text = toolkit.renderToSVG(page_number)
                if not svg_text.strip():
                    raise NotationBackendError(
                        f"Verovio가 {page_number}페이지 SVG를 생성하지 않았습니다."
                    )
                svg_text = _normalize_verovio_svg_for_fpdf2(svg_text)
                width_mm, height_mm = _svg_dimensions_mm(svg_text)
                svg_path = work / f"page-{page_number}.svg"
                svg_path.write_text(svg_text, encoding="utf-8")
                pdf.add_page(format=(width_mm, height_mm))
                pdf.image(str(svg_path), x=0, y=0, w=width_mm, h=height_mm)
        pdf.output(str(target))
    except (NotationBackendError, NotationBackendUnavailable):
        raise
    except Exception as exc:
        raise NotationBackendError(f"내장 PDF 생성 실패: {exc}") from exc

    if not target.is_file() or target.stat().st_size < 5:
        raise NotationBackendError("내장 renderer가 PDF를 생성하지 않았습니다.")
    if not target.read_bytes()[:5] == b"%PDF-":
        raise NotationBackendError("생성된 파일이 유효한 PDF가 아닙니다.")
    return target


def render_pdf(
    source: Path,
    target: Path,
    *,
    settings: Settings | None = None,
    cancel_event: Event | None = None,
) -> tuple[Path, str]:
    """Render a PDF entirely inside the packaged application runtime."""

    del settings
    return (
        musicxml_to_pdf_embedded(source, target, cancel_event=cancel_event),
        "verovio-fpdf2",
    )

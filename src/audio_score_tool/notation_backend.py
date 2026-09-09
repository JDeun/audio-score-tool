from __future__ import annotations

import shutil
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from threading import Event

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
    if result != target and result.is_file():
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
    if result != target and result.is_file():
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

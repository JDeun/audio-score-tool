from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from threading import Event

from .config import Settings
from .runner import CommandCancelled, CommandError, command_exists, run_command


class NotationBackendError(RuntimeError):
    pass


class NotationBackendUnavailable(NotationBackendError):
    pass


@dataclass(slots=True)
class NotationBackendStatus:
    music21: bool
    lilypond: bool
    musicxml2ly: bool
    musescore: bool

    def as_dict(self) -> dict[str, bool]:
        return {
            "music21": self.music21,
            "lilypond": self.lilypond,
            "musicxml2ly": self.musicxml2ly,
            "musescore": self.musescore,
        }


def music21_available() -> bool:
    try:
        import music21  # noqa: F401
    except ImportError:
        return False
    return True


def _resolve_musescore(settings: Settings) -> str | None:
    if settings.musescore_cmd and command_exists(settings.musescore_cmd):
        return settings.musescore_cmd
    candidates = ("mscore", "musescore", "MuseScore4", "musescore4", "MuseScore")
    for candidate in candidates:
        if shutil.which(candidate):
            return candidate
    mac = Path("/Applications/MuseScore 4.app/Contents/MacOS/mscore")
    if mac.is_file():
        return str(mac)
    return None


def backend_status(settings: Settings) -> dict[str, bool]:
    return NotationBackendStatus(
        music21=music21_available(),
        lilypond=command_exists(settings.lilypond_cmd),
        musicxml2ly=command_exists(settings.musicxml2ly_cmd),
        musescore=_resolve_musescore(settings) is not None,
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


def musicxml_to_pdf_lilypond(
    source: Path,
    target: Path,
    *,
    settings: Settings,
    cancel_event: Event | None = None,
) -> Path:
    if not command_exists(settings.musicxml2ly_cmd) or not command_exists(settings.lilypond_cmd):
        raise NotationBackendUnavailable(
            "LilyPond PDF backend에는 musicxml2ly와 lilypond 실행 파일이 필요합니다."
        )
    work = target.parent / ".lilypond-work"
    work.mkdir(parents=True, exist_ok=True)
    ly_path = work / "score.ly"
    output_base = work / "score"
    try:
        run_command(
            settings.musicxml2ly_cmd,
            ["-o", ly_path, source],
            cwd=work,
            cancel_event=cancel_event,
        )
        run_command(
            settings.lilypond_cmd,
            ["--pdf", "-o", output_base, ly_path],
            cwd=work,
            cancel_event=cancel_event,
        )
    except CommandCancelled:
        raise
    except CommandError as exc:
        raise NotationBackendError(f"LilyPond PDF 생성 실패:\n{exc}") from exc

    generated = output_base.with_suffix(".pdf")
    if not generated.is_file():
        raise NotationBackendError("LilyPond가 PDF를 생성하지 않았습니다.")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(generated, target)
    return target


def convert_with_musescore(
    source: Path,
    target: Path,
    *,
    settings: Settings,
    cancel_event: Event | None = None,
) -> Path:
    command = _resolve_musescore(settings)
    if not command:
        raise NotationBackendUnavailable("MuseScore를 찾을 수 없습니다.")
    try:
        run_command(command, ["-o", target, source], cancel_event=cancel_event)
    except CommandError as exc:
        raise NotationBackendError(f"MuseScore 변환 실패:\n{exc}") from exc
    if not target.is_file():
        raise NotationBackendError(f"MuseScore가 {target.name}을 생성하지 않았습니다.")
    return target


def render_pdf(
    source: Path,
    target: Path,
    *,
    settings: Settings,
    cancel_event: Event | None = None,
) -> tuple[Path, str]:
    """Render PDF without making MuseScore mandatory."""

    if command_exists(settings.musicxml2ly_cmd) and command_exists(settings.lilypond_cmd):
        return (
            musicxml_to_pdf_lilypond(
                source,
                target,
                settings=settings,
                cancel_event=cancel_event,
            ),
            "lilypond",
        )
    if _resolve_musescore(settings):
        return (
            convert_with_musescore(
                source,
                target,
                settings=settings,
                cancel_event=cancel_event,
            ),
            "musescore",
        )
    raise NotationBackendUnavailable(
        "PDF 생성 backend가 없습니다. LilyPond를 설치하거나 선택적으로 MuseScore를 지정하세요."
    )

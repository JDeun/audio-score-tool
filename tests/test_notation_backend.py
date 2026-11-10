import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from audio_score_tool.notation_backend import (
    NotationBackendError,
    _normalize_verovio_svg_for_fpdf2,
    backend_status,
    render_pdf,
)

SIMPLE_SCORE = """<?xml version='1.0' encoding='UTF-8'?>
<score-partwise version='4.0'>
  <part-list>
    <score-part id='P1'><part-name>Piano</part-name></score-part>
  </part-list>
  <part id='P1'>
    <measure number='1'>
      <attributes>
        <divisions>1</divisions>
        <key><fifths>0</fifths></key>
        <time><beats>4</beats><beat-type>4</beat-type></time>
        <clef><sign>G</sign><line>2</line></clef>
      </attributes>
      <note>
        <pitch><step>C</step><octave>4</octave></pitch>
        <duration>4</duration><type>whole</type>
      </note>
    </measure>
  </part>
</score-partwise>
"""


def test_backend_status_has_only_embedded_notation_dependencies(monkeypatch):
    monkeypatch.setattr("audio_score_tool.notation_backend.music21_available", lambda: True)
    monkeypatch.setattr("audio_score_tool.notation_backend.verovio_available", lambda: True)
    monkeypatch.setattr("audio_score_tool.notation_backend.fpdf2_available", lambda: True)

    status = backend_status()

    assert status == {"music21": True, "verovio": True, "fpdf2": True}
    assert "musescore" not in status
    assert "lilypond" not in status
    assert "musicxml2ly" not in status


def test_render_pdf_is_self_contained(tmp_path: Path):
    source = tmp_path / "score.musicxml"
    source.write_text(SIMPLE_SCORE, encoding="utf-8")
    target = tmp_path / "score.pdf"

    result, renderer = render_pdf(source, target)

    assert result == target
    assert renderer == "verovio-fpdf2"
    assert target.read_bytes().startswith(b"%PDF-")
    assert target.stat().st_size > 500
    assert not list(tmp_path.glob("*.ly"))


@pytest.mark.parametrize("render_fails", [False, True])
def test_pdf_closes_font_files_before_temporary_directory_cleanup(tmp_path, monkeypatch, render_fails):
    import tempfile

    from fpdf import FPDF

    from audio_score_tool import notation_backend

    documents = []

    class TrackedPDF(FPDF):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            documents.append(self)

        def image(self, *args, **kwargs):
            if render_fails:
                raise ValueError("render failure")
            return super().image(*args, **kwargs)

    class WindowsDirectory(tempfile.TemporaryDirectory):
        def __exit__(self, *args):
            # Simulate Windows refusing to remove an open font file.
            assert documents[0].fonts
            assert all(font.ttfont.reader is None for font in documents[0].fonts.values())
            return super().__exit__(*args)

    monkeypatch.setattr("fpdf.FPDF", TrackedPDF)
    monkeypatch.setattr(notation_backend.tempfile, "TemporaryDirectory", WindowsDirectory)
    source = tmp_path / "score.musicxml"
    source.write_text(SIMPLE_SCORE, encoding="utf-8")
    if render_fails:
        with pytest.raises(NotationBackendError, match="render failure"):
            render_pdf(source, tmp_path / "score.pdf")
    else:
        render_pdf(source, tmp_path / "score.pdf")


def test_pdf_preserves_unicode_punctuation_and_printed_metronome(tmp_path, caplog):
    source = tmp_path / "unicode.musicxml"
    source.write_text(SIMPLE_SCORE.replace(
        "<part-name>Piano</part-name>",
        "<part-name>Piano – étude</part-name>",
    ).replace(
        "      <note>",
        "      <direction><direction-type><metronome><beat-unit>quarter</beat-unit>"
        "<per-minute>90</per-minute></metronome></direction-type>"
        "<sound tempo='90'/></direction>\n      <note>",
    ), encoding="utf-8")
    original = source.read_bytes()
    target, _ = render_pdf(source, tmp_path / "unicode.pdf")
    assert target.read_bytes().startswith(b"%PDF-")
    assert target.stat().st_size > 1000
    assert source.read_bytes() == original
    assert "missing the following glyphs" not in caplog.text


def test_pdf_embeds_bundled_korean_font_without_system_font_installation(tmp_path, caplog):
    source = tmp_path / "korean.musicxml"
    source.write_text(SIMPLE_SCORE.replace(
        "<part-name>Piano</part-name>", "<part-name>보컬 멜로디</part-name>",
    ).replace(
        "  <part-list>", "  <work><work-title>한글 제목</work-title></work><part-list>",
    ).replace(
        "<duration>4</duration><type>whole</type>",
        "<duration>4</duration><type>whole</type><lyric><text>한글 가사</text></lyric>",
    ), encoding="utf-8")
    target, _ = render_pdf(source, tmp_path / "korean.pdf")
    payload = target.read_bytes()
    assert payload.startswith(b"%PDF-")
    assert b"NotoSansKR" in payload
    assert "missing the following glyphs" not in caplog.text


def test_svg_child_music_font_and_size_override_inherited_text_style():
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
           '<text font-family="Liberation" font-size="0px">'
           '<tspan><tspan font-family="Leipzig" font-size="20px">&#xECA5;</tspan></tspan>'
           '</text></svg>')
    root = ET.fromstring(_normalize_verovio_svg_for_fpdf2(svg))
    child = root.find(".//{http://www.w3.org/2000/svg}tspan")
    assert child.get("font-family") == "Leipzig"
    assert child.get("font-size") == "20px"
    assert len(root.findall(".//{http://www.w3.org/2000/svg}tspan")) == 1


def test_svg_nested_title_keeps_center_anchor_and_initial_coordinates():
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
           '<text font-size="0px"><tspan x="50" y="10" text-anchor="middle">'
           '<tspan font-size="12px">Title</tspan></tspan></text></svg>')
    root = ET.fromstring(_normalize_verovio_svg_for_fpdf2(svg))
    text = root.find("{http://www.w3.org/2000/svg}text")
    assert (text.get("x"), text.get("y"), text.get("text-anchor")) == ("50", "10", "middle")


def test_music21_export_skips_same_file_with_relative_target(tmp_path: Path, monkeypatch):
    """music21 may return an absolute path even when fp is relative."""
    from music21 import converter

    from audio_score_tool.notation_backend import midi_to_musicxml, musicxml_to_midi

    class FakeScore:
        metadata = None

        def recurse(self):
            from music21 import stream
            return stream.Score().recurse()

        def write(self, fmt: str, fp: str) -> str:
            written = Path(fp).resolve()
            written.write_text(fmt, encoding="utf-8")
            return str(written)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(converter, "parse", lambda _: FakeScore())
    monkeypatch.setattr(
        "audio_score_tool.midi_score_import.midi_to_score_xml",
        lambda _source, target: FakeScore().write("musicxml", str(target)),
    )
    monkeypatch.setattr("audio_score_tool.midi_channels.preserve_program_channels", lambda _: None)

    def forbidden_copy(*_args, **_kwargs):
        raise AssertionError("An export must not copy a file onto itself")

    monkeypatch.setattr("audio_score_tool.notation_backend.shutil.copy2", forbidden_copy)
    for export, suffix in ((midi_to_musicxml, "musicxml"), (musicxml_to_midi, "mid")):
        source = tmp_path / "input"
        source.write_text("source", encoding="utf-8")
        target = Path("out") / f"score.{suffix}"
        target.parent.mkdir(parents=True, exist_ok=True)
        assert export(source, target) == target
        assert target.read_text(encoding="utf-8")



def test_verovio_nested_svg_is_flattened_preserving_vector_paths_and_glyph_links():
    original = """<svg viewBox="0 0 2100 2970"
        xmlns="http://www.w3.org/2000/svg"
        xmlns:xlink="http://www.w3.org/1999/xlink">
        <defs><g id="owned-glyph"><path d="M 0 0 L 100 0" /></g></defs>
        <style>path { fill: #000; }</style>
        <svg viewBox="0 0 21000 29700" font-family="Liberation, serif">
          <g><path d="M 100 200 L 20000 200" stroke="black"/>
          <use xlink:href="#owned-glyph"/></g>
        </svg>
      </svg>"""
    converted = _normalize_verovio_svg_for_fpdf2(original)
    root = ET.fromstring(converted)
    namespace = "{http://www.w3.org/2000/svg}"
    assert root.tag == namespace + "svg"
    assert len(root.findall(f".//{namespace}svg")) == 0
    groups = root.findall(f"./{namespace}g")
    assert len(groups) == 1
    assert groups[0].get("transform") == "matrix(0.1 0 0 0.1 0 0)"
    assert groups[0].get("font-family") == "Liberation, serif"
    assert len(root.findall(f".//{namespace}path")) == 2
    assert len(root.findall(f".//{namespace}use")) == 1
    assert root.find(f"./{namespace}defs") is not None


def test_verovio_simple_svg_is_left_unmodified():
    original = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
                '<path d="M 0 0 L 10 10"/></svg>')
    assert _normalize_verovio_svg_for_fpdf2(original) == original


@pytest.mark.parametrize("nested_svg", [
    '<svg viewBox="0 0 20000 29700"><path d="M 0 0 L 1 1"/></svg>',
    '<svg viewBox="0 0 0 0"><path d="M 0 0 L 1 1"/></svg>',
    '<svg x="5" viewBox="0 0 21000 29700"><path d="M 0 0 L 1 1"/></svg>',
    '<svg viewBox="0 0 21000 29700"><svg viewBox="0 0 21000 29700"/></svg>',
])
def test_verovio_unsupported_nested_viewport_fails_instead_of_blank_pdf(nested_svg: str):
    source = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 2100 2970">'
        + nested_svg + "</svg>"
    )
    with pytest.raises(NotationBackendError, match="중첩 SVG|Verovio SVG"):
        _normalize_verovio_svg_for_fpdf2(source)


def test_verovio_nested_viewbox_offset_translation_is_not_discarded():
    original = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="2 3 2100 2970">'
        '<svg viewBox="100 200 21000 29700"><path d="M 0 0"/></svg></svg>'
    )
    root = ET.fromstring(_normalize_verovio_svg_for_fpdf2(original))
    converted = list(root)[0]
    assert converted.get("transform") == "matrix(0.1 0 0 0.1 -8 -17)"


@pytest.mark.parametrize('microseconds', [1, 0xFFFFFF])
def test_midi_tempo_valid_24_bit_boundaries(tmp_path, microseconds):
    import mido
    from music21 import note, stream, tempo

    from audio_score_tool.notation_backend import musicxml_to_midi

    score = stream.Score()
    part = stream.Part()
    part.append(tempo.MetronomeMark(number=60_000_000 / microseconds))
    part.append(note.Note('C4', quarterLength=1))
    score.insert(0, part)
    source = tmp_path / 'source.musicxml'
    score.write('musicxml', fp=str(source))
    midi = musicxml_to_midi(source, tmp_path / 'result.mid')
    assert [m.tempo for m in mido.MidiFile(midi) if m.type == 'set_tempo'] == [microseconds]


@pytest.mark.parametrize("bpm", [60 / 18.6, 120_000_001])
def test_midi_tempo_rejects_overflow_without_overwriting_target(tmp_path, bpm):
    from music21 import note, stream, tempo

    from audio_score_tool.notation_backend import musicxml_to_midi

    score = stream.Score()
    part = stream.Part()
    mark = tempo.MetronomeMark(number=bpm)
    mark.style.hideObjectOnPrint = True
    part.append(mark)
    part.append(note.Note('C4', quarterLength=1))
    score.insert(0, part)
    source = tmp_path / 'source.musicxml'
    score.write('musicxml', fp=str(source))
    original = source.read_bytes()
    target = tmp_path / 'result.mid'
    target.write_bytes(b'previous output')
    with pytest.raises(NotationBackendError, match='24-bit'):
        musicxml_to_midi(source, target)
    assert target.read_bytes() == b'previous output' and source.read_bytes() == original


def test_midi_tempo_multiple_normal_events(tmp_path):
    import mido
    from music21 import note, stream, tempo

    from audio_score_tool.notation_backend import musicxml_to_midi

    score = stream.Score()
    part = stream.Part()
    for bpm in (120, 90):
        part.append(tempo.MetronomeMark(number=bpm))
        part.append(note.Note('C4', quarterLength=1))
    score.insert(0, part)
    source = tmp_path / 'source.musicxml'
    score.write('musicxml', fp=str(source))
    midi = musicxml_to_midi(source, tmp_path / 'result.mid')
    assert [m.tempo for m in mido.MidiFile(midi) if m.type == 'set_tempo'] == [500000, 666667]


def test_no_chord_render_copy_preserves_offset_staff_and_original(tmp_path):
    import xml.etree.ElementTree as ET

    from audio_score_tool.notation_backend import _no_chord_render_copy

    source = tmp_path / 'source.musicxml'
    source.write_text('<score-partwise><part><measure><harmony placement="below">'
                      '<root><root-step text="">C</root-step></root><kind text="N.C.">none</kind>'
                      '<offset>7</offset><staff>2</staff></harmony></measure></part></score-partwise>')
    before = source.read_bytes()
    converted = ET.fromstring(_no_chord_render_copy(source))
    assert converted.find('.//harmony') is None
    direction = converted.find('.//direction')
    assert direction.get('placement') == 'below'
    assert direction.findtext('./direction-type/words') == 'N.C.'
    assert direction.findtext('offset') == '7' and direction.findtext('staff') == '2'
    assert source.read_bytes() == before


def test_no_chord_render_copy_supports_utf16_and_custom_visibility(tmp_path):
    import xml.etree.ElementTree as ET

    from audio_score_tool.notation_backend import _no_chord_render_copy

    source = tmp_path / 'source.musicxml'
    text = '''<?xml version="1.0" encoding="UTF-16"?><score-partwise><part><measure>
      <harmony font-weight="bold" color="#123456"><root><root-step text="">C</root-step></root><kind text="Break">none</kind><offset>3</offset><staff>2</staff></harmony>
      <harmony print-object="no"><root><root-step text="">C</root-step></root><kind text="Hidden">none</kind></harmony>
      <harmony><root><root-step text="">C</root-step></root><kind text="">none</kind></harmony>
      </measure></part></score-partwise>'''
    source.write_bytes(text.encode('utf-16'))
    before = source.read_bytes()
    copy = ET.fromstring(_no_chord_render_copy(source))
    words = copy.findall('.//direction/direction-type/words')
    assert len(words) == 1 and words[0].text == 'Break'
    assert words[0].get('font-weight') == 'bold' and words[0].get('color') == '#123456'
    assert copy.findtext('.//direction/offset') == '3' and copy.findtext('.//direction/staff') == '2'
    assert not copy.findall('.//harmony') and source.read_bytes() == before
    compressed = tmp_path / 'legacy.mxl'
    assert _no_chord_render_copy(compressed) is None

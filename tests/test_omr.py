from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from audio_score_tool.omr import normalize_musicxml


SCORE = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list>
  <part id="P1"><measure number="1"><note><rest/><duration>4</duration><type>whole</type></note></measure></part>
</score-partwise>
"""


def test_normalize_plain_musicxml(tmp_path: Path):
    source = tmp_path / "source.musicxml"
    source.write_text(SCORE, encoding="utf-8")
    target = tmp_path / "score.musicxml"

    assert normalize_musicxml(source, target) == target
    assert "score-partwise" in target.read_text(encoding="utf-8")


def test_normalize_compressed_mxl(tmp_path: Path):
    source = tmp_path / "score.mxl"
    with ZipFile(source, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
            <container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
              <rootfiles><rootfile full-path="music/score.xml" media-type="application/vnd.recordare.musicxml+xml"/></rootfiles>
            </container>""",
        )
        archive.writestr("music/score.xml", SCORE)

    target = tmp_path / "normalized.musicxml"
    normalize_musicxml(source, target)
    assert "Piano" in target.read_text(encoding="utf-8")

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from audio_score_tool.omr import OMRImportError, normalize_musicxml

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


def test_musicxml_rejects_doctype_entity_payload(tmp_path: Path):
    source = tmp_path / "unsafe.musicxml"
    source.write_text(
        """<?xml version="1.0"?>
        <!DOCTYPE score-partwise [<!ENTITY boom "boom">]>
        <score-partwise><part-list/></score-partwise>""",
        encoding="utf-8",
    )

    with pytest.raises(OMRImportError):
        normalize_musicxml(source, tmp_path / "normalized.musicxml")


def test_mxl_rejects_excessive_member_count(tmp_path: Path):
    source = tmp_path / "many.mxl"
    with ZipFile(source, "w", ZIP_DEFLATED) as archive:
        archive.writestr("META-INF/container.xml", "<container/>")
        for index in range(2050):
            archive.writestr(f"junk/{index}.txt", "x")
        archive.writestr("score.musicxml", SCORE)

    with pytest.raises(OMRImportError):
        normalize_musicxml(source, tmp_path / "normalized.musicxml")


_AUDIVERIS_DTD = (
    '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0.3 Partwise//EN" '
    '"http://www.musicxml.org/dtds/partwise.dtd">'
)


def _write_audiveris_mxl(destination: Path, score: str) -> None:
    with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "META-INF/container.xml",
            '<container><rootfiles><rootfile full-path="score.xml"/></rootfiles></container>',
        )
        archive.writestr("score.xml", score)


@pytest.mark.parametrize("version", ["4.0", "4.0.3"])
@pytest.mark.parametrize("suffix", [".musicxml", ".mxl"])
def test_only_native_omr_results_strip_known_musicxml_public_dtd(
    tmp_path: Path, suffix: str, version: str,
):
    score = SCORE.replace(
        "<score-partwise",
        _AUDIVERIS_DTD.replace("4.0.3", version) + "\n<score-partwise",
    )
    source = tmp_path / f"audiveris{suffix}"
    if suffix == ".mxl":
        _write_audiveris_mxl(source, score)
    else:
        source.write_text(score, encoding="utf-8")

    # Direct notation imports remain strict even for an apparently standard DTD.
    with pytest.raises(OMRImportError):
        normalize_musicxml(source, tmp_path / "direct.musicxml")

    normalized = tmp_path / "omr.musicxml"
    assert normalize_musicxml(source, normalized, audiveris_output=True) == normalized
    data = normalized.read_text(encoding="utf-8")
    assert "<!DOCTYPE" not in data
    assert "<!ENTITY" not in data
    assert "<score-partwise" in data
    assert "<part-name>Piano</part-name>" in data


@pytest.mark.parametrize(
    "declaration",
    [
        '<!DOCTYPE score-partwise SYSTEM "file:///etc/passwd">',
        '<!DOCTYPE score-partwise [<!ENTITY boom SYSTEM "file:///etc/passwd">]>',
        _AUDIVERIS_DTD.replace("http://www.musicxml.org", "file:///etc"),
        _AUDIVERIS_DTD.replace("partwise.dtd", "timewise.dtd"),
        _AUDIVERIS_DTD.replace("MusicXML 4.0.3 Partwise", "MusicXML 4.0.3 Timewise"),
        _AUDIVERIS_DTD + "\n" + _AUDIVERIS_DTD,
        "<!-- injected comment -->\n" + _AUDIVERIS_DTD,
        _AUDIVERIS_DTD + '\n<!ENTITY extra "boom">',
    ],
)
@pytest.mark.parametrize("suffix", [".musicxml", ".mxl"])
def test_native_omr_rejects_unsafe_or_nonheader_doctype(
    tmp_path: Path, suffix: str, declaration: str,
):
    score = SCORE.replace("<score-partwise", declaration + "\n<score-partwise")
    source = tmp_path / f"invalid{suffix}"
    if suffix == ".mxl":
        _write_audiveris_mxl(source, score)
    else:
        source.write_text(score, encoding="utf-8")
    target = tmp_path / "normalized.musicxml"
    with pytest.raises(OMRImportError):
        normalize_musicxml(source, target, audiveris_output=True)
    assert not target.exists()


def test_audiveris_export_is_discovered_and_normalized_before_job_completion(
    tmp_path: Path, monkeypatch,
):
    from types import SimpleNamespace

    from audio_score_tool import omr

    score = SCORE.replace("<score-partwise", _AUDIVERIS_DTD + "\n<score-partwise")
    monkeypatch.setattr(omr, "command_exists", lambda _command: True)

    def mock_native_omr(_command, args, **_kwargs):
        output_dir = Path(args[args.index("-output") + 1])
        _write_audiveris_mxl(output_dir / "source-score.mxl", score)
        return SimpleNamespace(stdout="Exported native MusicXML")

    monkeypatch.setattr(omr, "run_command", mock_native_omr)
    result = omr.transcribe_score(
        tmp_path / "score.pdf", tmp_path / "outputs", command="managed-audiveris"
    )
    assert result.musicxml_path.read_text(encoding="utf-8").count("<!DOCTYPE") == 0
    assert "<score-partwise" in result.musicxml_path.read_text(encoding="utf-8")

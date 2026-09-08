from audio_score_tool.direct_score_import_api import _ALLOWED


def test_direct_notation_import_supports_musicxml_mxl_and_midi():
    assert {".musicxml", ".xml", ".mxl", ".mid", ".midi"} <= _ALLOWED

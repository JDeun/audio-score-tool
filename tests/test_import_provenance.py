from audio_score_tool.song_store_v2 import SongStoreV2


def test_direct_notation_import_has_distinct_source_kind():
    assert SongStoreV2._source_kind({"kind": "notation-import", "filename": "score.musicxml"}) == "notation"


def test_omr_source_kind_remains_distinct():
    assert SongStoreV2._source_kind({"kind": "omr", "filename": "scan.pdf"}) == "omr"

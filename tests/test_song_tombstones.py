from pathlib import Path

from audio_score_tool.song_tombstones import SongTombstoneStore


def test_song_tombstones_are_persistent(tmp_path: Path):
    path = tmp_path / "app.sqlite3"
    store = SongTombstoneStore(path)
    assert store.contains("job-1") is False

    store.add("job-1")
    assert store.contains("job-1") is True
    assert SongTombstoneStore(path).contains("job-1") is True

    store.remove("job-1")
    assert store.contains("job-1") is False

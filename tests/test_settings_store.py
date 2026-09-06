from pathlib import Path

from audio_score_tool.settings_store import SettingsStore


def test_settings_store_round_trip(tmp_path: Path):
    store = SettingsStore(tmp_path / "settings.json")
    assert store.read() == {}

    saved = store.update({
        "muscriptor_cmd": "/opt/bin/muscriptor",
        "unknown": "ignored",
    })
    assert saved == {"muscriptor_cmd": "/opt/bin/muscriptor"}
    assert store.read()["muscriptor_cmd"] == "/opt/bin/muscriptor"

    cleared = store.update({"muscriptor_cmd": ""})
    assert cleared == {}

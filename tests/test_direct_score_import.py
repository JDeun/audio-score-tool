import zipfile
from pathlib import Path

import pytest

from audio_score_tool import direct_score_import_api as imports

VALID_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list>
  <part id="P1"><measure number="1"><note><rest/><duration>1</duration></note></measure></part>
</score-partwise>
"""


class FakeStore:
    def __init__(self):
        self.updates: list[tuple[str, dict]] = []

    def update(self, job_id: str, **values):
        self.updates.append((job_id, values))


def test_validate_musicxml_accepts_score(tmp_path: Path):
    source = tmp_path / "score.musicxml"
    source.write_text(VALID_XML, encoding="utf-8")
    imports._validate_musicxml_file(source)


@pytest.mark.parametrize(
    "payload",
    [
        "<!DOCTYPE score-partwise><score-partwise/>",
        "<!ENTITY x 'boom'><score-partwise/>",
        "<html/>",
    ],
)
def test_validate_musicxml_rejects_unsafe_or_wrong_root(tmp_path: Path, payload: str):
    source = tmp_path / "bad.musicxml"
    source.write_text(payload, encoding="utf-8")
    with pytest.raises(ValueError):
        imports._validate_musicxml_file(source)


def test_musicxml_worker_generates_canonical_job_result(tmp_path: Path, monkeypatch):
    jobs = tmp_path / "jobs"
    source = tmp_path / "source.musicxml"
    source.write_text(VALID_XML, encoding="utf-8")
    store = FakeStore()

    monkeypatch.setattr(imports, "_store", store)
    monkeypatch.setattr(imports, "jobs_dir", lambda: jobs)

    def fake_to_midi(_source: Path, target: Path):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"MThd")
        return target

    monkeypatch.setattr(imports, "musicxml_to_midi", fake_to_midi)
    imports._worker("job-1", source, ".musicxml")

    final = store.updates[-1][1]
    assert final["status"] == "done"
    assert final["result"]["import_format"] == "musicxml"
    assert Path(final["result"]["musicxml"]).is_file()
    assert Path(final["result"]["midi"]).is_file()


def test_mxl_worker_uses_safe_normalization(tmp_path: Path, monkeypatch):
    jobs = tmp_path / "jobs"
    source = tmp_path / "source.mxl"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container><rootfiles><rootfile full-path="score.musicxml"/></rootfiles></container>',
        )
        archive.writestr("score.musicxml", VALID_XML)
    store = FakeStore()

    monkeypatch.setattr(imports, "_store", store)
    monkeypatch.setattr(imports, "jobs_dir", lambda: jobs)

    def fake_to_midi(_source: Path, target: Path):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"MThd")
        return target

    monkeypatch.setattr(imports, "musicxml_to_midi", fake_to_midi)
    imports._worker("job-mxl", source, ".mxl")

    final = store.updates[-1][1]
    assert final["status"] == "done"
    normalized = Path(final["result"]["musicxml"])
    assert normalized.is_file()
    assert "<score-partwise" in normalized.read_text(encoding="utf-8")


def test_midi_worker_converts_to_musicxml(tmp_path: Path, monkeypatch):
    jobs = tmp_path / "jobs"
    source = tmp_path / "source.mid"
    source.write_bytes(b"MThd")
    store = FakeStore()

    monkeypatch.setattr(imports, "_store", store)
    monkeypatch.setattr(imports, "jobs_dir", lambda: jobs)

    def fake_to_xml(_source: Path, target: Path):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(VALID_XML, encoding="utf-8")
        return target

    monkeypatch.setattr(imports, "midi_to_musicxml", fake_to_xml)
    imports._worker("job-2", source, ".mid")

    final = store.updates[-1][1]
    assert final["status"] == "done"
    assert final["result"]["import_format"] == "midi"
    assert Path(final["result"]["musicxml"]).is_file()
    assert Path(final["result"]["midi"]).read_bytes() == b"MThd"


def test_malformed_midi_failure_is_contained_to_job(tmp_path: Path, monkeypatch):
    jobs = tmp_path / "jobs"
    source = tmp_path / "broken.mid"
    source.write_bytes(b"not-a-midi-file")
    store = FakeStore()

    monkeypatch.setattr(imports, "_store", store)
    monkeypatch.setattr(imports, "jobs_dir", lambda: jobs)

    def reject_midi(_source: Path, _target: Path):
        raise imports.NotationBackendError("malformed MIDI")

    monkeypatch.setattr(imports, "midi_to_musicxml", reject_midi)
    imports._worker("job-broken-midi", source, ".mid")

    final = store.updates[-1][1]
    assert final["status"] == "failed"
    assert final["stage"] == "failed"
    assert "malformed MIDI" in final["error"]
    assert not (jobs / "job-broken-midi" / "outputs" / "score.musicxml").exists()

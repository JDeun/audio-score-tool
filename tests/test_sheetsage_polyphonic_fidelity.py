"""Observed MR-MT3 + SheetSage2 CI regression on owned synthetic audio.

The compressed MusicXML is a 16-second model output over entirely original
synthesized notes, not third-party media or a licensed checkpoint. Source:
Actions 42378323698, mr_mt3/score.musicxml. It reproduces the original
56 -> 65 pitched-note corruption without downloading any model.
"""
from __future__ import annotations

import base64
import json
import zlib
from pathlib import Path

from audio_score_tool.sheetsage_hybrid import merge_sheetsage_musicxml
from scripts.run_tier2_hybrid_smoke import performed_note_signature

_FIXTURE = Path(__file__).parent / "fixtures" / "tier2-mrmt3-owned-score.zlib.b64"


def test_owned_polyphonic_mrmt3_harmony_merge_preserves_every_note(tmp_path: Path):
    source = tmp_path / "mr-score.musicxml"
    source.write_bytes(zlib.decompress(base64.b64decode(_FIXTURE.read_text().strip())))
    # Four score-level tie continuations are one sounding note each.
    assert len(performed_note_signature(source)) == 52

    events_file = tmp_path / "sheetsage2.json"
    roots = ["C:maj", "F:maj", "G:maj", "C:maj", "A:min", "F:maj", "G:maj", "C:maj"]
    starts = [0, 1.99, 3.99, 5.99, 7.99, 9.99, 11.99, 13.99]
    data = {
        "schema_version": 1,
        "provider": "openmirlab-sheetsage-infer",
        "model": "sheetsage2",
        "chords": [{"time_seconds": t, "label": label} for t, label in zip(starts, roots)],
        "keys": [{"time_seconds": 0.0, "label": "C:major"}],
        "meter": "4/4",
        "beats": [{"time_seconds": i * 0.5} for i in range(33)],
    }
    events_file.write_text(json.dumps(data), encoding="utf-8")
    output = tmp_path / "merged.musicxml"
    summary = merge_sheetsage_musicxml(source, events_file, output)
    before = performed_note_signature(source)
    after = performed_note_signature(output)
    assert after == before, (
        f"Original performed notes were changed: before={len(before)}, after={len(after)}"
    )
    assert summary["added"]["chords"] == 8
    assert summary["added"]["keys"] == 1

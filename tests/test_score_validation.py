import json

from audio_score_tool import score_validation
from audio_score_tool.score_validation import deterministic_validate


VALID_SCORE = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
      <note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
      <note><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
      <note><pitch><step>F</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
    </measure>
    <measure number="2">
      <note><pitch><step>G</step><octave>4</octave></pitch><duration>4</duration><type>whole</type></note>
    </measure>
  </part>
</score-partwise>
"""

BAD_SCORE = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <part-list><score-part id="P1"><part-name>Bass</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><type>whole</type></note>
    </measure>
    <measure number="2">
      <note><pitch><step>C</step><octave>8</octave></pitch><duration>1</duration><type>quarter</type></note>
      <note><rest/><duration>1</duration><type>quarter</type><lyric><text>잘못</text></lyric></note>
    </measure>
  </part>
</score-partwise>
"""


def test_deterministic_validation_accepts_balanced_score():
    report = deterministic_validate(VALID_SCORE)
    assert report["ok"] is True
    assert not any(issue["severity"] == "error" for issue in report["issues"])
    assert report["summary"]["part_count"] == 1


def test_deterministic_validation_flags_rhythm_range_and_rest_lyric():
    report = deterministic_validate(BAD_SCORE)
    categories = {issue["category"] for issue in report["issues"]}
    assert report["ok"] is False
    assert "rhythm" in categories
    assert "instrumentation" in categories
    assert "notation" in categories
    assert any(issue["severity"] == "error" for issue in report["issues"])


def test_llm_json_parser_accepts_fenced_json():
    payload = score_validation._extract_json_object(
        "```json\n" + json.dumps({"summary": "ok", "issues": []}) + "\n```"
    )
    assert payload["summary"] == "ok"
    assert payload["issues"] == []

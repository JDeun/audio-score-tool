from audio_score_tool.visual_validation import _parse_json


def test_visual_validation_parses_fenced_json():
    payload = _parse_json(
        """```json
        {"summary":"ok","issues":[{"page":1,"severity":"warning","category":"accidental"}]}
        ```"""
    )
    assert payload["summary"] == "ok"
    assert payload["issues"][0]["page"] == 1


def test_visual_validation_extracts_json_from_extra_text():
    payload = _parse_json('result: {"summary":"review","issues":[]} end')
    assert payload == {"summary": "review", "issues": []}

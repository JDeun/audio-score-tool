from audio_score_tool import presets


def test_known_presets_resolve():
    assert presets.resolve_preset("fast").muscriptor_model == "small"
    assert presets.resolve_preset("balanced").muscriptor_model == "medium"
    assert presets.resolve_preset("quality").whisperx_model == "large-v3"


def test_auto_resolves_recommendation(monkeypatch):
    monkeypatch.setattr(presets, "recommended_preset", lambda: "fast")
    assert presets.resolve_preset("auto").key == "fast"

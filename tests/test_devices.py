from audio_score_tool.devices import detect_device_plan


def test_device_plan_is_well_formed():
    plan = detect_device_plan()
    assert plan.muscriptor_device in {"cpu", "cuda", "mps"} or plan.muscriptor_device.startswith("cuda:")
    assert plan.whisperx_device in {"cpu", "cuda"}
    assert plan.whisperx_compute_type in {"int8", "float16"}

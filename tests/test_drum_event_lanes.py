"""Mathematical selector contracts; no study cohort or benchmark execution."""
from __future__ import annotations

import numpy as np
import pytest

from scripts import drum_event_lanes as lanes


def _trace(low, high, *, independent=False, refractory=.085):
    return lanes._select_peaks(
        np.arange(len(low)) * .01, np.array(low, dtype=float), np.array(high, dtype=float),
        .14, independent=independent, refractory=refractory,
    )


def test_independent_lanes_retain_simultaneous_classes_without_global_suppression():
    low, high = [0, .9, 0, 0, 0], [0, .6, 0, 0, 0]
    combined = _trace(low, high)
    independent = _trace(low, high, independent=True)
    assert [(time, role) for time, role, _ in combined] == [(.01, "kick")]
    assert {(time, role) for time, role, _ in independent} == {
        (.01, "kick"), (.01, "backbeat"),
    }


def test_refractory_ablation_preserves_two_resolved_same_class_peaks():
    low, high = [0, .8, 0, 0, .9, 0], [0] * 6
    assert _trace(low, high, refractory=.085) == [(.04, "kick", .9)]
    assert _trace(low, high, refractory=.01) == [(.01, "kick", .8), (.04, "kick", .9)]
    assert _trace(low, high, independent=True, refractory=.01) == [
        (.01, "kick", .8), (.04, "kick", .9),
    ]


def test_independent_refractory_does_not_cross_suppress_a_different_role():
    low, high = [0, .8, 0, 0, 0], [0, 0, 0, .9, 0]
    assert _trace(low, high) == [(.03, "backbeat", .9)]
    assert _trace(low, high, independent=True) == [(.01, "kick", .8), (.03, "backbeat", .9)]


def test_strict_local_peak_rule_does_not_claim_adjacent_frame_resolution():
    low, high = [0, .8, .9, 0], [0] * 4
    assert _trace(low, high, independent=True, refractory=.01) == [(.02, "kick", .9)]
    assert _trace([0, .9, .9, 0], high, independent=True, refractory=.01) == [(.02, "kick", .9)]


def test_global85_delegates_to_original_detector_and_checks_exact_parity(monkeypatch):
    samples = np.zeros(2048, dtype=np.float32)
    calls = []
    original = lanes.historical.detect_audio_roles

    def checked(audio, sr):
        assert audio is samples and sr == 16000
        calls.append(True)
        return original(audio, sr)

    monkeypatch.setattr(lanes.historical, "detect_audio_roles", checked)
    result = lanes.detect_all_arms(samples)
    assert calls == [True]
    assert tuple(result) == lanes.ARMS
    assert all(events == [] for events in result.values())
    monkeypatch.setattr(lanes.historical, "detect_audio_roles", lambda *_: [(1., "kick", 1.)])
    with pytest.raises(ValueError, match="parity"):
        lanes.detect_all_arms(samples)


def test_historical_numpy_scalars_are_exposed_as_json_event_numbers(monkeypatch):
    low, high = np.array([0., .9, 0.]), np.zeros(3)
    monkeypatch.setattr(lanes, "novelty_features", lambda *_: (np.arange(3) * .01, low, high, .14))
    monkeypatch.setattr(lanes.historical, "detect_audio_roles", lambda *_: [
        (np.float64(.01), "kick", np.float64(.9)),
    ])
    results = lanes.detect_all_arms(np.zeros(2048))
    assert type(results["global85"][0][0]) is float
    assert type(results["global85"][0][2]) is float


@pytest.mark.parametrize("samples,sr", [
    (np.zeros((2, 2048)), 16000), (np.zeros(2048), 8000),
    (np.array([np.nan] * 2048), 16000), (np.zeros(1000), 16000),
    (np.zeros(2048, dtype=complex), 16000),
])
def test_invalid_waveforms_fail_before_any_historical_detector_call(monkeypatch, samples, sr):
    def forbidden(*args):
        pytest.fail("detector called before input admission")

    monkeypatch.setattr(lanes.historical, "detect_audio_roles", forbidden)
    with pytest.raises(ValueError, match="waveform"):
        lanes.detect_all_arms(samples, sr)

"""Regression for floating-point boundary found in receipt arithmetic audit."""
from scripts.tempo_unit_probe import evaluate_rate, sequence_diagnostics


def test_inclusive_tolerance_boundary_survives_binary_roundoff():
    assert evaluate_rate(124.8, 120)['strict']
    result = sequence_diagnostics([.02, .38, .78, 1.18], 75)
    assert result['timeline']['intervals_within_10pct'] == 3
    assert not evaluate_rate(124.8001, 120)['strict']

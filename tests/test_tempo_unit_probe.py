"""Separate unit math, alias metrics, full sequences and serialized playback."""
import copy
import math
import xml.etree.ElementTree as ET
from fractions import Fraction

import pytest

from scripts.run_tempo_unit_probe import adversarial_trials, read_receipt
from scripts.tempo_unit_probe import (
    decode_musicxml,
    encode_musicxml,
    evaluate_rate,
    fixture_trials,
    hypotheses,
    sequence_diagnostics,
    template_scores,
    validate_beats,
)


@pytest.mark.parametrize('bad', (0, -1, float('nan'), float('inf'), '150', True))
def test_invalid_rate(bad):
    with pytest.raises(ValueError):
        hypotheses(bad)


@pytest.mark.parametrize('rate,truth,unit', ((150, 75, .5), (92, 184, 2), (120, 120, 1)))
def test_known_unit_conversion(rate, truth, unit):
    data = hypotheses(rate)
    assert len(data) == 3
    assert not any(h['automatically_selected'] for h in data)
    match = evaluate_rate(rate, truth)
    assert match['family']
    assert match['strict'] == (unit == 1)
    assert match['reference_assisted_unit'] == unit


def test_unavailable_not_false_correctness():
    v = evaluate_rate(None, 120)
    assert not v['available'] and not v['family'] and not v['strict']


def test_two_thirds_not_silently_added_to_allowed_family():
    assert not evaluate_rate(100, 150)['family']


@pytest.mark.parametrize('beats', ([], [0, 1, 2], [0, 1, 1, 2], [-1, 0, 1, 2],
                                   [0, 1, 2, float('nan')]))
def test_invalid_beats(beats):
    with pytest.raises(ValueError):
        validate_beats(beats)


def test_exact_double_is_same_relative_timeline():
    beats = [i * .4 for i in range(40)]
    before = copy.deepcopy(beats)
    v = sequence_diagnostics(beats, 75)
    assert v['timeline']['quarter_per_pulse'] == .5
    assert v['timeline']['max_relative_drift_seconds'] < 1e-10
    assert v['timeline']['intervals_within_10pct'] == 39
    assert before == beats


def test_first_beat_phase_not_needed_for_rate():
    a = sequence_diagnostics([i * .4 for i in range(20)], 75)
    b = sequence_diagnostics([3.2 + i * .4 for i in range(20)], 75)
    assert math.isclose(a['pulse_bpm'], b['pulse_bpm'])
    assert b['timeline']['max_relative_drift_seconds'] < 1e-10
    assert not b['bar_phase_evaluated']


def test_same_median_bpm_can_hide_missing_beats_or_rate_switch():
    r = adversarial_trials()
    for name in ('one_missing_pulse', 'pulse_unit_switch_midstream'):
        assert r[name]['rate_evaluation']['family']
        assert r[name]['timeline']['intervals_over_1_5_expected'] > 0
        assert r[name]['timeline']['max_relative_drift_seconds'] > .39


@pytest.mark.parametrize('unit,name', ((.5, 'eighth'), (1., 'quarter'), (2., 'half')))
def test_musicxml_metronome_and_sound_different_units(unit, name):
    score = template_scores()[0]
    raw, sums, _ = encode_musicxml(score, 75 / unit, unit)
    root = ET.fromstring(raw)
    assert root.findtext('part/measure/direction/direction-type/metronome/beat-unit') == name
    assert float(root.find('part/measure/direction/sound').get('tempo')) == 75
    notes, tempo, total = decode_musicxml(raw)
    assert notes == score['events']
    assert sums == [4., 4.] and tempo == 75 and total == 8


def test_pickup_and_tie_preserve_note_identity():
    for score in template_scores():
        raw, _, fragments = encode_musicxml(score, 150, .5)
        notes, _, total = decode_musicxml(raw)
        assert notes == score['events'] and total == score['total_q']
        if score['pickup_q']:
            first = ET.fromstring(raw).find('part/measure')
            assert first.get('implicit') == 'yes' and first.get('number') == '0'
        if score['name'] == 'tie_across_bar':
            assert fragments > len(notes)
            assert ET.fromstring(raw).find(".//tie[@type='start']") is not None


def test_wrong_playback_unit_is_detected():
    raw, _, _ = encode_musicxml(template_scores()[0], 150, .5)
    root = ET.fromstring(raw)
    root.find('part/measure/direction/sound').set('tempo', '150')
    with pytest.raises(ValueError, match='disagree'):
        decode_musicxml(ET.tostring(root))


def test_36_serialized_score_trials():
    data = fixture_trials()
    assert len(data) == 36 and all(x['passed'] for x in data)
    assert sum(x['unit_omission_control_correct'] for x in data) == 12
    assert max(x['max_time_error_s'] for x in data) < 1e-5
    assert Fraction(str(data[0]['bar_sums_q'][0])) == 4


def test_corrupt_receipt_refused(tmp_path):
    path = tmp_path / 'fake.zip'
    path.write_bytes(b'not the immutable original')
    with pytest.raises(ValueError, match='SHA256'):
        read_receipt(path)

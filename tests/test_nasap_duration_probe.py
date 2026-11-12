"""Offline contracts; no real evaluation outcomes used to set parameters."""
from __future__ import annotations

import copy
import math

import pytest

from scripts.nasap_duration_probe import (
    DURATION_METHODS,
    GATES,
    Observation,
    Reader,
    UNITS,
    VOCAB,
    beat_clock,
    choose_units,
    evaluate,
    fit,
    interpolate,
    selection,
    summary,
    validate,
)


def example():
    return [Observation(str(i), 60+i, i*.5, .45) for i in range(8)]


@pytest.mark.parametrize('mode', DURATION_METHODS)
def test_identity_is_preserved(mode):
    notes = example()
    frozen = copy.deepcopy(notes)
    prediction, loss = fit(notes, mode=mode)
    assert notes == frozen
    assert set(prediction) == {n.id for n in notes}
    assert math.isfinite(loss)
    assert all(d > 0 for _, d in prediction.values())


@pytest.mark.parametrize('unit', UNITS)
def test_shared_onset_fit_is_same_physical_coordinate(unit):
    notes = example()
    prediction, _ = fit(notes, unit)
    for n in notes:
        assert prediction[n.id][0] / unit == pytest.approx(n.onset)


def test_short_and_long_gate_hypotheses_are_explicit():
    assert {g for g, _ in GATES} == {1, .75, .5, 1.25}
    assert all(p >= 0 for _, p in GATES)
    assert all(d > 0 and c >= 0 for d, c in VOCAB)


def test_literal_baseline_is_nearest_allowed_duration():
    result, _ = fit([Observation('x', 60, 0, .51)], mode='literal')
    assert result['x'][1] == .5


def test_unit_selector_receives_no_score_fields():
    notes = example()
    a, _ = choose_units(notes, 120)
    b, _ = choose_units(notes, 120, {n.id: n.onset+.5 for n in notes})
    for k in ('keep_unit1', 'prior120', 'duration'):
        assert a[k] == b[k]
    assert a['keep_unit1'] == 1
    assert a['prior120'] == 1


def test_identical_observations_cannot_reveal_hidden_written_convention():
    a, _ = choose_units(example(), 150)
    b, _ = choose_units(example(), 150)
    assert a == b


@pytest.mark.parametrize('notes', ([], [Observation('x', 60, 0, 0)],
                                      [Observation('x', 60, float('nan'), 1)],
                                      [Observation('x', 128, 0, 1)]))
def test_invalid_observations_are_rejected(notes):
    with pytest.raises(ValueError):
        validate(notes)


def test_unsupported_units_and_nonfinite_rates_rejected():
    with pytest.raises(ValueError):
        fit(example(), 1.5)
    with pytest.raises(ValueError):
        choose_units(example(), float('nan'))


def test_piece_selection_deduplicates_and_caps_composers():
    values = []
    for composer in ('a', 'b'):
        for title in ('x', 'y', 'z'):
            for performance in range(3):
                values.append({'robust_note_alignment': '1.0',
                               'parangonada_data_folder': 'known',
                               'performance_annotations': 'known',
                               'composer': composer, 'title': title,
                               'midi_performance': f'{composer}/{title}/{performance}'})
    result = selection(values)
    assert len(result) == 4
    assert len({(r['composer'], r['title']) for r in result}) == 4
    assert result == selection(list(reversed(values)))


def test_extrapolation_is_not_silently_allowed():
    assert interpolate(.75, [0, .5, 1], [0, 1, 2]) == 1.5
    with pytest.raises(ValueError):
        interpolate(-.01, [0, .5, 1], [0, 1, 2])


def clock_fixture(meter='4/4', irregular=False):
    lines = []
    for i in range(50):
        label = 'bR' if irregular and i == 20 else ('db' if i % 4 == 0 else 'b')
        if i == 0:
            label += ','+meter
        lines.append(f'{i*.5}\t{i*.5}\t{label}')
    perf = [{'last_beat': str(i*.5), 'last_beat_ref': str(i)} for i in range(50)]
    return perf, '\n'.join(lines).encode()


def test_privileged_clock_origin_and_units_are_checked():
    times, q, meter = beat_clock(*clock_fixture())
    assert meter == '4/4'
    assert times[0] == 4 and times[-1] == 20
    assert q[0] == 8 and q[-1] == 40


@pytest.mark.parametrize('meter', ('3/8', '6/8', '2/2'))
def test_unsupported_meter_is_not_relabelled_as_quarter(meter):
    with pytest.raises(ValueError):
        beat_clock(*clock_fixture(meter))


def test_irregular_beats_and_wrong_export_mapping_rejected():
    with pytest.raises(ValueError):
        beat_clock(*clock_fixture(irregular=True))
    perf, raw = clock_fixture()
    perf[20]['last_beat_ref'] = '88'
    with pytest.raises(ValueError):
        beat_clock(perf, raw)


def test_metrics_count_onset_and_duration_separately():
    result = evaluate({'a': (0, 1), 'b': (.5, .25)}, {'a': (0, 1), 'b': (.5, .5)})
    assert result['n'] == 2
    assert result['onset_exact'] == 2
    assert result['duration_exact'] == 1
    assert result['pair_exact'] == 1


def test_unavailable_sources_remain_visible():
    result = summary([{'status': 'not_evaluated'}, {'status': 'not_evaluated'}])
    assert result['planned'] == 2 and result['completed'] == 0


@pytest.mark.parametrize('path', ('../file', '/root/file', 'a\\b', 'a?token=x', ''))
def test_network_path_validation_precedes_request(path):
    with pytest.raises(ValueError):
        Reader().get(path)

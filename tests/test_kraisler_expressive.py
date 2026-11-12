"""Cross-clock identity, ambiguity, duration independence and frozen ledgers."""
from __future__ import annotations

import copy
from fractions import Fraction
from types import SimpleNamespace

import pytest

from scripts import kraisler_correspondence as frozen
from scripts import kraisler_expressive as subject


class ClockFixture:
    def __init__(self, *, period=.5, unsupported=(), bounds=(0., 10.), mapping=None):
        self.period = period
        self.unsupported = set(map(Fraction, unsupported))
        self.bounds = bounds
        self.mapping = mapping or (lambda q: float(q))

    def candidate_time_at(self, q):
        return self.mapping(q)

    def time_at(self, q):
        return None if Fraction(q) in self.unsupported else self.mapping(q)

    def period_at(self, q):
        return self.period

    def supports_time_band(self, q, width):
        time = self.time_at(q)
        return (time is not None and self.bounds[0] <= time - width + 1e-12
                and time + width <= self.bounds[1] + 1e-12)

    def supports_interval(self, start, end):
        return (start < end and not any(start <= q <= end for q in self.unsupported)
                and self.time_at(start) is not None and self.time_at(end) is not None)


def attack(q, *, midi=60, identity='a', grace=False, ornaments=(), articulations=()):
    return SimpleNamespace(onset_q=Fraction(q), end_q=Fraction(q) + Fraction(1, 2),
                           midi=midi, id=identity, grace=grace,
                           ornaments=ornaments, articulations=articulations)


def score(*attacks):
    return SimpleNamespace(attacks=attacks, events=attacks, global_rests=(), rests=(),
                           unknown_intervals=())


def reference(onset=1., *, offset=1.4, midi=60):
    return frozen.Reference(onset, offset, midi)


@pytest.mark.parametrize(('period', 'scope', 'expected'), [
    (.1, 'tempo10', .05), (.5, 'tempo20', .1), (2., 'tempo20', .2),
    (.5, 'tempo30', .15), (3., 'fixed100', .1), (.2, 'tempo30', .06),
])
def test_pulse_fraction_floor_and_cap(period, scope, expected):
    assert subject.onset_half_width(ClockFixture(period=period), Fraction(1), scope) == pytest.approx(expected)


@pytest.mark.parametrize('period', [0, -1, float('nan'), float('inf'), True])
def test_invalid_period_is_not_silently_clamped(period):
    with pytest.raises(ValueError, match='positive finite'):
        subject.onset_half_width(ClockFixture(period=period), Fraction(1), 'tempo20')


def test_unknown_scope_does_not_choose_an_observed_best_window():
    with pytest.raises(ValueError, match='predeclared'):
        subject.onset_half_width(ClockFixture(), Fraction(1), 'best')


def test_exact_boundary_is_inclusive_and_pitch_still_required():
    sc = score(attack(1))
    clock = ClockFixture()
    pairs, result = subject.pair_local_references([reference(1.1)], sc, clock, clock, 'fixed100')
    assert pairs == {0: 0}
    assert result['matched_pairs'] == 1
    assert result['memberships']['unmarked'] == '1'
    pairs, result = subject.pair_local_references([reference(1.10001)], sc, clock, clock, 'fixed100')
    assert not pairs
    assert result['unresolved'] == 1
    pairs, _ = subject.pair_local_references([reference(1., midi=61)], sc, clock, clock, 'fixed100')
    assert not pairs


def test_unsupported_beat_competitor_prevents_manufactured_uniqueness():
    sc = score(attack(1), attack('1.05', identity='unsupported'))
    bclock = ClockFixture(unsupported=['1.05'])
    pclock = ClockFixture(unsupported=['1.05'])
    pairs, result = subject.pair_local_references([reference()], sc, bclock, pclock, 'fixed100')
    assert not pairs
    assert result['unresolved_reasons'] == {'reference_has_multiple_candidates': 1}
    assert result['memberships']['unresolved'] == '1'


def test_different_unique_identities_under_two_clocks_are_rejected():
    sc = score(attack(1), attack('1.3', identity='b'))
    bclock = ClockFixture()
    pclock = ClockFixture(mapping=lambda q: float(q) - .3)
    pairs, result = subject.pair_local_references([reference()], sc, bclock, pclock, 'fixed100')
    assert not pairs
    assert result['unresolved_reasons'] == {'clocks_disagree_on_identity': 1}


def test_reverse_uniqueness_counts_every_competing_reference():
    refs = [reference(.98), reference(1.02)]
    pairs, result = subject.pair_local_references(refs, score(attack(1)), ClockFixture(), ClockFixture(), 'fixed100')
    assert not pairs
    assert result['unresolved_reasons'] == {'score_attack_has_multiple_references': 2}
    assert result['memberships']['unresolved'] == '11'


def test_wider_window_can_lose_unique_identity():
    sc = score(attack(1), attack('1.2', identity='b'))
    refs = [reference(1.08)]
    bclock, pclock = ClockFixture(), ClockFixture()
    narrow, _ = subject.pair_local_references(refs, sc, bclock, pclock, 'tempo20')
    wider, result = subject.pair_local_references(refs, sc, bclock, pclock, 'tempo30')
    assert narrow == {0: 0}
    assert not wider
    assert result['unresolved_reasons'] == {'reference_has_multiple_candidates': 1}


def test_full_window_must_stay_inside_supported_component():
    sc = score(attack(1))
    clock = ClockFixture(bounds=(.94, 2.))
    narrow, _ = subject.pair_local_references([reference()], sc, clock, clock, 'tempo10')
    wider, result = subject.pair_local_references([reference()], sc, clock, clock, 'tempo20')
    assert narrow == {0: 0}
    assert not wider
    assert result['unresolved_reasons'] == {'full_onset_window_not_locally_supported': 1}


def test_offset_does_not_select_or_change_an_onset_pair():
    sc, clock = score(attack(1)), ClockFixture()
    short = subject.pair_local_references([reference(offset=1.02)], sc, clock, clock, 'tempo20')
    long = subject.pair_local_references([reference(offset=2.)], sc, clock, clock, 'tempo20')
    assert short == long
    assert short[0] == {0: 0}
    assert short[1]['offset_used_for_identity'] is False


@pytest.mark.parametrize('context', ['ornament', 'coincident_grace'])
def test_original_expression_context_exclusions_remain(context):
    events = [attack(1, ornaments=('trill-mark',) if context == 'ornament' else ())]
    if context == 'coincident_grace':
        events.append(attack(1, grace=True, identity='grace', midi=62))
    pairs, result = subject.pair_local_references([reference()], score(*events), ClockFixture(), ClockFixture(), 'tempo20')
    assert not pairs
    assert result['unresolved_reasons'] == {'ornament_or_grace_context': 1}


def test_missing_local_clock_keeps_whole_population():
    refs = [reference(), reference(2., offset=2.2)]
    pairs, result = subject.pair_local_references(refs, score(attack(1)), None, None, 'tempo20')
    assert not pairs
    assert result['reference_count'] == 2
    assert result['unresolved_reasons'] == {'source_clock_unadmitted': 2}
    assert result['memberships']['unresolved'] == '11'


def test_exact_historical_alignment_receipt_and_baseline_identity():
    historical = subject.read_alignment_baseline()
    assert historical['summary']['windows']['100']['matched_pairs'] == 225
    old = historical['cases'][0]
    candidate = {'frozen_baseline': copy.deepcopy(old['analysis']),
                 'reference_count': old['analysis']['reference_count']}
    subject.verify_baseline_case(old, candidate)
    candidate['frozen_baseline']['reference_count'] += 1
    with pytest.raises(ValueError, match='reproduce exactly'):
        subject.verify_baseline_case(old, candidate)


def test_historical_receipt_rejects_wrong_file_and_symlink(tmp_path):
    wrong = tmp_path / 'wrong.zip'
    wrong.write_bytes(b'not the receipt')
    with pytest.raises(ValueError, match='exact previous'):
        subject.read_alignment_baseline(wrong)
    linked = tmp_path / 'linked.zip'
    linked.symlink_to(subject.BASELINE_PATH)
    with pytest.raises(ValueError, match='exact previous'):
        subject.read_alignment_baseline(linked)


def all_unresolved_analysis(prior):
    n = prior['bases']['default']['arms']['raw']['metrics']['reference_note_count']
    memberships = {category: ('1' if category == 'unresolved' else '0') * n
                   for category in subject.CATEGORIES}
    return {'reference_count': n,
            'source_sha256': {'notes': prior['reference_sha256'], 'beats': prior['beats_sha256']},
            'correspondence': {'scopes': {scope: {'memberships': copy.deepcopy(memberships)}
                                          for scope in subject.SCOPES}}}


def test_all_new_scopes_preserve_immutable_matching_gain_loss():
    prior = frozen.read_previous_receipt()['cases'][0]
    analysis = all_unresolved_analysis(prior)
    untouched = copy.deepcopy(analysis)
    ledger = subject.attribute_expressive(prior, analysis)
    assert analysis == untouched
    assert ledger['new_f1_computed'] is False
    for scope in subject.SCOPES:
        for base in subject.BASES:
            for arm in subject.ARMS:
                metrics = prior['bases'][base]['arms'][arm]['metrics']
                for metric in ('onset', 'onset_offset'):
                    actual = ledger['scopes'][scope]['unresolved']['bases'][base][arm][metric]
                    assert actual['matched'] == metrics[metric + '_reference_mask'].count('1')
                    assert actual['gained'] == metrics['transition'][metric]['gained']
                    assert actual['damaged'] == metrics['transition'][metric]['damaged']


def test_changed_scope_population_and_invalid_partition_fail_closed():
    prior = frozen.read_previous_receipt()['cases'][0]
    analysis = all_unresolved_analysis(prior)
    analysis['correspondence']['scopes'].pop('tempo30')
    with pytest.raises(ValueError, match='scope population'):
        subject.attribute_expressive(prior, analysis)
    analysis = all_unresolved_analysis(prior)
    analysis['correspondence']['scopes']['tempo20']['memberships']['unmarked'] = '1' * analysis['reference_count']
    with pytest.raises(ValueError, match='partition'):
        subject.attribute_expressive(prior, analysis)


def test_pooled_mean_uses_counts_not_recording_quantiles_or_unweighted_means():
    rows = [{'count': 1, 'sum': .5, 'median': .5}, {'count': 9, 'sum': 9., 'median': 1.}]
    actual = subject._sum_ratio_rows(rows)
    assert actual['mean'] == pytest.approx(.95)
    assert actual['cohort_quantiles_computed'] is False
    assert 'median' not in actual


@pytest.mark.parametrize('cases', [[], [{'id': '02', 'status': 'failed'}],
                                  [{'id': ident, 'status': 'analyzed'} for ident in subject.PLANNED_IDS]])
def test_partial_cases_never_become_whole_cohort_aggregate(cases):
    assert subject.summarize_expressive(cases) is None


def test_synthetic_parser_to_local_ranges_and_six_case_aggregation():
    """A constructed source exercises the real new module interfaces together."""
    from scripts.kraisler_score import parse_score

    note = '<note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>'
    attributes = '<attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>'
    xml = ('<score-partwise version="4.0"><part-list><score-part id="P1"><part-name>test</part-name></score-part></part-list>'
           '<part id="P1"><measure number="1">' + attributes + note * 4
           + '</measure><measure number="2">' + note * 4 + '</measure></part></score-partwise>').encode()
    symbolic = parse_score(xml)
    anchors = tuple(SimpleNamespace(q=Fraction(i), time=i / 2) for i in range(8))
    match = SimpleNamespace(strict_score_consistency=True, anchors=anchors, diagnostics={})
    beat_rows = ['beat_time,beat_type,time_signature,piano,violin']
    for i in range(8):
        beat_rows.append(f'{i / 2},{"db" if i % 4 == 0 else "b"},{"4/4" if i == 0 else ""},True,True')
    raw_beats = ('\n'.join(beat_rows) + '\n').encode()
    raw_notes = b'onset,offset,midi,velocity\n1,1.25,60,127\n1.5,2,60,127\n2,2.7,60,127\n'
    analysis = subject.analyze_expressive(symbolic, symbolic, match, raw_beats, raw_notes, 4., raw_score=xml)
    assert analysis['reference_count'] == 3
    assert analysis['local_support']['supported_beat_cells'] == 7
    assert all(value['matched_pairs'] == 3 for value in analysis['correspondence']['scopes'].values())
    assert analysis['correspondence']['scopes']['stable_tempo']['residual_statistics_computed'] is False
    duration = analysis['duration_context']['tempo20']
    assert duration['supported_pairs'] == 3
    assert duration['band_counts'] == {'inside_both': 1, 'shorter_both': 1, 'longer_both': 1, 'clock_dependent': 0}
    assert sum(row['reference_notes'] for row in duration['by_category'].values()) == 3
    subject.verify_baseline_case({'status': 'analyzed', 'analysis': analysis['frozen_baseline']}, analysis)
    prior = {'status': 'scored', 'reference_sha256': analysis['source_sha256']['notes'],
             'beats_sha256': analysis['source_sha256']['beats'], 'bases': {}}
    for base in subject.BASES:
        prior['bases'][base] = {'arms': {}}
        for arm in subject.ARMS:
            metrics = {'reference_note_count': 3, 'transition': {}}
            for metric in ('onset', 'onset_offset'):
                metrics[metric + '_reference_mask'] = '101'
                metrics[metric + '_f1'] = round(2 / 3, 8)
                metrics['transition'][metric] = {'gained': 0, 'damaged': 0}
            prior['bases'][base]['arms'][arm] = {'count': 3, 'metrics': metrics}
    attribution = subject.attribute_expressive(prior, analysis)
    cases = [{'id': ident, 'status': 'analyzed', 'analysis': copy.deepcopy(analysis),
              'attribution': copy.deepcopy(attribution)} for ident in subject.PLANNED_IDS]
    combined = subject.summarize_expressive(cases)
    assert combined['reference_notes'] == 18
    assert combined['scopes']['tempo20']['matched_pairs'] == 18
    assert combined['duration_context']['tempo20']['band_counts']['shorter_both'] == 6
    assert combined['duration_context']['tempo20']['ratios']['global_beats']['mean'] == pytest.approx(2.9 / 3)
    assert combined['conditional_ledger']['tempo20']['unmarked']['bases']['default']['raw']['onset']['matched'] == 12
    corrupted = copy.deepcopy(cases)
    corrupted[0]['analysis']['duration_context']['tempo20']['supported_pairs'] += 1
    with pytest.raises(ValueError, match='duration articulation partition'):
        subject.summarize_expressive(corrupted)
    cases[-1]['status'] = 'attribution_failed'
    assert subject.summarize_expressive(cases) is None

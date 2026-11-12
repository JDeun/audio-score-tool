"""Duration and rest-boundary diagnostics after source-only note pairing.

The original written score and performed annotations remain unchanged. Bands
are declared diagnostic policies, not confidence intervals or musical truth.
No real-data swing map, audio processing, prediction, or parameter fitting is
performed. Public results contain counts and summaries, never source arrays.
"""
from __future__ import annotations

import math
import statistics
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from fractions import Fraction

from scripts.kraisler_correspondence import (
    CATEGORIES,
    Reference,
    _category,
    _rows,
    read_notes,
)
from scripts.kraisler_score import parse_score

DURATION_RATIO = .2
DURATION_MIN_S = .05
BOUNDARY_PULSE_RATIO = .2
BOUNDARY_MIN_S = .05
BOUNDARY_MAX_S = .2
ROUNDING_EPSILON = 1e-12
MAX_REFERENCES = 20_000
CLOCK_NAMES = ('global_beats', 'piano')
BAND_CLASSES = ('inside_both', 'shorter_both', 'longer_both', 'clock_dependent')


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _statistics(values):
    """Type-7 linear sample quantiles; no distributional confidence claim."""
    values = sorted(values)
    if not values:
        return dict(count=0, sum=0., mean=None, min=None, p10=None,
                    median=None, p90=None, max=None)

    def quantile(p):
        rank = (len(values) - 1) * p
        lo, hi = math.floor(rank), math.ceil(rank)
        return values[lo] + (rank - lo) * (values[hi] - values[lo])

    total = math.fsum(values)
    return dict(count=len(values), sum=total, mean=total / len(values), min=values[0],
                p10=quantile(.1), median=statistics.median(values),
                p90=quantile(.9), max=values[-1])


def _references(references):
    _require(len(references) <= MAX_REFERENCES, 'bounded reference population required')
    for ref in references:
        _require(not isinstance(ref.onset, bool) and not isinstance(ref.offset, bool)
                 and math.isfinite(ref.onset) and math.isfinite(ref.offset)
                 and 0 <= ref.onset < ref.offset, 'positive finite reference interval required')
        _require(not isinstance(ref.midi, bool) and isinstance(ref.midi, int)
                 and 0 <= ref.midi <= 127, 'integral MIDI reference pitch required')


def _pairs(score, references, pairs):
    _require(isinstance(pairs, dict), 'fixed reference-to-score pair mapping required')
    for ri, si in pairs.items():
        _require(type(ri) is int and type(si) is int and 0 <= ri < len(references)
                 and 0 <= si < len(score.attacks), 'pair index outside source population')
        _require(references[ri].midi == score.attacks[si].midi, 'pair pitch changed')
    _require(len(set(pairs.values())) == len(pairs), 'score attacks must be uniquely paired')


def _empty_group():
    return {'paired_notes': 0, 'supported_pairs': 0, 'unsupported_pairs': 0,
            'unsupported_reasons': Counter(), 'band_counts': dict.fromkeys(BAND_CLASSES, 0),
            'ratios': {name: [] for name in CLOCK_NAMES},
            'performed_durations': [],
            'projected_durations': {name: [] for name in CLOCK_NAMES}}


def _publish_group(group):
    return {key: group[key] for key in ('paired_notes', 'supported_pairs', 'unsupported_pairs', 'band_counts')} | {
        'reference_notes': group['paired_notes'], 'unpaired_notes': 0,
        'unsupported_reasons': dict(group['unsupported_reasons']),
        'ratios': {name: _statistics(values) for name, values in group['ratios'].items()},
        'performed_duration_s_sum': math.fsum(group['performed_durations']),
        'projected_duration_s_sum': {name: math.fsum(values)
                                     for name, values in group['projected_durations'].items()},
    }


def _project_interval(start, end, bclock, pclock):
    if bclock is None or pclock is None:
        return None, 'source_clock_unavailable'
    if start >= end:
        return None, 'nonpositive_score_interval'
    if not all(clock.supports_interval(start, end) for clock in (bclock, pclock)):
        return None, 'interval_not_supported_by_both_clocks'
    projections = []
    for clock in (bclock, pclock):
        left, right = clock.time_at(start), clock.time_at(end)
        if (left is None or right is None or not math.isfinite(left)
                or not math.isfinite(right) or right <= left):
            return None, 'nonpositive_or_unavailable_projection'
        projections.append((left, right))
    return tuple(projections), None


def _duration_side(performed, projected):
    width = max(DURATION_MIN_S, DURATION_RATIO * projected)
    if performed < projected - width - ROUNDING_EPSILON:
        return 'shorter'
    if performed > projected + width + ROUNDING_EPSILON:
        return 'longer'
    return 'inside'


def duration_context(score, references, pairs, bclock, pclock):
    """Describe already paired durations without using offsets to choose pairs."""
    _references(references)
    _pairs(score, references, pairs)
    total = _empty_group()
    categories = {name: _empty_group() for name in CATEGORIES}
    for ri, si in sorted(pairs.items()):
        ref, event = references[ri], score.attacks[si]
        groups = (total, categories[_category(event)])
        for group in groups:
            group['paired_notes'] += 1
        if not score.admissible_for_alignment:
            projected, reason = None, 'score_structure_unadmitted'
        else:
            projected, reason = _project_interval(event.onset_q, event.end_q, bclock, pclock)
        if reason is not None:
            for group in groups:
                group['unsupported_pairs'] += 1
                group['unsupported_reasons'][reason] += 1
            continue
        performed = ref.offset - ref.onset
        durations = [end - start for start, end in projected]
        sides = [_duration_side(performed, duration) for duration in durations]
        label = sides[0] + '_both' if sides[0] == sides[1] else 'clock_dependent'
        for group in groups:
            group['supported_pairs'] += 1
            group['band_counts'][label] += 1
            group['performed_durations'].append(performed)
            for name, duration in zip(CLOCK_NAMES, durations, strict=True):
                group['ratios'][name].append(performed / duration)
                group['projected_durations'][name].append(duration)
    by_category = {name: _publish_group(group) for name, group in categories.items()}
    unpaired = len(references) - len(pairs)
    by_category['unresolved']['reference_notes'] += unpaired
    by_category['unresolved']['unpaired_notes'] = unpaired
    return _publish_group(total) | {
        'reference_notes': len(references), 'unpaired_notes': unpaired,
        'by_category': by_category,
        'duration_band': {'minimum_seconds': DURATION_MIN_S,
                          'projected_slot_duration_ratio': DURATION_RATIO,
                          'inclusive': True},
        'identity_uses_duration': False, 'diagnostic_only': True,
        'category_partition': 'all references; unpaired notes remain unresolved, with duration statistics only for supported pairs',
        'musical_correctness_measured': False, 'confidence_interval_estimated': False,
        'interpretation': 'performed annotation / projected written slot; articulation may shorten or overlap sound',
        'offset_reference_uncertainty': 'violin annotation offsets are less reliable than onset and pitch',
    }


def _union(intervals):
    result = []
    for start, end in sorted(intervals):
        _require(math.isfinite(start) and math.isfinite(end) and start < end,
                 'positive finite projected interval required')
        if result and start <= result[-1][1]:
            result[-1] = (result[-1][0], max(result[-1][1], end))
        else:
            result.append((start, end))
    return result


def _subtract(intervals, remove):
    result, remove = [], _union(remove)
    for start, end in _union(intervals):
        cursor = start
        for left, right in remove:
            if right <= cursor:
                continue
            if left >= end:
                break
            if left > cursor:
                result.append((cursor, min(left, end)))
            cursor = max(cursor, right)
            if cursor >= end:
                break
        if cursor < end:
            result.append((cursor, end))
    return result


def _overlap(left, right):
    left, right = _union(left), _union(right)
    i = j = 0
    pieces = []
    while i < len(left) and j < len(right):
        pieces.append(max(0., min(left[i][1], right[j][1]) - max(left[i][0], right[j][0])))
        if left[i][1] <= right[j][1]:
            i += 1
        else:
            j += 1
    return math.fsum(pieces)


def _interval_statistics(intervals, reference_intervals):
    merged = _union(intervals)
    duration = math.fsum(end - start for start, end in merged)
    overlap = _overlap(merged, reference_intervals)
    return {'interval_count': len(merged), 'duration_s': duration,
            'annotated_note_overlap_s': overlap,
            'uncovered_by_note_annotations_s': max(0., duration - overlap)}


def rest_range_context(score, references, bclock, pclock):
    """Project only fully supported rest envelopes, cores and uncertain rims.

    Each boundary requires BOTH clocks to support its symmetric time band of
    guard + absolute clock disagreement. This conservatively covers the full
    expanded two-clock hull without clipping it to a component or extrapolating.
    """
    _references(references)
    envelopes, cores, guards, expanded_widths = [], [], [], []
    reasons = Counter()
    projected_count = collapsed_count = 0
    for rest in score.global_rests:
        if not score.admissible_for_alignment or score.counts['parts'] != 1:
            projections, reason = None, 'score_structure_unadmitted'
        else:
            projections, reason = _project_interval(rest.onset_q, rest.end_q, bclock, pclock)
        if reason is not None:
            reasons[reason] += 1
            continue
        (bstart, bend), (pstart, pend) = projections
        boundary_guards, widths = [], []
        for q, tb, tp in ((rest.onset_q, bstart, pstart), (rest.end_q, bend, pend)):
            period = bclock.period_at(q)
            if period is None or not math.isfinite(period) or period <= 0:
                reason = 'boundary_pulse_period_unavailable'
                break
            guard = min(BOUNDARY_MAX_S, max(BOUNDARY_MIN_S, BOUNDARY_PULSE_RATIO * period))
            width = guard + abs(tb - tp)
            if not all(clock.supports_time_band(q, width) for clock in (bclock, pclock)):
                reason = 'expanded_boundary_band_not_supported_by_both_clocks'
                break
            boundary_guards.append(guard)
            widths.append(width)
        if reason is not None:
            reasons[reason] += 1
            continue
        start_guard, end_guard = boundary_guards
        envelope = (min(bstart, pstart) - start_guard, max(bend, pend) + end_guard)
        core = (max(bstart, pstart) + start_guard, min(bend, pend) - end_guard)
        envelopes.append(envelope)
        if core[0] < core[1]:
            cores.append(core)
        else:
            collapsed_count += 1
        projected_count += 1
        guards.extend(boundary_guards)
        expanded_widths.extend(widths)
    uncertain = _subtract(envelopes, cores)
    reference_intervals = [(ref.onset, ref.offset) for ref in references]
    return {
        'explicit_rest_elements': len(score.rests),
        'instrument_wide_rest_intervals': len(score.global_rests),
        'unknown_score_intervals': len(score.unknown_intervals),
        'projected_rest_intervals': projected_count,
        'unprojectable_rest_intervals': len(score.global_rests) - projected_count,
        'unprojectable_reasons': dict(reasons),
        'nonempty_core_source_intervals': len(cores), 'collapsed_core_intervals': collapsed_count,
        'projections': {name: _interval_statistics(intervals, reference_intervals)
                        for name, intervals in (('envelope', envelopes), ('core', cores),
                                                 ('boundary_uncertain', uncertain))},
        'boundary_guards_s': _statistics(guards),
        'expanded_boundary_support_widths_s': _statistics(expanded_widths),
        'guard_policy': {'pulse_ratio': BOUNDARY_PULSE_RATIO, 'minimum_seconds': BOUNDARY_MIN_S,
                         'maximum_seconds': BOUNDARY_MAX_S,
                         'expanded_support_adds_absolute_clock_disagreement': True},
        'clipping_performed': False, 'extrapolation': False, 'diagnostic_only': True,
        'written_rest_accuracy_measured': False, 'prediction_occupancy_available': False,
        'acoustic_silence_verified': False,
        'interpretation': 'source annotation overlap within supported two-clock projections; not acoustic rest truth',
    }


def source_expression_metadata(raw_score: bytes, raw_notes: bytes):
    """Bounded source flags and annotation-velocity counts; no swing inference."""
    parsed = parse_score(raw_score)
    root = ET.fromstring(raw_score.decode('utf-8-sig'))
    for element in root.iter():
        element.tag = element.tag.split('}')[-1]
    rows = _rows(raw_notes, ('onset', 'offset', 'midi', 'velocity'))
    # Reuse the frozen validator with a data-derived upper bound only here:
    # this function inspects metadata, not correspondence to audio duration.
    values = [tuple(map(float, row)) for row in rows]
    _require(all(all(math.isfinite(v) for v in row) for row in values), 'finite note metadata required')
    read_notes(raw_notes, max(row[1] for row in values))
    velocities = Counter(int(row[3]) for row in values)
    notes = root.findall('./part/measure/note')
    for note in notes:
        for attribute in ('attack', 'release'):
            if attribute in note.attrib:
                _require(math.isfinite(float(note.attrib[attribute])), 'finite attack/release attribute required')
    return {
        'score_note_elements': len(notes), 'score_structure_admissible': parsed.admissible_for_alignment,
        'explicit_swing_elements': sum(e.tag == 'swing' for e in root.iter()),
        'explicit_straight_elements': sum(e.tag == 'straight' for e in root.iter()),
        'note_attack_attributes': sum('attack' in note.attrib for note in notes),
        'note_release_attributes': sum('release' in note.attrib for note in notes),
        'reference_notes': len(values), 'velocity_unique_count': len(velocities),
        'velocity_counts': {str(key): value for key, value in sorted(velocities.items())},
        'velocity_is_constant': len(velocities) == 1,
        'velocity_all_127': set(velocities) == {127},
        'violin_dynamics_measured': False,
        'velocity_interpretation': 'annotation values only; KRAISLER violin velocity is a fixed placeholder',
        'swing_status': 'unestablished', 'real_data_swing_applied': False, 'swing_fitted': False,
        'attack_release_modifications_applied': False,
        'absence_of_swing_tags_establishes_straight_performance': False,
        'offset_reference_uncertainty': 'KRAISLER violin offsets are less reliable than onset and pitch',
    }


@dataclass(frozen=True)
class _SyntheticClock:
    pulse: Fraction = Fraction(3, 5)
    swing_ratio: Fraction = Fraction(1)

    def time_at(self, q):
        q = Fraction(q)
        if not 0 <= q <= 4:
            return None
        beat = q.numerator // q.denominator
        phase = q - beat
        split = self.swing_ratio / (1 + self.swing_ratio)
        mapped = 2 * phase * split if phase <= Fraction(1, 2) else split + 2 * (phase - Fraction(1, 2)) * (1 - split)
        return float((beat + mapped) * self.pulse)

    def supports_interval(self, start, end):
        return 0 <= start < end <= 4

    def supports_time_band(self, q, width):
        time = self.time_at(q)
        return time is not None and 0 <= time - width <= time + width <= float(4 * self.pulse)

    def period_at(self, q):
        return float(self.pulse) if 0 <= q <= 4 else None


def _synthetic_pairs(references, candidates, width):
    """Tiny illustrative same-pitch, mutual-unique relation, no greedy tie-break."""
    forward = {i: {j for j, (_, time, pitch) in enumerate(candidates)
                   if pitch == ref[2] and abs(time - ref[1]) <= width + ROUNDING_EPSILON}
               for i, ref in enumerate(references)}
    reverse = {j: {i for i, candidates_for_ref in forward.items() if j in candidates_for_ref}
               for j in range(len(candidates))}
    pairs = [(i, next(iter(matches))) for i, matches in forward.items()
             if len(matches) == 1 and len(reverse[next(iter(matches))]) == 1]
    return {'reference_notes': len(references), 'candidate_notes': len(candidates),
            'admitted_pairs': len(pairs),
            'correct_identity_pairs': sum(references[i][0] == candidates[j][0] for i, j in pairs),
            'wrong_identity_pairs': sum(references[i][0] != candidates[j][0] for i, j in pairs),
            'unresolved_references': len(references) - len(pairs),
            'references_with_multiple_candidates': sum(len(v) > 1 for v in forward.values()),
            'tolerance_seconds': width}


def synthetic_controls():
    """Predeclared exact scenarios, illustrative controls rather than a benchmark."""
    straight = _SyntheticClock()
    swing = _SyntheticClock(swing_ratio=Fraction(2))
    positions = (Fraction(0), Fraction(1, 2), Fraction(1), Fraction(3, 2))
    straight_candidates = tuple((i, straight.time_at(q), 60) for i, q in enumerate(positions))
    swing_candidates = tuple((i, swing.time_at(q), 60) for i, q in enumerate(positions))
    jitter = (Fraction(12, 1000), Fraction(-5, 1000), Fraction(17, 1000), Fraction(-12, 1000))
    microtiming = tuple((i, float(q * straight.pulse + deviation), 60)
                       for i, (q, deviation) in enumerate(zip(positions, jitter, strict=True)))
    narrow, broad = float(straight.pulse / 10), float(3 * straight.pulse / 10)
    micro = _synthetic_pairs(microtiming, straight_candidates, narrow)
    swing_oracle = _synthetic_pairs(swing_candidates, swing_candidates, narrow)
    swing_straight = _synthetic_pairs(swing_candidates, straight_candidates, narrow)
    wrong_reference = (('eighth_offbeat', float(straight.pulse / 2), 60),)
    wrong_candidate = (('sixteenth_position', float(straight.pulse / 4), 60),)
    wrong_narrow = _synthetic_pairs(wrong_reference, wrong_candidate, narrow)
    wrong_broad = _synthetic_pairs(wrong_reference, wrong_candidate, broad)
    ambiguous = _synthetic_pairs(wrong_reference, wrong_candidate + wrong_reference, broad)
    symbolic = parse_score(b'<score-partwise><part id="P1"><measure number="1">'
                           b'<attributes><divisions>1</divisions><time><beats>1</beats>'
                           b'<beat-type>4</beat-type></time></attributes><note><pitch>'
                           b'<step>C</step><octave>4</octave></pitch><duration>1</duration>'
                           b'<notations><articulations><staccato/></articulations></notations>'
                           b'</note></measure></part></score-partwise>')
    staccato = duration_context(symbolic, (Reference(0., .24, 60),), {0: 0}, straight, straight)
    expected = (micro['correct_identity_pairs'] == 4 and swing_oracle['correct_identity_pairs'] == 4
                and swing_straight['correct_identity_pairs'] == 2
                and wrong_narrow['admitted_pairs'] == 0 and wrong_broad['wrong_identity_pairs'] == 1
                and ambiguous['admitted_pairs'] == 0 and ambiguous['references_with_multiple_candidates'] == 1
                and staccato['band_counts']['shorter_both'] == 1)
    _require(expected, 'predeclared synthetic control behavior changed')
    return {
        'status': 'completed', 'expected_behavior_observed': True, 'illustrative_only': True,
        'real_recordings_used': 0, 'audio_loaded': False, 'model_inferences': 0,
        'thresholds_selected_from_results': False, 'human_acceptability_benchmark': False,
        'pulse_seconds': float(straight.pulse), 'narrow_pulse_ratio': .1, 'broad_pulse_ratio': .3,
        'straight_with_microtiming': micro,
        'known_two_to_one_swing': {'oracle_map': swing_oracle, 'straight_map': swing_straight,
                                 'ratio_known_by_construction': 2., 'ratio_fitted': False},
        'incorrect_subdivision': {'narrow': wrong_narrow, 'broad': wrong_broad,
                                 'broad_with_competing_correct_candidate': ambiguous},
        'staccato_short_release': {'same_written_quarter_note_intent': True,
                                  'performed_to_projected_duration_ratio': .4,
                                  'duration_diagnostic': staccato,
                                  'short_duration_implies_musical_error': False},
    }

"""Conservative source correspondence, independent of model/gate outcomes.

This module never reads audio or model predictions. The source-only analysis is
complete before a separate function reads the immutable prior matching receipt.
Admitted pairs establish source consistency, not independent acoustic truth.
"""
from __future__ import annotations

import bisect
import csv
import hashlib
import io
import json
import math
import statistics
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

PLANNED_IDS = ('02', '19', '08', '12', '05', '06')
BASES = ('default', 'onset065')
ARMS = ('raw', 'relative_soft', 'tail_only', 'non_tail_only')
WINDOWS_MS = (50, 100, 200)
CATEGORIES = ('staccato', 'tenuto', 'accent', 'other_marked',
              'mixed_articulation', 'unmarked', 'unresolved')
PRIOR_ZIP_SHA256 = 'ba88b9bda70d4a560a3d05c85ea5301d2e8ff98ea81746d676a1c6695898e10e'
PRIOR_REPORT_SHA256 = 'e79ff94736b471da64638a93456ef4f1510750c843960ae924fc1f488ad2f754'
PRIOR_PATH = Path(__file__).resolve().parents[1] / 'docs/research/receipts/kraisler-gate-43184102838.zip'
MAX_CLOCK_GAP_Q = Fraction(4)
MAX_CLOCK_GAP_S = 3.0
MAX_CANDIDATES = 64
REST_GUARD_S = 0.1


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _identity(value):
    return _sha(json.dumps(value, separators=(',', ':'), sort_keys=True,
                           allow_nan=False).encode())


def _rows(raw, columns):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= 4_000_000:
        raise ValueError('bounded nonempty UTF-8 CSV bytes required')
    reader = csv.reader(io.StringIO(raw.decode('utf-8-sig')), strict=True)
    if tuple(next(reader, ())) != columns:
        raise ValueError('CSV header mismatch')
    result = list(reader)
    if not result or len(result) > 20_000 or any(len(row) != len(columns) for row in result):
        raise ValueError('empty, oversized or malformed CSV')
    return result


@dataclass(frozen=True)
class Reference:
    onset: float
    offset: float
    midi: int


@dataclass(frozen=True)
class Beat:
    time: float
    kind: str
    meter: tuple[int, int]
    piano: bool
    violin: bool


def read_notes(raw, duration):
    if isinstance(duration, bool) or not math.isfinite(duration) or duration <= 0:
        raise ValueError('positive finite audio duration metadata required')
    result, seen = [], set()
    for row in _rows(raw, ('onset', 'offset', 'midi', 'velocity')):
        onset, offset, pitch, velocity = map(float, row)
        if (not all(math.isfinite(v) for v in (onset, offset, pitch, velocity))
                or not 0 <= onset < offset <= duration or pitch != int(pitch)
                or not 0 <= pitch <= 127 or velocity != int(velocity)
                or not 0 <= velocity <= 127):
            raise ValueError('invalid reference row')
        key = (onset, offset, int(pitch))
        if key in seen or result and onset < result[-1].onset:
            raise ValueError('duplicate or unordered reference row')
        seen.add(key)
        result.append(Reference(*key))
    return tuple(result)


def read_beats(raw, duration):
    result, meter = [], None
    for time, kind, signature, piano, violin in _rows(
            raw, ('beat_time', 'beat_type', 'time_signature', 'piano', 'violin')):
        time = float(time)
        if signature:
            fields = signature.split('/')
            if len(fields) != 2 or any(not v.isdigit() for v in fields):
                raise ValueError('invalid beat meter')
            meter = tuple(map(int, fields))
        if (meter is None or not 1 <= meter[0] <= 32 or meter[1] not in (1, 2, 4, 8, 16, 32)
                or not math.isfinite(time) or not 0 <= time <= duration
                or result and time <= result[-1].time or kind not in ('b', 'db')
                or piano not in ('True', 'False') or violin not in ('True', 'False')):
            raise ValueError('invalid beat row/order/meter/activity')
        result.append(Beat(time, kind, meter, piano == 'True', violin == 'True'))
    return tuple(result)


@dataclass(frozen=True)
class Clock:
    points: tuple[tuple[Fraction, float], ...]

    def __post_init__(self):
        if not 2 <= len(self.points) <= 20_000:
            raise ValueError('clock requires bounded distinct anchors')
        for index, (q, time) in enumerate(self.points):
            if not math.isfinite(float(q)) or not math.isfinite(time) or time < 0:
                raise ValueError('invalid clock anchor')
            if index and (q <= self.points[index - 1][0] or time <= self.points[index - 1][1]):
                raise ValueError('clock must be strictly increasing; no repair permitted')

    def time_at(self, q):
        q = Fraction(q)
        positions = tuple(v[0] for v in self.points)
        index = bisect.bisect_left(positions, q)
        if index < len(positions) and positions[index] == q:
            return self.points[index][1]
        if index == 0 or index == len(positions):
            return None
        left_q, left_t = self.points[index - 1]
        right_q, right_t = self.points[index]
        if right_q - left_q > MAX_CLOCK_GAP_Q or right_t - left_t > MAX_CLOCK_GAP_S:
            return None
        return left_t + float((q - left_q) / (right_q - left_q)) * (right_t - left_t)

    def supports_interval(self, start, end):
        if start >= end or self.time_at(start) is None or self.time_at(end) is None:
            return False
        for (q0, t0), (q1, t1) in zip(self.points, self.points[1:]):
            if q0 < end and q1 > start and (q1 - q0 > MAX_CLOCK_GAP_Q or t1 - t0 > MAX_CLOCK_GAP_S):
                return False
        return True


def _percentile(values, p):
    values = sorted(values)
    if not values:
        return None
    rank = (len(values) - 1) * p
    lo, hi = math.floor(rank), math.ceil(rank)
    return values[lo] + (rank - lo) * (values[hi] - values[lo])


def _residuals(values):
    values = [abs(v) for v in values]
    return {'count': len(values), 'median_s': statistics.median(values) if values else None,
            'p95_s': _percentile(values, .95), 'max_s': max(values) if values else None}


def piano_clock(match):
    if not match.strict_score_consistency:
        raise ValueError('piano match/XML symbolic consistency not established')
    grouped = defaultdict(list)
    for anchor in match.anchors:
        grouped[Fraction(anchor.q)].append(float(anchor.time))
    points = tuple((q, statistics.median(times)) for q, times in sorted(grouped.items()))
    clock = Clock(points)
    return clock, {'eligible_note_anchors': sum(map(len, grouped.values())),
                   'distinct_quarter_anchors': len(points),
                   'coincident_group_max_spread_s': max(max(v) - min(v) for v in grouped.values()),
                   'largest_gap_q': float(max(b[0] - a[0] for a, b in zip(points, points[1:]))),
                   'largest_gap_s': max(b[1] - a[1] for a, b in zip(points, points[1:])),
                   'strictly_increasing': True, 'fitted_shift_or_warp': False}


def symbolic_beats(score):
    if not score.admissible_for_alignment or not score.measures:
        raise ValueError('score structure not admitted')
    if len({m.part for m in score.measures}) != 1:
        raise ValueError('single instrumental part required')
    result = []
    for measure in score.measures:
        numerator, denominator = measure.time_signature
        unit = Fraction(4, denominator)
        if numerator >= 6 and numerator % 3 == 0 and denominator >= 8:
            unit *= 3
        phase = measure.nominal_duration_q - (measure.end_q - measure.onset_q) if measure.pickup else Fraction(0)
        first = math.ceil(phase / unit) * unit - phase
        position = first
        while measure.onset_q + position < measure.end_q:
            q = measure.onset_q + position
            kind = 'db' if position == 0 and not measure.pickup else 'b'
            result.append((q, kind, measure.time_signature))
            if len(result) > 20_000:
                raise ValueError('symbolic beat budget exceeded')
            position += unit
    if not result or any(b[0] <= a[0] for a, b in zip(result, result[1:])):
        raise ValueError('invalid symbolic beat sequence')
    return tuple(result)


def _compatible_measures(violin, piano):
    if not violin.admissible_for_alignment or not piano.admissible_for_alignment:
        return False
    if len(violin.measures) != len(piano.measures):
        return False
    fields = ('onset_q', 'end_q', 'time_signature', 'pickup', 'short_final')
    return all(all(getattr(v, k) == getattr(p, k) for k in fields)
               for v, p in zip(violin.measures, piano.measures))


def align_beats(score, piano, beats, pclock):
    result = {'status': 'unadmitted', 'reason': None, 'observed_beats': len(beats),
              'candidate_budget': MAX_CANDIDATES, 'candidates': [],
              'independent_acoustic_truth': False}
    if not _compatible_measures(score, piano):
        result['reason'] = 'violin/piano measure structures differ or are unsupported'
        return None, result
    grid = symbolic_beats(score)
    result['symbolic_beats'] = len(grid)
    n = len(beats)
    candidates = []
    for start in range(max(0, len(grid) - n + 1)):
        selected = grid[start:start + n]
        if all((kind, meter) == (beat.kind, beat.meter)
               for (_, kind, meter), beat in zip(selected, beats)):
            candidates.append((start, selected))
    result['structural_candidate_count'] = len(candidates)
    if len(candidates) > MAX_CANDIDATES:
        result['reason'] = 'structural candidate budget exceeded'
        return None, result
    passing = []
    for start, selected in candidates:
        values = [(pclock.time_at(q), beat.time) for (q, _, _), beat in zip(selected, beats)]
        residuals = [actual - expected for expected, actual in values if expected is not None]
        stats = _residuals(residuals)
        coverage = len(residuals) / n
        reasons = []
        if coverage < .9:
            reasons.append('piano support below 90%')
        for name, bound in (('median_s', .1), ('p95_s', .25), ('max_s', .5)):
            if stats[name] is None or stats[name] > bound + 1e-12:
                reasons.append(name + ' exceeds fixed bound or unavailable')
        public = {'symbolic_start_index': start, 'symbolic_prefix_beats': start,
                  'symbolic_suffix_beats': len(grid) - start - n,
                  'supported_fraction': coverage, 'residuals': stats,
                  'admitted': not reasons, 'rejection_reasons': reasons}
        result['candidates'].append(public)
        if not reasons:
            passing.append((selected, public))
    if len(passing) != 1:
        result['reason'] = 'no candidate passed' if not passing else 'multiple candidates passed'
        return None, result
    selected, chosen = passing[0]
    clock = Clock(tuple((q, beat.time) for (q, _, _), beat in zip(selected, beats)))
    result.update(status='admitted', reason=None,
                  chosen_symbolic_start_index=chosen['symbolic_start_index'],
                  mapping_sha256=_identity([[str(q), beat.time] for (q, _, _), beat in zip(selected, beats)]))
    return clock, result


def _category(event):
    tags = set(event.articulations)
    groups = set()
    if tags & {'staccato', 'staccatissimo'}:
        groups.add('staccato')
    if 'tenuto' in tags:
        groups.add('tenuto')
    if tags & {'accent', 'strong-accent'}:
        groups.add('accent')
    if len(groups) > 1:
        return 'mixed_articulation'
    if groups:
        return next(iter(groups))
    return 'other_marked' if tags else 'unmarked'


def _membership(reference_count, pairs, attacks):
    labels = ['unresolved'] * reference_count
    for ri, si in pairs.items():
        labels[ri] = _category(attacks[si])
    return {name: ''.join('1' if label == name else '0' for label in labels)
            for name in CATEGORIES}


def _relations(references, attacks, clock, window):
    forward, reverse = defaultdict(set), defaultdict(set)
    for si, attack in enumerate(attacks):
        if attack.grace:
            continue
        time = clock.time_at(attack.onset_q)
        if time is None:
            continue
        for ri, reference in enumerate(references):
            if reference.midi == attack.midi and abs(reference.onset - time) <= window + 1e-12:
                forward[ri].add(si)
                reverse[si].add(ri)
    return forward, reverse


def pair_references(references, score, bclock, pclock, window_ms):
    attacks = score.attacks
    if bclock is None or pclock is None:
        return {}, {'window_ms': window_ms, 'matched_pairs': 0,
                    'reference_count': len(references), 'coverage': 0.,
                    'unresolved_reasons': {'source_clock_unadmitted': len(references)},
                    'memberships': _membership(len(references), {}, attacks),
                    'pair_identity_sha256': _identity([]), 'onset_residuals': {}}
    bf, br = _relations(references, attacks, bclock, window_ms / 1000)
    pf, pr = _relations(references, attacks, pclock, window_ms / 1000)
    pairs, reasons, berrors, perrors = {}, Counter(), [], []
    grace_positions = {e.onset_q for e in score.events if e.grace}
    for ri, reference in enumerate(references):
        if not bf[ri] or not pf[ri]:
            reasons['no_candidate_in_one_or_both_clocks'] += 1
            continue
        if len(bf[ri]) != 1 or len(pf[ri]) != 1:
            reasons['reference_has_multiple_candidates'] += 1
            continue
        si = next(iter(bf[ri]))
        if pf[ri] != {si}:
            reasons['clocks_disagree_on_identity'] += 1
            continue
        if len(br[si]) != 1 or len(pr[si]) != 1:
            reasons['score_attack_has_multiple_references'] += 1
            continue
        event = attacks[si]
        if event.ornaments or event.grace or event.onset_q in grace_positions:
            reasons['ornament_or_grace_context'] += 1
            continue
        pairs[ri] = si
        berrors.append(reference.onset - bclock.time_at(event.onset_q))
        perrors.append(reference.onset - pclock.time_at(event.onset_q))
    if len(pairs) + sum(reasons.values()) != len(references):
        raise ValueError('correspondence accounting failed')
    return pairs, {'window_ms': window_ms, 'matched_pairs': len(pairs),
                   'reference_count': len(references), 'coverage': len(pairs) / len(references),
                   'unresolved_reasons': dict(reasons),
                   'memberships': _membership(len(references), pairs, attacks),
                   'pair_identity_sha256': _identity([[ri, attacks[si].id] for ri, si in sorted(pairs.items())]),
                   'onset_residuals': {'global_beats': _residuals(berrors), 'piano': _residuals(perrors)}}


def union_intervals(intervals):
    result = []
    for start, end in sorted(intervals):
        if not math.isfinite(float(start)) or not math.isfinite(float(end)) or start >= end:
            raise ValueError('invalid interval')
        if result and start <= result[-1][1]:
            result[-1] = (result[-1][0], max(end, result[-1][1]))
        else:
            result.append((start, end))
    return result


def overlap_seconds(left, right):
    left, right = union_intervals(left), union_intervals(right)
    i = j = 0
    total = 0.
    while i < len(left) and j < len(right):
        total += max(0., min(left[i][1], right[j][1]) - max(left[i][0], right[j][0]))
        if left[i][1] <= right[j][1]:
            i += 1
        else:
            j += 1
    return total


def rest_context(score, references, bclock, pclock):
    result = {'explicit_rest_elements': len(score.rests),
              'instrument_wide_rest_intervals': len(score.global_rests),
              'unknown_score_intervals': len(score.unknown_intervals),
              'projected_rest_intervals': 0, 'unprojectable_rest_intervals': len(score.global_rests),
              'guard_seconds': REST_GUARD_S, 'written_rest_accuracy_measured': False,
              'prediction_occupancy_available': False}
    if bclock is None or pclock is None:
        result['status'] = 'source_clock_unadmitted'
        return result
    beat_intervals, piano_intervals, cores, endpoints = [], [], [], []
    for rest in score.global_rests:
        start, end = rest.onset_q, rest.end_q
        if not bclock.supports_interval(start, end) or not pclock.supports_interval(start, end):
            continue
        b = (bclock.time_at(start), bclock.time_at(end))
        p = (pclock.time_at(start), pclock.time_at(end))
        beat_intervals.append(b)
        piano_intervals.append(p)
        endpoints.extend((b[0] - p[0], b[1] - p[1]))
        core = (max(b[0], p[0]) + REST_GUARD_S, min(b[1], p[1]) - REST_GUARD_S)
        if core[0] < core[1]:
            cores.append(core)
    note_intervals = [(r.onset, r.offset) for r in references]
    result.update(status='projected_source_context', projected_rest_intervals=len(beat_intervals),
                  unprojectable_rest_intervals=len(score.global_rests) - len(beat_intervals),
                  endpoint_clock_disagreement=_residuals(endpoints),
                  guarded_shared_intervals=len(cores), projections={})
    for name, intervals in (('global_beats', beat_intervals), ('piano', piano_intervals),
                            ('guarded_shared_core', cores)):
        total = sum(b - a for a, b in union_intervals(intervals))
        overlap = overlap_seconds(intervals, note_intervals)
        result['projections'][name] = {'duration_s': total, 'annotated_note_overlap_s': overlap,
                                       'uncovered_by_note_annotations_s': max(0., total - overlap)}
    return result


def analyze_correspondence(score, piano_score, match_audit, raw_beats, raw_notes, audio_duration_s):
    references = read_notes(raw_notes, audio_duration_s)
    beats = read_beats(raw_beats, audio_duration_s)
    analysis = {'reference_count': len(references),
                'source_sha256': {'notes': _sha(raw_notes), 'beats': _sha(raw_beats)},
                'score': {'counts': dict(score.counts), 'warnings': list(score.warnings),
                          'unsupported': list(score.unsupported)},
                'piano_score': {'counts': dict(piano_score.counts),
                                'unsupported': list(piano_score.unsupported)},
                'piano_match': dict(match_audit.diagnostics),
                'independent_acoustic_truth': False, 'new_model_inferences': 0}
    bclock = pclock = None
    try:
        pclock, audit = piano_clock(match_audit)
        analysis['piano_clock'] = {'status': 'admitted', **audit}
        bclock, analysis['beat_alignment'] = align_beats(score, piano_score, beats, pclock)
    except ValueError as exc:
        analysis['piano_clock'] = {'status': 'unadmitted', 'reason': str(exc)[:400]}
        analysis['beat_alignment'] = {'status': 'unadmitted', 'reason': str(exc)[:400],
                                      'observed_beats': len(beats), 'candidates': []}
    if not score.admissible_for_alignment:
        bclock = None
    by_window, private_pairs = {}, {}
    for window in WINDOWS_MS:
        private_pairs[window], by_window[str(window)] = pair_references(
            references, score, bclock, pclock, window)
    stable = {ri: si for ri, si in private_pairs[100].items()
              if all(private_pairs[window].get(ri) == si for window in WINDOWS_MS)}
    analysis['correspondence'] = {
        'primary_window_ms': 100, 'windows': by_window,
        'stable_across_windows': {'matched_pairs': len(stable),
                                 'coverage': len(stable) / len(references),
                                 'memberships': _membership(len(references), stable, score.attacks),
                                 'pair_identity_sha256': _identity([[ri, score.attacks[si].id]
                                                                   for ri, si in sorted(stable.items())])}}
    analysis['rest_context'] = rest_context(score, references, bclock, pclock)
    return analysis


def read_previous_receipt(path=PRIOR_PATH):
    path = Path(path)
    if not path.is_file() or path.is_symlink() or path.stat().st_size != 16_111:
        raise ValueError('exact previous receipt ZIP required')
    raw = path.read_bytes()
    if _sha(raw) != PRIOR_ZIP_SHA256:
        raise ValueError('previous receipt ZIP digest mismatch')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if archive.namelist() != ['report.json'] or archive.getinfo('report.json').file_size != 155_591:
            raise ValueError('unexpected previous artifact members')
        payload = archive.read('report.json')
    if _sha(payload) != PRIOR_REPORT_SHA256:
        raise ValueError('previous report digest mismatch')
    report = json.loads(payload)
    if (report.get('status') != 'complete' or report.get('planned_ids') != list(PLANNED_IDS)
            or report.get('planned_bases') != list(BASES) or report.get('planned_arms') != list(ARMS)
            or report.get('summary', {}).get('scored_conditions') != 48
            or [r.get('id') for r in report.get('cases', [])] != list(PLANNED_IDS)):
        raise ValueError('previous study incomplete or changed')
    return report


def _validate_membership(memberships, count):
    if set(memberships) != set(CATEGORIES):
        raise ValueError('category population changed')
    if any(len(mask) != count or set(mask) - {'0', '1'} for mask in memberships.values()):
        raise ValueError('invalid category mask')
    if any(sum(mask[i] == '1' for mask in memberships.values()) != 1 for i in range(count)):
        raise ValueError('categories do not partition every reference')


def attribute_previous_case(prior_case, analysis):
    count = analysis['reference_count']
    if (prior_case.get('status') != 'scored'
            or prior_case.get('reference_sha256') != analysis['source_sha256']['notes']
            or prior_case.get('beats_sha256') != analysis['source_sha256']['beats']
            or set(prior_case.get('bases', {})) != set(BASES)):
        raise ValueError('previous case source identity or completeness mismatch')
    scopes = {'primary_100ms': analysis['correspondence']['windows']['100']['memberships'],
              'stable_50_100_200ms': analysis['correspondence']['stable_across_windows']['memberships']}
    result = {'source': 'immutable prior reference match masks', 'new_f1_computed': False,
              'prediction_false_positives_classified': False, 'scopes': {}}
    for scope, memberships in scopes.items():
        _validate_membership(memberships, count)
        groups = {name: {'reference_notes': mask.count('1'), 'bases': {}} for name, mask in memberships.items()}
        for base in BASES:
            arms = prior_case['bases'][base]['arms']
            if set(arms) != set(ARMS):
                raise ValueError('previous arm population mismatch')
            for name in CATEGORIES:
                groups[name]['bases'][base] = {}
            for arm in ARMS:
                metrics = arms[arm]['metrics']
                if metrics['reference_note_count'] != count:
                    raise ValueError('reference count differs from immutable receipt')
                for metric in ('onset', 'onset_offset'):
                    before = arms['raw']['metrics'][metric + '_reference_mask']
                    after = metrics[metric + '_reference_mask']
                    if any(len(mask) != count or set(mask) - {'0', '1'} for mask in (before, after)):
                        raise ValueError('invalid previous matching masks')
                    prediction_count = arms[arm]['count']
                    expected_f1 = round(2 * after.count('1') / (count + prediction_count), 8)
                    if abs(metrics[metric + '_f1'] - expected_f1) > 1e-8:
                        raise ValueError('previous count/mask/F1 identity failed')
                    total_gain = total_loss = total_matched = 0
                    for name, mask in memberships.items():
                        indexes = [i for i, bit in enumerate(mask) if bit == '1']
                        matched = sum(after[i] == '1' for i in indexes)
                        before_matched = sum(before[i] == '1' for i in indexes)
                        gained = sum(before[i] == '0' and after[i] == '1' for i in indexes)
                        damaged = sum(before[i] == '1' and after[i] == '0' for i in indexes)
                        if before_matched + gained - damaged != matched:
                            raise ValueError('conditional gain/damage conservation failed')
                        groups[name]['bases'][base].setdefault(arm, {})[metric] = {
                            'raw_matched': before_matched, 'matched': matched, 'gained': gained,
                            'damaged': damaged, 'reference_recall': matched / len(indexes) if indexes else None}
                        total_gain += gained
                        total_loss += damaged
                        total_matched += matched
                    transition = metrics['transition'][metric]
                    if (total_matched != after.count('1') or total_gain != transition['gained']
                            or total_loss != transition['damaged']):
                        raise ValueError('whole-recording match transition not conserved')
        result['scopes'][scope] = groups
    return result


def summarize_cases(cases, planned_ids=PLANNED_IDS):
    if (tuple(planned_ids) != PLANNED_IDS or len(cases) != 6
            or [c.get('id') for c in cases] != list(PLANNED_IDS)
            or any(c.get('status') != 'analyzed' or 'analysis' not in c or 'attribution' not in c for c in cases)):
        return None
    total = sum(c['analysis']['reference_count'] for c in cases)
    summary = {'recordings': 6, 'reference_notes': total, 'new_model_inferences': 0,
               'source_consistent_beat_maps': sum(c['analysis']['beat_alignment']['status'] == 'admitted' for c in cases),
               'independent_acoustic_alignment_verified': False, 'written_rest_accuracy_measured': False,
               'windows': {}, 'conditional_ledger': {}, 'rest_context': {}}
    for window in WINDOWS_MS:
        rows = [c['analysis']['correspondence']['windows'][str(window)] for c in cases]
        count = sum(r['matched_pairs'] for r in rows)
        summary['windows'][str(window)] = {'matched_pairs': count, 'coverage': count / total,
                                          'unresolved': total - count}
    stable = sum(c['analysis']['correspondence']['stable_across_windows']['matched_pairs'] for c in cases)
    summary['stable_across_windows'] = {'matched_pairs': stable, 'coverage': stable / total,
                                       'unresolved': total - stable}
    for scope in ('primary_100ms', 'stable_50_100_200ms'):
        summary['conditional_ledger'][scope] = {}
        for category in CATEGORIES:
            groups = [c['attribution']['scopes'][scope][category] for c in cases]
            n = sum(g['reference_notes'] for g in groups)
            out = {'reference_notes': n, 'bases': {}}
            for base in BASES:
                out['bases'][base] = {}
                for arm in ARMS:
                    out['bases'][base][arm] = {}
                    for metric in ('onset', 'onset_offset'):
                        rows = [g['bases'][base][arm][metric] for g in groups]
                        value = {key: sum(r[key] for r in rows) for key in ('raw_matched', 'matched', 'gained', 'damaged')}
                        value['reference_recall'] = value['matched'] / n if n else None
                        out['bases'][base][arm][metric] = value
            summary['conditional_ledger'][scope][category] = out
        if sum(g['reference_notes'] for g in summary['conditional_ledger'][scope].values()) != total:
            raise ValueError('aggregate category population failed')
    contexts = [c['analysis']['rest_context'] for c in cases]
    for key in ('explicit_rest_elements', 'instrument_wide_rest_intervals',
                'unknown_score_intervals', 'projected_rest_intervals', 'unprojectable_rest_intervals'):
        summary['rest_context'][key] = sum(c[key] for c in contexts)
    summary['rest_context']['projected_recordings'] = sum(c['status'] == 'projected_source_context' for c in contexts)
    summary['rest_context']['projections'] = {
        name: {key: sum(c.get('projections', {}).get(name, {}).get(key, 0.) for c in contexts)
               for key in ('duration_s', 'annotated_note_overlap_s', 'uncovered_by_note_annotations_s')}
        for name in ('global_beats', 'piano', 'guarded_shared_core')}
    summary['per_recording'] = [{'id': c['id'], 'beat_alignment': c['analysis']['beat_alignment']['status'],
                                  'reference_notes': c['analysis']['reference_count'],
                                  'matched_pairs_100ms': c['analysis']['correspondence']['windows']['100']['matched_pairs'],
                                  'stable_pairs': c['analysis']['correspondence']['stable_across_windows']['matched_pairs']}
                                 for c in cases]
    return summary

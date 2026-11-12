"""Source-only local correspondence and descriptive performed-time ranges.

No model outcomes or reference offsets select onset identities. Range
compatibility is not musical correctness or independent acoustic ground truth.
"""
from __future__ import annotations

import hashlib
import json
import math
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

from scripts import kraisler_correspondence as frozen
from scripts.kraisler_local_clock import build_local_clocks
from scripts.kraisler_rhythm_ranges import (
    duration_context,
    rest_range_context,
    source_expression_metadata,
)

PLANNED_IDS = frozen.PLANNED_IDS
CATEGORIES = frozen.CATEGORIES
BASES = frozen.BASES
ARMS = frozen.ARMS
WINDOW_SCOPES = ('fixed100', 'tempo10', 'tempo20', 'tempo30')
SCOPES = (*WINDOW_SCOPES, 'stable_tempo')
PRIMARY_SCOPE = 'tempo20'
ALPHAS = {'tempo10': .1, 'tempo20': .2, 'tempo30': .3}
BASELINE_PATH = (Path(__file__).resolve().parents[1]
                 / 'docs/research/receipts/kraisler-alignment-43201534121.zip')
BASELINE_ZIP_SHA256 = '6f8af87bef6fa8febc977e037130b520d05d0dab8df815e3684ae6239d475005'
BASELINE_REPORT_SHA256 = 'ec5048b11ede7364ca5c68e9f7fb6f4889ed818d881f502aa34726ba54335f7a'


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _identity(value):
    return _digest(json.dumps(value, sort_keys=True, separators=(',', ':'),
                              allow_nan=False).encode())


def onset_half_width(clock, q, scope):
    if scope not in WINDOW_SCOPES:
        raise ValueError('unknown predeclared onset scope')
    if scope == 'fixed100':
        return .1
    period = clock.period_at(q)
    if period is None:
        return None
    if isinstance(period, bool) or not math.isfinite(period) or period <= 0:
        raise ValueError('positive finite observed pulse period required')
    return min(.2, max(.05, ALPHAS[scope] * period))


def _scope_result(references, score, pairs, scope, reasons, berrors=(), perrors=(),
                  bnormalized=(), pnormalized=(), widths=()):
    count = len(references)
    if len(pairs) + sum(reasons.values()) != count:
        raise ValueError('every reference must remain in correspondence accounting')
    return {
        'scope': scope, 'reference_count': count, 'matched_pairs': len(pairs),
        'coverage': len(pairs) / count if count else 0.,
        'unresolved': count - len(pairs), 'unresolved_reasons': dict(reasons),
        'memberships': frozen._membership(count, pairs, score.attacks),
        'pair_identity_sha256': _identity([[ri, score.attacks[si].id]
                                           for ri, si in sorted(pairs.items())]),
        'residual_statistics_computed': scope != 'stable_tempo',
        'onset_residuals_seconds': {'global_beats': frozen._residuals(berrors),
                                   'piano': frozen._residuals(perrors)},
        'onset_residuals_pulse_fraction': {
            'global_beats': frozen._residuals(bnormalized),
            'piano': frozen._residuals(pnormalized)},
        'matched_half_width_seconds': frozen._residuals(widths),
        'offset_used_for_identity': False,
    }


def pair_local_references(references, score, bclock, pclock, scope):
    """Preserve unsupported beat competitors before admitting a unique pair."""
    if scope not in WINDOW_SCOPES:
        raise ValueError('unknown predeclared onset scope')
    if bclock is None or pclock is None:
        return {}, _scope_result(references, score, {}, scope,
                                 {'source_clock_unadmitted': len(references)})
    bf, br, pf, pr = (defaultdict(set) for _ in range(4))
    widths = {}
    for si, attack in enumerate(score.attacks):
        if attack.grace:
            continue
        provisional = bclock.candidate_time_at(attack.onset_q)
        width = onset_half_width(bclock, attack.onset_q, scope)
        if provisional is None or width is None:
            continue
        widths[si] = width
        supported_piano = pclock.time_at(attack.onset_q)
        for ri, reference in enumerate(references):
            if reference.midi != attack.midi:
                continue
            if abs(reference.onset - provisional) <= width + 1e-12:
                bf[ri].add(si)
                br[si].add(ri)
            if (supported_piano is not None
                    and abs(reference.onset - supported_piano) <= width + 1e-12):
                pf[ri].add(si)
                pr[si].add(ri)
    pairs, reasons = {}, Counter()
    berrors, perrors, bnormalized, pnormalized, used_widths = [], [], [], [], []
    grace_positions = {event.onset_q for event in score.events if event.grace}
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
        attack = score.attacks[si]
        width = widths[si]
        btime, ptime = bclock.time_at(attack.onset_q), pclock.time_at(attack.onset_q)
        if (btime is None or ptime is None
                or not bclock.supports_time_band(attack.onset_q, width)
                or not pclock.supports_time_band(attack.onset_q, width)):
            reasons['full_onset_window_not_locally_supported'] += 1
            continue
        if attack.ornaments or attack.grace or attack.onset_q in grace_positions:
            reasons['ornament_or_grace_context'] += 1
            continue
        period = bclock.period_at(attack.onset_q)
        if period is None or period <= 0:
            raise ValueError('admitted onset has no pulse period')
        pairs[ri] = si
        berrors.append(reference.onset - btime)
        perrors.append(reference.onset - ptime)
        bnormalized.append((reference.onset - btime) / period)
        pnormalized.append((reference.onset - ptime) / period)
        used_widths.append(width)
    return pairs, _scope_result(references, score, pairs, scope, reasons, berrors,
                                perrors, bnormalized, pnormalized, used_widths)


def analyze_expressive(score, piano_score, match_audit, raw_beats, raw_notes,
                       audio_duration_s, *, raw_score):
    references = frozen.read_notes(raw_notes, audio_duration_s)
    beats = frozen.read_beats(raw_beats, audio_duration_s)
    baseline = frozen.analyze_correspondence(
        score, piano_score, match_audit, raw_beats, raw_notes, audio_duration_s)
    bclock, pclock, support = build_local_clocks(score, piano_score, match_audit, beats)
    pairs, scopes = {}, {}
    for scope in WINDOW_SCOPES:
        pairs[scope], scopes[scope] = pair_local_references(
            references, score, bclock, pclock, scope)
    stable = {ri: si for ri, si in pairs[PRIMARY_SCOPE].items()
              if all(pairs[scope].get(ri) == si for scope in ALPHAS)}
    scopes['stable_tempo'] = _scope_result(
        references, score, stable, 'stable_tempo',
        {'not_same_unique_pair_at_all_tempo_windows': len(references) - len(stable)})
    before, after = pairs['fixed100'], pairs[PRIMARY_SCOPE]
    retained = sum(after.get(ri) == si for ri, si in before.items())
    different = sum(ri in after and after[ri] != si for ri, si in before.items())
    return {
        'reference_count': len(references),
        'source_sha256': {'notes': _digest(raw_notes), 'beats': _digest(raw_beats),
                          'score': _digest(raw_score)},
        'frozen_baseline': baseline,
        'local_clocks_available': bclock is not None and pclock is not None,
        'local_support': support,
        'correspondence': {'primary_scope': PRIMARY_SCOPE, 'scopes': scopes,
                           'fixed100_to_tempo20': {
                               'same_pair': retained, 'different_pair': different,
                               'newly_resolved_reference': len(after.keys() - before.keys()),
                               'newly_unresolved_reference': len(before.keys() - after.keys())}},
        'duration_context': {scope: duration_context(score, references, pairs[scope],
                                                      bclock, pclock)
                             for scope in ('fixed100', PRIMARY_SCOPE)},
        'rest_ranges': rest_range_context(score, references, bclock, pclock),
        'source_expression': source_expression_metadata(raw_score, raw_notes),
        'independent_acoustic_truth': False, 'new_model_inferences': 0,
        'range_aware_model_f1_measured': False,
    }


def read_alignment_baseline(path=BASELINE_PATH):
    path = Path(path)
    if not path.is_file() or path.is_symlink() or path.stat().st_size != 25_366:
        raise ValueError('exact previous alignment ZIP required')
    raw = path.read_bytes()
    if _digest(raw) != BASELINE_ZIP_SHA256:
        raise ValueError('previous alignment ZIP digest mismatch')
    with zipfile.ZipFile(path) as archive:
        if archive.namelist() != ['report.json'] or archive.getinfo('report.json').file_size != 543_226:
            raise ValueError('unexpected alignment artifact members')
        payload = archive.read('report.json')
    if _digest(payload) != BASELINE_REPORT_SHA256:
        raise ValueError('previous alignment report digest mismatch')
    report = json.loads(payload)
    if (report.get('status') != 'complete' or report.get('planned_ids') != list(PLANNED_IDS)
            or [row.get('id') for row in report.get('cases', [])] != list(PLANNED_IDS)
            or report.get('completed_analyses') != 6 or report.get('completed_attributions') != 6
            or report.get('summary', {}).get('reference_notes') != 947):
        raise ValueError('previous alignment baseline incomplete or changed')
    return report


def verify_baseline_case(old_case, analysis):
    if (old_case.get('status') != 'analyzed' or not isinstance(old_case.get('analysis'), dict)
            or _identity(old_case['analysis']) != _identity(analysis['frozen_baseline'])):
        raise ValueError('frozen global correspondence did not reproduce exactly')
    if old_case['analysis']['reference_count'] != analysis['reference_count']:
        raise ValueError('reference population changed from alignment baseline')


def attribute_expressive(prior_case, analysis):
    """Reuse the unchanged matching ledger; only its source memberships differ."""
    scopes = analysis['correspondence']['scopes']
    if set(scopes) != set(SCOPES):
        raise ValueError('predeclared scope population changed')
    ledger = {}
    for scope, population in scopes.items():
        adapter = {
            'reference_count': analysis['reference_count'],
            'source_sha256': analysis['source_sha256'],
            'correspondence': {'windows': {'100': population},
                               'stable_across_windows': population},
        }
        result = frozen.attribute_previous_case(prior_case, adapter)
        ledger[scope] = result['scopes']['primary_100ms']
    return {'source': 'immutable prior reference matching masks', 'scopes': ledger,
            'new_f1_computed': False, 'prediction_false_positives_classified': False,
            'original_matching_tolerances_unchanged': True}


def _sum_ratio_rows(rows):
    count, total = sum(row['count'] for row in rows), sum(row['sum'] for row in rows)
    return {'count': count, 'sum': total, 'mean': total / count if count else None,
            'cohort_quantiles_computed': False}


def _sum_duration_rows(rows):
    keys = ('reference_notes', 'paired_notes', 'unpaired_notes', 'supported_pairs', 'unsupported_pairs')
    for row in rows:
        if (row['reference_notes'] != row['paired_notes'] + row['unpaired_notes']
                or row['paired_notes'] != row['supported_pairs'] + row['unsupported_pairs']
                or sum(row['band_counts'].values()) != row['supported_pairs']
                or sum(row['unsupported_reasons'].values()) != row['unsupported_pairs']
                or any(row['ratios'][clock]['count'] != row['supported_pairs']
                       for clock in ('global_beats', 'piano'))):
            raise ValueError('duration population or band accounting failed')
    result = {key: sum(row[key] for row in rows) for key in keys}
    result['band_counts'] = dict(sum((Counter(row['band_counts']) for row in rows), Counter()))
    result['unsupported_reasons'] = dict(sum((Counter(row['unsupported_reasons']) for row in rows), Counter()))
    result['ratios'] = {clock: _sum_ratio_rows([row['ratios'][clock] for row in rows])
                        for clock in ('global_beats', 'piano')}
    result['musical_correctness_measured'] = False
    return result


def summarize_expressive(cases, planned_ids=PLANNED_IDS):
    if (tuple(planned_ids) != PLANNED_IDS or len(cases) != 6
            or [row.get('id') for row in cases] != list(PLANNED_IDS)
            or any(row.get('status') != 'analyzed' or not isinstance(row.get('analysis'), dict)
                   or not isinstance(row.get('attribution'), dict) for row in cases)):
        return None
    analyses = [row['analysis'] for row in cases]
    total = sum(row['reference_count'] for row in analyses)
    if total <= 0:
        raise ValueError('nonempty fixed reference population required')
    result = {'recordings': 6, 'reference_notes': total, 'new_model_inferences': 0,
              'primary_scope': PRIMARY_SCOPE, 'independent_acoustic_truth': False,
              'musical_correctness_measured': False, 'range_aware_model_f1_measured': False,
              'recordings_with_local_support': sum(row['local_clocks_available'] for row in analyses),
              'scopes': {}, 'conditional_ledger': {}, 'duration_context': {}, 'rest_ranges': {},
              'frozen_baseline': {
                  'primary_pairs': sum(row['frozen_baseline']['correspondence']['windows']['100']['matched_pairs']
                                       for row in analyses),
                  'stable_pairs': sum(row['frozen_baseline']['correspondence']['stable_across_windows']['matched_pairs']
                                      for row in analyses),
                  'admitted_recordings': sum(row['frozen_baseline']['beat_alignment']['status'] == 'admitted'
                                              for row in analyses)},
              'local_support': {key: sum(row['local_support'][key] for row in analyses)
                                for key in ('beat_cells', 'supported_beat_cells', 'unsupported_beat_cells',
                                            'supported_score_quarters', 'support_components')}}
    for scope in SCOPES:
        rows = [row['correspondence']['scopes'][scope] for row in analyses]
        count = sum(row['matched_pairs'] for row in rows)
        result['scopes'][scope] = {
            'matched_pairs': count, 'coverage': count / total, 'unresolved': total - count,
            'unresolved_reasons': dict(sum((Counter(row['unresolved_reasons']) for row in rows), Counter()))}
        if sum(result['scopes'][scope]['unresolved_reasons'].values()) != total - count:
            raise ValueError('aggregate unresolved accounting failed')
        result['conditional_ledger'][scope] = {}
        for category in CATEGORIES:
            groups = [row['attribution']['scopes'][scope][category] for row in cases]
            n = sum(group['reference_notes'] for group in groups)
            out = {'reference_notes': n, 'bases': {}}
            for base in BASES:
                out['bases'][base] = {}
                for arm in ARMS:
                    out['bases'][base][arm] = {}
                    for metric in ('onset', 'onset_offset'):
                        rows = [group['bases'][base][arm][metric] for group in groups]
                        value = {key: sum(row[key] for row in rows)
                                 for key in ('raw_matched', 'matched', 'gained', 'damaged')}
                        value['reference_recall'] = value['matched'] / n if n else None
                        out['bases'][base][arm][metric] = value
            result['conditional_ledger'][scope][category] = out
        if sum(group['reference_notes'] for group in result['conditional_ledger'][scope].values()) != total:
            raise ValueError('aggregate articulation partition failed')
    for scope in ('fixed100', PRIMARY_SCOPE):
        rows = [row['duration_context'][scope] for row in analyses]
        for row in rows:
            if any(sum(category[key] for category in row['by_category'].values()) != row[key]
                   for key in ('reference_notes', 'paired_notes', 'unpaired_notes',
                               'supported_pairs', 'unsupported_pairs')):
                raise ValueError('duration articulation partition failed')
        combined = _sum_duration_rows(rows)
        combined['by_category'] = {category: _sum_duration_rows([row['by_category'][category] for row in rows])
                                    for category in CATEGORIES}
        result['duration_context'][scope] = combined
    contexts = [row['rest_ranges'] for row in analyses]
    if any(row['instrument_wide_rest_intervals'] != row['projected_rest_intervals']
           + row['unprojectable_rest_intervals']
           or row['projected_rest_intervals'] != row['nonempty_core_source_intervals']
           + row['collapsed_core_intervals'] for row in contexts):
        raise ValueError('rest support population accounting failed')
    # Keep per-recording clock/length diagnostics in cases. Only additive union
    # measures are combined across these disjoint recordings.
    rest_keys = ('instrument_wide_rest_intervals', 'projected_rest_intervals',
                 'unprojectable_rest_intervals', 'collapsed_core_intervals')
    result['rest_ranges'] = {key: sum(row[key] for row in contexts) for key in rest_keys}
    result['rest_ranges']['projections'] = {
        name: {key: sum(row['projections'][name][key] for row in contexts)
               for key in ('duration_s', 'annotated_note_overlap_s', 'uncovered_by_note_annotations_s')}
        for name in ('envelope', 'core', 'boundary_uncertain')}
    result['fixed100_to_tempo20'] = {
        key: sum(row['correspondence']['fixed100_to_tempo20'][key] for row in analyses)
        for key in ('same_pair', 'different_pair', 'newly_resolved_reference', 'newly_unresolved_reference')}
    result['per_recording'] = [
        {'id': case['id'], 'reference_notes': case['analysis']['reference_count'],
         'local_support_status': case['analysis']['local_support']['status'],
         'supported_beat_cells': case['analysis']['local_support']['supported_beat_cells'],
         'scopes': {scope: case['analysis']['correspondence']['scopes'][scope]['matched_pairs']
                    for scope in SCOPES}}
        for case in cases]
    return result

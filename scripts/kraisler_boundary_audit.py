"""Original-waveform boundary descriptors with explicit annotation context.

All notes, including unavailable or confounded observations, retain their
denominator. A reference-conditioned harmonic descriptor is not pitch truth,
an estimated release, a silence detector, or a new model-matching result.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from dataclasses import dataclass

import numpy as np

from scripts.audio_gate_attribution import rms_envelope
from scripts.audio_gate_rest import gate_levels
from scripts.kraisler_correspondence import PLANNED_IDS, read_beats, read_notes
from scripts.kraisler_expressive import analyze_expressive
from scripts.kraisler_local_clock import build_local_clocks
from scripts.kraisler_rest_acoustics import rest_acoustic_context
from scripts.kraisler_rhythm_ranges import _overlap, _statistics, _union
from scripts.kraisler_waveform_features import extract_features, summarize_window

KINDS = ('onset', 'offset', 'midpoint')
CONTEXTS = ('same_pitch_neighbor', 'other_pitch_neighbor',
            'own_note_short_window', 'isolated_annotation_context')
WINDOWS = {'before': (-.100, -.020), 'after': (.020, .100)}
WATCHLIST = {'02': (14,), '19': (294,), '08': (), '12': (16,),
             '05': (), '06': (159,)}
AVAILABILITY = ('both', 'before_only', 'after_only', 'neither')
ENERGY_STATES = ('both_positive', 'before_zero_after_positive',
                 'before_positive_after_zero', 'both_zero', 'unavailable')
METRICS = ('target_change_db', 'total_change_db', 'target_fraction_change',
           'gate_quiet_fraction_change', 'before_target_dbfs', 'after_target_dbfs',
           'before_total_dbfs', 'after_total_dbfs',
           'before_target_fraction', 'after_target_fraction',
           'before_gate_quiet_fraction', 'after_gate_quiet_fraction')
CONTEXT_EPSILON = 1e-12


def _digest(value):
    raw = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()
    return hashlib.sha256(raw).hexdigest()


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


@dataclass(frozen=True)
class BoundaryResult:
    public: dict
    expressive_analysis: dict


def _quiet_window(edges, quiet, left, right):
    if left < edges[0] or right > edges[-1]:
        return {'available': False, 'reason': 'window_outside_audio',
                'duration_s': right - left, 'quiet_s': None,
                'active_s': None, 'quiet_fraction': None}
    intersections = np.maximum(0., np.minimum(edges[1:], right)
                                - np.maximum(edges[:-1], left))
    duration = right - left
    quiet_s = min(duration, max(0., math.fsum(intersections[quiet].tolist())))
    return {'available': True, 'reason': None, 'duration_s': duration,
            'quiet_s': quiet_s, 'active_s': duration - quiet_s,
            'quiet_fraction': quiet_s / duration}


def annotation_context(references, index, kind):
    """Describe annotated neighbours; do not equate isolation with acoustic truth."""
    _require(kind in KINDS and type(index) is int and 0 <= index < len(references),
             'valid boundary kind and reference index required')
    ref = references[index]
    time = ((ref.onset + ref.offset) / 2 if kind == 'midpoint' else getattr(ref, kind))
    windows = {side: (time + a, time + b) for side, (a, b) in WINDOWS.items()}
    hull = [(time - .1, time + .1)]
    same, other = [], []
    for j, note in enumerate(references):
        if j != index:
            (same if note.midi == ref.midi else other).append((note.onset, note.offset))
    same, other = _union(same), _union(other)
    same_neighbor = _overlap(hull, same) > CONTEXT_EPSILON
    other_neighbor = _overlap(hull, other) > CONTEXT_EPSILON
    expected_sides = ('after',) if kind == 'onset' else (
        ('before',) if kind == 'offset' else ('before', 'after'))
    own_supported = all(ref.onset <= windows[side][0] + CONTEXT_EPSILON
                        and windows[side][1] <= ref.offset + CONTEXT_EPSILON
                        for side in expected_sides)
    label = (CONTEXTS[0] if same_neighbor else CONTEXTS[1] if other_neighbor
             else CONTEXTS[2] if not own_supported else CONTEXTS[3])
    coverage = {}
    for side, interval in windows.items():
        own = [(ref.onset, ref.offset)]
        all_notes = _union(own + same + other)
        duration = interval[1] - interval[0]
        coverage[side] = {
            'duration_s': duration,
            'own_note_s': _overlap([interval], own),
            'other_same_pitch_s': _overlap([interval], same),
            'other_pitch_s': _overlap([interval], other),
            'other_notes_union_s': _overlap([interval], _union(same + other)),
            'uncovered_by_annotations_s': max(0., duration - _overlap([interval], all_notes)),
        }
    return time, windows, {
        'category': label, 'same_pitch_neighbor': same_neighbor,
        'other_pitch_neighbor': other_neighbor,
        'own_note_covers_expected_sides': own_supported,
        'window_annotation_coverage': coverage,
        'neighbour_scope': 'entire boundary +/-100ms hull, including excluded guard',
        'independent_acoustic_isolation_verified': False,
    }


def _difference(before, after):
    return None if before is None or after is None else after - before


def probe_boundary(bank, edges, quiet, references, index, kind):
    _, windows, context = annotation_context(references, index, kind)
    sides = {
        side: {'spectrum': summarize_window(bank, references[index].midi, *interval),
               'gate': _quiet_window(edges, quiet, *interval)}
        for side, interval in windows.items()
    }
    before, after = sides['before'], sides['after']
    a, b = before['spectrum']['available'], after['spectrum']['available']
    availability = 'both' if a and b else 'before_only' if a else 'after_only' if b else 'neither'
    metrics = {}
    for side in ('before', 'after'):
        spectrum = sides[side]['spectrum']
        for name, source_key in (('target_dbfs', 'target_band_dbfs'),
                                 ('total_dbfs', 'total_band_dbfs'),
                                 ('target_fraction', 'target_fraction')):
            metrics[f'{side}_{name}'] = spectrum[source_key] if spectrum['available'] else None
        metrics[f'{side}_gate_quiet_fraction'] = sides[side]['gate']['quiet_fraction']
    for target, source in (('target_change_db', 'target_dbfs'),
                           ('total_change_db', 'total_dbfs'),
                           ('target_fraction_change', 'target_fraction'),
                           ('gate_quiet_fraction_change', 'gate_quiet_fraction')):
        metrics[target] = _difference(metrics[f'before_{source}'], metrics[f'after_{source}'])
    return {'context': context, 'spectral_availability': availability,
            'before': before, 'after': after, 'metrics': metrics}


def _probe_summary(probes):
    availability = Counter(p['spectral_availability'] for p in probes)
    statistics = {}
    for metric in METRICS:
        values = [p['metrics'][metric] for p in probes if p['metrics'][metric] is not None]
        _require(all(math.isfinite(value) for value in values), 'nonfinite boundary descriptor')
        statistics[metric] = _statistics(values) | {'undefined': len(probes) - len(values)}
    energy_counts = {}
    for band, key in (('target', 'mean_target_band_power'), ('total', 'mean_total_band_power')):
        counts = Counter()
        for probe in probes:
            before, after = (probe[side]['spectrum'] for side in ('before', 'after'))
            if not before['available'] or not after['available']:
                state = 'unavailable'
            else:
                a, b = before[key], after[key]
                state = ('both_positive' if a > 0 and b > 0 else
                         'before_zero_after_positive' if a == 0 and b > 0 else
                         'before_positive_after_zero' if a > 0 and b == 0 else 'both_zero')
            counts[state] += 1
        energy_counts[band] = {key: counts[key] for key in ENERGY_STATES}
    return {'reference_count': len(probes),
            'spectral_availability': {key: availability[key] for key in AVAILABILITY},
            'energy_transition_counts': energy_counts,
            'statistics': statistics}


def summarize_probes(probes):
    result = _probe_summary(probes)
    result['by_context'] = {
        category: _probe_summary([p for p in probes if p['context']['category'] == category])
        for category in CONTEXTS
    }
    result['context_memberships'] = {
        category: ''.join('1' if p['context']['category'] == category else '0' for p in probes)
        for category in CONTEXTS
    }
    _require(sum(row['reference_count'] for row in result['by_context'].values()) == len(probes),
             'boundary context partition changed')
    result['all_probe_metadata_sha256'] = _digest(probes)
    return result


def _spectral_region(bank, intervals):
    """Pool full-frame powers, not segment dB means; never pad or clip a rest."""
    mask = np.zeros(len(bank.centers), dtype=bool)
    unavailable = 0
    for left, right in intervals:
        summary = summarize_window(bank, None, left, right)
        _require(summary['audio_interval_supported'], 'rest spectral interval outside original audio')
        if not summary['available']:
            unavailable += 1
        mask |= (bank.start_supports >= left) & (bank.end_supports <= right)
    values = bank.total_band_energy[mask]
    total = math.fsum(values.tolist())
    count = int(mask.sum())
    mean = total / count if count else None
    return {'interval_count': len(intervals), 'intervals_without_full_spectral_frame': unavailable,
            'full_frame_count': count, 'total_band_power_sum': total,
            'mean_total_band_power': mean,
            'total_band_dbfs': 10 * math.log10(mean) if mean is not None and mean > 0 else None,
            'zero_total_frames': int((values == 0).sum()),
            'full_frame_mask_sha256': hashlib.sha256(mask.astype(np.uint8).tobytes()).hexdigest()}, mask


def rest_spectral_context(bank, private_regions):
    public, masks = {}, {}
    for name, region in private_regions.items():
        public[name], masks[name] = _spectral_region(bank, region.whole)
        for part in ('annotated_note_overlap', 'uncovered_by_note_annotations'):
            public[name][part], _ = _spectral_region(bank, getattr(region, part))
    core, rim, envelope = (masks[key] for key in ('core', 'boundary_uncertain', 'envelope'))
    _require(not np.any(core & rim) and not np.any((core | rim) & ~envelope),
             'invalid rest spectral containment')
    return {'regions': public,
            'envelope_frames_crossing_core_uncertain_boundary': int((envelope & ~(core | rim)).sum()),
            'frame_support_must_fit_wholly_in_one_union_interval': True,
            'spectral_counts_do_not_partition_continuous_duration': True,
            'acoustic_silence_or_rest_accuracy_measured': False}


def analyze_boundaries(case_id, samples, sr, score, piano_score, match_audit,
                       raw_beats, raw_notes, *, raw_score):
    _require(case_id in PLANNED_IDS, 'unplanned recording')
    samples = np.asarray(samples, dtype=np.float64)
    _require(sr == 44100 and samples.ndim == 1 and 0 < len(samples) <= sr * 150
             and np.isfinite(samples).all() and np.all(np.abs(samples) <= 1),
             'original bounded mono PCM waveform required')
    duration = len(samples) / sr
    references = read_notes(raw_notes, duration)
    beats = read_beats(raw_beats, duration)
    # Frozen source-only diagnostic and exact waveform gate have no receipt input.
    expressive = analyze_expressive(score, piano_score, match_audit, raw_beats,
                                    raw_notes, duration, raw_score=raw_score)
    bclock, pclock, _ = build_local_clocks(score, piano_score, match_audit, beats)
    edges, levels = rms_envelope(samples[:, None], sr)
    quiet, gate = gate_levels(levels, 'relative')
    bank = extract_features(samples, sr)
    probes = {kind: [probe_boundary(bank, edges, quiet, references, i, kind)
                     for i in range(len(references))] for kind in KINDS}
    rests = rest_acoustic_context(score, references, bclock, pclock, edges, quiet)
    _require(rests.public['source_projection'] == expressive['rest_ranges'],
             'frozen rest range diagnostic changed')
    watchlist = {}
    for index in WATCHLIST[case_id]:
        _require(index < len(references), 'fixed watchlist reference unavailable')
        watchlist[str(index)] = {kind: probes[kind][index] for kind in KINDS}
    public = {
        'reference_count': len(references), 'duration_s': duration,
        'expressive_analysis_sha256': _digest(expressive),
        'gate': gate | {'frame_count': len(quiet), 'quiet_frame_count': int(quiet.sum()),
                        'mask_sha256': hashlib.sha256(quiet.astype(np.uint8).tobytes()).hexdigest()},
        'boundaries': {kind: summarize_probes(probes[kind]) for kind in KINDS},
        'rest_acoustics': rests.public,
        'rest_spectra': rest_spectral_context(bank, rests.regions),
        'watchlist': watchlist,
        'policy': {
            'boundary_windows_relative_s': {k: list(v) for k, v in WINDOWS.items()},
            'all_reference_onsets_offsets_midpoints_retained': True,
            'context_is_annotation_conditioned': True, 'pitch_is_annotation_conditioned': True,
            'no_endpoint_search_or_adjustment': True, 'predictions_available': False,
            'new_model_inferences': 0, 'new_f1_measured': False,
            'independent_acoustic_ground_truth': False, 'automatic_correction_enabled': False,
            'midpoints_are_within_note_controls_not_independent_samples': True,
            'watchlist_selected_from_prior_outcomes': True,
            'power_zero_retained_and_undefined_log_ratios_are_null': True,
        },
    }
    return BoundaryResult(public, expressive)


def _pool_statistics(rows):
    """Exact count/sum mean; per-recording quantiles cannot yield cohort quantiles."""
    count = sum(row['count'] for row in rows)
    total = math.fsum(row['sum'] for row in rows)
    nonempty = [row for row in rows if row['count']]
    return {'count': count, 'undefined': sum(row['undefined'] for row in rows),
            'sum': total, 'mean': total / count if count else None,
            'min': min(row['min'] for row in nonempty) if nonempty else None,
            'max': max(row['max'] for row in nonempty) if nonempty else None,
            'cohort_quantiles_computed': False}


def _pool_probe_summaries(rows):
    result = {
        'reference_count': sum(row['reference_count'] for row in rows),
        'spectral_availability': {key: sum(row['spectral_availability'][key] for row in rows)
                                  for key in AVAILABILITY},
        'energy_transition_counts': {
            band: {key: sum(row['energy_transition_counts'][band][key] for row in rows)
                   for key in ENERGY_STATES} for band in ('target', 'total')},
        'statistics': {key: _pool_statistics([row['statistics'][key] for row in rows])
                       for key in METRICS},
    }
    _require(sum(result['spectral_availability'].values()) == result['reference_count'],
             'spectral availability denominator changed')
    _require(all(sum(counts.values()) == result['reference_count']
                 for counts in result['energy_transition_counts'].values()),
             'zero-energy transition denominator changed')
    _require(all(value['count'] + value['undefined'] == result['reference_count']
                 for value in result['statistics'].values()), 'descriptor denominator changed')
    return result


def _pool_time(rows):
    result = {key: math.fsum(row[key] for row in rows)
              for key in ('duration_s', 'quiet_s', 'active_s')}
    result['quiet_fraction'] = (result['quiet_s'] / result['duration_s']
                                if result['duration_s'] else None)
    _require(math.isclose(result['quiet_s'] + result['active_s'], result['duration_s'],
                         rel_tol=1e-12, abs_tol=1e-12), 'pooled gate duration changed')
    return result


def _pool_spectra(rows):
    counts = ('interval_count', 'intervals_without_full_spectral_frame',
              'full_frame_count', 'zero_total_frames')
    result = {key: sum(row[key] for row in rows) for key in counts}
    total = math.fsum(row['total_band_power_sum'] for row in rows)
    mean = total / result['full_frame_count'] if result['full_frame_count'] else None
    return result | {'total_band_power_sum': total, 'mean_total_band_power': mean,
                     'total_band_dbfs': 10 * math.log10(mean) if mean and mean > 0 else None}


def summarize_boundaries(cases, planned_ids=PLANNED_IDS):
    _require(tuple(row['id'] for row in cases) == tuple(planned_ids)
             and len(set(planned_ids)) == len(planned_ids)
             and all(row['status'] == 'complete' for row in cases),
             'only all planned unique complete cases may be aggregated')
    analyses = [row['analysis'] for row in cases]
    _require(all(analysis['boundaries'][kind]['reference_count'] == analysis['reference_count']
                 for analysis in analyses for kind in KINDS),
             'each boundary kind must retain every reference')
    boundaries = {}
    for kind in KINDS:
        rows = [row['boundaries'][kind] for row in analyses]
        boundaries[kind] = _pool_probe_summaries(rows)
        boundaries[kind]['by_context'] = {
            name: _pool_probe_summaries([row['by_context'][name] for row in rows])
            for name in CONTEXTS
        }
        _require(sum(row['reference_count'] for row in boundaries[kind]['by_context'].values())
                 == boundaries[kind]['reference_count'], 'cohort context partition changed')
    rest_regions, spectral_regions = {}, {}
    for name in ('envelope', 'core', 'boundary_uncertain'):
        rest_rows = [row['rest_acoustics']['regions'][name] for row in analyses]
        rest_regions[name] = _pool_time(rest_rows)
        spectral_rows = [row['rest_spectra']['regions'][name] for row in analyses]
        spectral_regions[name] = _pool_spectra(spectral_rows)
        for part in ('annotated_note_overlap', 'uncovered_by_note_annotations'):
            rest_regions[name][part] = _pool_time([row[part] for row in rest_rows])
            spectral_regions[name][part] = _pool_spectra([row[part] for row in spectral_rows])
    for key in ('duration_s', 'quiet_s', 'active_s'):
        _require(math.isclose(rest_regions['core'][key] + rest_regions['boundary_uncertain'][key],
                             rest_regions['envelope'][key], rel_tol=1e-12, abs_tol=1e-12),
                 'cohort rest decomposition changed')
    return {
        'recordings': len(cases), 'reference_count': sum(row['reference_count'] for row in analyses),
        'duration_s': math.fsum(row['duration_s'] for row in analyses), 'boundaries': boundaries,
        'rest_counts': {key: sum(row['rest_acoustics']['source_projection'][key] for row in analyses)
                        for key in ('instrument_wide_rest_intervals', 'projected_rest_intervals',
                                    'unprojectable_rest_intervals', 'collapsed_core_intervals')},
        'rest_regions': rest_regions, 'rest_spectra': spectral_regions,
        'envelope_frames_crossing_core_uncertain_boundary': sum(
            row['rest_spectra']['envelope_frames_crossing_core_uncertain_boundary'] for row in analyses),
        'watchlist_reference_count': sum(len(row['watchlist']) for row in analyses),
        'cohort_quantiles_computed': False, 'new_model_f1_or_endpoint_accuracy_measured': False,
        'same_six_recordings_reused_development_diagnostic': True,
    }

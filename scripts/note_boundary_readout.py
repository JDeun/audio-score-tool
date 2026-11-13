"""One frozen research factor: persistent raw-pitch cuts inside fixed G parents.

This module never decodes a path, reads a reference, or changes voiced support.
The full input contour supplies the existing five-frame hysteresis labels; only
positive-to-positive label changes strictly inside a decoded parent are cuts.
Each child then receives the original raw-positive median/rounding/80 ms readout.
Detailed bounds and pitches belong to the returned private trace, not a public
corpus artifact. Public diagnostics contain counts, distributions and hashes.
"""
from __future__ import annotations

import hashlib
import math

import numpy as np

from scripts.dsp_note_probe import (
    CHANGE_FRAMES,
    DT,
    MIN_SECONDS,
    Note,
    fingerprint,
    labels_from_hz,
)
from scripts.note_state_hmm import (
    ATTACK,
    SILENT,
    STABLE,
    _duration,
    _frequencies,
    _state_path,
)

ARM = 'gaussian_raw_hysteresis_split'
BASE_ARM = 'gaussian_exponent_1'
SETTINGS = {
    'arm': ARM, 'base_arm': BASE_ARM,
    'change_support_frames': CHANGE_FRAMES,
    'candidate_cut': 'adjacent_nonnegative_unequal_global_raw_hysteresis_labels',
    'cut_scope': 'strictly_inside_original_decoded_voiced_pitch_parent_before_audio_end',
    'hysteresis_backdate': 'first_evidence_frame',
    'parent_source': 'same_gaussian_exponent_1_path',
    'event_pitch': 'rint(median(raw_positive_fractional_midi_in_child))',
    'minimum_note_seconds': MIN_SECONDS,
    'raw_unvoiced_posthoc_split': False,
    'time_shift_seconds': 0.,
    'reference_informed_cuts': False,
}


def _summary(values):
    values = [float(value) for value in values]
    if not values:
        return {'count': 0, 'min': None, 'q25': None, 'median': None,
                'q75': None, 'max': None, 'mean': None}
    q25, median, q75 = np.quantile(values, [.25, .5, .75], method='linear')
    return {'count': len(values), 'min': min(values), 'q25': float(q25),
            'median': float(median), 'q75': float(q75), 'max': max(values),
            'mean': math.fsum(values) / len(values)}


def _diagnostics(phases, raw_voiced):
    decoded_voiced = phases != SILENT
    return {
        'frames': len(phases), 'raw_voiced_frames': int(raw_voiced.sum()),
        'decoded_voiced_frames': int(decoded_voiced.sum()),
        'attack_frames': int((phases == ATTACK).sum()),
        'stable_frames': int((phases == STABLE).sum()),
        'silent_frames': int((phases == SILENT).sum()),
        'decoded_voiced_over_raw_unvoiced_frames': int((decoded_voiced & ~raw_voiced).sum()),
        'raw_voiced_decoded_silent_frames': int((raw_voiced & ~decoded_voiced).sum()),
        'segments_before_filter': 0, 'emitted_notes': 0,
        'segments_without_raw_voiced_support': 0,
        'zero_duration_segments': 0, 'short_segments_discarded': 0,
        'short_segments_discarded_seconds': 0., 'attack_only_segments': 0,
        'segments_touching_audio_start': 0, 'segments_touching_audio_end': 0,
        'emitted_notes_with_raw_unvoiced_frames': 0,
        'emitted_raw_unvoiced_frames': 0, 'emitted_note_seconds': 0.,
    }


def _segment(begin, stop, raw_voiced, midi, duration, prediction_index):
    onset, offset = begin * DT, min(stop * DT, duration)
    support = raw_voiced[begin:stop]
    median = float(np.median(midi[begin:stop][support])) if support.any() else None
    pitch = int(np.rint(median)) if median is not None else None
    if offset <= onset:
        reason = 'zero_duration'
    elif not support.any():
        reason = 'no_raw_support'
    elif offset - onset < MIN_SECONDS - 1e-10:
        reason = 'short'
    else:
        reason = None
    return {
        'begin_frame': begin, 'stop_frame': stop,
        'onset_seconds': onset, 'offset_seconds': offset,
        'frame_count': stop - begin, 'raw_voiced_frames': int(support.sum()),
        'raw_unvoiced_frames': int((~support).sum()),
        'raw_positive_midi_median': median, 'pitch': pitch,
        'clipped': bool(stop * DT > duration),
        'emitted': reason is None,
        'prediction_index': prediction_index if reason is None else None,
        'discard_reason': reason,
    }


def _record(diagnostics, segment, phases, duration):
    begin, stop = segment['begin_frame'], segment['stop_frame']
    diagnostics['segments_before_filter'] += 1
    diagnostics['attack_only_segments'] += int(np.all(phases[begin:stop] == ATTACK))
    diagnostics['segments_touching_audio_start'] += int(begin == 0)
    diagnostics['segments_touching_audio_end'] += int(stop * DT >= duration - 1e-10)
    reason = segment['discard_reason']
    if reason == 'zero_duration':
        diagnostics['zero_duration_segments'] += 1
    elif reason == 'no_raw_support':
        diagnostics['segments_without_raw_voiced_support'] += 1
    elif reason == 'short':
        diagnostics['short_segments_discarded'] += 1
        diagnostics['short_segments_discarded_seconds'] += (
            segment['offset_seconds'] - segment['onset_seconds'])
    else:
        diagnostics['emitted_notes'] += 1
        raw_unvoiced_count = segment['raw_unvoiced_frames']
        diagnostics['emitted_notes_with_raw_unvoiced_frames'] += int(raw_unvoiced_count > 0)
        diagnostics['emitted_raw_unvoiced_frames'] += raw_unvoiced_count
        diagnostics['emitted_note_seconds'] += (
            segment['offset_seconds'] - segment['onset_seconds'])


def notes_from_state_path(path, hz, duration):
    """Return ``(notes, public_diagnostics, private_trace)`` from one fixed G path.

    Validation and event construction retain the original G readout contract.
    Original parents include every prefilter voiced pitch segment. Their emitted
    prediction indices refer to the original G order; child indices refer to the
    new arm. Discarded segments retain their trace and have a null index.
    """
    values, midi = _frequencies(hz)
    states = _state_path(path, len(values))
    _duration(duration, len(values))
    phases, raw_voiced = states % 3, values > 0
    labels = labels_from_hz(values, support=CHANGE_FRAMES)
    candidate_array = np.flatnonzero(
        (labels[:-1] >= 0) & (labels[1:] >= 0) & (labels[:-1] != labels[1:])) + 1
    candidates = candidate_array.tolist()
    parent_labels = np.where(phases != SILENT, states // 3, -1)
    baseline, readout = _diagnostics(phases, raw_voiced), _diagnostics(phases, raw_voiced)
    notes, parents, all_children, applied = [], [], [], []
    begin = 0
    for stop in range(1, len(parent_labels) + 1):
        if stop < len(parent_labels) and parent_labels[stop] == parent_labels[begin]:
            continue
        if parent_labels[begin] >= 0:
            original = _segment(begin, stop, raw_voiced, midi, duration,
                                baseline['emitted_notes'])
            _record(baseline, original, phases, duration)
            lo = int(np.searchsorted(candidate_array, begin, side='right'))
            hi = int(np.searchsorted(candidate_array, stop, side='left'))
            cuts = [int(k) for k in candidate_array[lo:hi]
                    if k * DT < min(stop * DT, duration)]
            applied.extend(cuts)
            children = []
            bounds = [begin, *cuts, stop]
            for child_begin, child_stop in zip(bounds[:-1], bounds[1:]):
                child = _segment(child_begin, child_stop, raw_voiced, midi, duration,
                                 readout['emitted_notes'])
                child['child_id'] = len(all_children)
                _record(readout, child, phases, duration)
                if child['emitted']:
                    notes.append(Note(child['pitch'], child['onset_seconds'],
                                      child['offset_seconds']))
                children.append(child)
                all_children.append(child)
            parents.append({
                'parent_id': len(parents), 'begin_frame': begin, 'stop_frame': stop,
                'state_pitch_index': int(parent_labels[begin]),
                'applied_cut_frames': cuts, 'original': original, 'children': children,
            })
        begin = stop
    trace = {'schema_version': 1, 'candidate_cut_frames': candidates, 'parents': parents}
    baseline_seconds, emitted_seconds = (baseline['emitted_note_seconds'],
                                         readout['emitted_note_seconds'])
    emitted_parents = [parent for parent in parents if parent['original']['emitted']]
    diagnostics = {
        'schema_version': 1,
        'candidate_cut_count': len(candidates), 'applied_cut_count': len(applied),
        'affected_parent_count': sum(bool(parent['applied_cut_frames']) for parent in parents),
        'parent_segment_count': len(parents), 'child_segment_count': len(all_children),
        'originally_emitted_parents_all_children_pruned': sum(
            not any(child['emitted'] for child in parent['children'])
            for parent in emitted_parents),
        'originally_emitted_parents_with_short_children': sum(
            any(child['discard_reason'] == 'short' for child in parent['children'])
            for parent in emitted_parents),
        'originally_emitted_parents_with_any_pruned_children': sum(
            any(not child['emitted'] for child in parent['children'])
            for parent in emitted_parents),
        'baseline_emitted_seconds': baseline_seconds, 'emitted_seconds': emitted_seconds,
        'emitted_seconds_change': emitted_seconds - baseline_seconds,
        'baseline_emitted_coverage_fraction': baseline_seconds / duration if duration else 0.,
        'emitted_coverage_fraction': emitted_seconds / duration if duration else 0.,
        'clipped_child_count': sum(child['clipped'] for child in all_children),
        'baseline': baseline, 'readout': readout,
        'child_midi_median_summary': _summary(
            child['raw_positive_midi_median'] for child in all_children
            if child['raw_positive_midi_median'] is not None),
        'child_raw_voiced_frames_summary': _summary(
            child['raw_voiced_frames'] for child in all_children),
        'child_seconds_summary': _summary(
            max(0., child['offset_seconds'] - child['onset_seconds'])
            for child in all_children),
        'candidate_cut_frames_sha256': fingerprint(candidates),
        'applied_cut_frames_sha256': fingerprint(applied),
        'raw_hysteresis_label_identity': {
            'dtype': str(labels.dtype), 'shape': list(labels.shape),
            'sha256': hashlib.sha256(labels.tobytes()).hexdigest()},
        'trace_sha256': fingerprint(trace),
    }
    return notes, diagnostics, trace

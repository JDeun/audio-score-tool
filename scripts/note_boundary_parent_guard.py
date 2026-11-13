"""Research-only all-or-nothing approval of the frozen raw-pitch split.

Only originally emitted G parents may propose children. Every proposed child
must pass the unchanged readout; otherwise the original G Note object survives.
No path is decoded here, and private segment details never enter public counts.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import asdict

import numpy as np

from scripts.dsp_note_probe import CHANGE_FRAMES, DT, MIN_SECONDS, Note, fingerprint, labels_from_hz
from scripts.note_boundary_readout import _diagnostics, _record, _segment, _summary
from scripts.note_state_hmm import SILENT, _duration, _frequencies, _state_path

ARM = 'gaussian_raw_hysteresis_parent_guard'
BASE_ARM = 'gaussian_exponent_1'
SPLIT_ARM = 'gaussian_raw_hysteresis_split'
SETTINGS = {
    'arm': ARM, 'base_arm': BASE_ARM, 'secondary_baseline': SPLIT_ARM,
    'change_support_frames': CHANGE_FRAMES,
    'candidate_cut': 'adjacent_nonnegative_unequal_global_raw_hysteresis_labels',
    'cut_scope': 'strictly_inside_original_emitted_G_parent_before_clipped_audio_end',
    'hysteresis_backdate': 'first_evidence_frame',
    'parent_source': 'same_gaussian_exponent_1_path',
    'event_pitch': 'rint(median(raw_positive_fractional_midi_in_child))',
    'minimum_note_seconds': MIN_SECONDS,
    'approval': 'all_proposed_children_pass_original_readout_or_restore_original_Note',
    'nonemitted_parent_resurrection': False,
    'partial_cut_selection': False,
    'raw_unvoiced_posthoc_split': False,
    'time_shift_seconds': 0.,
    'reference_informed_cuts': False,
}


def interval_union(notes):
    """Canonical exact interval union; touching endpoints are not rounded."""
    result = []
    for onset, offset in sorted((note.onset, note.offset) for note in notes):
        if result and onset <= result[-1][1]:
            result[-1][1] = max(result[-1][1], offset)
        else:
            result.append([onset, offset])
    return result


def _event(segment):
    return Note(segment['pitch'], segment['onset_seconds'], segment['offset_seconds'])


def notes_from_state_path(path, hz, duration, *, original_notes=None):
    """Return ``(notes, public_diagnostics, private_trace)`` on the shared G path.

    ``original_notes`` may be the existing G arm, whose Note instances are then
    returned unchanged for no-cut and rejected parents. Their exact serialized
    values are checked against the unchanged readout. Without this argument the
    original Notes are constructed once using that same readout.
    """
    values, midi = _frequencies(hz)
    states = _state_path(path, len(values))
    _duration(duration, len(values))
    supplied = None if original_notes is None else list(original_notes)
    phases, raw_voiced = states % 3, values > 0
    raw_labels = labels_from_hz(values, support=CHANGE_FRAMES)
    candidate_array = np.flatnonzero(
        (raw_labels[:-1] >= 0) & (raw_labels[1:] >= 0)
        & (raw_labels[:-1] != raw_labels[1:])) + 1
    candidates = candidate_array.tolist()
    labels = np.where(phases != SILENT, states // 3, -1)
    baseline, readout, proposed = (_diagnostics(phases, raw_voiced) for _ in range(3))
    original_events, notes, parents, all_proposals = [], [], [], []
    proposed_cuts, accepted_cuts = [], []
    begin = 0
    for stop in range(1, len(labels) + 1):
        if stop < len(labels) and labels[stop] == labels[begin]:
            continue
        if labels[begin] >= 0:
            original = _segment(begin, stop, raw_voiced, midi, duration,
                                baseline['emitted_notes'])
            _record(baseline, original, phases, duration)
            original_event = None
            if original['emitted']:
                expected = _event(original)
                index = original['prediction_index']
                if supplied is not None:
                    if (index >= len(supplied) or not isinstance(supplied[index], Note)
                            or fingerprint(asdict(supplied[index])) != fingerprint(asdict(expected))):
                        raise ValueError('original G Note differs from frozen parent readout')
                    original_event = supplied[index]
                else:
                    original_event = expected
                original_events.append(original_event)
            cuts = []
            if original['emitted']:
                lo = int(np.searchsorted(candidate_array, begin, side='right'))
                hi = int(np.searchsorted(candidate_array, stop, side='left'))
                cuts = [int(frame) for frame in candidate_array[lo:hi]
                        if frame * DT < min(stop * DT, duration)]
            children = []
            if cuts:
                proposed_cuts.extend(cuts)
                bounds = [begin, *cuts, stop]
                for child_begin, child_stop in zip(bounds[:-1], bounds[1:], strict=True):
                    child = _segment(child_begin, child_stop, raw_voiced, midi, duration, None)
                    child.update(child_id=len(all_proposals), passes_readout=child['emitted'],
                                 emitted=False)
                    _record(proposed, child, phases, duration)
                    children.append(child)
                    all_proposals.append(child)
            reasons = sorted({child['discard_reason'] for child in children
                              if child['discard_reason'] is not None})
            if not original['emitted']:
                decision = 'nonemitted'
            elif not cuts:
                decision = 'no_cut'
            elif reasons:
                decision = 'rejected'
            else:
                decision = 'accepted'
            final_segments = []
            if decision == 'accepted':
                accepted_cuts.extend(cuts)
                for child in children:
                    child.update(emitted=True, prediction_index=len(notes))
                    final_segments.append({key: value for key, value in child.items()
                                           if key != 'passes_readout'})
                    notes.append(_event(child))
            else:
                final = {**original, 'prediction_index': len(notes) if original['emitted'] else None}
                final_segments.append(final)
                if original_event is not None:
                    notes.append(original_event)
            for final in final_segments:
                _record(readout, final, phases, duration)
            parents.append({
                'parent_id': len(parents), 'begin_frame': begin, 'stop_frame': stop,
                'state_pitch_index': int(labels[begin]), 'original': original,
                'proposed_cut_frames': cuts,
                'accepted_cut_frames': cuts if decision == 'accepted' else [],
                'decision': decision, 'rejection_reasons': reasons,
                'proposed_children': children, 'final_segments': final_segments,
            })
        begin = stop
    if supplied is not None and len(supplied) != len(original_events):
        raise ValueError('original G Note count differs from frozen parent readout')
    original_union, final_union = interval_union(original_events), interval_union(notes)
    if fingerprint(original_union) != fingerprint(final_union):
        raise ValueError('guard changed the original emitted interval union')
    trace = {'schema_version': 1, 'candidate_cut_frames': candidates, 'parents': parents}
    rejected = [parent for parent in parents if parent['decision'] == 'rejected']
    accepted = [parent for parent in parents if parent['decision'] == 'accepted']
    final_segments = [segment for parent in parents for segment in parent['final_segments']]
    baseline_seconds, emitted_seconds = baseline['emitted_note_seconds'], readout['emitted_note_seconds']
    diagnostics = {
        'schema_version': 1,
        'candidate_cut_count': len(candidates), 'parent_segment_count': len(parents),
        'originally_emitted_parent_count': len(original_events),
        'originally_nonemitted_parent_count': len(parents) - len(original_events),
        'proposed_parent_count': sum(bool(parent['proposed_cut_frames']) for parent in parents),
        'proposed_cut_count': len(proposed_cuts), 'proposed_child_count': len(all_proposals),
        'accepted_parent_count': len(accepted), 'accepted_cut_count': len(accepted_cuts),
        'accepted_child_count': sum(len(parent['final_segments']) for parent in accepted),
        'rejected_parent_count': len(rejected), 'restored_original_event_count': len(rejected),
        'unchanged_original_event_count': sum(parent['decision'] == 'no_cut' for parent in parents),
        'rejected_parent_reason_counts': {
            reason: sum(reason in parent['rejection_reasons'] for parent in rejected)
            for reason in ('short', 'no_raw_support', 'zero_duration')},
        'final_segment_count': len(final_segments),
        'originally_emitted_parents_all_children_pruned': 0,
        'nonemitted_parents_resurrected': 0,
        'baseline': baseline, 'readout': readout, 'proposed': proposed,
        'baseline_emitted_seconds': baseline_seconds, 'emitted_seconds': emitted_seconds,
        'emitted_seconds_change': emitted_seconds - baseline_seconds,
        'baseline_emitted_coverage_fraction': baseline_seconds / duration if duration else 0.,
        'emitted_coverage_fraction': emitted_seconds / duration if duration else 0.,
        'baseline_interval_union_count': len(original_union),
        'output_interval_union_count': len(final_union),
        'baseline_interval_union_seconds': math.fsum(stop - start for start, stop in original_union),
        'output_interval_union_seconds': math.fsum(stop - start for start, stop in final_union),
        'baseline_interval_union_sha256': fingerprint(original_union),
        'output_interval_union_sha256': fingerprint(final_union),
        'output_interval_union_preserved': True,
        'proposed_child_seconds_summary': _summary(
            max(0., child['offset_seconds'] - child['onset_seconds']) for child in all_proposals),
        'proposed_child_midi_median_summary': _summary(
            child['raw_positive_midi_median'] for child in all_proposals
            if child['raw_positive_midi_median'] is not None),
        'proposed_child_raw_voiced_frames_summary': _summary(
            child['raw_voiced_frames'] for child in all_proposals),
        'final_emitted_seconds_summary': _summary(note.offset - note.onset for note in notes),
        'candidate_cut_frames_sha256': fingerprint(candidates),
        'proposed_cut_frames_sha256': fingerprint(proposed_cuts),
        'accepted_cut_frames_sha256': fingerprint(accepted_cuts),
        'raw_hysteresis_label_identity': {
            'dtype': str(raw_labels.dtype), 'shape': list(raw_labels.shape),
            'sha256': hashlib.sha256(raw_labels.tobytes()).hexdigest()},
        'trace_sha256': fingerprint(trace),
    }
    return notes, diagnostics, trace

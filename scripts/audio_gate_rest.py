"""Waveform-gate hypotheses for research, never a production rest detector.

The selector has no score, reference pitch, beat grid, or annotation inputs.
Silence evidence and absence of an annotated performed note are NOT a written rest.
"""
from __future__ import annotations

import math
from dataclasses import replace

import numpy as np

from scripts.vocal_recovery import Event, event_digest, events_from

SETTINGS = {
    'frame_seconds': .020, 'hop_seconds': .010, 'hold_seconds': .060,
    'hysteresis_db': 6., 'absolute_close_dbfs': -45.,
    'relative_reference_percentile': 95., 'relative_below_reference_db': 30.,
    'minimum_fragment_seconds': .060,
    'soft_quiet_cost_per_second': 3., 'soft_removed_cost_per_second': 1.,
    'soft_changed_event_cost': .120, 'soft_count_change_cost': .080,
    'soft_onset_move_cost_per_second': .5,
}
MODES = ('absolute', 'relative')
ARMS = ('raw', 'absolute_hard', 'absolute_soft', 'relative_hard', 'relative_soft')


def rms_envelope(samples, sr):
    """Centered 20ms RMS; 10ms cells. Stereo power averaging avoids cancellation."""
    samples = np.asarray(samples, dtype=np.float64)
    if (samples.ndim not in (1, 2) or len(samples) == 0 or
            not np.isfinite(samples).all() or not isinstance(sr, int) or sr < 8000):
        raise ValueError('invalid waveform')
    if samples.ndim == 2 and not 1 <= samples.shape[1] <= 8:
        raise ValueError('invalid channel count')
    power = samples ** 2
    if samples.ndim == 2:
        power = power.mean(axis=1)
    length = len(samples) / sr
    count = int(math.ceil(length / SETTINGS['hop_seconds']))
    edges = np.minimum(np.arange(count + 1) * SETTINGS['hop_seconds'], length)
    centers = (edges[:-1] + edges[1:]) / 2
    half = SETTINGS['frame_seconds'] * sr / 2
    lo = np.maximum(0, np.floor(centers * sr - half).astype(int))
    hi = np.minimum(len(power), np.ceil(centers * sr + half).astype(int))
    cumulative = np.concatenate(([0.], np.cumsum(power)))
    energy = np.maximum(0., (cumulative[hi] - cumulative[lo]) / (hi - lo))
    levels = 10 * np.log10(np.maximum(energy, 1e-24))
    return edges, levels


def gate_levels(levels, mode):
    """Offline gate: closing is backdated after 60ms continuous low level."""
    levels = np.asarray(levels, dtype=float)
    if (mode not in MODES or levels.ndim != 1 or not len(levels)
            or not np.isfinite(levels).all()):
        raise ValueError('invalid gate levels')
    reference = float(np.percentile(levels, SETTINGS['relative_reference_percentile']))
    close = (SETTINGS['absolute_close_dbfs'] if mode == 'absolute' else
             reference - SETTINGS['relative_below_reference_db'])
    opening = close + SETTINGS['hysteresis_db']
    hold = int(round(SETTINGS['hold_seconds'] / SETTINGS['hop_seconds']))
    quiet = np.ones(len(levels), dtype=bool)
    opened, low_start = False, None
    # Exactly silent input has no usable relative-level reference.
    if float(levels.max()) <= -239:
        return quiet, {'close_db': close, 'open_db': opening, 'reference_db': reference}
    for i, value in enumerate(levels):
        if not opened:
            if value >= opening:
                opened, low_start = True, None
                quiet[i] = False
        else:
            quiet[i] = False
            if value < close:
                if low_start is None:
                    low_start = i
                if i - low_start + 1 >= hold:
                    quiet[low_start:i + 1] = True
                    opened, low_start = False, None
            else:
                low_start = None
    return quiet, {'close_db': close, 'open_db': opening, 'reference_db': reference}


def mask_intervals(edges, mask):
    edges, mask = np.asarray(edges), np.asarray(mask, dtype=bool)
    if (edges.ndim != 1 or len(edges) != len(mask) + 1
            or not np.isfinite(edges).all() or np.any(np.diff(edges) <= 0)):
        raise ValueError('invalid frame timeline')
    transitions = np.diff(np.concatenate(([False], mask, [False])).astype(int))
    return [(float(edges[a]), float(edges[b])) for a, b in
            zip(np.flatnonzero(transitions == 1), np.flatnonzero(transitions == -1))]


def proposal(note: Event, active):
    return [replace(note, onset=max(note.onset, a), offset=min(note.offset, b))
            for a, b in active
            if min(note.offset, b) - max(note.onset, a)
            >= SETTINGS['minimum_fragment_seconds'] - 1e-9]


def apply_gate(notes, edges, quiet, policy):
    """Hard intersection vs raw/cut candidate selection with a frozen edit cost.

    Not the nASAP joint bar decoder: no true beat or notated-rest reference exists
    in the vocal corpus. Onsets/count may change and must be evaluated, not hidden.
    """
    if policy not in ('hard', 'soft'):
        raise ValueError('unsupported policy')
    notes = events_from(notes)
    before = event_digest(notes)
    active = mask_intervals(edges, ~np.asarray(quiet, dtype=bool))
    quiet_intervals = mask_intervals(edges, quiet)
    out = []
    diagnostics = dict(changed_parents=0, deleted=0, split_parents=0,
                       extra_fragments=0, out_of_audio_unchanged=0, removed_seconds=0.)
    for note in notes:
        if note.is_drum or note.onset < edges[0] or note.offset > edges[-1] + 1e-8:
            out.append(note)
            diagnostics['out_of_audio_unchanged'] += 1
            continue
        quiet_seconds = sum(max(0., min(note.offset, b) - max(note.onset, a))
                            for a, b in quiet_intervals)
        if quiet_seconds < 1e-9:
            out.append(note)
            continue
        cut = proposal(note, active)
        removed = (note.offset - note.onset) - sum(n.offset - n.onset for n in cut)
        cost_cut = (SETTINGS['soft_removed_cost_per_second'] * removed
                    + SETTINGS['soft_changed_event_cost']
                    + SETTINGS['soft_count_change_cost'] * abs(len(cut) - 1)
                    + SETTINGS['soft_onset_move_cost_per_second']
                    * (cut[0].onset - note.onset if cut else 0.))
        cost_keep = SETTINGS['soft_quiet_cost_per_second'] * quiet_seconds
        selected = cut if policy == 'hard' or cost_cut < cost_keep - 1e-9 else [note]
        out.extend(selected)
        if selected != [note]:
            diagnostics['changed_parents'] += 1
            diagnostics['deleted'] += not selected
            diagnostics['split_parents'] += len(selected) > 1
            diagnostics['extra_fragments'] += max(0, len(selected) - 1)
            diagnostics['removed_seconds'] += removed
    if before != event_digest(notes):
        raise ValueError('source mutation')
    diagnostics['output_count'] = len(out)
    return out, diagnostics


def occupied(intervals, centers):
    value = np.zeros(len(centers), dtype=bool)
    for start, end in intervals:
        value |= (centers >= start) & (centers < end)
    return value


def occupancy_score(predicted, reference, edges):
    """Evaluation only. Crop easy leading/trailing silence using reference here."""
    centers = (edges[:-1] + edges[1:]) / 2
    widths = np.diff(edges)
    inside = (centers >= reference[:, 0].min()) & (centers < reference[:, 1].max())
    true_note = occupied(reference, centers)
    predicted_note = occupied(predicted, centers)
    def duration(mask):
        return float(widths[inside & mask].sum())
    tp = duration(~true_note & ~predicted_note)
    fp = duration(true_note & ~predicted_note)
    fn = duration(~true_note & predicted_note)
    true_quiet = tp + fn
    predicted_quiet = tp + fp
    return {'reference_note_s': duration(true_note), 'reference_gap_s': true_quiet,
            'correct_gap_s': tp, 'lost_note_s': fp, 'filled_reference_gap_s': fn,
            'gap_precision': tp / predicted_quiet if predicted_quiet else None,
            'gap_recall': tp / true_quiet if true_quiet else None,
            'gap_f1': 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None}


def scored_notes(notes, reference_raw, edges):
    """Original-Hz reference, unchanged 50ms/50c and 20%/50ms offset scorer."""
    import mir_eval.transcription as mt

    from scripts.vocadito_reference import read_notes, score_annotations

    reference, hz = read_notes(reference_raw)
    prediction = np.array([(n.onset, n.offset) for n in notes], dtype=float).reshape(-1, 2)
    pitches = np.array([440 * 2 ** ((n.pitch - 69) / 12) for n in notes])
    result = score_annotations(notes, reference_raw)
    for metric, ratio in (('onset', None), ('onset_offset', .2)):
        pairs = (mt.match_notes(reference, hz, prediction, pitches,
                               onset_tolerance=.05, pitch_tolerance=50,
                               offset_ratio=ratio, offset_min_tolerance=.05)
                 if len(prediction) else [])
        matched = {int(i) for i, _ in pairs}
        result[metric + '_reference_mask'] = ''.join('1' if i in matched else '0'
                                                    for i in range(len(reference)))
    result['occupancy'] = occupancy_score(prediction, reference, edges)
    return result


def gains_and_damage(before, after):
    if len(before) != len(after) or set(before + after) - {'0', '1'}:
        raise ValueError('incomparable reference mask')
    return {'gained': sum(a == '0' and b == '1' for a, b in zip(before, after)),
            'damaged': sum(a == '1' and b == '0' for a, b in zip(before, after))}

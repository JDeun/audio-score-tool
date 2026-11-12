"""Development ablation of frozen relative-soft gate edits by operation.

The gate thresholds and soft selector remain in the archived audio_gate_rest
module. These arms only retain or withhold already selected edits; no reference
annotation, new candidate search, or parameter fitting enters the partition.
"""
from __future__ import annotations

from dataclasses import replace
from fractions import Fraction

import numpy as np

from scripts.audio_gate_rest import SETTINGS, apply_gate, mask_intervals
from scripts.vocal_recovery import Event, event_digest, events_from

ARMS = ('raw', 'relative_soft', 'tail_only', 'non_tail_only')
OPERATIONS = ('unchanged', 'tail_trim', 'onset_trim', 'delete', 'split')


def rms_envelope(samples, sr: int) -> tuple[np.ndarray, np.ndarray]:
    """Legacy RMS arithmetic with an exact sample-domain count of 10ms cells.

    Floating-point ceil(duration / hop) can add a zero-width final cell at
    exactly 70ms, for example. Rational counting fixes that boundary while
    retaining the historical edges, window arithmetic, and energy calculations
    for every input whose old cell count was already correct.
    """
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
    hop = Fraction(str(SETTINGS['hop_seconds']))
    denominator = sr * hop.numerator
    count = (len(samples) * hop.denominator + denominator - 1) // denominator
    edges = np.minimum(np.arange(count + 1) * SETTINGS['hop_seconds'], length)
    centers = (edges[:-1] + edges[1:]) / 2
    half = SETTINGS['frame_seconds'] * sr / 2
    lo = np.maximum(0, np.floor(centers * sr - half).astype(int))
    hi = np.minimum(len(power), np.ceil(centers * sr + half).astype(int))
    cumulative = np.concatenate(([0.], np.cumsum(power)))
    energy = np.maximum(0., (cumulative[hi] - cumulative[lo]) / (hi - lo))
    levels = 10 * np.log10(np.maximum(energy, 1e-24))
    return edges, levels


def classify_edit(parent: Event, children: list[Event]) -> str:
    """Classify one selected intersection, giving onset movement precedence.

    A single fragment with both boundaries moved is an onset_trim, never a
    tail-only edit. Identity includes pitch, channel, program, and drum status.
    """
    if children == [parent]:
        return 'unchanged'
    if not children:
        return 'delete'
    if any(replace(child, onset=parent.onset, offset=parent.offset) != parent
           or child.onset < parent.onset or child.offset > parent.offset
           or child.offset <= child.onset for child in children):
        raise ValueError('selected gate edit changed identity or extended its parent')
    if len(children) > 1:
        if any(a.offset > b.onset for a, b in zip(children, children[1:])):
            raise ValueError('selected gate fragments overlap or are out of order')
        return 'split'
    child = children[0]
    if child.onset == parent.onset and child.offset < parent.offset:
        return 'tail_trim'
    if child.onset > parent.onset:
        return 'onset_trim'
    raise ValueError('unrecognized selected gate edit')


def make_attribution_arms(notes, edges, quiet) -> dict[str, tuple[list[Event], dict]]:
    """Partition each frozen relative-soft edit without running a new selector.

    The caller supplies the relative gate's closed-cell mask. tail_only keeps
    strictly offset-shortening edits with an unchanged onset and event identity.
    non_tail_only keeps the complementary selected deletions, splits, and onset
    trims. All arm outputs preserve parent order; split children remain adjacent.

    Diagnostics include the archived gate counters, operation_counts over all
    parents, and zero-based selected_parent_indices. These indices identify
    disjoint interventions, not inferred musical note identities or new labels.
    """
    notes = events_from(notes)
    before = event_digest(notes)
    edges = np.asarray(edges, dtype=float)
    quiet = np.asarray(quiet)
    if quiet.ndim != 1 or quiet.dtype.kind != 'b':
        raise ValueError('invalid gate mask')
    if edges.ndim != 1 or len(edges) < 2 or len(quiet) != len(edges) - 1:
        raise ValueError('invalid frame timeline')
    # Validate the clock even for empty note input, as the archived gate does.
    mask_intervals(edges, quiet)
    mask_intervals(edges, ~quiet)

    selected = []
    operations = []
    excluded = []
    for parent in notes:
        children, diagnostics = apply_gate([parent], edges, quiet, 'soft')
        selected.append(children)
        operations.append(classify_edit(parent, children))
        excluded.append(diagnostics['out_of_audio_unchanged'])

    result = {}
    for arm in ARMS:
        output = []
        diagnostic = dict(changed_parents=0, deleted=0, split_parents=0,
                          extra_fragments=0, out_of_audio_unchanged=sum(excluded),
                          removed_seconds=0., output_count=0,
                          operation_counts=dict.fromkeys(OPERATIONS, 0),
                          selected_parent_indices=[])
        for i, (parent, children, operation) in enumerate(zip(notes, selected, operations)):
            keep_edit = (operation != 'unchanged' and
                         (arm == 'relative_soft'
                          or arm == 'tail_only' and operation == 'tail_trim'
                          or arm == 'non_tail_only' and operation != 'tail_trim'))
            chosen = children if keep_edit else [parent]
            applied_operation = operation if keep_edit else 'unchanged'
            diagnostic['operation_counts'][applied_operation] += 1
            output.extend(chosen)
            if keep_edit:
                diagnostic['selected_parent_indices'].append(i)
                diagnostic['changed_parents'] += 1
                diagnostic['deleted'] += int(not chosen)
                diagnostic['split_parents'] += int(len(chosen) > 1)
                diagnostic['extra_fragments'] += max(0, len(chosen) - 1)
                diagnostic['removed_seconds'] += (parent.offset - parent.onset
                                                  - sum(n.offset - n.onset for n in chosen))
        diagnostic['output_count'] = len(output)
        result[arm] = output, diagnostic
    if event_digest(notes) != before:
        raise ValueError('source mutation')
    return result

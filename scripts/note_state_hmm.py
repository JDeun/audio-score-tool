"""Frozen research-only note-state model over the existing pYIN F0 contour.

This independent implementation is inspired by Mauch et al., *Computer-aided
Melody Note Transcription Using the Tony Software: Accuracy and Efficiency*
(TENOR 2015), sections 3.1-3.3 and 4.1. It is not Tony, a vendor algorithm, or a
reproduction of their unpublished transition kernel. See SETTINGS for the
explicit choices made here. No annotation, score, or reference enters this API.

States are interleaved by pitch: Attack=0, Stable=1, Silent=2. A Silent state
retains the preceding pitch as memory, not as voiced support. All returned
times refer to the unshifted, centered 10 ms pYIN frame clock.
"""
from __future__ import annotations

import math
from functools import lru_cache

import numpy as np

from scripts.dsp_note_probe import DT, FRAME, HOP, MIN_SECONDS, SR, Note

STATE_NAMES = ('attack', 'stable', 'silent')
ATTACK, STABLE, SILENT = range(3)
ARMS = ('note_state_hmm', 'note_state_hmm_rms')
PITCHES = 33. + np.arange(145, dtype=float) / 3
PITCHES.setflags(write=False)
PAPER_DT = 256 / 44100
UNVOICED_VOICED_MASS = 1e-12
RMS_SENSITIVITY, RMS_DENOMINATOR_FLOOR = .7, 1e-12
SETTINGS = {
    'model': 'independent_tony_inspired_attack_stable_silent',
    'sample_rate': SR, 'hop_samples': HOP, 'frame_seconds': DT,
    'pitch_min_midi': 33., 'pitch_max_midi': 81., 'pitches_per_semitone': 3,
    'pitch_count': len(PITCHES), 'phase_order': list(STATE_NAMES),
    'state_index': 'pitch_index * 3 + phase',
    'paper_hop_seconds': PAPER_DT,
    'paper_self_probabilities': [.9, .99, .9999],
    'self_probabilities': [p ** (DT / PAPER_DT) for p in (.9, .99, .9999)],
    'self_probability_rescaling': 'paper_probability ** (hop_seconds / paper_hop_seconds)',
    'jump_kernel': 'exp(-abs(destination_midi - source_midi) / 2)',
    'jump_normalization': 'per_outgoing_silent_pitch_row',
    'jump_min_nonzero_semitones': 2 / 3, 'jump_max_semitones': 13.,
    'same_pitch_jump_allowed': True,
    'attack_sigma_semitones': 5., 'stable_sigma_semitones': .9,
    'gaussian_exponent_tau': .1, 'positive_f0_voiced_mass': .5,
    'emission_normalization': 'joint_across_all_2N_attack_and_stable_states',
    'unvoiced_f0_voiced_mass': UNVOICED_VOICED_MASS,
    'unvoiced_f0_voiced_distribution': 'uniform_across_all_2N_states',
    'silent_emission_distribution': 'uniform_across_N_states',
    'initial_attack_mass': .5, 'initial_stable_mass': 0., 'initial_silent_mass': .5,
    'initial_pitch_distribution': 'uniform', 'end_state': 'unconstrained',
    'tie_break': 'smallest_predecessor_state_id_then_smallest_final_state_id',
    'event_pitch': 'rint(median(raw_voiced_fractional_midi_within_decoded_segment))',
    'event_requires_raw_voiced_support': True,
    'raw_unvoiced_posthoc_split': False,
    'minimum_note_seconds': MIN_SECONDS, 'short_segment_policy': 'drop_independently',
    'time_shift_seconds': 0., 'global_tuning_correction': False,
    'rms_frame_samples': FRAME, 'rms_hop_samples': HOP,
    'rms_center': True, 'rms_pad_mode': 'constant',
    'rms_sensitivity': RMS_SENSITIVITY, 'rms_denominator_floor': RMS_DENOMINATOR_FLOOR,
    'rms_test': 'rms[i-1] / rms[i+1] < sensitivity for 2 <= i <= T-2',
    'rms_edit': 'set frame i-2 Silent in a copy of the single decoded path',
    'rms_stable_interior_gate': False,
}


def _pitch_grid(pitches):
    grid = np.asarray(pitches, dtype=float)
    if (grid.ndim != 1 or not len(grid) or len(grid) > 10922
            or not np.isfinite(grid).all() or np.any(np.diff(grid) <= 0)
            or grid[0] < 0 or grid[-1] > 127):
        raise ValueError('invalid pitch-state grid')
    return grid


def _frequencies(hz, grid=PITCHES):
    values = np.asarray(hz, dtype=float)
    if (values.ndim != 1 or not np.isfinite(values).all() or np.any(values < 0)):
        raise ValueError('invalid F0 observations')
    voiced = values > 0
    midi = np.full(values.shape, np.nan)
    midi[voiced] = 69 + 12 * np.log2(values[voiced] / 440.)
    if (np.any(midi[voiced] < grid[0] - 1e-10)
            or np.any(midi[voiced] > grid[-1] + 1e-10)):
        raise ValueError('fractional F0 outside note-state pitch range')
    return values, midi


def _duration(duration, frame_count):
    if not math.isfinite(duration) or duration < 0:
        raise ValueError('invalid audio duration')
    if frame_count == 0:
        if duration != 0:
            raise ValueError('empty F0 requires zero audio duration')
    elif not (max(0., (frame_count - 1) * DT) - 1e-10
              <= duration <= frame_count * DT + 1e-10):
        raise ValueError('duration is inconsistent with the centered F0 frame clock')


@lru_cache(maxsize=8)
def _model(pitch_tuple, dt):
    grid = _pitch_grid(pitch_tuple)
    if not math.isfinite(dt) or dt <= 0:
        raise ValueError('invalid frame duration')
    count = len(grid)
    self_probs = np.array([.9, .99, .9999]) ** (dt / PAPER_DT)
    # Row = source Silent pitch; column = destination Attack pitch.
    distance = np.abs(grid[:, None] - grid[None, :])
    allowed = ((distance < 1e-10) | (distance >= 2 / 3 - 1e-10))
    allowed &= distance <= 13 + 1e-10
    jump = np.where(allowed, np.exp(-distance / 2), 0.)
    jump /= jump.sum(axis=1, keepdims=True)
    width = int(allowed.sum(axis=0).max())
    incoming_ids = np.zeros((count, width), dtype=np.int16)
    incoming_log = np.full((count, width), -np.inf)
    for destination in range(count):
        sources = np.flatnonzero(allowed[:, destination])
        incoming_ids[destination, :len(sources)] = 3 * sources + SILENT
        incoming_log[destination, :len(sources)] = (
            np.log1p(-self_probs[SILENT]) + np.log(jump[sources, destination])
        )
    initial = np.full(3 * count, -np.inf)
    initial[ATTACK::3] = initial[SILENT::3] = math.log(.5 / count)
    return self_probs, jump, incoming_ids, incoming_log, initial


def transition_probabilities(pitches=PITCHES, *, dt=DT):
    """Dense audit representation; decoding itself only visits allowed incoming edges."""
    grid = _pitch_grid(pitches)
    self_probs, jump, _, _, _ = _model(tuple(grid), float(dt))
    count = len(grid)
    result = np.zeros((3 * count, 3 * count))
    indexes = np.arange(count) * 3
    result[indexes, indexes] = self_probs[ATTACK]
    result[indexes, indexes + STABLE] = 1 - self_probs[ATTACK]
    result[indexes + STABLE, indexes + STABLE] = self_probs[STABLE]
    result[indexes + STABLE, indexes + SILENT] = 1 - self_probs[STABLE]
    result[indexes + SILENT, indexes + SILENT] = self_probs[SILENT]
    result[SILENT::3, ATTACK::3] = (1 - self_probs[SILENT]) * jump
    return result


def _observation_log_weights(midi, grid):
    count = len(grid)
    result = np.empty(3 * count)
    if math.isnan(midi):
        result[ATTACK::3] = result[STABLE::3] = math.log(
            UNVOICED_VOICED_MASS / (2 * count))
        result[SILENT::3] = math.log((1 - UNVOICED_VOICED_MASS) / count)
        return result
    delta = midi - grid
    attack = .1 * (-math.log(5.) - .5 * math.log(2 * math.pi) - .5 * (delta / 5.)**2)
    stable = .1 * (-math.log(.9) - .5 * math.log(2 * math.pi) - .5 * (delta / .9)**2)
    maximum = max(float(attack.max()), float(stable.max()))
    normalizer = maximum + math.log(
        float(np.exp(attack - maximum).sum() + np.exp(stable - maximum).sum()))
    result[ATTACK::3] = math.log(.5) + attack - normalizer
    result[STABLE::3] = math.log(.5) + stable - normalizer
    result[SILENT::3] = math.log(.5 / count)
    return result


def observation_log_weights(hz, pitches=PITCHES):
    """Single-frame normalized log weights, exposed for reproducibility checks."""
    grid = _pitch_grid(pitches)
    _, midi = _frequencies([hz], grid)
    return _observation_log_weights(float(midi[0]), grid)


def _decode(midi, grid):
    count, frames = len(grid), len(midi)
    if frames == 0:
        return np.empty(0, dtype=np.int16), 0.
    self_probs, _, sources, jump_log, initial = _model(tuple(grid), DT)
    log_self, log_exit = np.log(self_probs), np.log1p(-self_probs)
    attack_ids = np.arange(count, dtype=np.int16) * 3
    stable_ids, silent_ids = attack_ids + STABLE, attack_ids + SILENT
    rows = np.arange(count)
    back = np.empty((frames, 3 * count), dtype=np.int16)
    back[0] = -1
    previous = initial + _observation_log_weights(float(midi[0]), grid)
    for frame in range(1, frames):
        incoming = previous[sources] + jump_log
        positions = np.argmax(incoming, axis=1)
        jump_scores = incoming[rows, positions]
        jump_sources = sources[rows, positions]
        self_scores = previous[attack_ids] + log_self[ATTACK]
        use_self = ((self_scores > jump_scores)
                    | ((self_scores == jump_scores) & (attack_ids < jump_sources)))
        current = np.empty_like(previous)
        current[ATTACK::3] = np.where(use_self, self_scores, jump_scores)
        back[frame, ATTACK::3] = np.where(use_self, attack_ids, jump_sources)

        attack_scores = previous[attack_ids] + log_exit[ATTACK]
        stable_scores = previous[stable_ids] + log_self[STABLE]
        from_attack = attack_scores >= stable_scores  # Attack ID is smaller on a tie.
        current[STABLE::3] = np.where(from_attack, attack_scores, stable_scores)
        back[frame, STABLE::3] = np.where(from_attack, attack_ids, stable_ids)

        stable_scores = previous[stable_ids] + log_exit[STABLE]
        silent_scores = previous[silent_ids] + log_self[SILENT]
        from_stable = stable_scores >= silent_scores  # Stable ID is smaller on a tie.
        current[SILENT::3] = np.where(from_stable, stable_scores, silent_scores)
        back[frame, SILENT::3] = np.where(from_stable, stable_ids, silent_ids)
        previous = current + _observation_log_weights(float(midi[frame]), grid)
    final_state = int(np.argmax(previous))
    score = float(previous[final_state])
    path = np.empty(frames, dtype=np.int16)
    path[-1] = final_state
    for frame in range(frames - 1, 0, -1):
        path[frame - 1] = back[frame, path[frame]]
    return path, score


def decode_state_path(hz, *, pitches=PITCHES):
    """Sparse Viterbi path; the optional small grid exists only for synthetic audit tests."""
    grid = _pitch_grid(pitches)
    _, midi = _frequencies(hz, grid)
    return _decode(midi, grid)[0]


def centered_rms(samples):
    """2048-sample RMS, centered constant padding, one value per 160-sample F0 hop."""
    audio = np.asarray(samples, dtype=float)
    if audio.ndim != 1 or not len(audio) or not np.isfinite(audio).all():
        raise ValueError('invalid audio for centered RMS')
    # Frame-local summation avoids cancellation in long quiet tails after loud audio.
    padded = np.pad(audio, (FRAME // 2, FRAME // 2), mode='constant')
    windows = np.lib.stride_tricks.sliding_window_view(padded, FRAME)[::HOP]
    with np.errstate(over='ignore', invalid='ignore'):
        result = np.sqrt(np.einsum('ij,ij->i', windows, windows) / FRAME)
    if not np.isfinite(result).all():
        raise ValueError('nonfinite RMS energy')
    return result


def _state_path(path, frame_count):
    values = np.asarray(path)
    if (values.ndim != 1 or len(values) != frame_count
            or not np.issubdtype(values.dtype, np.integer)
            or np.any(values < 0) or np.any(values >= 3 * len(PITCHES))):
        raise ValueError('invalid decoded state path')
    return values


def notes_from_state_path(path, hz, duration):
    """Read events from decoded support, retaining Silent gaps even at the same pitch."""
    values, midi = _frequencies(hz)
    states = _state_path(path, len(values))
    _duration(duration, len(values))
    phases = states % 3
    decoded_voiced, raw_voiced = phases != SILENT, values > 0
    labels = np.where(decoded_voiced, states // 3, -1)
    diagnostics = {
        'frames': len(values), 'raw_voiced_frames': int(raw_voiced.sum()),
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
    notes, begin = [], 0
    for end in range(1, len(labels) + 1):
        if end < len(labels) and labels[end] == labels[begin]:
            continue
        if labels[begin] >= 0:
            diagnostics['segments_before_filter'] += 1
            onset, offset = begin * DT, min(end * DT, duration)
            support = raw_voiced[begin:end]
            diagnostics['attack_only_segments'] += int(np.all(phases[begin:end] == ATTACK))
            diagnostics['segments_touching_audio_start'] += int(begin == 0)
            diagnostics['segments_touching_audio_end'] += int(end * DT >= duration - 1e-10)
            if offset <= onset:
                diagnostics['zero_duration_segments'] += 1
            elif not support.any():
                diagnostics['segments_without_raw_voiced_support'] += 1
            elif offset - onset < MIN_SECONDS - 1e-10:
                diagnostics['short_segments_discarded'] += 1
                diagnostics['short_segments_discarded_seconds'] += offset - onset
            else:
                pitch = int(np.rint(np.median(midi[begin:end][support])))
                notes.append(Note(pitch, onset, offset))
                raw_unvoiced_count = int((~support).sum())
                diagnostics['emitted_notes_with_raw_unvoiced_frames'] += int(raw_unvoiced_count > 0)
                diagnostics['emitted_raw_unvoiced_frames'] += raw_unvoiced_count
                diagnostics['emitted_note_seconds'] += offset - onset
        begin = end
    diagnostics['emitted_notes'] = len(notes)
    return notes, diagnostics


def rms_silence_path(path, rms):
    """Remove one decoded support frame at i-2 for each fixed two-frame RMS rise.

    This is an edit to a copied path, not a second Viterbi decode. The edited
    path need not obey HMM transitions. It never adds voiced support; converting
    it to notes can increase event count or discard short fragments.
    """
    energy = np.asarray(rms, dtype=float)
    if energy.ndim != 1 or not np.isfinite(energy).all() or np.any(energy < 0):
        raise ValueError('invalid RMS observations')
    states = _state_path(path, len(energy))
    edited = states.astype(np.int16, copy=True)
    centers = np.arange(2, len(energy) - 1)
    denominators = energy[centers + 1]
    eligible = denominators > RMS_DENOMINATOR_FLOOR
    ratios = np.full(len(centers), np.inf)
    np.divide(energy[centers - 1], denominators, out=ratios, where=eligible)
    marked = centers[eligible & (ratios < RMS_SENSITIVITY)] - 2
    changed = marked[states[marked] % 3 != SILENT]
    edited[changed] = (edited[changed] // 3) * 3 + SILENT
    return edited, {
        'rms_rise_candidates': int(len(marked)),
        'rms_frames_changed_to_silent': int(len(changed)),
        'rms_candidates_already_silent': int(len(marked) - len(changed)),
    }


def infer_note_states(hz, duration, *, rms=None):
    """Decode once and return notes, private full-state paths, and scalar diagnostics.

    Result keys: arms, phase_path, rms_phase_path, diagnostics. With rms=None,
    arms contains only note_state_hmm; otherwise both frozen candidate arms are
    returned. Callers must keep contour/path arrays in the private artifact.
    """
    values, midi = _frequencies(hz)
    _duration(duration, len(values))
    path, score = _decode(midi, PITCHES)
    notes, base_diagnostics = notes_from_state_path(path, values, duration)
    arms = {ARMS[0]: notes}
    diagnostics = {
        'viterbi_path_log_weight': score,
        'arms': {ARMS[0]: base_diagnostics},
    }
    edited = None
    if rms is not None:
        edited, rms_diagnostics = rms_silence_path(path, rms)
        rms_notes, arm_diagnostics = notes_from_state_path(edited, values, duration)
        arms[ARMS[1]] = rms_notes
        diagnostics['arms'][ARMS[1]] = arm_diagnostics
        diagnostics['rms'] = rms_diagnostics
    return {'arms': arms, 'phase_path': path, 'rms_phase_path': edited,
            'diagnostics': diagnostics}

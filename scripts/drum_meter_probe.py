"""Reference-free metrical candidates from drum-hit times (research only)."""
from __future__ import annotations

import io
import math
from dataclasses import dataclass

import numpy as np

KICK = frozenset({35, 36})
BACKBEAT = frozenset({37, 38, 39, 40})  # rim/side-stick, snare, clap; no GM snap
HATS = frozenset({22, 26, 42, 44, 46})
METERS = (3, 4)
TEMPI = tuple(range(60, 201, 2))
PHASE_STEP_BEATS = .25
METER_MARGIN = .025
PHASE_MARGIN = .025
MIN_KICK = 3
MIN_BACKBEAT = 3


@dataclass(frozen=True)
class Hit:
    time: float
    role: str
    weight: float = 1.0


@dataclass(frozen=True)
class Candidate:
    bpm: float
    meter: int
    phase_beats: float
    quality: float
    periodicity: float
    repeating: float
    role_fit: float


def parse_midi(raw: bytes):
    """Convert MIDI ticks to observed seconds, never disclose MIDI tempo to selector."""
    import mido

    mid = mido.MidiFile(file=io.BytesIO(raw))
    tempo, seconds = 500000, 0.0
    hits, signatures, tempos = [], [], []
    for msg in mido.merge_tracks(mid.tracks):
        seconds += mido.tick2second(msg.time, mid.ticks_per_beat, tempo)
        if msg.type == 'set_tempo':
            tempo = msg.tempo
            tempos.append((seconds, tempo))
        elif msg.type == 'time_signature':
            signatures.append((seconds, msg.numerator, msg.denominator))
        elif (msg.type == 'note_on' and msg.velocity > 0 and
              getattr(msg, 'channel', -1) == 9):
            role = ('kick' if msg.note in KICK else 'backbeat' if msg.note in BACKBEAT
                    else 'hat' if msg.note in HATS else None)
            if role is not None:
                hits.append(Hit(round(seconds, 6), role, msg.velocity / 127.0))
    return tuple(hits), signatures, tempos


def validate_hits(hits):
    if len(hits) < 2 or any(
        not isinstance(h, Hit) or h.role not in {'kick', 'backbeat', 'hat'} or
        not math.isfinite(h.time) or h.time < 0 or not math.isfinite(h.weight)
        or not 0 < h.weight <= 1 for h in hits
    ):
        raise ValueError('invalid hit observations')
    if any(a.time > b.time for a, b in zip(hits, hits[1:])):
        raise ValueError('unsorted observations')


def periodicity(hits, bpm):
    observed = [h for h in hits if h.role != 'hat']
    if not observed:
        return 0.0
    times = np.array([h.time for h in observed])
    weights = np.array([h.weight for h in observed])
    beat = times * (bpm / 60.0)
    return float(.55 * abs(np.sum(weights * np.exp(2j * np.pi * beat)) / weights.sum())
                 + .45 * abs(np.sum(weights * np.exp(4j * np.pi * beat)) / weights.sum()))


def repeat_score(hits, bpm, meter):
    values = []
    duration = max(x.time for x in hits)
    period = 60.0 / bpm * meter
    tol = period / meter * .20
    for role in ('kick', 'backbeat'):
        arr = np.array([h.time for h in hits if h.role == role])
        if len(arr) < 2:
            continue
        targets = arr + period
        targets = targets[targets < duration - tol]
        if not len(targets):
            continue
        idx = np.searchsorted(arr, targets)
        left = np.clip(idx - 1, 0, len(arr) - 1)
        right = np.clip(idx, 0, len(arr) - 1)
        delta = np.minimum(abs(arr[left] - targets), abs(arr[right] - targets))
        values.append(float(np.mean(np.exp(-.5 * (delta / tol) ** 2))))
    return float(np.mean(values)) if values else 0.0


def role_phase_fit(hits, bpm, meter):
    """Fixed toy popular-backbeat templates; not a genre-independent meter rule."""
    groups = [(role, np.array([x.time * bpm / 60.0 for x in hits if x.role == role]),
               np.array([x.weight for x in hits if x.role == role]))
              for role in ('kick', 'backbeat')]
    phases = np.arange(0, meter, PHASE_STEP_BEATS)
    total = np.zeros(len(phases))
    norm = 0.0
    for role, beat, weights in groups:
        if len(beat) == 0:
            continue
        targets = ((0, 2) if meter == 4 else (0,)) if role == 'kick' else (
            (1, 3) if meter == 4 else (1, 2))
        wrapped = (beat[None, :] - phases[:, None]) % meter
        dist = np.stack([np.minimum(abs(wrapped - x), meter - abs(wrapped - x))
                         for x in targets], axis=0)
        match = np.exp(-.5 * (dist.min(axis=0) / .25) ** 2)
        total += (match @ weights) / weights.sum()
        norm += 1.0
    return phases, total / norm if norm else total


def best_for_meter(hits, bpm, meter):
    phases, fits = role_phase_fit(hits, bpm, meter)
    idx = int(np.argmax(fits))
    periodic = periodicity(hits, bpm)
    repeats = repeat_score(hits, bpm, meter)
    # These deliberately simple fixed weights are not data-tuned/calibrated.
    score = .25 * periodic + .35 * float(fits[idx]) + .40 * repeats
    return Candidate(float(bpm), meter, float(phases[idx]), score,
                     periodic, repeats, float(fits[idx])), phases, fits


def infer(hits, *, bpm=None, meter=None):
    """BPM/meter restrict candidate search only when explicitly provided.

    No incoming hits contain reference tempo, downbeat or recording IDs.
    """
    validate_hits(hits)
    if meter is not None and meter not in METERS:
        raise ValueError('unsupported meter')
    if bpm is not None and (not math.isfinite(bpm) or not 35 <= bpm <= 260):
        raise ValueError('invalid bpm constraint')
    if (sum(x.role == 'kick' for x in hits) < MIN_KICK or
            sum(x.role == 'backbeat' for x in hits) < MIN_BACKBEAT):
        return {'status': 'insufficient_drum_roles', 'bpm': None, 'meter': None,
                'phase': None, 'best_quality': None, 'candidates': []}
    all_candidates = []
    for t in (TEMPI if bpm is None else (float(bpm),)):
        for m in (METERS if meter is None else (meter,)):
            candidate, phase_arr, fit_arr = best_for_meter(hits, t, m)
            all_candidates.append((candidate, phase_arr, fit_arr))
    all_candidates.sort(key=lambda x: (-x[0].quality, x[0].bpm, x[0].meter))
    best, phases, fits = all_candidates[0]
    per_meter = {m: max((c.quality for c, _, _ in all_candidates if c.meter == m),
                        default=-float('inf')) for m in (METERS if meter is None else (meter,))}
    meter_margin = (abs(per_meter[3] - per_meter[4]) if meter is None else None)
    meter_selected = (best.meter if meter is not None or meter_margin > METER_MARGIN else None)
    # For the selected tempo and meter, keep more than one comparable phase.
    second = sorted(fits, reverse=True)[1] if len(fits) > 1 else -float('inf')
    phase = (best.phase_beats if (meter_selected is not None and
                                float(fits.max()) - float(second) > PHASE_MARGIN) else None)
    return {'status': 'scored', 'bpm': best.bpm, 'meter': meter_selected, 'phase': phase,
            'raw_best_meter': best.meter, 'best_quality': best.quality,
            'meter_margin': meter_margin,
            'phase_margin': float(fits.max()) - float(second),
            'tempo_candidates': len(TEMPI if bpm is None else (bpm,)),
            'candidates': [{'bpm': c.bpm, 'meter': c.meter, 'phase': c.phase_beats,
                            'quality': round(c.quality, 6)} for c, _, _ in all_candidates[:3]]}


def metadata_candidate(payload, expected_recording_id):
    """An external tempo is NOT trusted without exact version identity evidence."""
    if not isinstance(payload, dict) or not expected_recording_id:
        raise ValueError('metadata payload or reference identity missing')
    same = payload.get('recording_id') == expected_recording_id
    bpm = payload.get('bpm')
    ts = payload.get('time_signature')
    if not same:
        return {'status': 'unverified_recording', 'bpm': None, 'meter': None}
    if type(bpm) not in (int, float) or not math.isfinite(bpm) or not 35 <= bpm <= 260:
        return {'status': 'invalid_bpm', 'bpm': None, 'meter': None}
    if ts not in ('3/4', '4/4'):
        return {'status': 'unsupported_or_missing_meter', 'bpm': float(bpm), 'meter': None}
    return {'status': 'matched', 'bpm': float(bpm), 'meter': int(ts[0])}


def conflict(audio, external):
    """Diagnostic conflict only; NEVER override an exact recording match blindly."""
    if external['status'] != 'matched' or audio['status'] != 'scored':
        return 'not_comparable'
    if audio['meter'] is None:
        return 'uncertain_audio'
    audio_bpm, declared_bpm = audio['bpm'], external['bpm']
    compatible = any(abs(audio_bpm / (declared_bpm * multiplier) - 1) <= .04
                     for multiplier in (0.5, 1., 2.))
    if not compatible or audio['meter'] != external['meter']:
        return 'conflicting_candidates'
    return 'compatible_candidates'

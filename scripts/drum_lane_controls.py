"""Fixed schematic drum controls for the #305 event-lane experiment.

These are integer-authored waveforms, not recordings of acoustic instruments.
Oscillators, noise, envelopes, mixing, and timing use Python integer arithmetic.
The final signed-int16 values are converted exactly to float32 by a power-of-two
scale. There are no NumPy transcendental operations, random generators, model
imports, or sample-dependent parameter choices.

Only ``control_reference`` exposes reference events. Input synthesis uses its
private construction schedule and never invokes the reference-access function.
The experiment runner must freeze every prediction before reading references.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np

CONTROL_SCHEMA = 'authored-drum-lane-controls-v1'
SAMPLE_RATE = 16000
CONTROL_COUNT = 100
CONTROL_IDS = tuple(f'ctl{index:03d}' for index in range(1, CONTROL_COUNT + 1))
LEVELS = (('quiet', 2048), ('normal', 8192))
SEEDS = (17, 91, 203)
PAIR_GAP_FRAMES = (240, 480, 960, 1440)  # Exactly 15/30/60/90 ms at 16 kHz.
LEADING_SILENCE_FRAMES = (1920, 4000, 6080)
INPUT_HASH_ENCODING = 'sha256 of C-order little-endian float32 samples; no file header'


@dataclass(frozen=True)
class _Case:
    id: str
    category: str
    frames: int
    level: str
    amplitude: int
    seed: int
    start_frame: int
    roles: tuple[str, ...]
    gap_frames: int = 0


def _plan():
    cases = []

    def add(category, roles, gap_frames=0):
        for level, amplitude in LEVELS:
            for variant, seed in enumerate(SEEDS):
                cases.append(_Case(CONTROL_IDS[len(cases)], category, SAMPLE_RATE,
                                   level, amplitude, seed, LEADING_SILENCE_FRAMES[variant],
                                   roles, gap_frames))

    for role in ('kick', 'backbeat'):
        add('supported_singleton', (role,))
    for role in ('kick', 'backbeat'):
        for gap in PAIR_GAP_FRAMES:
            add('same_class_pair', (role, role), gap)
    add('simultaneous_supported', ('kick', 'backbeat'))
    for roles in (('kick', 'backbeat', 'hat'), ('kick', 'hat'), ('backbeat', 'hat')):
        add('simultaneous_with_unsupported', roles)
    for role in ('hat', 'tom'):
        add('unsupported_singleton', (role,))
    for seed, frames in enumerate((8000, 12000, 16000, 24000)):
        cases.append(_Case(CONTROL_IDS[len(cases)], 'silence', frames,
                           'silent', 0, seed, 0, ()))
    if len(cases) != CONTROL_COUNT:
        raise ValueError('fixed authored control population changed')
    return tuple(cases)


_CASES = _plan()
_BY_ID = {case.id: case for case in _CASES}


def _metadata(case):
    return {'id': case.id, 'category': case.category, 'sample_rate': SAMPLE_RATE,
            'sample_count': case.frames, 'duration_seconds': case.frames / SAMPLE_RATE,
            'level': case.level, 'seed': case.seed}


def control_inventory():
    """Return the ordered input plan without roles, onset times, or event counts."""
    return [_metadata(case) for case in _CASES]


def _resolve(case):
    if isinstance(case, str):
        identifier = case
    elif isinstance(case, dict) and isinstance(case.get('id'), str):
        identifier = case['id']
    else:
        raise ValueError('known control ID or exact inventory entry required')
    if identifier not in _BY_ID:
        raise ValueError('unknown authored control ID')
    spec = _BY_ID[identifier]
    if isinstance(case, dict):
        expected = _metadata(spec)
        if set(case) != set(expected) or any(
                type(case[key]) is not type(value) or case[key] != value
                for key, value in expected.items()):
            raise ValueError('control inventory metadata was altered')
    return spec


def _schedule(spec):
    return tuple((spec.start_frame + index * spec.gap_frames, role)
                 for index, role in enumerate(spec.roles))


def _pulse(role, seed, amplitude):
    """Integer schematic timbres with fixed lengths and no fitted parameters."""
    lengths = {'kick': 1440, 'backbeat': 720, 'hat': 320, 'tom': 1920}
    if role not in lengths or amplitude not in (2048, 8192):
        raise ValueError('unknown authored timbre or amplitude')
    length = lengths[role]
    frequency = (70 if role == 'kick' else 240) + (seed % 5 - 2) * (3 if role == 'kick' else 11)
    increment, phase = frequency * 65536 // SAMPLE_RATE, 0
    # Fixed unsigned LCG arithmetic is independent of Python's randomized hash
    # seed and NumPy's RNG/version. Different timbres use different streams.
    salt = {'kick': 0x16A5, 'backbeat': 0x3C79, 'hat': 0x77E3, 'tom': 0x5A91}[role]
    state = (seed ^ salt) & 0xFFFFFFFF
    previous_noise = 0
    result = []
    for index in range(length):
        if role in ('kick', 'tom'):
            carrier = 32767 - abs(2 * phase - 65535)
            phase = (phase + increment) & 0xFFFF
        else:
            state = (1664525 * state + 1013904223) & 0xFFFFFFFF
            noise = (state >> 16) - 32768
            carrier = (noise - previous_noise) // 2
            previous_noise = noise
            if role == 'hat' and index % 2:
                carrier = -carrier
        remaining = length - index
        result.append(carrier * amplitude * remaining * remaining // (32768 * length * length))
    return result


def synthesize_input(case):
    """Return (mono float32 samples, exact hash of the actual detector input).

    Roles and construction times are never returned. No reference function is
    called; no clipping, resampling, normalization, or calibration is applied.
    """
    spec = _resolve(case)
    mixed = [0] * spec.frames
    for start, role in _schedule(spec):
        pulse = _pulse(role, spec.seed, spec.amplitude)
        if start < 0 or start + len(pulse) > spec.frames:
            raise ValueError('authored event extends beyond its input')
        for index, value in enumerate(pulse, start):
            mixed[index] += value
    if any(value < -32768 or value > 32767 for value in mixed):
        raise ValueError('authored PCM overflow; clipping is forbidden')
    pcm = np.asarray(mixed, dtype='<i2')
    samples = pcm.astype('<f4') * np.float32(1 / 32768)
    samples.setflags(write=False)
    return samples, hashlib.sha256(samples.tobytes(order='C')).hexdigest()


def control_reference(case):
    """Expose authored events only after the runner's all-predictions barrier.

    The names describe schematic construction intent. In particular, hat/tom
    are unsupported labels, and waveform amplitude is not a MIDI velocity.
    """
    spec = _resolve(case)
    return [{'event_id': f'{spec.id}:e{index:02d}', 'time': frame / SAMPLE_RATE,
             'role': role, 'velocity': None}
            for index, (frame, role) in enumerate(_schedule(spec), 1)]

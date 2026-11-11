"""Research-only performed-vs-notated duration and signal-extracted accent trials.

No model training, original-score lookup, real recording, or product edits.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np

from scripts.bar_sum_rhythm import (
    Clock,
    Solution,
    accent_cost,
    candidates,
    notation_cost,
    validate,
)

# These are exploratory, frozen hypotheses, not calibrated probabilities.
# The earlier synthetic 60%-gate failure motivated including shorter gates.
GATE_HYPOTHESES = ((1.0, 0.0), (0.75, 0.09), (0.5, 0.17))
ONSET_SIGMA_TICKS = 1.25
OFFSET_SIGMA_TICKS = 2.0
OFFSET_WEIGHT = 0.35
PHASE_ABSTAIN_MARGIN = 0.02
SAMPLE_RATE = 8000
AUDIO_ONSET_MIN_RELATIVE = 0.14


@dataclass(frozen=True)
class ArticulationSolution:
    solution: Solution
    note_gate_choices: tuple[float, ...]


def gate_cost(note, observed, clock: Clock):
    """Choose a latent sounding fraction, without the hidden score duration."""
    s = observed.onset / clock.tick_seconds
    e = observed.offset / clock.tick_seconds
    onset = ((note.start - s) / ONSET_SIGMA_TICKS) ** 2
    losses = [
        (OFFSET_WEIGHT * ((note.start + fraction * note.duration - e)
                          / OFFSET_SIGMA_TICKS) ** 2 + prior, fraction)
        for fraction, prior in GATE_HYPOTHESES
    ]
    residual, fraction = min(losses, key=lambda z: (z[0], -z[1]))
    return onset + residual, fraction


def solve_articulation(observations, clock, phase):
    """Exact shortest path over the SAME bounded candidate lattice as #250."""
    validate(observations, clock)
    if not isinstance(phase, int) or not 0 <= phase < clock.bar:
        raise ValueError("invalid phase")
    states = {0: (0.0, (), ())}  # ending tick -> cost, path, sound fraction choices
    for observed in observations:
        incoming = {}
        for start in sorted({n.start for n, _ in candidates(observed, clock)}):
            paths = [
                (value + notation_cost(end, start, phase, clock.bar, False), seq, fractions)
                for end, (value, seq, fractions) in states.items() if end <= start
            ]
            if paths:
                incoming[start] = min(paths, key=lambda z: z[0])
        next_states = {}
        for note, _ in candidates(observed, clock):
            if note.start not in incoming:
                continue
            base, path, fractions = incoming[note.start]
            evidence, fraction = gate_cost(note, observed, clock)
            cost = base + evidence + notation_cost(
                note.start, note.end, phase, clock.bar, True
            )
            if note.end not in next_states or cost < next_states[note.end][0] - 1e-12:
                next_states[note.end] = (
                    cost, path + (note,), fractions + (fraction,)
                )
        if not next_states:
            raise ValueError("no legal path in frozen lattice")
        states = next_states
    cost, notes, fractions = min(states.values(), key=lambda z: z[0])
    return ArticulationSolution(Solution(phase, cost, notes), fractions)


def search_articulation_phases(observations, clock, accents=()):
    """Do not select a phase when the frozen near-tie criterion is ambiguous."""
    scored = []
    for phase in range(clock.bar):
        result = solve_articulation(observations, clock, phase)
        value = result.solution.cost / len(observations) + accent_cost(
            accents, phase, clock.bar
        )
        scored.append((value, result))
    scored.sort(key=lambda z: (z[0], z[1].solution.phase))
    lowest = scored[0][0]
    retained = [
        result.solution.phase for value, result in scored
        if value <= lowest + PHASE_ABSTAIN_MARGIN + 1e-12
    ]
    return {
        "selected_phase": retained[0] if len(retained) == 1 else None,
        "candidate_phases": retained,
        "best": scored[0][1].solution,
        "gates": scored[0][1].note_gate_choices,
        "runner_up_margin": scored[1][0] - lowest,
    }


def synthetic_beat_audio(clock: Clock, phase: int, total_ticks: int, seed: int):
    """Synthesize an OTHER-part pulse waveform. Truth used only by generator."""
    if not 0 <= phase < clock.bar or total_ticks <= clock.bar:
        raise ValueError("invalid generated pulse plan")
    rng = np.random.default_rng(seed)
    total_seconds = (total_ticks + 2) * clock.tick_seconds
    samples = rng.normal(0.0, 0.004, int(np.ceil(total_seconds * SAMPLE_RATE)))
    quarter_ticks = int(round(clock.beat_quarters * 12))
    for tick in range(phase, total_ticks, quarter_ticks):
        downbeat = (tick - phase) % clock.bar == 0
        # Mild beat-to-beat performance timing perturbation; amplitude is not a
        # transcript of detected downbeats (the audio features must recover it).
        shift = float(rng.uniform(-0.003, 0.003))
        start = max(0, round((tick * clock.tick_seconds + shift) * SAMPLE_RATE))
        count = min(round(SAMPLE_RATE * 0.07), len(samples) - start)
        if count <= 0:
            continue
        t = np.arange(count) / SAMPLE_RATE
        low_amplitude = (0.82 if downbeat else 0.18) * rng.uniform(0.9, 1.1)
        samples[start:start + count] += (
            low_amplitude * np.exp(-75.0 * t) * np.sin(2 * np.pi * 120 * t)
            + 0.12 * np.exp(-100.0 * t) * np.sin(2 * np.pi * 1200 * t)
        )
    return samples


def extract_audio_accents(samples, clock: Clock, total_ticks: int):
    """Sample a low-band onset envelope from AUDIO, with no phase or score input.

    This extractor is intentionally simple; it has not been calibrated on
    recorded musical performances. It never receives the source beat schedule.
    """
    if (samples.ndim != 1 or len(samples) < 100 or not np.isfinite(samples).all()
            or total_ticks < 1):
        raise ValueError("invalid wave")
    n = int(round(SAMPLE_RATE * 0.045))
    freq = np.fft.rfftfreq(n, 1.0 / SAMPLE_RATE)
    band = (freq >= 60.0) & (freq <= 210.0)
    envelope = np.zeros(total_ticks + 1, dtype=float)
    for tick in range(total_ticks + 1):
        center = int(round(tick * clock.tick_seconds * SAMPLE_RATE))
        start = max(0, center - int(0.006 * SAMPLE_RATE))
        block = samples[start:start + n]
        if len(block) < n:
            continue
        spec = np.abs(np.fft.rfft(block * np.hanning(n)))
        envelope[tick] = float(np.linalg.norm(spec[band]))
    scale = float(envelope.max())
    if scale <= 0:
        return (), envelope
    strengths = envelope / scale
    selected = []
    # Local maxima plus a refractory period in musical ticks.
    for t in range(1, total_ticks):
        if (strengths[t] >= AUDIO_ONSET_MIN_RELATIVE
                and strengths[t] >= strengths[t - 1]
                and strengths[t] > strengths[t + 1]
                and (not selected or t - selected[-1][0] >= 2)):
            selected.append((float(t), float(strengths[t])))
    # A genuine first-beat click at tick zero cannot have a left neighbor.
    if strengths[0] >= AUDIO_ONSET_MIN_RELATIVE and strengths[0] > strengths[1]:
        selected.insert(0, (0.0, float(strengths[0])))
    return tuple(selected), envelope


def sha256_audio(samples):
    return hashlib.sha256(np.asarray(samples).tobytes()).hexdigest()


def gate_model_settings():
    return {
        "gate_hypotheses": GATE_HYPOTHESES,
        "onset_sigma_ticks": ONSET_SIGMA_TICKS,
        "offset_sigma_ticks": OFFSET_SIGMA_TICKS,
        "offset_weight": OFFSET_WEIGHT,
        "phase_abstain_margin": PHASE_ABSTAIN_MARGIN,
        "audio_sample_rate": SAMPLE_RATE,
        "audio_min_relative": AUDIO_ONSET_MIN_RELATIVE,
        "audio_is_synthetic": True,
        "training": False,
        "quality_approved": False,
    }

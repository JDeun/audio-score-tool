"""Fixed metadata admission and post-prediction MIDI references for #305.

This module does not import a detector or scorer. Source WAVs are the original
GMD TD-11 recordings, not locally rendered replacement audio.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
from pathlib import Path

from scripts.run_drum_meter_probe import manifest, safe_member

ROOT = Path(__file__).resolve().parents[1]
EXCLUSION_PATH = ROOT / 'docs/research/TEMPO_BEAT_MODEL_INPUTS_2026-11-12.json'
EXCLUSION_SHA256 = '6f78287bf8ab42a6df61fd8e251d154af61b2121283acd2fabbd7d9fb8764957'
METADATA_SHA256 = '3e17eef2f18012c0160c183ad5b106964eb429876cceb1eee1b746def4e6b11b'
SUPPORTED_ROLES = ('kick', 'backbeat')
OLD_IDS = ('drummer7/session2/93', 'drummer7/session2/2',
           'drummer7/session3/87', 'drummer1/session2/1')
ROLE_PITCHES = {
    'kick': (35, 36), 'backbeat': (37, 38, 39, 40),
    'hat_closed': (22, 42, 44), 'hat_open': (26, 46),
    'tom_low': (43, 58), 'tom_mid': (45, 47), 'tom_high': (48, 50),
    'crash': (49, 52, 55, 57), 'ride': (51, 53, 59),
}
PITCH_ROLE = {pitch: role for role, pitches in ROLE_PITCHES.items() for pitch in pitches}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def exclusion_inventory():
    raw = EXCLUSION_PATH.read_bytes()
    if digest(raw) != EXCLUSION_SHA256:
        raise ValueError('historical_waveform_inventory_identity')
    rows = json.loads(raw)['inputs']
    if len(rows) != 16 or len({row['id'] for row in rows}) != 16:
        raise ValueError('historical_waveform_inventory_population')
    return rows


def select_rows(rows):
    """Select by metadata only, never using MIDI events or detector outputs."""
    by_id = {row['id']: row for row in rows}
    if len(by_id) != len(rows) or not all(key in by_id for key in OLD_IDS):
        raise ValueError('metadata_unique_ids_and_original_four_required')
    excluded = {row['id'] for row in exclusion_inventory()}
    fresh = []
    for kind, count, max_duration in (('beat', 4, 28.0), ('fill', 2, 15.0)):
        eligible = [row for row in rows if row['id'] not in excluded
                    and row['split'] == 'test' and row['time_signature'] == '4-4'
                    and row['beat_type'] == kind
                    and 4.0 <= float(row['duration']) <= max_duration]
        ordered = sorted(eligible, key=lambda row: digest(row['id'].encode()))
        if len(ordered) < count:
            raise ValueError('insufficient_predeclared_new_waveform_population')
        fresh.extend(dict(row, cohort='new_waveform') for row in ordered[:count])
    replay = [dict(by_id[key], cohort='development_replay') for key in OLD_IDS]
    return fresh + replay


def read_metadata(archive):
    base, rows = manifest(archive)
    raw = safe_member(archive, base + 'info.csv')
    if digest(raw) != METADATA_SHA256:
        raise ValueError('original_metadata_identity')
    return base, rows


def midi_reference(raw, duration):
    """Called only after the whole prediction artifact has been frozen.

    Source tempo messages convert ticks to elapsed seconds. No alignment shift,
    beat quantization, given BPM or inferred clock corrects these times.
    """
    import mido

    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('reference_excerpt_duration')
    midi = mido.MidiFile(file=io.BytesIO(raw))
    if midi.type == 2 or midi.ticks_per_beat <= 0:
        raise ValueError('unsupported_reference_midi_clock')
    tempo, elapsed = 500000, 0.0
    events = []
    total_messages = 0
    for message in mido.merge_tracks(midi.tracks):
        total_messages += 1
        if total_messages > 100000 or message.time < 0:
            raise ValueError('reference_message_budget_or_delta')
        elapsed += mido.tick2second(message.time, midi.ticks_per_beat, tempo)
        if message.type == 'set_tempo':
            if message.tempo <= 0:
                raise ValueError('reference_tempo')
            tempo = message.tempo
        if message.type != 'note_on' or message.velocity == 0 or elapsed >= duration:
            continue
        if message.channel != 9:
            raise ValueError('unexpected_nonpercussion_reference_channel')
        events.append({'event_id': f'r{len(events):05d}', 'time': float(elapsed),
                       'role': PITCH_ROLE.get(message.note, f'unsupported_pitch_{message.note}'),
                       'velocity': message.velocity})
    return events

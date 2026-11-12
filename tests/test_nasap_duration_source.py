"""MIDI semantics checks independent from performance accuracy evaluation."""
import io
from collections import defaultdict

import mido

from scripts.audit_nasap_duration_source import compare_rows, midi_key_events


def test_pedal_can_extend_export_without_extending_key_press():
    f = mido.MidiFile(ticks_per_beat=480)
    t = mido.MidiTrack()
    f.tracks.append(t)
    t.extend([mido.MetaMessage('set_tempo', tempo=500000),
              mido.Message('control_change', control=64, value=127),
              mido.Message('note_on', note=60, velocity=90),
              mido.Message('note_off', note=60, time=480),
              mido.Message('control_change', control=64, value=0, time=480)])
    b = io.BytesIO()
    f.save(file=b)
    notes, pedals = midi_key_events(b.getvalue())
    assert notes[0]['offset'] == .5
    csv = [{'onset_sec': '0', 'duration_sec': '1', 'pitch': '60', 'channel': '0'}]
    result = compare_rows(csv, notes, pedals, 0, 2)
    assert result['key_duration_equal_2ms'] == 0
    assert result['pedal_only_equal_2ms'] == 1
    assert result['csv_longer_than_key_10ms'] == 1


def test_no_pedal_duration_matches_key():
    notes = [{'onset': 1., 'offset': 1.5, 'pitch': 60, 'channel': 0}]
    csv = [{'onset_sec': '1', 'duration_sec': '.5', 'pitch': '60', 'channel': '0'}]
    result = compare_rows(csv, notes, defaultdict(list), 0, 2)
    assert result['key_duration_equal_2ms'] == 1
    assert result['pedal_only_equal_2ms'] == 1

"""Post-study semantic audit, not a new accuracy condition or parameter search."""
from __future__ import annotations

import argparse
import bisect
import io
import json
from collections import defaultdict
from pathlib import Path

import mido

from scripts.nasap_duration_probe import Reader, beat_clock, rows, sha


def midi_key_events(raw):
    file = mido.MidiFile(file=io.BytesIO(raw))
    timeline = []
    for track, messages in enumerate(file.tracks):
        tick = 0
        for order, message in enumerate(messages):
            tick += message.time
            timeline.append((tick, track, order, message))
    timeline.sort(key=lambda x: x[:3])
    tempo, seconds, tick_before = 500000, 0., 0
    active, pedals, notes = defaultdict(list), defaultdict(list), []
    for tick, track, _, message in timeline:
        seconds += (tick - tick_before) * tempo / (file.ticks_per_beat * 1_000_000)
        tick_before = tick
        if message.type == 'set_tempo':
            tempo = message.tempo
        elif message.type == 'control_change' and message.control == 64:
            pedals[message.channel].append((seconds, message.value))
        elif message.type == 'note_on' and message.velocity:
            active[(track, message.channel, message.note)].append(seconds)
        elif message.type == 'note_off' or (message.type == 'note_on' and not message.velocity):
            key = (track, message.channel, message.note)
            if active[key]:
                onset = active[key].pop(0)
                notes.append({'onset': onset, 'offset': seconds,
                              'pitch': message.note, 'channel': message.channel})
    notes.sort(key=lambda x: (x['onset'], x['pitch']))
    return notes, pedals


def compare_rows(perf, notes, pedals, start, end):
    by_pitch = defaultdict(list)
    for note in notes:
        by_pitch[(note['pitch'], note['channel'])].append(note)
    totals = {'csv_notes': 0, 'matched_unique_onsets': 0, 'key_duration_equal_2ms': 0,
              'csv_longer_than_key_10ms': 0, 'pedal_only_equal_2ms': 0,
              'pedal_retrigger_cap_equal_2ms': 0, 'cc64_events': sum(map(len, pedals.values()))}
    extensions = []
    for r in perf:
        onset, duration = float(r['onset_sec']), float(r['duration_sec'])
        if not start <= onset or onset + duration > end or duration <= 0:
            continue
        totals['csv_notes'] += 1
        candidates = [n for n in by_pitch[(int(r['pitch']), int(r['channel']))]
                      if abs(n['onset'] - onset) <= .002]
        if len(candidates) != 1:
            continue
        n = candidates[0]
        totals['matched_unique_onsets'] += 1
        key_duration = n['offset'] - n['onset']
        extension = duration - key_duration
        extensions.append(extension)
        totals['key_duration_equal_2ms'] += abs(extension) <= .002
        totals['csv_longer_than_key_10ms'] += extension > .010
        controls = pedals[n['channel']]
        i = bisect.bisect_right([p[0] for p in controls], n['offset']) - 1
        sound_off = n['offset']
        if i >= 0 and controls[i][1] >= 64:
            releases = [t for t, value in controls[i+1:] if value < 64]
            if releases:
                sound_off = releases[0]
        retriggers = [x['onset'] for x in by_pitch[(n['pitch'], n['channel'])]
                      if x['onset'] > n['onset'] + .002]
        capped = min(sound_off, min(retriggers)) if retriggers else sound_off
        totals['pedal_only_equal_2ms'] += abs((sound_off-n['onset']) - duration) <= .002
        totals['pedal_retrigger_cap_equal_2ms'] += abs((capped-n['onset']) - duration) <= .002
    totals['max_csv_minus_key_seconds'] = max(extensions, default=None)
    return totals


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--study', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists() or args.output.is_symlink():
        p.error('new audit output required')
    source = args.study.read_bytes()
    study = json.loads(source)
    reader = Reader()
    metadata_raw = reader.get('metadata.csv')
    if sha(metadata_raw) != study['files']['metadata.csv']['sha256']:
        raise ValueError('metadata changed from measured study')
    metadata = {r['midi_performance']: r for r in rows(metadata_raw)}
    report = {'scope': 'CSV duration versus original MIDI key release and CC64; not re-scored accuracy',
              'study_sha256': sha(source), 'cases': [], 'predictor_changes': False}
    for case in study['cases']:
        if case['status'] != 'complete':
            continue
        row = metadata[case['id']]
        perf_path = row['parangonada_data_folder'].rstrip('/') + '/ppart.csv'
        raw = reader.get(perf_path)
        if sha(raw) != study['files'][perf_path]['sha256']:
            raise ValueError('performance CSV changed')
        perf = rows(raw)
        annotation = reader.get(row['performance_annotations'])
        if sha(annotation) != study['files'][row['performance_annotations']]['sha256']:
            raise ValueError('beat annotation changed')
        times, _, _ = beat_clock(perf, annotation)
        midi = reader.get(row['midi_performance'])
        notes, pedals = midi_key_events(midi)
        report['cases'].append({'id': case['id'], 'status': 'complete',
                                **compare_rows(perf, notes, pedals, times[0], times[-1])})
    report['files'] = reader.files
    report['downloaded_bytes'] = reader.total
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print('Source duration semantics audited:', len(report['cases']), flush=True)


if __name__ == '__main__':
    main()

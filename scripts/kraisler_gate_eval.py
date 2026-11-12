"""Performed-note evaluation and unaligned score audit for frozen KRAISLER arms.

Mono WAV channels do not imply monophonic music. Simultaneous pitches and
overlapping reference notes are retained. XML counts never become timed rest
labels without an independently established score-to-performance alignment.
"""
from __future__ import annotations

import csv
import hashlib
import heapq
import io
import math
import re
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, replace
from statistics import mean

import numpy as np

from scripts.audio_gate_attribution import ARMS, OPERATIONS
from scripts.audio_gate_rest import gains_and_damage, mask_intervals, scored_notes
from scripts.vocal_recovery import event_digest, events_from

BASES = ('default', 'onset065')
NOTE_COLUMNS = ('onset', 'offset', 'midi', 'velocity')
BEAT_COLUMNS = ('beat_time', 'beat_type', 'time_signature', 'piano', 'violin')
METRICS = ('onset_f1', 'onset_offset_f1')
OCCUPANCY_SECONDS = ('reference_note_s', 'reference_gap_s', 'correct_gap_s',
                     'lost_note_s', 'filled_reference_gap_s')


@dataclass(frozen=True)
class NoteReference:
    intervals: tuple[tuple[float, float], ...]
    midi: tuple[int, ...]
    velocities: tuple[int, ...]
    equivalent_hz_csv: bytes

    @property
    def note_count(self) -> int:
        return len(self.intervals)


def _csv_rows(raw: bytes, columns: tuple[str, ...]) -> list[list[str]]:
    if not isinstance(raw, bytes) or len(raw) > 4_000_000:
        raise ValueError('bounded UTF-8 CSV bytes required')
    reader = csv.reader(io.StringIO(raw.decode('utf-8-sig')), strict=True)
    if tuple(next(reader, ())) != columns:
        raise ValueError('CSV header mismatch: ' + ','.join(columns))
    rows = list(reader)
    if not rows or any(len(row) != len(columns) for row in rows):
        raise ValueError('empty or malformed CSV rows')
    return rows


def read_reference(raw: bytes, audio_duration_s: float | None = None) -> NoteReference:
    """Read original onset/offset seconds and integral MIDI labels without sorting.

    Strict source order is nondecreasing onset, allowing chords. Reference
    intervals must be positive, within observed audio when its duration is given,
    and contain no duplicate onset/offset/pitch labels. Nothing is clipped or
    dropped. MIDI-to-Hz conversion is exact to ordinary float precision and is
    passed to the unchanged original-Hz scorer as onset,Hz,duration CSV bytes.
    """
    if audio_duration_s is not None and (
            not isinstance(audio_duration_s, (int, float)) or isinstance(audio_duration_s, bool)
            or not math.isfinite(audio_duration_s) or audio_duration_s <= 0):
        raise ValueError('positive finite audio duration required')
    intervals, pitches, velocities, seen, converted = [], [], [], set(), []
    for row in _csv_rows(raw, NOTE_COLUMNS):
        onset, offset, midi, velocity = map(float, row)
        if (not all(math.isfinite(x) for x in (onset, offset, midi, velocity))
                or onset < 0 or offset <= onset or not 0 <= midi <= 127
                or midi != int(midi) or not 0 <= velocity <= 127 or velocity != int(velocity)):
            raise ValueError('invalid reference time, MIDI pitch, or velocity')
        if audio_duration_s is not None and offset > audio_duration_s:
            raise ValueError('reference note extends beyond observed audio')
        if intervals and onset < intervals[-1][0]:
            raise ValueError('reference onsets are out of order')
        identity = (onset, offset, int(midi))
        if identity in seen:
            raise ValueError('duplicate reference onset/offset/pitch')
        seen.add(identity)
        intervals.append((onset, offset))
        pitches.append(int(midi))
        velocities.append(int(velocity))
        hz = 440. * 2 ** ((midi - 69.) / 12.)
        converted.append(f'{onset!r},{hz!r},{offset - onset!r}\n')
    return NoteReference(tuple(intervals), tuple(pitches), tuple(velocities),
                         ''.join(converted).encode('utf-8'))


def evaluate_arms(predictions: dict, reference_raw: bytes, edges) -> dict:
    """Score one decoder's four arms using the unchanged performed-note APIs.

    predictions is make_attribution_arms() output. Returned entries contain
    count/event_sha256/edits/metrics only; reference CSV and events stay private.
    """
    if not isinstance(predictions, dict) or set(predictions) != set(ARMS):
        raise ValueError('exactly four predeclared arms required')
    edges = np.asarray(edges, dtype=float)
    if edges.ndim != 1 or len(edges) < 2 or edges[0] != 0:
        raise ValueError('audio timeline must start at zero and contain cells')
    mask_intervals(edges, np.zeros(len(edges) - 1, dtype=bool))
    reference = read_reference(reference_raw, float(edges[-1]))
    before = {arm: event_digest(events_from(predictions[arm][0])) for arm in ARMS}
    raw = events_from(predictions['raw'][0])
    tail = events_from(predictions['tail_only'][0])
    if len(tail) != len(raw) or any(
            replace(child, offset=parent.offset) != parent or child.offset > parent.offset
            for parent, child in zip(raw, tail)):
        raise ValueError('tail-only changed count, onset, identity, or extended an offset')
    entries = {}
    for arm in ARMS:
        notes, edits = predictions[arm]
        notes = events_from(notes)
        if any(note.is_drum for note in notes):
            raise ValueError('performed-pitch scorer requires non-drum predictions')
        value = scored_notes(notes, reference.equivalent_hz_csv, edges)
        baseline = value if arm == 'raw' else entries['raw']['metrics']
        value['transition'] = {
            metric: gains_and_damage(baseline[metric + '_reference_mask'],
                                     value[metric + '_reference_mask'])
            for metric in ('onset', 'onset_offset')}
        if arm == 'tail_only' and value['onset_f1'] != baseline['onset_f1']:
            raise ValueError('tail-only altered onset F1')
        entries[arm] = {'count': len(notes), 'event_sha256': event_digest(notes),
                        'edits': edits, 'metrics': value}
    if any(event_digest(events_from(predictions[arm][0])) != before[arm] for arm in ARMS):
        raise ValueError('scoring mutated predictions')
    return entries


def _paired(values):
    return {'improved': sum(x > 1e-9 for x in values),
            'worsened': sum(x < -1e-9 for x in values),
            'equal': sum(abs(x) <= 1e-9 for x in values)}


def summarize(cases: list[dict], planned_ids) -> dict | None:
    """Require all six planned recordings, both decoders, and all four arms."""
    planned_ids = tuple(planned_ids)
    if (len(planned_ids) != 6 or len(set(planned_ids)) != 6 or len(cases) != 6
            or {r.get('id') for r in cases} != set(planned_ids)
            or any(r.get('status') != 'scored' or set(r.get('bases', {})) != set(BASES)
                   for r in cases)):
        return None
    if any(set(r['bases'][base].get('arms', {})) != set(ARMS)
           for r in cases for base in BASES):
        return None
    for case in cases:
        n_reference = None
        for base in BASES:
            rows = case['bases'][base]['arms']
            for arm in ARMS:
                entry = rows[arm]
                value = entry['metrics']
                n = value['reference_note_count']
                if type(n) is not int or n <= 0 or (n_reference is not None and n != n_reference):
                    raise ValueError('reference population differs between arms')
                n_reference = n
                if type(entry['count']) is not int or entry['count'] < 0:
                    raise ValueError('invalid predicted count')
                for metric in METRICS:
                    if not math.isfinite(value[metric]) or not 0 <= value[metric] <= 1:
                        raise ValueError('invalid note metric')
                for key in OCCUPANCY_SECONDS:
                    if not math.isfinite(value['occupancy'][key]) or value['occupancy'][key] < 0:
                        raise ValueError('invalid occupancy seconds')
                for metric in ('onset', 'onset_offset'):
                    mask = value[metric + '_reference_mask']
                    if len(mask) != n or set(mask) - {'0', '1'}:
                        raise ValueError('reference mask population mismatch')
                    expected = gains_and_damage(rows['raw']['metrics'][metric + '_reference_mask'], mask)
                    if value['transition'][metric] != expected:
                        raise ValueError('gain/damage ledger mismatch')
    result = {'recordings': 6, 'aggregation': 'six-recording macro',
              'planned_ids': list(planned_ids), 'scored_conditions': 6 * len(BASES) * len(ARMS),
              'bases': {}, 'explicit_written_rest_f1_evaluated': False}
    for base in BASES:
        result['bases'][base] = {}
        for arm in ARMS:
            rows = [r['bases'][base]['arms'][arm] for r in cases]
            raw = [r['bases'][base]['arms']['raw'] for r in cases]
            values = [r['metrics'] for r in rows]
            deltas = [r['metrics']['onset_offset_f1'] - b['metrics']['onset_offset_f1']
                      for r, b in zip(rows, raw)]
            entry = {metric: mean(v[metric] for v in values) for metric in METRICS}
            entry.update(delta_vs_raw={metric: mean(r['metrics'][metric] - b['metrics'][metric]
                                                     for r, b in zip(rows, raw)) for metric in METRICS},
                         paired_recordings=_paired(deltas), output_notes=sum(r['count'] for r in rows),
                         reference_notes=sum(v['reference_note_count'] for v in values),
                         changed_parents=sum(r['edits']['changed_parents'] for r in rows),
                         operation_counts={key: sum(r['edits']['operation_counts'][key] for r in rows)
                                           for key in OPERATIONS},
                         occupancy_seconds_totals={key: sum(v['occupancy'][key] for v in values)
                                                   for key in OCCUPANCY_SECONDS})
            for metric in ('onset', 'onset_offset'):
                entry[metric + '_transition'] = {
                    key: sum(v['transition'][metric][key] for v in values)
                    for key in ('gained', 'damaged')}
            entry['per_recording'] = [
                {'id': case['id'], **{metric: row['metrics'][metric] for metric in METRICS},
                 'onset_offset_delta_vs_raw': delta, 'output_notes': row['count'],
                 'changed_parents': row['edits']['changed_parents']}
                for case, row, delta in zip(cases, rows, deltas)]
            result['bases'][base][arm] = entry
    contexts = [r.get('score_context', {}) for r in cases]
    audited = [context for context in contexts if context.get('status') == 'audited']
    result['score_context'] = {
        'audited_recordings': len(audited), 'unsupported_or_missing_recordings': 6 - len(audited),
        'aligned_recordings': 0, 'unaligned_recordings': 6,
        'xml_count_totals': {key: sum(c['xml_counts'][key] for c in audited)
                             for key in ('parts', 'measures', 'pitched_notes', 'explicit_rests',
                                         'chord_members', 'grace_notes', 'duplicate_note_ids')},
        'articulation_tag_totals': dict(sum((Counter(c['articulation_tags']) for c in audited), Counter())),
        'interpretation': 'structural counts only; score-to-audio alignment unestablished',
    }
    return result


def score_context_audit(raw_musicxml: bytes, raw_beat_csv: bytes, reference_csv: bytes) -> dict:
    """Audit explicit XML/beat structure without fabricating timed score labels.

    No score-to-performance measure/repeat/beat-unit correspondence is established
    by these three files alone. Even a successful structural audit stays unaligned.
    Unsupported inputs produce an explicit audit failure, not invented rest scores.
    """
    result = {'status': 'unsupported', 'alignment_status': 'unaligned',
              'explicit_written_rest_f1_evaluated': False,
              'source_sha256': {name: hashlib.sha256(raw).hexdigest() for name, raw in (
                  ('musicxml', raw_musicxml), ('beats', raw_beat_csv), ('reference', reference_csv))}}
    try:
        reference = read_reference(reference_csv)
        beat_rows = _csv_rows(raw_beat_csv, BEAT_COLUMNS)
        previous_time, beat_types, meters = -1., Counter(), []
        for row in beat_rows:
            timestamp, kind, meter, piano, violin = row
            timestamp = float(timestamp)
            if (not math.isfinite(timestamp) or timestamp < 0 or timestamp <= previous_time
                    or kind not in ('b', 'db') or piano not in ('True', 'False')
                    or violin not in ('True', 'False')
                    or meter and not re.fullmatch(r'[1-9][0-9]*/[1-9][0-9]*', meter)):
                raise ValueError('invalid beat row/order/signature/activity flag')
            previous_time = timestamp
            beat_types[kind] += 1
            if meter and (not meters or meters[-1] != meter):
                meters.append(meter)
        if len(raw_musicxml) > 4_000_000 or b'<!ENTITY' in raw_musicxml.upper():
            raise ValueError('unsafe or oversized XML')
        root = ET.fromstring(raw_musicxml)
        if root.tag != 'score-partwise':
            raise ValueError('unsupported MusicXML root/namespace')
        counts = Counter(parts=0, measures=0, pitched_notes=0, explicit_rests=0,
                         chord_members=0, grace_notes=0, duplicate_note_ids=0,
                         unpitched_notes=0, tie_starts=0, tie_stops=0)
        articulations, voices, note_ids, time_signatures = Counter(), set(), [], []
        for part in root.findall('part'):
            counts['parts'] += 1
            for measure in part.findall('measure'):
                counts['measures'] += 1
                for time in measure.findall('./attributes/time'):
                    time_signatures.append('/'.join((time.findtext('beats', '?'),
                                                     time.findtext('beat-type', '?'))))
                for note in measure.findall('note'):
                    voices.add((part.get('id'), note.findtext('voice', '1')))
                    if note.get('id'):
                        note_ids.append(note.get('id'))
                    for key, tag in (('pitched_notes', 'pitch'), ('explicit_rests', 'rest'),
                                     ('chord_members', 'chord'), ('grace_notes', 'grace'),
                                     ('unpitched_notes', 'unpitched')):
                        counts[key] += note.find(tag) is not None
                    for tie in note.findall('tie'):
                        counts['tie_starts'] += tie.get('type') == 'start'
                        counts['tie_stops'] += tie.get('type') == 'stop'
                    for tag in note.findall('./notations/articulations/*'):
                        articulations[tag.tag] += 1
        counts['duplicate_note_ids'] = sum(n - 1 for n in Counter(note_ids).values())
        active, overlap_pairs, max_polyphony = [], 0, 0
        for onset, offset in reference.intervals:
            while active and active[0] <= onset:
                heapq.heappop(active)
            overlap_pairs += len(active)
            heapq.heappush(active, offset)
            max_polyphony = max(max_polyphony, len(active))
        result.update(status='audited', xml_counts=dict(counts), articulation_tags=dict(articulations),
                      voice_count=len(voices), xml_time_signatures=sorted(set(time_signatures)),
                      beat_count=len(beat_rows), beat_type_counts=dict(beat_types),
                      beat_time_signature_sequence=meters,
                      reference_note_count=reference.note_count,
                      overlapping_reference_note_pairs=overlap_pairs,
                      max_simultaneous_reference_notes=max_polyphony,
                      alignment_reason='No verified score measure/repeat/beat-unit to audio mapping; '
                                       'beat timestamps and score labels are not combined.')
    except (ValueError, TypeError, UnicodeError, csv.Error, ET.ParseError) as exc:
        result.update(error_type=type(exc).__name__, reason=str(exc)[:200])
    return result

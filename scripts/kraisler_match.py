"""Audit original KRAISLER piano match coordinates against its symbolic score.

Match beats use the time-signature denominator, and symbolic offsets/durations
use whole-note fractions. These differ from compound-meter beat-CSV pulses.
No source prediction, fitted clock shift, acoustic inference, or clock repair is
used here. The returned anchors describe the supplied piano alignment only.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from fractions import Fraction
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scripts.kraisler_score import ParsedScore

MAX_BYTES = 4_000_000
# Original Match export prints beat coordinates to four decimal places.
BEAT_ROUNDING_BOUND = Fraction(1, 20000)
PITCH_CLASS = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}
ALTER = {'': 0, 'n': 0, 'b': -1, '#': 1, 'bb': -2, 'x': 2, '##': 2}
ORNAMENT_ATTRIBUTES = {'tremolo', 'trill', 'trill-mark', 'turn', 'inverted-turn',
                       'delayed-turn', 'delayed-inverted-turn', 'mordent',
                       'inverted-mordent', 'schleifer', 'shake', 'wavy-line',
                       'other-ornament'}


@dataclass(frozen=True)
class MatchAnchor:
    q: Fraction
    time: float
    score_end_q: Fraction
    pitch: int
    score_id: str
    performance_id: str
    score_support_ids: tuple[str, ...]
    attributes: tuple[str, ...]
    line_number: int

    @property
    def score_q(self):
        return self.q

    @property
    def performance_onset_s(self):
        return self.time


@dataclass(frozen=True)
class MatchAudit:
    anchors: tuple[MatchAnchor, ...]
    strict_score_consistency: bool
    diagnostics: dict


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _fields(text):
    """Split the fixed Prolog-like syntax without evaluation or naïve commas."""
    result, start, depth = [], 0, 0
    for i, char in enumerate(text):
        if char == '[':
            depth += 1
        elif char == ']':
            depth -= 1
            _require(depth >= 0, 'unbalanced Match list')
        elif char == ',' and depth == 0:
            result.append(text[start:i].strip())
            start = i + 1
    _require(depth == 0, 'unbalanced Match list')
    result.append(text[start:].strip())
    return result


def _list(text):
    _require(text.startswith('[') and text.endswith(']'), 'Match list required')
    return tuple(_fields(text[1:-1])) if text[1:-1] else ()


def _int(text, minimum=None, maximum=None):
    _require(re.fullmatch(r'-?\d+', text), 'integral Match field required')
    value = int(text)
    _require(minimum is None or value >= minimum, 'Match integer below range')
    _require(maximum is None or value <= maximum, 'Match integer above range')
    return value


def _fraction(text, nonnegative=False):
    _require(re.fullmatch(r'-?\d+(?:/[1-9]\d*)?', text), 'symbolic Match fraction required')
    value = Fraction(text)
    _require(not nonnegative or value >= 0, 'negative symbolic Match duration/offset')
    return value


def _decimal(text):
    _require(re.fullmatch(r'-?\d+(?:\.\d+)?', text), 'finite decimal Match beat required')
    return Fraction(text)


def _position(text):
    values = text.split(':')
    _require(len(values) == 2, 'Match measure:beat required')
    return _int(values[0], 0), _int(values[1], 1)


def _identifier(text):
    _require(re.fullmatch(r'[A-Za-z0-9_.-]+', text), 'invalid Match identifier')
    return text


def _performance_note(text):
    values = _fields(text)
    _require(len(values) == 7, 'Match 1.1 performance note must have seven fields')
    identity = _identifier(values[0])
    pitch = _int(values[1], 0, 127)
    onset, offset = _int(values[2], 0), _int(values[3], 0)
    # MIDI can contain a zero-length event. The selected source has such rows
    # only among insertions; preserve/count them rather than inventing duration.
    _require(offset >= onset, 'negative performed-note duration')
    _int(values[4], 0, 127)
    _int(values[5], 0, 15)
    _int(values[6], 0)
    return identity, pitch, onset, offset


def _score_note(text):
    values = _fields(text)
    _require(len(values) == 9, 'Match score note must have nine fields')
    identity = _identifier(values[0])
    spelling = _list(values[1])
    _require(len(spelling) == 2 and spelling[0] in PITCH_CLASS and spelling[1] in ALTER,
             'unsupported Match pitch spelling')
    pitch = 12 * (_int(values[2], -1, 9) + 1) + PITCH_CLASS[spelling[0]] + ALTER[spelling[1]]
    _require(0 <= pitch <= 127, 'Match score pitch outside MIDI range')
    measure, beat = _position(values[3])
    offset, duration = _fraction(values[4], True), _fraction(values[5], True)
    onset_beats, offset_beats = _decimal(values[6]), _decimal(values[7])
    attributes = _list(values[8])
    _require(all(re.fullmatch(r'[A-Za-z0-9_-]+', item) for item in attributes), 'invalid Match attribute')
    grace = 'grace' in attributes or 'appoggiatura' in attributes
    _require(duration > 0 or grace, 'non-grace score note must have duration')
    return {'id': identity, 'pitch': pitch, 'measure': measure, 'beat': beat,
            'offset': offset, 'duration': duration, 'onset_beats': onset_beats,
            'offset_beats': offset_beats, 'attributes': attributes, 'grace': grace}


class _ScoreClock:
    def __init__(self, score):
        _require(len({measure.part for measure in score.measures}) == 1,
                 'piano Match audit requires one symbolic part')
        self.measures = tuple(score.measures)
        _require(bool(self.measures), 'empty symbolic score')
        _require(self.measures[0].onset_q == 0, 'symbolic score must start at zero')
        self.pickup = bool(self.measures[0].pickup)
        self.starts = []
        first = self.measures[0]
        _require(first.time_signature is not None, 'missing score time signature')
        beats = (-(first.end_q - first.onset_q) * first.time_signature[1] / 4
                 if self.pickup else Fraction(0))
        for previous, measure in zip((None, *self.measures[:-1]), self.measures):
            _require(previous is None or previous.end_q == measure.onset_q, 'noncontiguous score measures')
            _require(measure.time_signature is not None, 'missing score time signature')
            self.starts.append(beats)
            beats += (measure.end_q - measure.onset_q) * measure.time_signature[1] / 4
        self.final_beats = beats

    def position(self, measure_number, beat, offset):
        index = measure_number if self.pickup else measure_number - 1
        _require(0 <= index < len(self.measures), 'Match measure outside symbolic score')
        measure = self.measures[index]
        numerator, denominator = measure.time_signature
        _require(beat <= numerator, 'Match beat outside meter')
        _require(offset < Fraction(1, denominator), 'Match sub-beat offset exceeds one denominator beat')
        within = Fraction(4 * (beat - 1), denominator) + 4 * offset
        if self.pickup and index == 0:
            within -= measure.nominal_duration_q - (measure.end_q - measure.onset_q)
        q = measure.onset_q + within
        _require(measure.onset_q <= q <= measure.end_q, 'Match position outside actual measure')
        return q

    def beats(self, q):
        _require(self.measures[0].onset_q <= q <= self.measures[-1].end_q,
                 'Match duration outside symbolic score')
        if q == self.measures[-1].end_q:
            return self.final_beats
        for measure, start in zip(self.measures, self.starts):
            if measure.onset_q <= q < measure.end_q:
                return start + (q - measure.onset_q) * measure.time_signature[1] / 4
        raise ValueError('unrepresented symbolic score position')


def parse_piano_match(raw_match: bytes, parsed_score: ParsedScore) -> MatchAudit:
    """Return non-grace, structurally supported original piano note anchors.

    Exact attack q/pitch/tie-collapsed duration is checked against MusicXML,
    including the complete multiset of matched and deleted symbolic rows.
    Generated Match IDs are not treated as XML IDs. Repeated identical XML
    candidates are counted as identity ambiguity, although their clock position
    agrees. Grace and ornament rows remain diagnosed but never enter the ordinary
    clock, following the source-only eligibility rule fixed in the protocol.
    No residual-based filtering is performed.
    """
    _require(isinstance(raw_match, bytes) and 0 < len(raw_match) <= MAX_BYTES,
             'bounded Match bytes required')
    try:
        lines = raw_match.decode('utf-8-sig').splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError('UTF-8 Match file required') from exc
    clock = _ScoreClock(parsed_score)
    info, score_ids, performance_ids = {}, set(), set()
    records, properties = [], []
    counts = Counter(lines=len(lines), matched_notes=0, deleted_score_notes=0, inserted_notes=0,
                     virtual_pairs=0, pedal_events=0, grace_matched_notes=0,
                     zero_duration_matched_notes=0, zero_duration_inserted_notes=0,
                     source_position_errors=0, source_beat_coordinate_errors=0,
                     score_attack_disagreements=0, matched_pitch_disagreements=0,
                     non_unique_xml_identity_matches=0, voice_staff_disagreements=0,
                     supported_matched_notes=0, supported_non_grace_notes=0,
                     matched_ornament_notes=0, excluded_grace=0, excluded_ornament=0,
                     excluded_unverified=0, verified_deleted_score_notes=0)
    diagnostics_examples = []
    for line_number, line in enumerate(lines, 1):
        _require(line.endswith('.'), f'Match line {line_number}: missing terminator')
        if line.startswith('info(') and line.endswith(').'):
            fields = _fields(line[5:-2])
            _require(len(fields) == 2 and fields[0] not in info, 'duplicate/malformed Match info')
            info[fields[0]] = fields[1]
        elif line.startswith('scoreprop(') and line.endswith(').'):
            fields = _fields(line[10:-2])
            _require(len(fields) == 5 and fields[0] in ('keySignature', 'timeSignature'),
                     'unsupported Match score property')
            properties.append(fields)
        elif line.startswith('snote('):
            _require(')-' in line, 'malformed Match alignment row')
            symbolic, performed = line[6:].split(')-', 1)
            note = _score_note(symbolic)
            _require(note['id'] not in score_ids, 'duplicate Match score identifier')
            score_ids.add(note['id'])
            if performed == 'deletion.':
                counts['deleted_score_notes'] += 1
                performance = None
            else:
                _require(performed.startswith('note(') and performed.endswith(').'),
                         'unsupported Match note relation')
                performance = _performance_note(performed[5:-2])
                _require(performance[0] not in performance_ids, 'duplicate performed-note identifier')
                performance_ids.add(performance[0])
                counts['matched_notes'] += 1
                counts['grace_matched_notes'] += int(note['grace'])
                counts['zero_duration_matched_notes'] += int(performance[2] == performance[3])
            records.append((line_number, note, performance))
        elif line.startswith('insertion-note(') and line.endswith(').'):
            performance = _performance_note(line[len('insertion-note('):-2])
            _require(performance[0] not in performance_ids, 'duplicate performed-note identifier')
            performance_ids.add(performance[0])
            counts['inserted_notes'] += 1
            counts['zero_duration_inserted_notes'] += int(performance[2] == performance[3])
        elif re.fullmatch(r'virtualSnote\([A-Za-z0-9_.-]+,\[\]\)-virtualPnote\([A-Za-z0-9_.-]+,\)\.', line):
            # Explicitly unsupported performance/score content, never a clock anchor.
            counts['virtual_pairs'] += 1
        elif line.startswith(('sustain(', 'soft(')) and line.endswith(').'):
            fields = _fields(line[line.index('(') + 1:-2])
            _require(len(fields) == 2, 'unsupported Match pedal row')
            _int(fields[0], 0)
            _int(fields[1], 0, 127)
            counts['pedal_events'] += 1
        else:
            raise ValueError(f'unsupported Match line class at {line_number}')
    _require(info.get('matchFileVersion') == '1.1.0', 'only observed Match version 1.1.0 is admitted')
    _require('midiClockUnits' in info and 'midiClockRate' in info, 'missing performance tick clock')
    ppq = _int(info['midiClockUnits'], 1, 1_000_000)
    microseconds_per_quarter = _int(info['midiClockRate'], 1, 1_000_000_000)
    seconds_per_tick = Fraction(microseconds_per_quarter, ppq * 1_000_000)

    for fields in properties:
        measure, beat = _position(fields[2])
        q = clock.position(measure, beat, _fraction(fields[3], True))
        _require(abs(clock.beats(q) - _decimal(fields[4])) <= BEAT_ROUNDING_BOUND,
                 'Match score property beat coordinate disagrees with XML')
        if fields[0] == 'timeSignature':
            pair = fields[1].split('/')
            _require(len(pair) == 2, 'invalid Match time signature')
            meter = tuple(_int(v, 1) for v in pair)
            index = measure if clock.pickup else measure - 1
            _require(meter == clock.measures[index].time_signature,
                     'Match time signature disagrees with XML')

    attacks = defaultdict(list)
    for event in parsed_score.attacks:
        attacks[(event.onset_q, event.end_q, event.midi, event.grace)].append(event)
    score_inventory = Counter({key: len(events) for key, events in attacks.items()})
    match_inventory = Counter()
    anchors = []
    for line_number, note, performance in records:
        q = end = None
        failures = []
        candidates = []
        try:
            q = clock.position(note['measure'], note['beat'], note['offset'])
            end = q + 4 * note['duration']
            onset_beats, offset_beats = clock.beats(q), clock.beats(end)
        except ValueError:
            counts['source_position_errors'] += 1
            failures.append('score_position')
        if q is not None and not failures:
            match_inventory[(q, end, note['pitch'], note['grace'])] += 1
            if (abs(onset_beats - note['onset_beats']) > BEAT_ROUNDING_BOUND
                    or abs(offset_beats - note['offset_beats']) > BEAT_ROUNDING_BOUND):
                counts['source_beat_coordinate_errors'] += 1
                failures.append('redundant_beat_coordinate')
            candidates = attacks.get((q, end, note['pitch'], note['grace']), [])
            if not candidates:
                counts['score_attack_disagreements'] += 1
                failures.append('xml_attack')
            elif len(candidates) > 1:
                counts['non_unique_xml_identity_matches'] += 1
            if candidates:
                voice = [item[1:] for item in note['attributes'] if re.fullmatch(r'v\d+', item)]
                staff = [item[5:] for item in note['attributes'] if re.fullmatch(r'staff\d+', item)]
                if not any((not voice or str(event.voice) in voice) and
                           (not staff or str(event.staff) in staff) for event in candidates):
                    counts['voice_staff_disagreements'] += 1
                    failures.append('xml_voice_staff')
        if performance is not None and note['pitch'] != performance[1]:
            counts['matched_pitch_disagreements'] += 1
            failures.append('score_performance_pitch')
        ornament = (bool(set(note['attributes']) & ORNAMENT_ATTRIBUTES)
                    or any(event.ornaments for event in candidates))
        if performance is not None:
            counts['matched_ornament_notes'] += int(ornament)
            if note['grace']:
                counts['excluded_grace'] += 1
            elif ornament:
                counts['excluded_ornament'] += 1
        if failures:
            diagnostics_examples.append({'line': line_number, 'score_id': note['id'], 'reasons': failures})
            if performance is not None and not note['grace'] and not ornament:
                counts['excluded_unverified'] += 1
            continue
        if performance is None:
            counts['verified_deleted_score_notes'] += 1
            continue
        counts['supported_matched_notes'] += 1
        if note['grace']:
            continue
        counts['supported_non_grace_notes'] += 1
        if ornament:
            continue
        anchors.append(MatchAnchor(q, float(performance[2] * seconds_per_tick), end, note['pitch'],
                                   note['id'], performance[0], tuple(event.id for event in candidates),
                                   note['attributes'], line_number))
    counts['xml_attack_count'] = len(parsed_score.attacks)
    counts['symbolic_note_rows'] = len(records)
    counts['missing_xml_attack_rows'] = sum((score_inventory - match_inventory).values())
    counts['excess_match_score_rows'] = sum((match_inventory - score_inventory).values())
    strict = (parsed_score.admissible_for_alignment and
              not any(counts[key] for key in ('source_position_errors', 'source_beat_coordinate_errors',
                                             'score_attack_disagreements', 'matched_pitch_disagreements',
                                             'voice_staff_disagreements', 'missing_xml_attack_rows',
                                             'excess_match_score_rows')))
    return MatchAudit(tuple(anchors), strict, {
        **dict(counts), 'strict_score_consistency': strict,
        'xml_unsupported_count': len(parsed_score.unsupported),
        'xml_unsupported_sha256': hashlib.sha256(
            json.dumps(parsed_score.unsupported, separators=(',', ':')).encode()).hexdigest(),
        'match_sha256': hashlib.sha256(raw_match).hexdigest(), 'match_version': info['matchFileVersion'],
        'midi_clock_units': ppq, 'midi_clock_rate': microseconds_per_quarter,
        'seconds_per_tick': str(seconds_per_tick), 'pickup_measure_zero': clock.pickup,
        'grace_clock_anchors_excluded': counts['grace_matched_notes'],
        'anchor_notes': len(anchors), 'anchor_positions': len({anchor.q for anchor in anchors}),
        'contradictory_score_rows': len(diagnostics_examples),
        'contradictory_rows_sha256': hashlib.sha256(
            json.dumps(diagnostics_examples, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
        'clock_fitted': False, 'isotonic_repair': False, 'extrapolation': False,
        'interpretation': 'original piano-alignment source consistency; no acoustic truth verification',
    })

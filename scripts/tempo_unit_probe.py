"""Research: pulse rate is not necessarily quarter-notes/minute. No model editing."""
from __future__ import annotations

import io
import math
import statistics
import xml.etree.ElementTree as ET
from fractions import Fraction

UNITS = (0.5, 1.0, 2.0)
UNIT_NAMES = {0.5: 'eighth', 1.0: 'quarter', 2.0: 'half'}
TOLERANCE = .04
DIVISIONS = 96


def positive(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError('finite positive number required')
    return float(value)


def hypotheses(pulse_bpm):
    """No reference, file name, meter or downbeat enters this candidate generator."""
    rate = positive(pulse_bpm)
    return [{'pulse_bpm': rate, 'quarter_per_pulse': u, 'beat_unit': UNIT_NAMES[u],
             'quarter_bpm': rate * u, 'automatically_selected': False} for u in UNITS]


def evaluate_rate(pulse_bpm, reference_qpm):
    """REFERENCE-ASSISTED evaluation only; never an automatic unit selector."""
    truth = positive(reference_qpm)
    if pulse_bpm is None:
        return {'available': False, 'strict': False, 'family': False,
                'reference_assisted_unit': None}
    candidates = hypotheses(pulse_bpm)
    best = min(candidates, key=lambda c: abs(c['quarter_bpm'] / truth - 1))
    error = abs(best['quarter_bpm'] / truth - 1)
    return {'available': True, 'strict': abs(pulse_bpm / truth - 1) <= TOLERANCE,
            'family': error <= TOLERANCE,
            'reference_assisted_unit': best['quarter_per_pulse'] if error <= TOLERANCE else None,
            'best_family_relative_error': error, 'automatic_unit_selection': False}


def validate_beats(beats):
    values = tuple(float(v) for v in beats)
    if len(values) < 4 or any(not math.isfinite(v) or v < 0 for v in values):
        raise ValueError('at least four finite nonnegative beat times required')
    if any(b <= a for a, b in zip(values, values[1:])):
        raise ValueError('strictly ordered beats required')
    return values


def sequence_diagnostics(beats, reference_qpm):
    """First predicted pulse anchors RELATIVE timing; no score/bar phase inferred."""
    values = validate_beats(beats)
    intervals = [b - a for a, b in zip(values, values[1:])]
    pulse_bpm = 60 / statistics.median(intervals)
    result = evaluate_rate(pulse_bpm, reference_qpm)
    answer = {'pulse_bpm': pulse_bpm, 'beat_count': len(values),
              'interval_count': len(intervals), 'rate_evaluation': result,
              'reference_assisted': True, 'bar_phase_evaluated': False}
    if not result['family']:
        answer['timeline'] = None
        return answer
    unit = result['reference_assisted_unit']
    period = 60 * unit / reference_qpm
    residual = [(t - values[0]) - index * period for index, t in enumerate(values)]
    errors = sorted(abs(x) for x in residual)
    answer['timeline'] = {
        'quarter_per_pulse': unit, 'expected_interval_seconds': period,
        'intervals_within_4pct': sum(abs(dt / period - 1) <= .04 for dt in intervals),
        'intervals_within_10pct': sum(abs(dt / period - 1) <= .10 for dt in intervals),
        'intervals_within_10pct_fraction': sum(
            abs(dt / period - 1) <= .10 for dt in intervals) / len(intervals),
        'intervals_over_1_5_expected': sum(dt > 1.5 * period for dt in intervals),
        'intervals_under_0_67_expected': sum(dt < .67 * period for dt in intervals),
        'max_relative_drift_seconds': max(errors),
        'p95_relative_drift_seconds': errors[math.ceil(.95 * len(errors)) - 1],
        'last_relative_drift_seconds': residual[-1],
        'quarter_coordinate_span': (len(values) - 1) * unit,
        'not_a_calibrated_confidence_or_approval': True,
    }
    return answer


def template_scores():
    # Sequential monophonic written notes, not inferred from any benchmark song.
    definitions = (
        ('four_four_rearticulation', 4, 0,
         [(60, 1), (62, .5), (62, .5), (64, 2), (None, .5), (64, .5), (64, 1), (67, 2)]),
        ('three_four_dotted', 3, 0,
         [(60, 1.5), (None, .5), (64, 1), (65, 1), (67, 1), (65, 1)]),
        ('pickup_one_quarter', 4, 1,
         [(60, .5), (62, .5), (64, 1), (65, 1), (67, 2), (None, 1), (67, 1), (65, 2)]),
        ('tie_across_bar', 4, 0, [(None, 1), (60, 2), (64, 2), (67, 3)]),
    )
    answer = []
    for name, numerator, pickup, source in definitions:
        position = Fraction(0)
        events = []
        for pitch, duration in source:
            duration = Fraction(str(duration))
            events.append({'pitch': pitch, 'onset_q': position, 'duration_q': duration})
            position += duration
        answer.append({'name': name, 'numerator': numerator, 'denominator': 4,
                       'pickup_q': Fraction(pickup), 'events': events, 'total_q': position})
    return answer


def encode_musicxml(score, pulse_bpm, quarter_per_pulse):
    """Tiny mono-score conversion fixture, NOT the application's notation engine."""
    if quarter_per_pulse not in UNITS:
        raise ValueError('unsupported written pulse unit')
    qpm = positive(pulse_bpm) * quarter_per_pulse
    root = ET.Element('score-partwise', version='4.0')
    partlist = ET.SubElement(root, 'part-list')
    sp = ET.SubElement(partlist, 'score-part', id='P1')
    ET.SubElement(sp, 'part-name').text = 'Authored unit fixture'
    part = ET.SubElement(root, 'part', id='P1')
    start, index, fragments = Fraction(0), 0, 0
    bar_q = Fraction(4 * score['numerator'], score['denominator'])
    sums = []
    while start < score['total_q']:
        capacity = score['pickup_q'] if index == 0 and score['pickup_q'] else bar_q
        end = min(score['total_q'], start + capacity)
        attrs = {'number': str(index if score['pickup_q'] else index + 1)}
        if index == 0 and score['pickup_q']:
            attrs['implicit'] = 'yes'
        measure = ET.SubElement(part, 'measure', **attrs)
        if index == 0:
            properties = ET.SubElement(measure, 'attributes')
            ET.SubElement(properties, 'divisions').text = str(DIVISIONS)
            signature = ET.SubElement(properties, 'time')
            ET.SubElement(signature, 'beats').text = str(score['numerator'])
            ET.SubElement(signature, 'beat-type').text = str(score['denominator'])
            direction = ET.SubElement(measure, 'direction')
            metronome = ET.SubElement(ET.SubElement(direction, 'direction-type'), 'metronome')
            ET.SubElement(metronome, 'beat-unit').text = UNIT_NAMES[quarter_per_pulse]
            ET.SubElement(metronome, 'per-minute').text = format(pulse_bpm, '.12g')
            ET.SubElement(direction, 'sound', tempo=format(qpm, '.12g'))
        filled = Fraction(0)
        for event in score['events']:
            a, b = event['onset_q'], event['onset_q'] + event['duration_q']
            left, right = max(a, start), min(b, end)
            if right <= left:
                continue
            note = ET.SubElement(measure, 'note')
            if event['pitch'] is None:
                ET.SubElement(note, 'rest')
            else:
                pitch = ET.SubElement(note, 'pitch')
                midi = event['pitch']
                names = ('C', 'C', 'D', 'D', 'E', 'F', 'F', 'G', 'G', 'A', 'A', 'B')
                ET.SubElement(pitch, 'step').text = names[midi % 12]
                if midi % 12 in (1, 3, 6, 8, 10):
                    ET.SubElement(pitch, 'alter').text = '1'
                ET.SubElement(pitch, 'octave').text = str(midi // 12 - 1)
            duration = right - left
            ticks = duration * DIVISIONS
            if ticks.denominator != 1:
                raise ValueError('fixture duration not representable')
            ET.SubElement(note, 'duration').text = str(ticks.numerator)
            ties = [] if event['pitch'] is None else (
                (['stop'] if left > a else []) + (['start'] if right < b else []))
            for tie in ties:
                ET.SubElement(note, 'tie', type=tie)
            ET.SubElement(note, 'voice').text = '1'
            spellings = {Fraction(1, 2): ('eighth', False), Fraction(1): ('quarter', False),
                         Fraction(3, 2): ('quarter', True), Fraction(2): ('half', False),
                         Fraction(3): ('half', True), Fraction(4): ('whole', False)}
            if duration in spellings:
                typename, dot = spellings[duration]
                ET.SubElement(note, 'type').text = typename
                if dot:
                    ET.SubElement(note, 'dot')
            if ties:
                notations = ET.SubElement(note, 'notations')
                for tie in ties:
                    ET.SubElement(notations, 'tied', type=tie)
            filled += duration
            fragments += 1
        if filled != end - start:
            raise ValueError('fixture bar occupancy mismatch')
        sums.append(float(filled))
        start, index = end, index + 1
    return ET.tostring(root, encoding='utf-8', xml_declaration=True), sums, fragments


def decode_musicxml(raw):
    """Read only the supported generated monophonic subset; merge explicit ties."""
    root = ET.fromstring(raw)
    part = root.find('part')
    divisions = int(part.findtext('measure/attributes/divisions'))
    sound_qpm = float(part.find('measure/direction/sound').get('tempo'))
    metronome = part.find('measure/direction/direction-type/metronome')
    unit = {v: k for k, v in UNIT_NAMES.items()}[metronome.findtext('beat-unit')]
    if not math.isclose(unit * float(metronome.findtext('per-minute')), sound_qpm,
                        abs_tol=1e-8):
        raise ValueError('display and playback tempo disagree')
    position, active, events = Fraction(0), None, []
    for note in part.findall('measure/note'):
        duration = Fraction(int(note.findtext('duration')), divisions)
        if note.find('rest') is not None:
            if active:
                raise ValueError('rest interrupts tie')
            pitch = None
        else:
            pc = dict(C=0, D=2, E=4, F=5, G=7, A=9, B=11)[note.findtext('pitch/step')]
            pitch = 12 * (int(note.findtext('pitch/octave')) + 1) + pc
            pitch += int(note.findtext('pitch/alter', '0'))
        ties = {v.get('type') for v in note.findall('tie')}
        if 'stop' in ties:
            if active is None or active['pitch'] != pitch:
                raise ValueError('invalid tie stop')
            active['duration_q'] += duration
        else:
            if active is not None:
                raise ValueError('unclosed tie')
            active = {'pitch': pitch, 'onset_q': position, 'duration_q': duration}
        if 'start' not in ties:
            events.append(active)
            active = None
        position += duration
    if active:
        raise ValueError('trailing tie')
    return events, sound_qpm, position


def midi_roundtrip(events, total_q, qpm):
    """Independent tick/tempo serialization, including repeated same pitches."""
    import mido

    file = mido.MidiFile(ticks_per_beat=960)
    track = mido.MidiTrack()
    file.tracks.append(track)
    track.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(qpm)))
    scheduled = []
    for event in events:
        if event['pitch'] is None:
            continue
        start = int(event['onset_q'] * 960)
        end = int((event['onset_q'] + event['duration_q']) * 960)
        scheduled.extend([(start, 1, event['pitch']), (end, 0, event['pitch'])])
    previous = 0
    for tick, on, pitch in sorted(scheduled):
        track.append(mido.Message('note_on' if on else 'note_off', note=pitch,
                                  velocity=90 if on else 0, time=tick - previous))
        previous = tick
    track.append(mido.MetaMessage('end_of_track', time=int(total_q * 960) - previous))
    buffer = io.BytesIO()
    file.save(file=buffer)
    active, result, elapsed = {}, [], 0.0
    for message in mido.MidiFile(file=io.BytesIO(buffer.getvalue())):
        elapsed += message.time
        if message.type == 'note_on' and message.velocity:
            if message.note in active:
                raise ValueError('overlapping repeated pitch')
            active[message.note] = elapsed
        elif message.type == 'note_off' or (message.type == 'note_on' and not message.velocity):
            result.append((message.note, active.pop(message.note), elapsed))
    if active:
        raise ValueError('unclosed MIDI note')
    return sorted(result, key=lambda v: v[1]), elapsed


def fixture_trials():
    results = []
    for score in template_scores():
        for qpm in (75., 120., 184.):
            for unit in UNITS:
                pulse_bpm = qpm / unit
                # Authored event pulse coordinates supplied; no audio/score inference claim.
                restored = []
                for event in score['events']:
                    pulse_start = event['onset_q'] / Fraction(str(unit))
                    pulse_duration = event['duration_q'] / Fraction(str(unit))
                    restored.append({'pitch': event['pitch'],
                                     'onset_q': pulse_start * Fraction(str(unit)),
                                     'duration_q': pulse_duration * Fraction(str(unit))})
                score_copy = {**score, 'events': restored}
                raw, sums, fragments = encode_musicxml(score_copy, pulse_bpm, unit)
                recovered, playback, total = decode_musicxml(raw)
                midi_events, elapsed = midi_roundtrip(recovered, total, playback)
                expected = [(e['pitch'], float(e['onset_q']) * 60 / qpm,
                             float(e['onset_q'] + e['duration_q']) * 60 / qpm)
                            for e in score['events'] if e['pitch'] is not None]
                errors = [abs(a - b) for left, right in zip(midi_events, expected)
                          for a, b in zip(left[1:], right[1:])]
                total_error = abs(elapsed - float(score['total_q']) * 60 / qpm)
                if (recovered != score['events'] or len(midi_events) != len(expected)
                        or [e[0] for e in midi_events] != [e[0] for e in expected]):
                    raise ValueError('event identity/count changed')
                results.append({'id': f"{score['name']}/{qpm}/{unit}",
                                'pulse_bpm': pulse_bpm, 'quarter_per_pulse': unit,
                                'sound_tempo_qpm': playback, 'bar_sums_q': sums,
                                'pickup_q': float(score['pickup_q']), 'xml_fragments': fragments,
                                'performed_events': len(expected), 'max_time_error_s': max(errors),
                                'total_time_error_s': total_error,
                                'passed': max(errors + [total_error]) < 1e-5,
                                'unit_omission_duration_ratio': unit,
                                'unit_omission_control_correct': unit == 1.0,
                                'authored_score_and_unit_provided': True})
    return results

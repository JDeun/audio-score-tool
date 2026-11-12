"""Exact written-score structure for KRAISLER alignment admission.

This parser does not infer performance timing. ``duration / divisions`` is the
score duration in quarter notes; note type/dots and the tuplet multiplier are
retained separately. A short first measure is never padded. Events preserve XML
order and include grace notes; attacks are tie-collapsed in stable score order.
Tie collapse prefers the same voice/staff. A uniquely determined contiguous
same-part/pitch parent may change voice/staff, with an explicit warning. Grace
ties and ambiguous/noncontiguous chains remain unsupported method limitations.

``global_rests`` means explicit rests minus every sounding voice/staff *within
each part*. Uncovered time is reported separately and never becomes a rest.
Consumers must check ``admissible_for_alignment`` before using these intervals.
Grace/ornament warnings additionally require local abstention by the matcher.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from dataclasses import dataclass, replace
from fractions import Fraction
from types import MappingProxyType

_ZERO = Fraction(0)
_TYPES = {name: Fraction(4, 2 ** index) for index, name in enumerate(
    ('whole', 'half', 'quarter', 'eighth', '16th', '32nd', '64th', '128th',
     '256th', '512th', '1024th'))}
_TYPES.update(maxima=Fraction(32), long=Fraction(16), breve=Fraction(8))
_PITCH = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}
_DECIMAL = re.compile(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)\Z')
_NAVIGATION = re.compile(r'\b(?:d\s*\.?\s*[cs]\s*\.?|da\s+capo|dal\s+segno|'
                         r'to\s+coda|al\s+coda|fine)\b', re.I)


@dataclass(frozen=True)
class ScoreEvent:
    id: str
    part: str
    measure_index: int
    note_index: int
    onset_q: Fraction
    end_q: Fraction
    midi: int
    voice: str
    staff: str
    source_ids: tuple[str, ...]
    articulations: tuple[str, ...]
    ornaments: tuple[str, ...]
    grace: bool
    chord: bool
    tie_start: bool
    tie_stop: bool
    written_duration_q: Fraction | None
    tuplet_ratio: Fraction | None

    @property
    def duration_q(self) -> Fraction:
        return self.end_q - self.onset_q


@dataclass(frozen=True)
class ScoreRest:
    id: str
    part: str
    measure_index: int
    note_index: int
    onset_q: Fraction
    end_q: Fraction
    voice: str
    staff: str
    source_ids: tuple[str, ...]
    measure_rest: bool

    @property
    def duration_q(self) -> Fraction:
        return self.end_q - self.onset_q


@dataclass(frozen=True)
class ScoreMeasure:
    part: str
    index: int
    number: str
    onset_q: Fraction
    end_q: Fraction
    time_signature: tuple[int, int] | None
    nominal_duration_q: Fraction | None
    pickup: bool
    short_final: bool
    implicit: bool

    @property
    def duration_q(self) -> Fraction:
        return self.end_q - self.onset_q


@dataclass(frozen=True)
class ScoreInterval:
    part: str
    onset_q: Fraction
    end_q: Fraction

    @property
    def duration_q(self) -> Fraction:
        return self.end_q - self.onset_q


@dataclass(frozen=True)
class ParsedScore:
    events: tuple[ScoreEvent, ...]
    attacks: tuple[ScoreEvent, ...]
    rests: tuple[ScoreRest, ...]
    measures: tuple[ScoreMeasure, ...]
    global_rests: tuple[ScoreInterval, ...]
    unknown_intervals: tuple[ScoreInterval, ...]
    warnings: tuple[str, ...]
    unsupported: tuple[str, ...]
    counts: Mapping[str, int]

    @property
    def admissible_for_alignment(self) -> bool:
        return not self.unsupported

    @property
    def duration_q(self) -> Fraction:
        return max((m.end_q for m in self.measures), default=_ZERO)


def _number(text: str | None, context: str, *, positive: bool = False) -> Fraction:
    text = (text or '').strip()
    if len(text) > 64 or not _DECIMAL.fullmatch(text):
        raise ValueError(f'{context}: finite decimal number required')
    value = Fraction(text)
    if positive and value <= 0:
        raise ValueError(f'{context}: positive number required')
    return value


def _integer(text: str | None, context: str, *, positive: bool = False) -> int:
    value = _number(text, context, positive=positive)
    if value.denominator != 1:
        raise ValueError(f'{context}: integral value required')
    return int(value)


def _single(parent: ET.Element, name: str, context: str) -> ET.Element | None:
    children = parent.findall(name)
    if len(children) > 1:
        raise ValueError(f'{context}: duplicate {name}')
    return children[0] if children else None


def _token(note: ET.Element, name: str, context: str) -> str:
    child = _single(note, name, context)
    value = '1' if child is None else (child.text or '').strip()
    if not value or len(value) > 64:
        raise ValueError(f'{context}: invalid {name}')
    return value


def _meter(element: ET.Element, context: str, unsupported: list[str]):
    beats, denominators = element.findall('beats'), element.findall('beat-type')
    if len(beats) != 1 or len(denominators) != 1:
        unsupported.append(f'{context}: unsupported composite or unmeasured meter')
        return None
    text = (beats[0].text or '').strip()
    pieces = text.split('+')
    numerator = sum(_integer(p, context + ' beats', positive=True) for p in pieces)
    denominator = _integer(denominators[0].text, context + ' beat-type', positive=True)
    if len(pieces) != 1 or denominator & (denominator - 1):
        unsupported.append(f'{context}: unsupported additive or irrational meter')
    return numerator, denominator


def _notations(note: ET.Element, context: str, unsupported: list[str]):
    sound = {e.get('type') for e in note.findall('tie')}
    written = {e.get('type') for e in note.findall('notations/tied')}
    if (sound | written) - {'start', 'stop'}:
        unsupported.append(f'{context}: unsupported tie type')
    if sound and written and sound != written:
        unsupported.append(f'{context}: sound and written ties disagree')
    ties = sound or written
    articulations = tuple(e.tag for p in note.findall('notations/articulations') for e in p)
    ornaments = tuple(e.tag for p in note.findall('notations/ornaments') for e in p)
    if note.find('notations/arpeggiate') is not None:
        # A rolled chord is not a set of simultaneous literal attacks.
        ornaments += ('arpeggiate',)
    return 'start' in ties, 'stop' in ties, articulations, ornaments


def _notation_duration(note: ET.Element, context: str, unsupported: list[str]):
    kind = _single(note, 'type', context)
    written = None
    if kind is not None:
        base = _TYPES.get((kind.text or '').strip())
        if base is None:
            unsupported.append(f'{context}: unsupported written note type')
        else:
            written = base * sum((Fraction(1, 2 ** i)
                                  for i in range(len(note.findall('dot')) + 1)), _ZERO)
    ratio = None
    tuplet = _single(note, 'time-modification', context)
    if tuplet is not None:
        actual = _integer(tuplet.findtext('actual-notes'), context + ' actual-notes', positive=True)
        normal = _integer(tuplet.findtext('normal-notes'), context + ' normal-notes', positive=True)
        ratio = Fraction(normal, actual)
    return written, ratio


def _pitch(note: ET.Element, context: str) -> int:
    pitch = note.find('pitch')
    step = pitch.findtext('step')
    if step not in _PITCH:
        raise ValueError(f'{context}: invalid pitch step')
    octave = _integer(pitch.findtext('octave'), context + ' octave')
    alter = _integer(pitch.findtext('alter', '0'), context + ' alter')
    midi = 12 * (octave + 1) + _PITCH[step] + alter
    if not 0 <= midi <= 127:
        raise ValueError(f'{context}: MIDI pitch outside 0..127')
    return midi


def _union(intervals):
    result = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if result and start <= result[-1][1]:
            result[-1] = (result[-1][0], max(result[-1][1], end))
        else:
            result.append((start, end))
    return result


def _subtract(intervals, occupied):
    result, occupied = [], _union(occupied)
    for start, end in _union(intervals):
        cursor = start
        for left, right in occupied:
            if right <= cursor:
                continue
            if left >= end:
                break
            if left > cursor:
                result.append((cursor, min(left, end)))
            cursor = max(cursor, right)
            if cursor >= end:
                break
        if cursor < end:
            result.append((cursor, end))
    return result


def _collapse_ties(events: list[ScoreEvent], unsupported: list[str],
                   warnings: list[str]) -> tuple[ScoreEvent, ...]:
    attacks, active = [], {}
    part_order = {part: i for i, part in enumerate(dict.fromkeys(e.part for e in events))}
    ordered = sorted(enumerate(events), key=lambda p: (part_order[p[1].part], p[1].onset_q, p[0]))
    for _, event in ordered:
        key = (event.part, event.voice, event.staff, event.midi)
        if event.grace:
            if event.tie_start or event.tie_stop:
                unsupported.append(f'{event.id}: grace tie has no score duration')
            attacks.append(event)
            continue
        parent_key, previous = key, active.get(key)
        joined = False
        if event.tie_stop:
            if previous is None:
                candidates = [candidate for candidate, index in active.items()
                              if candidate[0] == event.part and candidate[3] == event.midi
                              and attacks[index].end_q == event.onset_q]
                if len(candidates) == 1:
                    parent_key = candidates[0]
                    previous = active[parent_key]
                    warnings.append(f'{event.id}: cross_voice_or_staff_tie')
                else:
                    reason = 'ambiguous cross-voice/staff tie' if candidates else 'orphan tie stop'
                    unsupported.append(f'{event.id}: {reason}')
            if previous is not None and attacks[previous].end_q != event.onset_q:
                unsupported.append(f'{event.id}: noncontiguous tie')
                active.pop(parent_key)
            elif previous is not None:
                first = attacks[previous]
                written = (first.written_duration_q + event.written_duration_q
                           if first.written_duration_q is not None
                           and event.written_duration_q is not None else None)
                attacks[previous] = replace(
                    first, end_q=event.end_q, source_ids=first.source_ids + event.source_ids,
                    articulations=tuple(dict.fromkeys(first.articulations + event.articulations)),
                    ornaments=tuple(dict.fromkeys(first.ornaments + event.ornaments)),
                    tie_stop=True, written_duration_q=written,
                    tuplet_ratio=first.tuplet_ratio if first.tuplet_ratio == event.tuplet_ratio else None)
                joined = True
                active.pop(parent_key)
        elif previous is not None:
            unsupported.append(f'{event.id}: interrupted or ambiguous tie')
            active.pop(key)
        if not joined:
            attacks.append(event)
        if event.tie_start:
            active[key] = previous if joined else len(attacks) - 1
    for index in active.values():
        unsupported.append(f'{attacks[index].id}: open tie at end of part')
    return tuple(attacks)


def _parse_part(part, events, rests, measures, occupied, warnings, unsupported):
    part_id, position, divisions, meter = part.get('id'), _ZERO, None, None
    xml_measures = part.findall('measure')
    if not xml_measures:
        raise ValueError(f'{part_id}: no measures')
    note_count, nonpitch_count, compressed_rests = 0, 0, []
    for index, measure in enumerate(xml_measures):
        context = f'{part_id}/m{index:04d}'
        cursor, extent, anchor, ordinal = _ZERO, _ZERO, None, 0
        measure_meter = meter
        if measure.get('non-controlling') == 'yes':
            unsupported.append(f'{context}: non-controlling measure')
        for child in measure:
            if child.tag == 'attributes':
                value = _single(child, 'divisions', context)
                if value is not None:
                    divisions = _number(value.text, context + ' divisions', positive=True)
                times = child.findall('time')
                if len(times) > 1 or any(t.get('number') is not None for t in times):
                    unsupported.append(f'{context}: staff-specific or multiple meters')
                if times:
                    meter = _meter(times[0], context, unsupported)
                    if extent > 0:
                        unsupported.append(f'{context}: mid-measure time-signature change')
                    else:
                        measure_meter = meter
                for style in child.findall('measure-style'):
                    multiple = style.find('multiple-rest')
                    if multiple is not None:
                        count = _integer(multiple.text, context + ' multiple-rest', positive=True)
                        compressed_rests.append((index, count, style.get('number')))
            elif child.tag in ('backup', 'forward'):
                if divisions is None:
                    raise ValueError(f'{context}: duration before divisions')
                duration = _number(child.findtext('duration'), context + ' cursor duration',
                                   positive=True) / divisions
                cursor += duration if child.tag == 'forward' else -duration
                if cursor < 0:
                    raise ValueError(f'{context}: backup precedes measure start')
                extent, anchor = max(extent, cursor), None
            elif child.tag == 'note':
                identity = f'{context}/n{ordinal:04d}'
                ordinal += 1
                note_count += 1
                voice, staff = _token(child, 'voice', identity), _token(child, 'staff', identity)
                kinds = [e for e in child if e.tag in ('pitch', 'rest', 'unpitched')]
                if len(kinds) != 1:
                    raise ValueError(f'{identity}: exactly one pitch, rest, or unpitched required')
                kind = kinds[0].tag
                grace = _single(child, 'grace', identity) is not None
                chord = _single(child, 'chord', identity) is not None
                raw_duration = _single(child, 'duration', identity)
                if grace:
                    if raw_duration is not None or kind == 'rest':
                        raise ValueError(f'{identity}: grace requires pitch and no duration')
                    duration = _ZERO
                else:
                    if divisions is None:
                        raise ValueError(f'{identity}: duration before divisions')
                    duration = _number(None if raw_duration is None else raw_duration.text,
                                       identity + ' duration', positive=True) / divisions
                if chord:
                    if (anchor is None or kind == 'rest' or anchor[4] == 'rest'
                            or voice != anchor[2] or grace != anchor[3]):
                        raise ValueError(f'{identity}: chord lacks a compatible preceding note')
                    onset = anchor[0]
                    if duration > anchor[1]:
                        unsupported.append(f'{identity}: chord duration exceeds its leading note')
                else:
                    onset = cursor
                    cursor += duration
                    anchor = (onset, duration, voice, grace, kind)
                end = onset + duration
                extent = max(extent, cursor, end)
                tie_start, tie_stop, articulations, ornaments = _notations(child, identity, unsupported)
                written, ratio = _notation_duration(child, identity, unsupported)
                measure_rest = kind == 'rest' and kinds[0].get('measure') == 'yes'
                if (not grace and not measure_rest and written is not None
                        and duration != written * (ratio if ratio is not None else 1)):
                    diagnostic = f'{identity}: duration and written type/tuplet disagree'
                    (warnings if 'tremolo' in ornaments else unsupported).append(diagnostic)
                if child.find('cue') is not None:
                    unsupported.append(f'{identity}: cue note may not sound')
                if kind == 'rest':
                    if tie_start or tie_stop:
                        raise ValueError(f'{identity}: rest cannot carry ties')
                    rests.append(ScoreRest(identity, part_id, index, ordinal - 1,
                                           position + onset, position + end, voice, staff,
                                           (identity,), measure_rest))
                else:
                    occupied.append((part_id, position + onset, position + end))
                    if kind == 'unpitched':
                        nonpitch_count += 1
                        unsupported.append(f'{identity}: unpitched note')
                        continue
                    events.append(ScoreEvent(
                        identity, part_id, index, ordinal - 1, position + onset, position + end,
                        _pitch(child, identity), voice, staff, (identity,), articulations, ornaments,
                        grace, chord, tie_start, tie_stop, written, ratio))
        nominal = Fraction(4 * measure_meter[0], measure_meter[1]) if measure_meter else None
        short = nominal is not None and extent < nominal
        pickup, short_final = short and index == 0, short and index == len(xml_measures) - 1
        if nominal is None:
            unsupported.append(f'{context}: no supported time signature')
        elif extent > nominal or (short and not (pickup or short_final)) or extent == 0:
            unsupported.append(f'{context}: overfull, empty, or internal underfull measure')
        measures.append(ScoreMeasure(part_id, index, measure.get('number', ''), position,
                                     position + extent, measure_meter, nominal, pickup,
                                     short_final, measure.get('implicit') == 'yes'))
        position += extent
    # Multiple-rest is a display compression, not extra duration. Require every
    # covered bar to exist and contain explicit full-bar rest coverage.
    part_measures = [m for m in measures if m.part == part_id]
    for start, count, staff in compressed_rests:
        region = part_measures[start:start + count]
        selected_rests = [(r.onset_q, r.end_q) for r in rests
                          if r.part == part_id and (staff is None or r.staff == staff)]
        if len(region) != count or any(
                _subtract([(m.onset_q, m.end_q)], selected_rests) for m in region):
            unsupported.append(f'{part_id}/m{start:04d}: incomplete multiple-rest coverage')
        if any(e.part == part_id and start <= e.measure_index < start + count
               and (staff is None or e.staff == staff) and not e.grace for e in events):
            unsupported.append(f'{part_id}/m{start:04d}: pitched note inside multiple-rest')
    return note_count, nonpitch_count


def parse_score(raw: bytes) -> ParsedScore:
    """Parse bounded UTF-8 partwise XML; reject malformed timing, flag ambiguity.

    All IDs are generated from part ID and zero-based measure/note ordinals,
    including rests in note numbering. Repeated display measure numbers and
    absent source note IDs therefore cannot merge identities. Unsupported
    navigation, open/orphan ties, or incomplete bars are admission failures, not
    repaired timing. Tuplet and grace performance timing is never fabricated.
    """
    if not isinstance(raw, bytes) or not raw or len(raw) > 4_000_000:
        raise ValueError('bounded UTF-8 MusicXML bytes required')
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise ValueError('UTF-8 MusicXML required') from exc
    if '\x00' in text or '<!ENTITY' in text.upper() or re.search(r'<!DOCTYPE[^>]*\[', text, re.I):
        raise ValueError('MusicXML entities and internal DTD subsets are forbidden')
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError('malformed MusicXML') from exc
    namespace = root.tag.split('}')[0] + '}' if root.tag.startswith('{') else ''
    for element in root.iter():
        if namespace:
            if not element.tag.startswith(namespace):
                raise ValueError('mixed MusicXML namespaces')
            element.tag = element.tag[len(namespace):]
        elif element.tag.startswith('{'):
            raise ValueError('mixed MusicXML namespaces')
    if root.tag != 'score-partwise':
        raise ValueError('partwise MusicXML required')
    parts = root.findall('part')
    part_ids = [part.get('id', '') for part in parts]
    if (not parts or len(set(part_ids)) != len(parts)
            or any(not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.:-]*', p) for p in part_ids)):
        raise ValueError('nonempty unique XML part IDs required')
    events, rests, measures, occupied, warnings, unsupported = [], [], [], [], [], []
    for element in root.iter():
        if element.tag in ('repeat', 'ending', 'segno', 'coda', 'measure-repeat',
                           'beat-repeat', 'slash', 'transpose', 'octave-shift'):
            unsupported.append(f'unsupported structural instruction: {element.tag}')
        if element.tag == 'sound' and set(element.attrib) & {
                'dacapo', 'dalsegno', 'tocoda', 'fine', 'segno', 'coda', 'forward-repeat'}:
            unsupported.append('unsupported sound navigation')
        if element.tag == 'words' and _NAVIGATION.search(''.join(element.itertext())):
            unsupported.append('unsupported navigation words')
    note_count = nonpitch_count = 0
    for part in parts:
        n, u = _parse_part(part, events, rests, measures, occupied, warnings, unsupported)
        note_count, nonpitch_count = note_count + n, nonpitch_count + u
    attacks = _collapse_ties(events, unsupported, warnings)
    global_rests, unknown = [], []
    for part_id in part_ids:
        sound = [(start, end) for p, start, end in occupied if p == part_id]
        explicit = [(r.onset_q, r.end_q) for r in rests if r.part == part_id]
        end = max(m.end_q for m in measures if m.part == part_id)
        global_rests.extend(ScoreInterval(part_id, start, stop)
                            for start, stop in _subtract(explicit, sound))
        unknown.extend(ScoreInterval(part_id, start, stop)
                       for start, stop in _subtract([(_ZERO, end)], sound + explicit))
    if any(e.grace for e in events):
        warnings.append('grace events have zero score duration; local performance correspondence unresolved')
    if any(e.ornaments for e in events):
        warnings.append('ornament events may have nonliteral attacks; local correspondence unresolved')
    if unknown:
        warnings.append('uncovered score intervals are unknown, not written rests')
    if len(parts) > 1:
        grids = [tuple((m.onset_q, m.end_q, m.time_signature)
                       for m in measures if m.part == part_id) for part_id in part_ids]
        if any(grid != grids[0] for grid in grids[1:]):
            unsupported.append('part measure grids disagree')
    counts = MappingProxyType({
        'parts': len(parts), 'measures': len(measures), 'note_elements': note_count,
        'events': len(events), 'attacks': len(attacks), 'rests': len(rests),
        'grace_events': sum(e.grace for e in events), 'chord_events': sum(e.chord for e in events),
        'tie_starts': sum(e.tie_start for e in events), 'tie_stops': sum(e.tie_stop for e in events),
        'voices': len({(e.part, e.voice) for e in (*events, *rests)}),
        'staffs': len({(e.part, e.staff) for e in (*events, *rests)}),
        'nonpitch_events': nonpitch_count, 'global_rest_intervals': len(global_rests),
        'unknown_intervals': len(unknown),
    })
    return ParsedScore(tuple(events), attacks, tuple(rests), tuple(measures), tuple(global_rests),
                       tuple(unknown), tuple(dict.fromkeys(warnings)),
                       tuple(dict.fromkeys(unsupported)), counts)

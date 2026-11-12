"""Research-only voice/rest joint decoding with explicitly supplied score topology.

No audio transcription; the caller must separate privileged context from targets.
"""
from __future__ import annotations

import argparse
import functools
import json
import math
import os
import re
import statistics
import time
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from scripts.audit_nasap_duration_source import midi_key_events
from scripts.nasap_duration_probe import (
    GATES,
    GRID,
    VOCAB,
    Observation,
    Reader,
    beat_clock,
    fingerprint,
    fit,
    interpolate,
    rows,
    sha,
    validate,
)
from scripts.nasap_keyoff_paired import (
    FrozenReader,
    TOL,
    load_targets,
    masks_for,
    match_key_releases,
    paired_counts,
)

PREVIOUS_ZIP_SHA = 'a9fd6bb76b56ac0e7dc609e3dd9562326265571820d59cbab2edcf5833f99760'
PREVIOUS_REPORT_SHA = 'ef57078bf20bff35a56e2f35cada222fe05bea3d0754785781296531111d0890'
METHODS = ('independent', 'joint_structure', 'joint_rest_cost')
INPUTS = ('csv_sustain', 'key_release')
START_RADIUS_Q = .25
START_SIGMA_Q = .10
REST_WEIGHT = .20
MAX_BLOCKS_PER_SOURCE = 64
TICKS = tuple(sorted({round(d * GRID) for d, _ in VOCAB}))


@dataclass(frozen=True)
class Group:
    ids: tuple[str, ...]
    onsets: tuple[float, ...]
    durations: tuple[float, ...]


def merged_intervals(intervals):
    result = []
    for a, b in sorted(intervals):
        if b <= a:
            raise ValueError('nonpositive interval')
        if result and a <= result[-1][1] + 1e-8:
            result[-1] = (result[-1][0], max(result[-1][1], b))
        else:
            result.append((a, b))
    return result


def complement(intervals, length):
    cursor, result = 0., []
    for a, b in merged_intervals(intervals):
        if a > cursor + 1e-8:
            result.append((cursor, a))
        cursor = max(cursor, b)
    if cursor < length - 1e-8:
        result.append((cursor, length))
    return result


def parse_score(raw):
    """Restricted MusicXML partwise parser; never resolve the external DTD.

    Fraction durations, backup/forward/chord, explicit rests, and contiguous ties.
    Repeats are NOT guessed: unfolded CSV note IDs/coordinates bind occurrences.
    """
    if len(raw) > 4_000_000 or b'<!ENTITY' in raw.upper():
        raise ValueError('unsafe or oversized XML')
    root = ET.fromstring(raw)
    if root.tag != 'score-partwise':
        raise ValueError('unsupported XML root/namespace')
    notes, measures, rests, grace, active = {}, [], [], [], {}
    for part in root.findall('part'):
        part_id = part.get('id')
        absolute = Fraction(0)
        divisions, beats, denominator = None, None, None
        for index, measure in enumerate(part.findall('measure')):
            cursor, maximum, previous_start = Fraction(0), Fraction(0), None
            meter_changed = False
            local_notes, local_rests = [], []
            for node in measure:
                if node.tag == 'attributes':
                    div = node.findtext('divisions')
                    if div is not None:
                        divisions = int(div)
                    tm = node.find('time')
                    if tm is not None:
                        pair = (tm.findtext('beats'), tm.findtext('beat-type'))
                        if not all(x is not None and x.isdigit() for x in pair):
                            raise ValueError('unsupported composite signature')
                        new = tuple(map(int, pair))
                        if cursor and beats is not None and new != (beats, denominator):
                            meter_changed = True
                        beats, denominator = new
                elif node.tag in ('backup', 'forward'):
                    if not divisions or divisions <= 0:
                        raise ValueError('missing divisions')
                    amount = Fraction(int(node.findtext('duration')), divisions)
                    cursor += amount if node.tag == 'forward' else -amount
                    if cursor < 0:
                        raise ValueError('negative XML cursor')
                    maximum = max(maximum, cursor)
                elif node.tag == 'note':
                    voice = (part_id, node.findtext('voice', '1'))
                    if node.find('grace') is not None:
                        grace.append((voice, float(absolute + cursor)))
                        continue
                    if not divisions or divisions <= 0:
                        raise ValueError('missing divisions')
                    duration = Fraction(int(node.findtext('duration')), divisions)
                    if duration <= 0:
                        raise ValueError('nonpositive note/rest')
                    chord = node.find('chord') is not None
                    if chord and previous_start is None:
                        raise ValueError('chord without preceding attack')
                    start = previous_start if chord else cursor
                    end = start + duration
                    if not chord:
                        previous_start = start
                        cursor = end
                    maximum = max(maximum, cursor, end)
                    if node.find('rest') is not None:
                        local_rests.append((voice, absolute + start, absolute + end))
                        continue
                    nid = node.get('id')
                    if not nid:
                        raise ValueError('missing XML note identity')
                    pitch = node.find('pitch')
                    if pitch is None:
                        raise ValueError('unpitched score unsupported')
                    step = dict(C=0, D=2, E=4, F=5, G=7, A=9, B=11)[pitch.findtext('step')]
                    midi = 12 * (int(pitch.findtext('octave')) + 1) + step
                    midi += int(pitch.findtext('alter', '0'))
                    ties = {n.get('type') for n in node.findall('tie')}
                    key = (voice, midi)
                    a, b = absolute + start, absolute + end
                    if 'stop' in ties:
                        if key not in active or notes[active[key]]['end'] != a:
                            raise ValueError('noncontiguous or unmatched tie')
                        first = active[key]
                        notes[first]['end'] = b
                        notes[first]['segments'] += 1
                        if 'start' not in ties:
                            del active[key]
                    else:
                        if nid in notes or key in active:
                            raise ValueError('duplicate identity or ambiguous tied pitch')
                        notes[nid] = {'id': nid, 'voice': voice, 'pitch': midi,
                                      'start': a, 'end': b, 'segments': 1}
                        if 'start' in ties:
                            active[key] = nid
                        local_notes.append(nid)
            if beats is None or denominator is None:
                raise ValueError('missing time signature')
            nominal = Fraction(4 * beats, denominator)
            actual = maximum if measure.get('implicit') == 'yes' else max(nominal, maximum)
            if actual <= 0:
                raise ValueError('empty undefined measure')
            measures.append({'part': part_id, 'index': index, 'start': absolute,
                             'end': absolute + actual, 'nominal': nominal,
                             'simple_full': (actual == nominal and denominator == 4
                                             and beats in (2, 3, 4) and not meter_changed)})
            rests.extend(local_rests)
            absolute += actual
    if active:
        raise ValueError('unclosed score tie')
    return {'notes': notes, 'measures': measures, 'rests': rests, 'grace': grace}


def base_id(value, note_ids):
    if value in note_ids:
        return value
    root = re.sub(r'-\d+$', '', value)
    return root if root in note_ids else None


def make_blocks(score, score_rows, alignment, inputs, origin):
    """Gold-context diagnostic: supplies voice, chord membership, boundaries.

    Only fully covered same-duration chord voices with explicit XML occupancy.
    Selection depends on annotation support, NOT any algorithm's predictions.
    """
    events = score['notes']
    by_occurrence = defaultdict(dict)
    obs = {n.id: n for n in inputs['csv_sustain']}
    links = defaultdict(list)
    for row in alignment:
        if row['matchtype'] == '0' and row['ppartid'] in obs:
            links[row['partid']].append(row['ppartid'])
    multiplicity = Counter(a['ppartid'] for a in alignment if a['matchtype'] == '0')
    for row in score_rows:
        bid = base_id(row['id'], events)
        if bid is None:
            continue
        event = events[bid]
        offset = float(row['onset_quarter']) - float(event['start'])
        key = (event['voice'][0], round(offset * GRID))
        if abs(offset * GRID - key[1]) > 1e-5:
            continue
        if bid in by_occurrence[key]:
            raise ValueError('duplicate unfolded occurrence')
        by_occurrence[key][bid] = row
    measures = defaultdict(list)
    for measure in score['measures']:
        measures[measure['part']].append(measure)
    attempts, accepted, seen = [], [], set()
    for (part, tick_shift), mapping in sorted(by_occurrence.items()):
        shift = tick_shift / GRID
        available = [m for m in measures[part] if m['simple_full']
                     and float(m['start']) + shift >= origin - 1e-7
                     and float(m['end']) + shift <= origin + 32 + 1e-7]
        # Fixed adjacent, non-overlapping pairs; no search for a successful block.
        for i in range(0, len(available) - 1, 2):
            left, right = available[i:i+2]
            if left['index'] + 1 != right['index'] or left['end'] != right['start']:
                continue
            if left['nominal'] != right['nominal']:
                continue
            a, b = left['start'], right['end']
            candidate_events = [e for e in events.values() if e['voice'][0] == part
                                and e['start'] < b and e['end'] > a]
            voices = sorted({e['voice'] for e in candidate_events})
            for voice in voices:
                identity = (voice, round((float(a) + shift) * GRID))
                if identity in seen:
                    continue
                seen.add(identity)
                label = f'{part}/{voice[1]}/{identity[1]}'
                attempt = {'block': label, 'status': 'not_evaluated'}
                attempts.append(attempt)
                if len(attempts) > MAX_BLOCKS_PER_SOURCE:
                    attempt['reason'] = 'predeclared_block_cap'
                    continue
                local = [e for e in candidate_events if e['voice'] == voice]
                try:
                    if len(local) < 2:
                        raise ValueError('fewer_than_two_notes')
                    if any(e['start'] < a or e['end'] > b for e in local):
                        raise ValueError('tie_or_note_crosses_block_edge')
                    if any(v == voice and float(a) <= t < float(b) for v, t in score['grace']):
                        raise ValueError('grace_notes_in_block')
                    grouped = defaultdict(list)
                    targets, local_ids = {}, set()
                    for event in local:
                        row = mapping.get(event['id'])
                        if row is None or len(links[row['id']]) != 1:
                            raise ValueError('missing_unique_performance_alignment')
                        nid = links[row['id']][0]
                        if multiplicity[nid] != 1 or nid in local_ids:
                            raise ValueError('nonbijective_note_alignment')
                        d = float(event['end'] - event['start'])
                        if (abs(float(row['duration_quarter']) - d) > TOL
                                or int(row['pitch']) != event['pitch']
                                or obs[nid].pitch != event['pitch']):
                            raise ValueError('xml_csv_note_semantics_mismatch')
                        targets[nid] = (float(event['start'] - a), d)
                        grouped[event['start']].append(nid)
                        local_ids.add(nid)
                    reference_notes = []
                    membership = []
                    for onset, ids in sorted(grouped.items()):
                        durations = {round(targets[n][1] * GRID) for n in ids}
                        if len(durations) != 1:
                            raise ValueError('unequal_duration_chord')
                        reference_notes.append((float(onset - a),
                                                float(onset - a) + targets[ids[0]][1]))
                        membership.append(tuple(sorted(ids)))
                    if any(y[0] < x[1] - 1e-7 for x, y in zip(reference_notes, reference_notes[1:])):
                        raise ValueError('overlapping_score_voice')
                    true_rests = merged_intervals([
                        (max(0., float(x-a)), min(float(b-a), float(y-a)))
                        for v, x, y in score['rests'] if v == voice and x < b and y > a])
                    coverage = sorted(reference_notes + true_rests)
                    cursor = 0.
                    for x, y in coverage:
                        if abs(x - cursor) > 1e-7:
                            raise ValueError('explicit_voice_occupancy_not_exact')
                        cursor = y
                    if abs(cursor - float(b-a)) > 1e-7:
                        raise ValueError('explicit_voice_occupancy_not_exact')
                    start_in_window = float(a) + shift - origin
                    context = {}
                    for rep, values in inputs.items():
                        lookup = {n.id: n for n in values}
                        groups = [Group(ids, tuple(lookup[n].onset - start_in_window for n in ids),
                                        tuple(lookup[n].duration for n in ids)) for ids in membership]
                        groups.sort(key=lambda g: (statistics.median(g.onsets), g.ids))
                        context[rep] = groups
                    accepted.append({'id': label, 'groups': context, 'targets': targets,
                                     'rests': true_rests, 'bar_q': float(left['nominal']),
                                     'length_q': float(b-a), 'membership': membership})
                    attempt.update(status='admitted', notes=len(targets),
                                   attack_groups=len(membership), rests=len(true_rests))
                except ValueError as exc:
                    attempt['reason'] = str(exc)
    return accepted, attempts


@functools.lru_cache(maxsize=None)
def spell_cost(ticks):
    if ticks < 0:
        return math.inf
    if ticks == 0:
        return 0.
    return min((1 + .04 * cost + spell_cost(ticks - round(d * GRID))
                for d, cost in VOCAB if round(d * GRID) <= ticks), default=math.inf)


@functools.lru_cache(maxsize=100000)
def gap_cost(start, end, bar):
    cost = 0.
    while start < end:
        stop = min(end, (start // bar + 1) * bar)
        cost += spell_cost(stop-start)
        start = stop
    return cost


def candidate_lattice(group, length, bar):
    center = statistics.median(group.onsets)
    lo = max(0, math.ceil((center - START_RADIUS_Q) * GRID - 1e-8))
    hi = min(length-1, math.floor((center + START_RADIUS_Q) * GRID + 1e-8))
    result = []
    for start in range(lo, hi+1):
        # Identical onset and note-spelling priors in ALL arms.
        simplicity = 0. if start % 12 == 0 else .15 if start % 6 == 0 else .30 if start % 4 == 0 else .50
        onset_cost = statistics.mean(((start/GRID-t)/START_SIGMA_Q)**2 for t in group.onsets)
        for duration, notation in VOCAB:
            dt = round(duration*GRID)
            end = start + dt
            if end > length or not math.isfinite(gap_cost(start, end, bar)):
                continue
            sounding = statistics.mean(min(math.log(obs/(gate*duration))**2 + penalty
                                          for gate, penalty in GATES) for obs in group.durations)
            split_count = (end-1)//bar - start//bar
            cost = onset_cost + simplicity + sounding + .04*notation + .04*split_count
            result.append((start, end, cost))
    if not result:
        raise ValueError('empty_shared_lattice')
    return result


def decode(groups, bar_q, length_q, method):
    if method not in METHODS or not groups or len({n for g in groups for n in g.ids}) != sum(len(g.ids) for g in groups):
        raise ValueError('invalid decoding input')
    if any(not g.ids or len(g.ids) != len(g.onsets) or len(g.ids) != len(g.durations)
           or any(not math.isfinite(t) for t in g.onsets)
           or any(not math.isfinite(d) or d <= 0 for d in g.durations) for g in groups):
        raise ValueError('invalid group')
    bar, length = round(bar_q*GRID), round(length_q*GRID)
    if bar <= 0 or length <= 0 or length % bar:
        raise ValueError('invalid full-measure block')
    lattices = [candidate_lattice(g, length, bar) for g in groups]
    if method == 'independent':
        path = tuple(min(c, key=lambda x: (x[2], x[0], x[1]))[:2] for c in lattices)
        total = sum(min(c, key=lambda x: (x[2], x[0], x[1]))[2] for c in lattices)
    else:
        states = {0: (0., ())}
        weight = REST_WEIGHT if method == 'joint_rest_cost' else 0.
        for candidates in lattices:
            incoming = {}
            for start in sorted({c[0] for c in candidates}):
                feasible = []
                for end, (cost, history) in states.items():
                    bridge = gap_cost(end, start, bar) if end <= start else math.inf
                    if math.isfinite(bridge):
                        feasible.append((cost + weight*bridge, history))
                if feasible:
                    incoming[start] = min(feasible)
            updated = {}
            for start, end, unary in candidates:
                if start not in incoming:
                    continue
                prev, history = incoming[start]
                value = (prev+unary, history + ((start, end),))
                if end not in updated or value < updated[end]:
                    updated[end] = value
            if not updated:
                raise ValueError('no_legal_joint_path')
            states = updated
        finals = [(cost + weight*gap_cost(end, length, bar), history)
                  for end, (cost, history) in states.items() if math.isfinite(gap_cost(end, length, bar))]
        if not finals:
            raise ValueError('no_legal_final_rest')
        total, path = min(finals)
    intervals = [(a/GRID, b/GRID) for a, b in path]
    rests = complement(intervals, length_q)
    nonoverlap = all(b <= c for (_, b), (c, _) in zip(sorted(path), sorted(path)[1:]))
    valid_rests = all(math.isfinite(gap_cost(round(a*GRID), round(b*GRID), bar)) for a, b in rests)
    predictions = {nid: (a/GRID, (b-a)/GRID) for group, (a, b) in zip(groups, path) for nid in group.ids}
    return {'predictions': predictions, 'rests': rests, 'cost': total,
            'structural_valid': nonoverlap and valid_rests,
            'note_count_preserved': len(predictions) == sum(len(g.ids) for g in groups)}


def rest_matches(predicted, reference):
    used, matched = set(), 0
    for a, b in predicted:
        choices = [i for i, (x, y) in enumerate(reference) if i not in used
                   and abs(a-x) <= TOL and abs(b-y) <= TOL]
        if choices:
            used.add(choices[0])
            matched += 1
    return {'predicted': len(predicted), 'reference': len(reference), 'matched': matched}


def run_block(block):
    results = {}
    ordered = sorted(block['targets'])
    before = fingerprint({r: [g.__dict__ for g in gs] for r, gs in block['groups'].items()})
    for rep in INPUTS:
        for method in METHODS:
            name = rep+'/'+method
            try:
                out = decode(block['groups'][rep], block['bar_q'], block['length_q'], method)
                metric = masks_for(out['predictions'], block['targets'], ordered)
                metric.update(status='complete', rest=rest_matches(out['rests'], block['rests']),
                              structural_valid=out['structural_valid'], cost=out['cost'])
                def tied(value):
                    a, d = value
                    return math.floor((a+d-1e-7)/block['bar_q']) > math.floor((a+1e-7)/block['bar_q'])
                metric['tie_crossing_correct'] = sum(tied(out['predictions'][k]) == tied(block['targets'][k]) for k in ordered)
                results[name] = metric
            except ValueError as exc:
                results[name] = {'status': 'unavailable', 'reason': str(exc), 'n': len(ordered)}
    if before != fingerprint({r: [g.__dict__ for g in gs] for r, gs in block['groups'].items()}):
        raise ValueError('mutated observations')
    paired = {}
    for rep in INPUTS:
        base = results[rep+'/independent']
        for method in METHODS[1:]:
            new = results[rep+'/'+method]
            if base['status'] == new['status'] == 'complete':
                paired[rep+'/'+method] = {k: paired_counts(base[k+'_mask'], new[k+'_mask'])
                                        for k in ('onset', 'duration', 'pair')}
    ceilings = {}
    for rep, groups in block['groups'].items():
        count = 0
        for group in groups:
            try:
                lattice = candidate_lattice(group, round(block['length_q']*GRID), round(block['bar_q']*GRID))
            except ValueError:
                lattice = []
            for nid in group.ids:
                s, d = block['targets'][nid]
                count += any(abs(a/GRID-s) <= TOL and abs((b-a)/GRID-d) <= TOL for a, b, _ in lattice)
        ceilings[rep] = count
    return {'id': block['id'], 'n': len(ordered), 'ordered_ids_sha256': fingerprint(ordered),
            'reference_rest_count': len(block['rests']), 'lattice_pair_ceiling': ceilings,
            'arms': results, 'paired': paired}


def load_previous(path):
    if path.is_symlink() or path.stat().st_size > 2_000_000 or sha(path.read_bytes()) != PREVIOUS_ZIP_SHA:
        raise ValueError('prior artifact checksum or path failure')
    with zipfile.ZipFile(path) as z:
        if z.getinfo('report.json').file_size > 2_000_000:
            raise ValueError('oversized report')
        raw = z.read('report.json')
    if sha(raw) != PREVIOUS_REPORT_SHA:
        raise ValueError('prior report checksum mismatch')
    return json.loads(raw)


def assess(reader, xml_reader, row, previous):
    folder = row['parangonada_data_folder'].rstrip('/')
    perf = rows(reader.get(folder+'/ppart.csv'))
    clock_t, clock_q, meter = beat_clock(perf, reader.get(row['performance_annotations']))
    origin, observations = clock_q[0], []
    for r in perf:
        start, length = float(r['onset_sec']), float(r['duration_sec'])
        if clock_t[0] <= start and start+length <= clock_t[-1] and length > 0:
            a = interpolate(start, clock_t, clock_q)-origin
            b = interpolate(start+length, clock_t, clock_q)-origin
            observations.append(Observation(r['id'], int(r['pitch']), a, b-a))
    observations.sort(key=lambda n: (n.onset, n.pitch, n.id))
    validate(observations)
    midi, _ = midi_key_events(reader.get(row['midi_performance']))
    keys, _ = match_key_releases(perf, observations, midi, clock_t, clock_q)
    inputs = dict(zip(INPUTS, (observations, keys)))
    for rep, values in inputs.items():
        if fingerprint([n.__dict__ for n in values]) != previous['source_observation_hashes'][rep]:
            raise ValueError('input differs from frozen endpoint comparison')
    score_rows = rows(reader.get(folder+'/part.csv'))
    alignment = rows(reader.get(folder+'/align.csv'))
    targets = load_targets(score_rows, alignment, observations, origin)
    if fingerprint(sorted(targets)) != previous['ordered_target_ids_sha256']:
        raise ValueError('prior evaluation IDs differ')
    for rep, values in inputs.items():
        for method in ('literal', 'spelling', 'articulation'):
            scored = masks_for(fit(values, mode=method)[0], targets, sorted(targets))
            if scored != previous['metrics'][rep][method]:
                raise ValueError('prior full-cohort baseline not reproduced')
    parsed = parse_score(xml_reader.get(row['xml_score']))
    blocks, admission = make_blocks(parsed, score_rows, alignment, inputs, origin)
    outcomes = [run_block(b) for b in blocks]
    used = {nid for b in blocks for nid in b['targets']}
    return {'status': 'complete' if blocks else 'no_supported_blocks', 'meter': meter,
            'previous_observed_notes': len(observations), 'previous_target_notes': len(targets),
            'prior_six_baselines_reproduced': True, 'unique_evaluated_notes': len(used),
            'admission': admission, 'blocks': outcomes,
            'oracle_context': ['annotated beat clock', 'correct quarter unit', 'bar boundaries',
                               'voice membership', 'chord membership', 'aligned complete note inventory']}


def aggregate(cases):
    blocks = [b for c in cases for b in c.get('blocks', [])]
    result = {'sources_planned': len(cases), 'source_statuses': dict(Counter(c['status'] for c in cases)),
              'blocks_admitted': len(blocks), 'note_evaluations': sum(b['n'] for b in blocks),
              'admission_statuses': dict(Counter(a.get('reason', a['status']) for c in cases for a in c.get('admission', []))),
              'arms': {}}
    for rep in INPUTS:
        for method in METHODS:
            name = rep+'/'+method
            values = [b['arms'][name] for b in blocks if b['arms'][name]['status'] == 'complete']
            score = {k: sum(v[k] for v in values) for k in ('n', 'onset_exact', 'duration_exact', 'pair_exact', 'tie_crossing_correct')}
            score.update(blocks_complete=len(values), blocks_unavailable=len(blocks)-len(values),
                         structural_valid=sum(v['structural_valid'] for v in values),
                         rests={k: sum(v['rest'][k] for v in values) for k in ('predicted', 'reference', 'matched')})
            if method != 'independent':
                paired = [b['paired'][name] for b in blocks if name in b['paired']]
                score['paired_vs_independent'] = {k: {m: sum(p[k][m] for p in paired)
                                                     for m in ('fixed', 'damaged', 'both_correct', 'both_wrong')}
                                                  for k in ('onset', 'duration', 'pair')}
            result['arms'][name] = score
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--previous', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists() or args.output.is_symlink():
        p.error('new output required')
    previous = load_previous(args.previous)
    reader, xml_reader = FrozenReader(previous['files']), Reader()
    metadata = {r['midi_performance']: r for r in rows(reader.get('metadata.csv'))}
    report = {'status': 'started', 'source_revision': os.getenv('GITHUB_SHA', 'local'),
              'previous_report_sha256': PREVIOUS_REPORT_SHA,
              'planned_ids': previous['planned_ids'], 'cases': [],
              'context_is_provided': True, 'audio_inference': False, 'quality_approved': False,
              'license_scope': 'CC BY-NC-SA4.0 data; no product data bundling or commercial clearance',
              'settings': {'start_radius_q': START_RADIUS_Q, 'start_sigma_q': START_SIGMA_Q,
                           'rest_weight': REST_WEIGHT, 'grid': GRID, 'methods': METHODS},
              'code_sha256': {str(f): sha(f.read_bytes()) for f in (
                  Path('scripts/nasap_joint_rhythm.py'), Path('tests/test_nasap_joint_rhythm.py'),
                  Path('docs/research/NASAP_JOINT_RHYTHM_PROTOCOL_2026-11-12.md'))}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    def save():
        report['original_files'], report['xml_files'] = reader.files, xml_reader.files
        tmp = args.output.with_suffix('.tmp')
        tmp.write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
        tmp.replace(args.output)
    save()
    start = time.monotonic()
    for old in previous['cases']:
        record = {'id': old['id']}
        if old['status'] != 'complete':
            record.update(status='prior_not_evaluated', reason=old.get('reason', 'prior exclusion'))
        else:
            try:
                record.update(assess(reader, xml_reader, metadata[old['id']], old))
            except (ValueError, KeyError, OSError, ET.ParseError) as exc:
                record.update(status='not_evaluated', reason=str(exc)[:250], error_type=type(exc).__name__)
        report['cases'].append(record)
        save()
        print(record['id'], record['status'], flush=True)
    report['summary'] = aggregate(report['cases'])
    report['elapsed_seconds'] = time.monotonic()-start
    report['downloaded_bytes'] = reader.total + xml_reader.total
    report['status'] = 'complete_with_reported_coverage' if report['summary']['blocks_admitted'] else 'blocked_no_supported_blocks'
    save()
    return 0 if report['summary']['blocks_admitted'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

"""Development-only silence-evidence ablation; never receives target rests."""
from __future__ import annotations

import argparse
import json
import math
import os
import time
import zipfile
from pathlib import Path

from scripts import nasap_joint_rhythm as joint
from scripts.nasap_joint_holdout import rest_occupancy

DEV_ZIP_SHA = '224dd43e067bdfbb87d1e0ef9c1af48baaf5ccd385c259c388ab69f543fd55e4'
DEV_REPORT_SHA = '281bad7ffb899a1e0ce67a148c832cb56cb7ddd377aa0e94c0abddaf19664b59'
MIN_GAP_Q = .25
EDGE_MARGIN_Q = 1/16
SILENCE_WEIGHT = 8.
NEW_METHODS = ('silence_soft', 'silence_hard')
METHODS = joint.METHODS + NEW_METHODS


def silence_evidence(by_rep, length_q):
    """Interior quiet cores supported by BOTH given endpoint observations.

    This is performed-event evidence, NOT an acoustically detected rest label.
    Identical pitch/ID inventory and onset coordinates must be preserved.
    """
    if set(by_rep) != set(joint.INPUTS) or not math.isfinite(length_q) or length_q <= 0:
        raise ValueError('invalid paired evidence input')
    maps = []
    for groups in by_rep.values():
        data = {}
        for g in groups:
            if not (len(g.ids) == len(g.onsets) == len(g.durations)):
                raise ValueError('invalid evidence shape')
            for nid, onset, duration in zip(g.ids, g.onsets, g.durations):
                if nid in data or not math.isfinite(onset) or not math.isfinite(duration) or duration <= 0:
                    raise ValueError('invalid evidence event')
                data[nid] = (onset, onset+duration)
        maps.append(data)
    if not maps[0] or set(maps[0]) != set(maps[1]):
        raise ValueError('paired inventory mismatch')
    occupied = []
    for nid in maps[0]:
        a, b = maps[0][nid]
        c, d = maps[1][nid]
        if abs(a-c) > 1e-9:
            raise ValueError('paired onsets changed')
        start, end = max(0., a), min(length_q, max(b, d))
        if end > start:
            occupied.append((start, end))
    result = []
    for a, b in joint.complement(occupied, length_q):
        if a <= 1e-9 or b >= length_q-1e-9 or b-a < MIN_GAP_Q-1e-9:
            continue
        result.append((a+EDGE_MARGIN_Q, b-EDGE_MARGIN_Q))
    return result


def overlap(a, b, intervals):
    return sum(max(0., min(b, y)-max(a, x)) for x, y in intervals)


def solve_path(lattices, bar, length):
    """Same exact non-overlap/rest DP as the frozen control, new unary only."""
    states = {0: (0., ())}
    for candidates in lattices:
        incoming = {}
        for start in sorted({c[0] for c in candidates}):
            choices = []
            for end, (cost, history) in states.items():
                bridge = joint.gap_cost(end, start, bar) if end <= start else math.inf
                if math.isfinite(bridge):
                    choices.append((cost+joint.REST_WEIGHT*bridge, history))
            if choices:
                incoming[start] = min(choices)
        updated = {}
        for start, end, unary in candidates:
            if start not in incoming:
                continue
            cost, history = incoming[start]
            value = (cost+unary, history+((start, end),))
            if end not in updated or value < updated[end]:
                updated[end] = value
        if not updated:
            raise ValueError('no_legal_silence_path')
        states = updated
    finals = [(cost+joint.REST_WEIGHT*joint.gap_cost(end, length, bar), path)
              for end, (cost, path) in states.items()
              if math.isfinite(joint.gap_cost(end, length, bar))]
    if not finals:
        raise ValueError('no_legal_silence_tail')
    return min(finals)


def decode(groups, bar_q, length_q, evidence, method):
    if method not in NEW_METHODS:
        raise ValueError('unknown evidence method')
    if any(not (0 <= a < b <= length_q) for a, b in evidence):
        raise ValueError('invalid silence evidence')
    if joint.merged_intervals(evidence) != list(evidence):
        raise ValueError('evidence must be sorted disjoint intervals')
    bar, length = round(bar_q*joint.GRID), round(length_q*joint.GRID)
    if bar <= 0 or length <= 0 or length % bar or not groups:
        raise ValueError('invalid block')
    candidates = []
    for g in groups:
        modified = []
        for start, end, cost in joint.candidate_lattice(g, length, bar):
            conflict = overlap(start/joint.GRID, end/joint.GRID, evidence)
            if method == 'silence_hard' and conflict > 1e-9:
                continue
            modified.append((start, end, cost+SILENCE_WEIGHT*conflict))
        candidates.append(modified)
    total, path = solve_path(candidates, bar, length)
    pred = {nid: (a/joint.GRID, (b-a)/joint.GRID)
            for g, (a, b) in zip(groups, path) for nid in g.ids}
    intervals = [(a/joint.GRID, b/joint.GRID) for a, b in path]
    return {'predictions': pred, 'rests': joint.complement(intervals, length_q),
            'cost': total, 'structural_valid': True,
            'note_count_preserved': len(pred) == sum(len(g.ids) for g in groups)}


def run_block(block, prior):
    before = joint.fingerprint({k: [g.__dict__ for g in v] for k, v in block['groups'].items()})
    evidence = silence_evidence(block['groups'], block['length_q'])
    outs = {}
    for rep in joint.INPUTS:
        for method in METHODS:
            try:
                outs[rep+'/'+method] = (joint.decode(block['groups'][rep], block['bar_q'], block['length_q'], method)
                    if method in joint.METHODS else decode(block['groups'][rep], block['bar_q'], block['length_q'], evidence, method))
            except ValueError as exc:
                outs[rep+'/'+method] = {'error': str(exc)}
    if before != joint.fingerprint({k: [g.__dict__ for g in v] for k, v in block['groups'].items()}):
        raise ValueError('observation mutation')
    ordered = sorted(block['targets'])
    if len(ordered) != prior['n'] or joint.fingerprint(ordered) != prior['ordered_ids_sha256']:
        raise ValueError('development block inventory changed')
    arms = {}
    for name, out in outs.items():
        if 'error' in out:
            arms[name] = {'status': 'unavailable', 'reason': out['error'], 'n': len(ordered)}
            continue
        metric = joint.masks_for(out['predictions'], block['targets'], ordered)
        rest = joint.rest_matches(out['rests'], block['rests'])
        if name in prior['arms']:
            old = prior['arms'][name]
            if any(old[k] != value for k, value in metric.items()) or old['rest'] != rest:
                raise ValueError('frozen control does not reproduce')
        metric.update(status='complete', rest=rest, cost=out['cost'],
                      structural_valid=out['structural_valid'],
                      rest_occupancy=rest_occupancy(out['rests'], block['rests']))
        arms[name] = metric
    paired = {}
    for rep in joint.INPUTS:
        base = arms[rep+'/joint_rest_cost']
        for method in NEW_METHODS:
            found = arms[rep+'/'+method]
            if found['status'] == 'complete':
                paired[rep+'/'+method] = joint.paired_counts(base['pair_mask'], found['pair_mask'])
    return {'id': block['id'], 'n': len(ordered), 'ordered_ids_sha256': joint.fingerprint(ordered),
            'arms': arms, 'paired_vs_rest_cost': paired, 'evidence_intervals': len(evidence),
            'evidence_audit': rest_occupancy(evidence, block['rests'])}


def prepare(reader, row):
    folder = row['parangonada_data_folder'].rstrip('/')
    perf = joint.rows(reader.get(folder+'/ppart.csv'))
    ts, qs, _ = joint.beat_clock(perf, reader.get(row['performance_annotations']))
    origin, notes = qs[0], []
    for r in perf:
        start, duration = float(r['onset_sec']), float(r['duration_sec'])
        if ts[0] <= start and start+duration <= ts[-1] and duration > 0:
            a = joint.interpolate(start, ts, qs)-origin
            b = joint.interpolate(start+duration, ts, qs)-origin
            notes.append(joint.Observation(r['id'], int(r['pitch']), a, b-a))
    notes.sort(key=lambda n: (n.onset, n.pitch, n.id))
    midi, _ = joint.midi_key_events(reader.get(row['midi_performance']))
    keys, _ = joint.match_key_releases(perf, notes, midi, ts, qs)
    inputs = dict(zip(joint.INPUTS, (notes, keys)))
    score = joint.rows(reader.get(folder+'/part.csv'))
    alignment = joint.rows(reader.get(folder+'/align.csv'))
    parsed = joint.parse_score(reader.get(row['xml_score']))
    return joint.make_blocks(parsed, score, alignment, inputs, origin)


def summarize(cases):
    blocks = [b for c in cases for b in c.get('blocks', [])]
    names = [r+'/'+m for r in joint.INPUTS for m in METHODS]
    result = {'planned_sources': len(cases), 'evaluated_sources': sum(bool(c.get('blocks')) for c in cases),
              'blocks': len(blocks), 'notes': sum(b['n'] for b in blocks), 'arms': {}}
    for name in names:
        values = [b['arms'][name] for b in blocks if b['arms'][name]['status'] == 'complete']
        entry = {k: sum(v[k] for v in values) for k in ('n','onset_exact','duration_exact','pair_exact')}
        entry['complete_blocks'] = len(values)
        entry['unavailable_blocks'] = len(blocks)-len(values)
        entry['rests'] = {k: sum(v['rest'][k] for v in values) for k in ('predicted','reference','matched')}
        entry['occupancy'] = {k: sum(v['rest_occupancy'][k] for v in values)
                              for k in ('predicted_q','reference_q','overlap_q','false_rest_q','missed_rest_q')}
        result['arms'][name] = entry
    result['common_blocks'] = sum(all(v['status']=='complete' for v in b['arms'].values()) for b in blocks)
    result['evidence_blocks'] = sum(b['evidence_intervals']>0 for b in blocks)
    result['evidence_audit'] = {k: sum(b['evidence_audit'][k] for b in blocks)
                               for k in ('predicted_q','reference_q','overlap_q','false_rest_q','missed_rest_q')}
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--development', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    args = p.parse_args()
    if args.output.exists() or args.output.is_symlink():
        p.error('fresh output required')
    raw = args.development.read_bytes()
    if joint.sha(raw) != DEV_ZIP_SHA:
        raise ValueError('development artifact mismatch')
    with zipfile.ZipFile(args.development) as z:
        report_raw = z.read('report.json')
        if joint.sha(report_raw) != DEV_REPORT_SHA:
            raise ValueError('development report mismatch')
        for name in ('nasap_joint_rhythm.py','nasap_keyoff_paired.py','nasap_duration_probe.py','audit_nasap_duration_source.py'):
            path = 'scripts/'+name
            if Path(path).read_bytes() != z.read('reproduction/'+path):
                raise ValueError('frozen inherited code changed')
    previous = json.loads(report_raw)
    expected = dict(previous['original_files'])
    expected.update(previous['xml_files'])
    reader = joint.FrozenReader(expected)
    metadata = {r['midi_performance']: r for r in joint.rows(reader.get('metadata.csv'))}
    report = {'status': 'running', 'source_revision': os.getenv('GITHUB_SHA'),
              'development_report_sha256': DEV_REPORT_SHA, 'cases': [],
              'planned_ids': previous['planned_ids'], 'holdout_265_reused': False,
              'context_is_provided': True, 'audio_inference': False, 'quality_approved': False,
              'settings': {'min_gap_q': MIN_GAP_Q, 'edge_margin_q': EDGE_MARGIN_Q,
                           'silence_weight': SILENCE_WEIGHT, 'methods': METHODS},
              'code_sha256': {str(f): joint.sha(f.read_bytes()) for f in (Path(__file__), Path('tests/test_nasap_rest_evidence.py'))}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    def save():
        report['files'] = reader.files
        tmp = args.output.with_suffix('.tmp')
        tmp.write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
        tmp.replace(args.output)
    save()
    start = time.monotonic()
    for old in previous['cases']:
        record = {'id': old['id']}
        if old['status'] != 'complete':
            record.update(status='prior_not_evaluated', reason=old.get('reason', old['status']))
        else:
            try:
                blocks, admission = prepare(reader, metadata[old['id']])
                if admission != old['admission'] or [b['id'] for b in blocks] != [b['id'] for b in old['blocks']]:
                    raise ValueError('development admission changed')
                record.update(status='complete', blocks=[run_block(b, prev) for b, prev in zip(blocks,old['blocks'])])
            except (ValueError, KeyError, OSError) as exc:
                record.update(status='not_evaluated', reason=str(exc)[:240])
        report['cases'].append(record)
        save()
        print(record['id'], record['status'], flush=True)
    report['summary'] = summarize(report['cases'])
    report['elapsed_seconds'] = time.monotonic()-start
    report['status'] = 'complete_development_evaluation' if report['summary']['blocks']==38 else 'partial'
    save()
    return 0 if report['summary']['blocks']==38 else 1


if __name__ == '__main__':
    raise SystemExit(main())

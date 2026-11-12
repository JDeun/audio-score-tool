"""Frozen-decoder evaluation on composition-disjoint (n)ASAP passages, research only."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import time
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from pathlib import Path

from scripts import nasap_joint_rhythm as joint
from scripts.nasap_duration_probe import METADATA_BLOB, REVISION

PRIOR_ZIP_SHA = '224dd43e067bdfbb87d1e0ef9c1af48baaf5ccd385c259c388ab69f543fd55e4'
PRIOR_REPORT_SHA = '281bad7ffb899a1e0ce67a148c832cb56cb7ddd377aa0e94c0abddaf19664b59'
PLANNED_PIECES = 24
MAX_PER_COMPOSER = 3
SELECTION_SEED = 'nasap-joint-holdout-v1/'
SCHEMA_INSPECTIONS = {('bach', 'fugue_bwv_846'), ('bach', 'fugue_bwv_848')}
FROZEN_PATHS = (
    'scripts/nasap_joint_rhythm.py', 'scripts/nasap_keyoff_paired.py',
    'scripts/nasap_duration_probe.py', 'scripts/audit_nasap_duration_source.py',
)


def canonical(value):
    return ' '.join(unicodedata.normalize('NFKC', value).strip().casefold().split())


def piece_key(row):
    return canonical(row['composer']), canonical(row['title'])


def choose_new_sources(metadata, old_ids, limit=PLANNED_PIECES):
    """Never read note/beat/score data or accuracy while choosing the new cohort."""
    by_id = {r['midi_performance']: r for r in metadata}
    if len(by_id) != len(metadata) or any(p not in by_id for p in old_ids):
        raise ValueError('metadata IDs missing or ambiguous')
    old_rows = [by_id[p] for p in old_ids]
    excluded_pieces = {piece_key(r) for r in old_rows} | SCHEMA_INSPECTIONS
    excluded_paths = {r[k] for r in old_rows for k in ('xml_score', 'midi_score', 'folder') if r.get(k)}
    pool = [r for r in metadata if r.get('robust_note_alignment') in ('1', '1.0')
            and r.get('parangonada_data_folder') and r.get('performance_annotations')
            and piece_key(r) not in excluded_pieces
            and not any(r.get(k) in excluded_paths for k in ('xml_score', 'midi_score', 'folder'))]
    pool.sort(key=lambda r: joint.sha((SELECTION_SEED+r['midi_performance']).encode()))
    result, used_pieces, used_paths, composers = [], set(), set(), Counter()
    for row in pool:
        key = piece_key(row)
        paths = {row[k] for k in ('xml_score', 'midi_score', 'folder') if row.get(k)}
        if key in used_pieces or paths & used_paths or composers[key[0]] >= MAX_PER_COMPOSER:
            continue
        result.append(row)
        used_pieces.add(key)
        used_paths.update(paths)
        composers[key[0]] += 1
        if len(result) == limit:
            break
    return result, {'excluded_compositions': sorted(excluded_pieces),
                    'previous_source_count': len(old_ids), 'candidate_rows': len(pool),
                    'selected_composers': dict(composers)}


class CachedReader(joint.Reader):
    """Reuse exact source bytes; inherited 4MB/file and 40MB total bounds apply."""
    def __init__(self):
        super().__init__()
        self.cache = {}

    def get(self, path):
        if path not in self.cache:
            self.cache[path] = super().get(path)
        return self.cache[path]


def load_prior(path):
    if path.is_symlink() or path.stat().st_size > 2_000_000:
        raise ValueError('invalid prior artifact')
    raw = path.read_bytes()
    if joint.sha(raw) != PRIOR_ZIP_SHA:
        raise ValueError('prior artifact digest changed')
    with zipfile.ZipFile(path) as archive:
        report_raw = archive.read('report.json')
        if joint.sha(report_raw) != PRIOR_REPORT_SHA:
            raise ValueError('prior report digest changed')
        report = json.loads(report_raw)
        for name in FROZEN_PATHS:
            if Path(name).read_bytes() != archive.read('reproduction/'+name):
                raise ValueError('frozen decoder, loader, evaluator or MIDI parser changed')
    actual = {'start_radius_q': joint.START_RADIUS_Q, 'start_sigma_q': joint.START_SIGMA_Q,
              'rest_weight': joint.REST_WEIGHT, 'grid': joint.GRID, 'methods': list(joint.METHODS)}
    if actual != report['settings']:
        raise ValueError('frozen settings changed')
    return report


def rest_occupancy(predicted, reference):
    """Silence overlap supplements, but does not replace, strict rest matching."""
    pred, ref = joint.merged_intervals(predicted), joint.merged_intervals(reference)
    overlap = sum(max(0., min(b, d)-max(a, c)) for a, b in pred for c, d in ref)
    predicted_q, reference_q = sum(b-a for a, b in pred), sum(b-a for a, b in ref)
    return {'predicted_q': predicted_q, 'reference_q': reference_q,
            'overlap_q': overlap, 'false_rest_q': max(0., predicted_q-overlap),
            'missed_rest_q': max(0., reference_q-overlap)}


def crosses_inner_bar(value, bar):
    start, duration = value
    return start < bar-joint.TOL and start+duration > bar+joint.TOL


def run_frozen_block(block):
    result = joint.run_block(block)
    # Unchanged primary evaluator. Repeat deterministic decoding only to obtain
    # secondary rest-occupancy/tie diagnostics absent from the older receipt.
    for rep in joint.INPUTS:
        for method in joint.METHODS:
            arm = result['arms'][rep+'/'+method]
            if arm['status'] != 'complete':
                continue
            out = joint.decode(block['groups'][rep], block['bar_q'], block['length_q'], method)
            check = joint.masks_for(out['predictions'], block['targets'], sorted(block['targets']))
            if any(check[k] != arm[k] for k in check):
                raise ValueError('secondary diagnostic changed the frozen result')
            arm['rest_occupancy'] = rest_occupancy(out['rests'], block['rests'])
            confusion = dict(tp=0, fp=0, fn=0, tn=0)
            for nid, target in block['targets'].items():
                truth = crosses_inner_bar(target, block['bar_q'])
                found = crosses_inner_bar(out['predictions'][nid], block['bar_q'])
                confusion['tp' if truth and found else 'fn' if truth else 'fp' if found else 'tn'] += 1
            arm['inner_bar_crossing'] = confusion
    return result


def assess_source(reader, row, record):
    folder = row['parangonada_data_folder'].rstrip('/')
    record['stage'] = 'clock_and_performance'
    perf = joint.rows(reader.get(folder+'/ppart.csv'))
    clock_t, clock_q, meter = joint.beat_clock(perf, reader.get(row['performance_annotations']))
    origin, observations = clock_q[0], []
    for note in perf:
        start, duration = float(note['onset_sec']), float(note['duration_sec'])
        if clock_t[0] <= start and start+duration <= clock_t[-1] and duration > 0:
            a = joint.interpolate(start, clock_t, clock_q)-origin
            b = joint.interpolate(start+duration, clock_t, clock_q)-origin
            observations.append(joint.Observation(note['id'], int(note['pitch']), a, b-a))
    observations.sort(key=lambda n: (n.onset, n.pitch, n.id))
    joint.validate(observations)
    record.update(meter=meter, observed_notes=len(observations))
    record['stage'] = 'key_release_pairing'
    midi, _ = joint.midi_key_events(reader.get(row['midi_performance']))
    keys, _ = joint.match_key_releases(perf, observations, midi, clock_t, clock_q)
    inputs = dict(zip(joint.INPUTS, (observations, keys)))
    record['observation_hashes'] = {k: joint.fingerprint([n.__dict__ for n in v]) for k, v in inputs.items()}
    record['stage'] = 'score_parser'
    score_rows = joint.rows(reader.get(folder+'/part.csv'))
    alignment = joint.rows(reader.get(folder+'/align.csv'))
    parsed = joint.parse_score(reader.get(row['xml_score']))
    record['stage'] = 'fixed_block_admission'
    blocks, attempts = joint.make_blocks(parsed, score_rows, alignment, inputs, origin)
    record['admission'] = attempts
    used = [nid for b in blocks for nid in b['targets']]
    if len(used) != len(set(used)):
        raise ValueError('duplicate evaluation note across admitted blocks')
    record['stage'] = 'frozen_decoding'
    outcomes = [run_frozen_block(b) for b in blocks]
    record.update(status='complete' if blocks else 'no_supported_blocks',
                  blocks=outcomes, unique_evaluated_notes=len(set(used)), stage='finished')


def f1_counts(counts):
    p, r, m = counts['predicted'], counts['reference'], counts['matched']
    return {'precision': m/p if p else None, 'recall': m/r if r else None,
            'f1': 2*m/(p+r) if p+r else None}


def extend_summary(cases):
    result = joint.aggregate(cases)
    blocks = [b for c in cases for b in c.get('blocks', [])]
    paired = [b for b in blocks if all(a['status'] == 'complete' for a in b['arms'].values())]
    result['all_six_arms_complete_blocks'] = len(paired)
    result['all_six_arms_complete_notes'] = sum(b['n'] for b in paired)
    # Never compare unequal denominators without this explicit same-block scope.
    common = joint.aggregate([{'status': 'paired_scope', 'blocks': paired}])
    result['paired_scope'] = common['arms']
    for name, aggregate in result['arms'].items():
        aggregate['rest_scores'] = f1_counts(aggregate['rests'])
        valid = [b['arms'][name] for b in blocks if b['arms'][name]['status'] == 'complete']
        aggregate['rest_occupancy'] = {k: sum(v['rest_occupancy'][k] for v in valid)
                                      for k in ('predicted_q', 'reference_q', 'overlap_q', 'false_rest_q', 'missed_rest_q')}
        aggregate['inner_bar_crossing'] = {k: sum(v['inner_bar_crossing'][k] for v in valid)
                                          for k in ('tp', 'fp', 'fn', 'tn')}
        rates = []
        for case in cases:
            values = [b['arms'][name] for b in case.get('blocks', []) if b['arms'][name]['status'] == 'complete']
            n = sum(v['n'] for v in values)
            if n:
                rates.append(sum(v['pair_exact'] for v in values)/n)
        aggregate['composition_equal_pair_accuracy'] = statistics.mean(rates) if rates else None
    directions = {}
    for rep in joint.INPUTS:
        for method in joint.METHODS[1:]:
            counts = Counter(better=0, worse=0, equal=0)
            for case in cases:
                usable = [b for b in case.get('blocks', []) if all(a['status'] == 'complete' for a in b['arms'].values())]
                if not usable:
                    continue
                diff = sum(b['arms'][rep+'/'+method]['pair_exact']-b['arms'][rep+'/independent']['pair_exact'] for b in usable)
                counts['better' if diff > 0 else 'worse' if diff < 0 else 'equal'] += 1
            directions[rep+'/'+method] = dict(counts)
    result['paired_composition_directions'] = directions
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--previous', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error('new output required')
    old = load_prior(args.previous)
    reader = CachedReader()
    metadata_raw = reader.get('metadata.csv')
    blob = hashlib.sha1(b'blob '+str(len(metadata_raw)).encode()+b'\0'+metadata_raw).hexdigest()
    if blob != METADATA_BLOB or joint.sha(metadata_raw) != old['original_files']['metadata.csv']['sha256']:
        raise ValueError('dataset metadata identity mismatch')
    metadata = joint.rows(metadata_raw)
    plan, disjoint = choose_new_sources(metadata, old['planned_ids'])
    if len(plan) != PLANNED_PIECES:
        raise ValueError('insufficient predeclared composition-disjoint cohort')
    report = {'status': 'running', 'previous_report_sha256': PRIOR_REPORT_SHA,
              'dataset_revision': REVISION, 'source_revision': os.getenv('GITHUB_SHA', 'local'),
              'settings': old['settings'], 'selection_seed': SELECTION_SEED,
              'planned_ids': [r['midi_performance'] for r in plan],
              'planned_compositions': [{'composer': r['composer'], 'title': r['title']} for r in plan],
              'disjointness': disjoint, 'cases': [], 'context_is_provided': True,
              'audio_inference': False, 'trained_or_retuned': False, 'quality_approved': False,
              'licensing': 'CC BY-NC-SA4.0 source data; no commercial-use clearance or product bundling',
              'code_sha256': {p: joint.sha(Path(p).read_bytes()) for p in FROZEN_PATHS + (
                  'scripts/nasap_joint_holdout.py', 'tests/test_nasap_joint_holdout.py',
                  'docs/research/NASAP_JOINT_HOLDOUT_PROTOCOL_2026-11-12.md')}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    def save():
        report['files'] = reader.files
        temporary = args.output.with_suffix('.tmp')
        temporary.write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
        temporary.replace(args.output)
    save()  # all 24 source IDs persisted BEFORE inspecting their musical content
    started = time.monotonic()
    for row in plan:
        case = {'id': row['midi_performance'], 'composer': row['composer'], 'title': row['title']}
        try:
            assess_source(reader, row, case)
        except (ValueError, KeyError, OSError, ET.ParseError) as exc:
            case.update(status='not_evaluated', reason=str(exc)[:250], error_type=type(exc).__name__)
        report['cases'].append(case)
        save()
        print(case['id'], case['status'], case.get('reason', ''), flush=True)
    report['summary'] = extend_summary(report['cases'])
    report['downloaded_bytes'] = reader.total
    report['elapsed_seconds'] = time.monotonic()-started
    report['status'] = 'complete_with_reported_coverage' if report['summary']['blocks_admitted'] else 'blocked_no_supported_blocks'
    save()
    return 0 if report['summary']['blocks_admitted'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

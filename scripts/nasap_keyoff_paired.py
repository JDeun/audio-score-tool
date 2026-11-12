"""Fixed-cohort endpoint ablation; labels only evaluate, never choose inputs."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import time
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

from scripts.audit_nasap_duration_source import midi_key_events
from scripts.nasap_duration_probe import (
    DURATION_METHODS,
    EPS,
    GRID,
    VOCAB,
    Observation,
    Reader,
    beat_clock,
    fingerprint,
    fit,
    interpolate,
    rows,
    selection,
    sha,
    validate,
)

ZIP_SHA = '8aae98a772c0a6494ba243ebe0f123d0a3de7e1d4d44108dd5f61cb7ebf170b8'
REPORT_SHA = 'ad4ab109f11850ab270bc43310e328d7e5cb9f5f8894af2e6e1975b5e2e6cd4e'
AUDIT_SHA = 'dc244b40827e34516b8659208175887d76e5464540ffc2cc47a45c6ef42cd09d'
PREDICTOR_SHA = '881a0a7544745d5fe50317ca81bca8ea05adce510bbfb2facc46405c65ffa973'
PARSER_BLOB = 'a61a9283daf2c815dbe762e481e1e008f8d2d5a0'
REPRESENTATIONS = ('csv_sustain', 'key_release')
TOL = 1 / 96 + EPS


def load_previous(path):
    if path.is_symlink() or path.stat().st_size > 1_000_000:
        raise ValueError('unsafe prior artifact')
    if sha(path.read_bytes()) != ZIP_SHA:
        raise ValueError('prior artifact digest mismatch')
    with zipfile.ZipFile(path) as z:
        if sorted(z.namelist()) != ['report.json', 'source-audit.json']:
            raise ValueError('unexpected artifact members')
        if any(i.file_size > 2_000_000 for i in z.infolist()):
            raise ValueError('oversized artifact member')
        raw, audit_raw = z.read('report.json'), z.read('source-audit.json')
    if sha(raw) != REPORT_SHA or sha(audit_raw) != AUDIT_SHA:
        raise ValueError('prior report hash mismatch')
    report, audit = json.loads(raw), json.loads(audit_raw)
    if audit['study_sha256'] != REPORT_SHA:
        raise ValueError('audit and report disagree')
    return report, audit


class FrozenReader(Reader):
    def __init__(self, evidence):
        super().__init__()
        self.evidence = evidence

    def get(self, path):
        if path not in self.evidence:
            raise ValueError('source not present in prior evidence')
        raw = super().get(path)
        if sha(raw) != self.evidence[path]['sha256']:
            raise ValueError('musical source changed from prior experiment')
        return raw


def same_grid(notes, other):
    if [(n.id, n.pitch, n.onset) for n in notes] != [(n.id, n.pitch, n.onset) for n in other]:
        raise ValueError('note identity, pitch or onset changed')


def match_key_releases(perf_rows, selected, midi_notes, clock_t, clock_q):
    """Keep the original CSV onset; change only its endpoint to MIDI key-off."""
    by_pitch = defaultdict(list)
    for index, note in enumerate(midi_notes):
        by_pitch[(note['pitch'], note['channel'])].append((index, note))
    source = {r['id']: r for r in perf_rows}
    used, answer, details = set(), [], {}
    origin = clock_q[0]
    for obs in selected:
        row = source[obs.id]
        onset = float(row['onset_sec'])
        matches = [(i, n) for i, n in by_pitch[(int(row['pitch']), int(row['channel']))]
                   if abs(n['onset'] - onset) <= .002]
        if len(matches) != 1 or matches[0][0] in used:
            raise ValueError('MIDI onset mapping not unique and one-to-one')
        index, key = matches[0]
        used.add(index)
        end = key['offset']
        if not math.isfinite(end) or not onset < end <= clock_t[-1]:
            raise ValueError('key-off outside frozen observation clock')
        key_q = interpolate(end, clock_t, clock_q) - origin - obs.onset
        answer.append(Observation(obs.id, obs.pitch, obs.onset, key_q))
        details[obs.id] = {
            'extended': float(row['duration_sec']) - (key['offset'] - key['onset']) > .010,
            'onset_residual': abs(key['onset'] - onset),
            'end_sec': end,
        }
    validate(answer)
    same_grid(selected, answer)
    return answer, details


def load_targets(score, alignment, observations, origin):
    score_ids = {s['id']: s for s in score}
    if len(score_ids) != len(score):
        raise ValueError('duplicate score IDs')
    obs_ids = {o.id: o for o in observations}
    multiplicity = Counter(a['ppartid'] for a in alignment if a['matchtype'] == '0')
    targets = {}
    for a in alignment:
        nid = a['ppartid']
        if a['matchtype'] != '0' or nid not in obs_ids:
            continue
        s = score_ids.get(a['partid'])
        if multiplicity[nid] != 1 or s is None:
            continue
        onset, duration = float(s['onset_quarter']) - origin, float(s['duration_quarter'])
        if abs(float(s['onset_beat']) - float(s['onset_quarter'])) > 1e-4:
            raise ValueError('score beat and quarter conventions differ')
        if duration <= 0 or not 0 <= onset < 32 or int(s['pitch']) != obs_ids[nid].pitch:
            continue
        targets[nid] = (onset, duration)
    return targets


def masks_for(predictions, targets, ordered):
    onset = ''.join('1' if abs(predictions[k][0] - targets[k][0]) <= TOL else '0'
                    for k in ordered)
    duration = ''.join('1' if abs(predictions[k][1] - targets[k][1]) <= TOL else '0'
                       for k in ordered)
    pair = ''.join('1' if a == b == '1' else '0' for a, b in zip(onset, duration))
    return {'n': len(ordered), 'onset_exact': onset.count('1'),
            'duration_exact': duration.count('1'), 'pair_exact': pair.count('1'),
            'onset_mask': onset, 'duration_mask': duration, 'pair_mask': pair}


def paired_counts(before, after):
    if len(before) != len(after) or any(x not in '01' for x in before + after):
        raise ValueError('invalid paired correctness masks')
    return {'fixed': sum(a == '0' and b == '1' for a, b in zip(before, after)),
            'damaged': sum(a == '1' and b == '0' for a, b in zip(before, after)),
            'both_correct': sum(a == b == '1' for a, b in zip(before, after)),
            'both_wrong': sum(a == b == '0' for a, b in zip(before, after))}


def representation_check(targets, ordered):
    exact = ''.join('1' if min(abs(d - targets[k][1]) for d, _ in VOCAB) <= EPS else '0'
                    for k in ordered)
    tolerant = ''.join('1' if min(abs(d - targets[k][1]) for d, _ in VOCAB) <= TOL else '0'
                       for k in ordered)
    onset = ''.join('1' if abs(round(targets[k][0] * GRID) / GRID - targets[k][0]) <= TOL
                    else '0' for k in ordered)
    truth_input = [Observation(k, 60, *targets[k]) for k in ordered]
    truth_pred = fit(truth_input, mode='literal')[0]
    identity = masks_for(truth_pred, targets, ordered)
    if identity['duration_mask'] != tolerant or identity['onset_mask'] != onset:
        raise ValueError('known-score literal identity violates representability')
    return {'exact_duration_vocab_mask': exact, 'tolerant_duration_vocab_mask': tolerant,
            'onset_grid_mask': onset, 'literal_score_input': identity,
            'diagnostic_reference_supplied': True}


def assess(reader, row, previous):
    folder = row['parangonada_data_folder'].rstrip('/')
    perf = rows(reader.get(folder + '/ppart.csv'))
    clock_t, clock_q, meter = beat_clock(perf, reader.get(row['performance_annotations']))
    origin = clock_q[0]
    observed, original_seconds = [], []
    for r in perf:
        start, length = float(r['onset_sec']), float(r['duration_sec'])
        if not (clock_t[0] <= start and start + length <= clock_t[-1] and length > 0):
            continue
        onset = interpolate(start, clock_t, clock_q) - origin
        end = interpolate(start + length, clock_t, clock_q) - origin
        observed.append(Observation(r['id'], int(r['pitch']), onset, end - onset))
        original_seconds.extend((start, start + length))
    observed.sort(key=lambda n: (n.onset, n.pitch, n.id))
    validate(observed)
    if (len(observed) != previous['observed_notes'] or
            fingerprint([n.__dict__ for n in observed]) != previous['observation_sha256']):
        raise ValueError('CSV observation set differs from frozen baseline')
    midi_notes, _pedals = midi_key_events(reader.get(row['midi_performance']))
    keys, mapping = match_key_releases(perf, observed, midi_notes, clock_t, clock_q)
    all_seconds = original_seconds + [v['end_sec'] for v in mapping.values()]
    rt_error = max(abs(interpolate(interpolate(t, clock_t, clock_q), clock_q, clock_t) - t)
                   for t in all_seconds)
    if rt_error > 1e-8:
        raise ValueError('clock arithmetic roundtrip failed')
    inputs = dict(zip(REPRESENTATIONS, (observed, keys)))
    before = {rep: fingerprint([n.__dict__ for n in notes]) for rep, notes in inputs.items()}
    # Written score and alignment are not read until all SIX predictions exist.
    predictions = {rep: {m: fit(notes, mode=m)[0] for m in DURATION_METHODS}
                   for rep, notes in inputs.items()}
    frozen_predictions = fingerprint(predictions)
    targets = load_targets(rows(reader.get(folder + '/part.csv')),
                           rows(reader.get(folder + '/align.csv')), observed, origin)
    if len(targets) != previous['matched_notes']:
        raise ValueError('evaluation target denominator changed')
    ordered = sorted(targets)
    check = representation_check(targets, ordered)
    metrics = {rep: {m: masks_for(p, targets, ordered) for m, p in methods.items()}
               for rep, methods in predictions.items()}
    baseline_onsets = metrics['csv_sustain']['literal']['onset_mask']
    for rep in REPRESENTATIONS:
        for m in DURATION_METHODS:
            if metrics[rep][m]['onset_mask'] != baseline_onsets:
                raise ValueError('onset correctness changed in duration-only ablation')
            if rep == 'csv_sustain':
                for k in ('n', 'onset_exact', 'duration_exact', 'pair_exact'):
                    if metrics[rep][m][k] != previous['duration_scores'][m][k]:
                        raise ValueError('previous sustain method result not reproduced')
    if frozen_predictions != fingerprint(predictions):
        raise ValueError('evaluation altered predictions')
    if before != {rep: fingerprint([n.__dict__ for n in notes]) for rep, notes in inputs.items()}:
        raise ValueError('input mutation')
    changes = {m: paired_counts(metrics['csv_sustain'][m]['duration_mask'],
                               metrics['key_release'][m]['duration_mask']) for m in DURATION_METHODS}
    return {'status': 'complete', 'meter': meter, 'observed_notes': len(observed),
            'matched_notes': len(ordered), 'onset_pitch_identity_preserved': True,
            'source_observation_hashes': before, 'ordered_target_ids_sha256': fingerprint(ordered),
            'max_clock_roundtrip_seconds': rt_error,
            'max_midi_csv_onset_residual_seconds': max(v['onset_residual'] for v in mapping.values()),
            'original_result_reproduced': True, 'preflight': check,
            'extended_gt_10ms_mask': ''.join('1' if mapping[k]['extended'] else '0' for k in ordered),
            'metrics': metrics, 'paired_key_vs_csv': changes}


def aggregate(cases):
    done = [c for c in cases if c['status'] == 'complete']
    result = {'planned': len(cases), 'paired_complete': len(done),
              'statuses': dict(Counter(c['status'] for c in cases)),
              'observed_notes': sum(c['observed_notes'] for c in done),
              'matched_notes': sum(c['matched_notes'] for c in done),
              'arms': {}, 'paired': {}, 'preflight': {}}
    if not done:
        return result
    for rep in REPRESENTATIONS:
        for method in DURATION_METHODS:
            values = [c['metrics'][rep][method] for c in done]
            total = {k: sum(v[k] for v in values)
                     for k in ('n', 'onset_exact', 'duration_exact', 'pair_exact')}
            total['duration_micro'] = total['duration_exact'] / total['n']
            total['duration_macro'] = statistics.mean(v['duration_exact'] / v['n'] for v in values)
            total['pair_micro'] = total['pair_exact'] / total['n']
            total['pair_macro'] = statistics.mean(v['pair_exact'] / v['n'] for v in values)
            total['representable_duration_correct'] = sum(
                a == b == '1' for c in done for a, b in zip(
                    c['metrics'][rep][method]['duration_mask'],
                    c['preflight']['tolerant_duration_vocab_mask']))
            result['arms'][rep + '/' + method] = total
    for method in DURATION_METHODS:
        totals = {k: sum(c['paired_key_vs_csv'][method][k] for c in done)
                  for k in ('fixed', 'damaged', 'both_correct', 'both_wrong')}
        delta = [c['metrics']['key_release'][method]['duration_exact'] -
                 c['metrics']['csv_sustain'][method]['duration_exact'] for c in done]
        totals.update(better_passages=sum(d > 0 for d in delta),
                      worse_passages=sum(d < 0 for d in delta),
                      equal_passages=sum(d == 0 for d in delta))
        result['paired'][method] = totals
    for k in ('exact_duration_vocab_mask', 'tolerant_duration_vocab_mask', 'onset_grid_mask'):
        result['preflight'][k.replace('_mask', '_count')] = sum(c['preflight'][k].count('1') for c in done)
    result['preflight']['max_clock_roundtrip_seconds'] = max(c['max_clock_roundtrip_seconds'] for c in done)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--previous', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error('output must be new')
    old, audit = load_previous(args.previous)
    if sha(Path('scripts/nasap_duration_probe.py').read_bytes()) != PREDICTOR_SHA:
        raise ValueError('inherited predictor changed')
    raw = Path('scripts/audit_nasap_duration_source.py').read_bytes()
    if hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() != PARSER_BLOB:
        raise ValueError('inherited MIDI parser changed')
    evidence = dict(old['files'])
    for path, details in audit['files'].items():
        if path in evidence and evidence[path] != details:
            raise ValueError('previous evidence disagrees')
        evidence[path] = details
    reader = FrozenReader(evidence)
    metadata = rows(reader.get('metadata.csv'))
    plan = selection(metadata)
    if [r['midi_performance'] for r in plan] != old['planned_ids']:
        raise ValueError('original source selection changed')
    previous = {r['id']: r for r in old['cases']}
    report = {'status': 'running', 'source_revision': os.getenv('GITHUB_SHA', 'local'),
              'previous_report_sha256': REPORT_SHA, 'previous_source_audit_sha256': AUDIT_SHA,
              'planned_ids': old['planned_ids'], 'cases': [],
              'inputs': list(REPRESENTATIONS), 'methods': list(DURATION_METHODS),
              'annotated_clock_and_correct_unit_supplied': True,
              'new_audio_inference': False, 'new_unit_selection': False,
              'original_raw_data_redistributed': False, 'quality_approved': False,
              'code_sha256': {p: sha(Path(p).read_bytes()) for p in (
                  'scripts/nasap_keyoff_paired.py', 'tests/test_nasap_keyoff_paired.py',
                  'docs/research/NASAP_KEYOFF_PAIRED_PROTOCOL_2026-11-12.md')}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    def save():
        report['files'] = reader.files
        tmp = args.output.with_suffix('.tmp')
        tmp.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
        tmp.replace(args.output)
    save()
    started = time.monotonic()
    for row in plan:
        ident = row['midi_performance']
        before = previous[ident]
        case = {'id': ident, 'composer': row['composer'], 'title': row['title']}
        if before['status'] != 'complete':
            case.update(status='prior_not_evaluated', reason=before.get('reason', 'previous gate'))
        else:
            try:
                case.update(assess(reader, row, before))
            except (ValueError, KeyError, OSError) as exc:
                case.update(status='failed_pair', error_type=type(exc).__name__, reason=str(exc)[:240])
        report['cases'].append(case)
        save()
        print(ident, case['status'], flush=True)
    report['summary'] = aggregate(report['cases'])
    expected = sum(c['status'] == 'complete' for c in old['cases'])
    report['status'] = ('complete_with_prior_exclusions'
                        if report['summary']['paired_complete'] == expected else 'incomplete')
    report['elapsed_seconds'] = time.monotonic() - started
    report['downloaded_bytes'] = reader.total
    save()
    return 0 if report['status'] == 'complete_with_prior_exclusions' else 1


if __name__ == '__main__':
    raise SystemExit(main())

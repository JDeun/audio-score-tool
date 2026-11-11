"""Frozen multi-window tempo experiment on GMD, with no reference in selection."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import platform
import time
import zipfile
from collections import Counter
from importlib.metadata import version
from pathlib import Path

import mido
import numpy as np

from scripts.drum_meter_probe import parse_midi
from scripts.gmd_audio_range_probe import (
    MAX_TOTAL_BYTES,
    RangeZipReader,
    decode_excerpt,
    detect_audio_roles,
    guarded_wav_member,
    select_audio_rows,
)
from scripts.run_drum_meter_probe import ARCHIVE_SHA256, manifest, safe_member
from scripts.tempo_consensus_probe import METHODS, SETTINGS, estimate, score
from scripts.tempo_pattern_probe import (
    BPMS,
    _acf_curve,
    _rank,
    _validated,
    audio_flux,
    event_envelope,
    select_audio,
)

RUNTIME = {'numpy': '1.26.4', 'scipy': '1.13.1', 'mido': '1.3.3'}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def fingerprint(obj):
    return digest(json.dumps(obj, sort_keys=True, allow_nan=False).encode())


def plans(rows, mode):
    """Selection uses only split/kind/length and fixed hashes, not outcomes/BPM."""
    previous_audio = select_audio(rows, [r['id'] for r in select_audio_rows(rows)])
    prior_ids = {r['id'] for r, _ in previous_audio}
    if mode == 'audio':
        prior = [(r, 'previous12_audio') for r, _ in previous_audio]
        new = [r for r in rows if r['split'] == 'validation'
               and r['time_signature'] == '4-4' and r['beat_type'] == 'beat'
               and 12 <= float(r['duration']) <= 40 and r['id'] not in prior_ids]
        new.sort(key=lambda r: digest(('consensus-audio-v1/' + r['id']).encode()))
        return prior + [(r, 'new_validation4_audio') for r in new[:4]]
    prior = [(r, 'reused_official_test') for r in rows if r['split'] == 'test']
    prior += [(r, 'reused_non_test3_4') for r in rows
              if r['split'] != 'test' and r['time_signature'] == '3-4']
    prior.sort(key=lambda item: item[0]['id'])
    new = [r for r in rows if r['split'] == 'validation' and r['time_signature'] == '4-4'
           and r['id'] not in prior_ids]
    new.sort(key=lambda r: digest(('consensus-midi-v1/' + r['id']).encode()))
    return prior + [(r, 'new_validation32_midi') for r in new[:32]]


def infer_env(env):
    before = digest(env.tobytes())
    methods, diagnostic = estimate(env)
    if before != digest(env.tobytes()) or set(methods) != set(METHODS):
        raise ValueError('input mutation or missing methods')
    # Verify the old baseline implementation, not merely an approximate rewrite.
    _env, unavailable = _validated(env)
    baseline = methods['mean8_prior120']
    if unavailable:
        if baseline['status'] != unavailable:
            raise ValueError('baseline unavailable mismatch')
    else:
        old_scores = _acf_curve(env) * np.exp(-.5 * np.log2(BPMS / 120.) ** 2)
        if float(old_scores.max()) > 1e-8:
            old_candidates = _rank(old_scores)
            if baseline['bpm'] != old_candidates[0]['bpm'] or any(
                a['bpm'] != b['bpm'] or abs(a['score'] - b['score']) > 1e-10
                for a, b in zip(baseline['candidates'], old_candidates)
            ):
                raise ValueError('earlier ACF baseline changed')
    return {'envelope_sha256': before, 'frames': len(env),
            'prior_baseline_replay_passed': True, 'methods': methods,
            'window_diagnostic': diagnostic}


def attach_truth(representations, row):
    """Called only AFTER all blind predictions at both lengths have been made."""
    truth = float(row['bpm'])
    for representation in representations.values():
        for method, prediction in list(representation['methods'].items()):
            representation['methods'][method] = {'prediction': prediction,
                                                  'evaluation': score(prediction, truth)}
    return truth


def evaluate_midi(package, base, row):
    raw = safe_member(package, base + row['midi_filename'])
    hits, _signatures, tempos = parse_midi(raw)
    if len({t for _, t in tempos}) > 1:
        return {'status': 'unsupported_tempo_change'}
    length = mido.MidiFile(file=io.BytesIO(raw)).length
    if not np.isfinite(length) or length <= 0:
        return {'status': 'no_duration'}
    representations = {}
    durations = {'primary24': min(length, 24.)}
    if length > 24.:
        durations['extended60'] = min(length, 60.)
    for context, duration in durations.items():
        for name, roles in (('kick_backbeat', {'kick', 'backbeat'}),
                            ('kick_backbeat_hat', {'kick', 'backbeat', 'hat'})):
            env, count = event_envelope([(h.time, h.weight) for h in hits
                                          if h.time < duration and h.role in roles], duration)
            value = infer_env(env)
            value.update(excerpt_seconds=duration, unique_hit_count=count)
            representations[context + '/' + name] = value
    truth = attach_truth(representations, row)
    return {'status': 'scored', 'source_sha256': digest(raw), 'source_duration': length,
            'nominal_bpm': truth, 'representations': representations}


def evaluate_audio(package, base, row):
    raw, crc, member_bytes = guarded_wav_member(package, base + row['audio_filename'])
    samples, duration, original_sr = decode_excerpt(raw, seconds=24.)
    detected = detect_audio_roles(samples)
    env, count = event_envelope([(t, w) for t, _role, w in detected], duration)
    dense = audio_flux(samples)
    representations = {'primary24/detected_hit_train': infer_env(env),
                       'primary24/continuous_flux': infer_env(dense)}
    for value in representations.values():
        value.update(excerpt_seconds=duration, unique_hit_count=count)
    truth = attach_truth(representations, row)
    return {'status': 'scored', 'source_sha256': digest(raw), 'audio_crc32': crc,
            'audio_bytes': member_bytes, 'original_sample_rate': original_sr,
            'nominal_bpm': truth, 'representations': representations}


def summarize(cases, planned):
    if (len(cases) != len(planned) or len(set(planned)) != len(planned)
            or {r['id'] for r in cases} != set(planned)):
        return None
    answer = {'planned': len(planned), 'statuses': dict(Counter(r['status'] for r in cases)),
              'all_cases_evaluated': all(r['status'] == 'scored' for r in cases),
              'groups': {}}
    for cohort in sorted({r['cohort'] for r in cases}):
        full = [r for r in cases if r['cohort'] == cohort]
        representations = sorted({rep for r in full if r['status'] == 'scored'
                                  for rep in r['representations']})
        for rep in representations:
            evaluated = [r for r in full if r['status'] == 'scored' and rep in r['representations']]
            # Long context is a separately labelled eligible subset, never full-corpus.
            denominator = len(evaluated) if rep.startswith('extended60/') else len(full)
            summary = {}
            for name in METHODS:
                values = [r['representations'][rep]['methods'][name]['evaluation'] for r in evaluated]
                predictions = [r['representations'][rep]['methods'][name]['prediction'] for r in evaluated]
                valid = [v for v in values if v['status'] == 'estimated']
                correct = sum(v['within_4pct'] for v in values)
                summary[name] = {
                    'denominator': denominator, 'evaluated': len(evaluated),
                    'estimated': len(valid), 'correct': correct,
                    'half_double': sum(v['alias'] == 'half_double' for v in values),
                    'other_wrong': sum(v['alias'] == 'other' for v in values),
                    'abstained': sum(v['status'] == 'abstained' for v in values),
                    'unavailable_or_failed': denominator - len(valid),
                    'correct_rate_all_planned': correct / denominator if denominator else None,
                    'precision_among_estimated': correct / len(valid) if valid else None,
                    'coverage': len(valid) / denominator if denominator else None,
                    'candidate_recall_at3': sum(v['candidate_recall_at3'] for v in values),
                    'reasons': dict(Counter(reason for p in predictions for reason in p.get('reasons', []))),
                }
                baseline = [r['representations'][rep]['methods'][METHODS[0]]['evaluation'] for r in evaluated]
                summary[name]['paired_repaired'] = sum(
                    not b['within_4pct'] and v['within_4pct'] for b, v in zip(baseline, values))
                summary[name]['paired_lost_correct'] = sum(
                    b['within_4pct'] and not v['within_4pct'] for b, v in zip(baseline, values))
            answer['groups'][cohort + '/' + rep] = summary
    return answer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('midi', 'audio'), required=True)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists() or args.report.is_symlink():
        parser.error('new output path required')
    if (args.archive.is_symlink() or not args.archive.is_file() or
            args.archive.stat().st_size > 8_000_000 or digest(args.archive.read_bytes()) != ARCHIVE_SHA256):
        parser.error('original checksum-bound GMD archive required')
    root = Path(__file__).resolve().parents[1]
    paths = ('scripts/tempo_consensus_probe.py', 'scripts/run_tempo_consensus_probe.py',
             'tests/test_tempo_consensus_probe.py', 'scripts/tempo_pattern_probe.py',
             'scripts/drum_meter_probe.py', 'scripts/gmd_audio_range_probe.py',
             'scripts/run_drum_meter_probe.py', 'docs/research/TEMPO_CONSENSUS_PROTOCOL_2026-11-12.md')
    report = {'status': 'started', 'mode': args.mode, 'source_revision': os.getenv('GITHUB_SHA'),
              'python': platform.python_version(), 'runtime': {p: version(p) for p in RUNTIME},
              'source_sha256': {p: digest((root / p).read_bytes()) for p in paths},
              'settings': SETTINGS, 'settings_sha256': fingerprint(SETTINGS),
              'archive_sha256': ARCHIVE_SHA256, 'reference_bpm_input': False,
              'meter_or_downbeat_inferred': False, 'api_metadata_called': False,
              'training': False, 'full_zip_sha_verified': False,
              'product_quality_approved': False, 'cases': [], 'summary': None}

    def save():
        args.report.parent.mkdir(parents=True, exist_ok=True)
        temp = args.report.with_suffix('.tmp')
        temp.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
        temp.replace(args.report)

    save()
    if report['runtime'] != RUNTIME:
        report['status'] = 'blocked_runtime_mismatch'
        save()
        return 1
    started = time.monotonic()
    with zipfile.ZipFile(args.archive) as local:
        base, rows = manifest(local)
        planned = plans(rows, args.mode)
        report['planned_ids'] = [r['id'] for r, _ in planned]
        report['planned_by_cohort'] = dict(Counter(c for _, c in planned))
        report['selection_sha256'] = fingerprint(report['planned_ids'])
        save()
        remote, package, blocked = None, None, None
        if args.mode == 'audio':
            try:
                remote = RangeZipReader()
                package = zipfile.ZipFile(remote)
                local_csv = safe_member(local, base + 'info.csv')
                if digest(local_csv) != digest(package.read(base + 'info.csv')):
                    raise ValueError('publisher metadata mismatch')
                report['info_csv_sha256'] = digest(local_csv)
                compressed = sum(package.getinfo(base + r['audio_filename']).compress_size
                                 for r, _ in planned)
                report['selected_compressed_bytes'] = compressed
                if compressed + (2 * len(planned) + 8) * 1024 ** 2 > MAX_TOTAL_BYTES:
                    raise ValueError('selection exceeds frozen budget')
            except Exception as exc:
                blocked = type(exc).__name__ + ': ' + str(exc)[:180]
        try:
            for row, cohort in planned:
                value = {'id': row['id'], 'cohort': cohort, 'split': row['split'],
                         'meter_for_reporting_only': row['time_signature'], 'beat_type': row['beat_type']}
                if blocked:
                    value.update(status='blocked_audio_access', reason=blocked)
                else:
                    try:
                        value.update(evaluate_midi(local, base, row) if args.mode == 'midi'
                                     else evaluate_audio(package, base, row))
                    except Exception as exc:
                        value.update(status='failed', reason=type(exc).__name__ + ': ' + str(exc)[:180])
                report['cases'].append(value)
                save()
                print(value['id'], value['status'], flush=True)
        finally:
            if package is not None:
                package.close()
            if remote is not None:
                report['range_requests'] = remote.requests_made
                report['range_bytes_fetched'] = remote.bytes_fetched
                report['remote_archive_bytes'] = remote.size
                remote.close()
    report['summary'] = summarize(report['cases'], report['planned_ids'])
    report['status'] = 'complete' if report['summary'] and report['summary']['all_cases_evaluated'] else 'incomplete'
    report['elapsed_seconds'] = time.monotonic() - started
    save()
    return 0 if report['status'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())

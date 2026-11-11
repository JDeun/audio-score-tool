"""GMD human drum MIDI -> metadata/drum-event meter experiment, not raw audio."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import platform
import time
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath

from scripts.drum_meter_probe import conflict, infer, metadata_candidate, parse_midi

ARCHIVE_SHA256 = '651cbc524ffb891be1a3e46d89dc82a1cecb09a57c748c7b45b844c4841dcc1e'
MAX_BYTES = 8_000_000
MAX_44 = 48
MAX_34 = 24
SPLIT = 'test'
EXPECTED_ARMS = ('events_only', 'metadata_bpm', 'metadata_bpm_meter')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def safe_member(z, member):
    parts = PurePosixPath(member).parts
    if member.startswith('/') or '..' in parts or '\\' in member:
        raise ValueError('unsafe zip path')
    info = z.getinfo(member)
    if info.file_size > MAX_BYTES:
        raise ValueError('file too large')
    return z.read(info)


def manifest(z):
    files = [n for n in z.namelist() if n.endswith('/info.csv') or n == 'info.csv']
    if len(files) != 1:
        raise ValueError('missing or ambiguous official info.csv')
    path = files[0]
    base = path.removesuffix('info.csv')
    rows = list(csv.DictReader(io.StringIO(safe_member(z, path).decode('utf-8'))))
    required = {'id', 'split', 'beat_type', 'bpm', 'time_signature', 'midi_filename'}
    if not rows or not required.issubset(rows[0]):
        raise ValueError('invalid official metadata schema')
    return base, rows


def candidates_from_manifest(rows):
    filtered = [r for r in rows if r['split'] == SPLIT
                and r['time_signature'] in ('3-4', '4-4')]
    # Predefined hash ordering, independent of model scores or labels within meter.
    by_meter = {}
    for ts, cap in (('3-4', MAX_34), ('4-4', MAX_44)):
        group = [r for r in filtered if r['time_signature'] == ts]
        by_meter[ts] = sorted(group, key=lambda r: sha(r['id'].encode()))[:cap]
    return by_meter['3-4'] + by_meter['4-4'], Counter(r['time_signature'] for r in filtered)


def supplementary_three_four(rows):
    """Post-admission exploratory 3/4 coverage, NEVER part of official test."""
    source = [r for r in rows if r['time_signature'] == '3-4'
              and r['split'] in ('validation', 'train')]
    # Validation preferred; deterministic ID hash independent of musical score.
    chosen = sorted(source, key=lambda r: (r['split'] != 'validation', sha(r['id'].encode())))
    return chosen[:16], dict(Counter(r['split'] for r in source))


def matches_bpm(estimate, truth):
    if estimate is None:
        return False
    return abs(estimate / truth - 1) <= .04


def tempo_alias(estimate, truth):
    if estimate is None:
        return None
    if matches_bpm(estimate, truth):
        return 'nominal'
    if any(abs(estimate / (truth * x) - 1) <= .04 for x in (.5, 2.)):
        return 'half_double'
    return 'other'


def case(z, prefix, row):
    base = row['midi_filename']
    if not base or base.startswith('/') or '..' in PurePosixPath(base).parts:
        raise ValueError('unsafe MIDI name')
    member = prefix + base
    raw = safe_member(z, member)
    hits, signatures, tempos = parse_midi(raw)
    label = int(row['time_signature'].split('-')[0])
    official_bpm = float(row['bpm'])
    if not math.isfinite(official_bpm) or not 35 <= official_bpm <= 260:
        raise ValueError('invalid official BPM')
    # Verify data catalog identity without letting the inference see this truth.
    meta = metadata_candidate({'recording_id': row['id'], 'bpm': official_bpm,
                              'time_signature': row['time_signature'].replace('-', '/')}, row['id'])
    if meta['status'] != 'matched':
        raise ValueError('dataset identity mismatch')
    # Actual performances may have offset tempo events; note metadata issues.
    catalog_signature = (signatures[0][1], signatures[0][2]) if signatures else None
    if catalog_signature is not None and catalog_signature != (label, 4):
        return {'id': row['id'], 'status': 'reference_mismatch',
                'metadata_meter': row['time_signature'], 'midi_meter': catalog_signature}
    if len(set((n, d) for _, n, d in signatures)) > 1:
        return {'id': row['id'], 'status': 'unsupported_meter_change'}
    if len(set(t for _, t in tempos)) > 1:
        return {'id': row['id'], 'status': 'unsupported_tempo_change'}

    raw_arm = infer(hits)
    bpm_arm = infer(hits, bpm=meta['bpm'])
    full_arm = infer(hits, bpm=meta['bpm'], meter=meta['meter'])
    arms = dict(zip(EXPECTED_ARMS, (raw_arm, bpm_arm, full_arm)))
    # Bad version of metadata must never become a silent 'exact reference'.
    spoof = metadata_candidate({'recording_id': row['id'], 'bpm': official_bpm,
                                'time_signature': '3/4' if label == 4 else '4/4'},
                               row['id'])
    unsafe_title_only = metadata_candidate({'recording_id': 'other-version',
                                           'bpm': official_bpm,
                                           'time_signature': row['time_signature'].replace('-', '/')},
                                          row['id'])
    return {
        'id': row['id'], 'status': 'scored', 'split': row['split'],
        'cohort': 'official_test' if row['split'] == 'test' else 'supplemental_3_4',
        'beat_type': row['beat_type'], 'meter': row['time_signature'],
        'metadata_bpm': official_bpm, 'sha256_midi': sha(raw),
        'kick_count': sum(h.role == 'kick' for h in hits),
        'backbeat_count': sum(h.role == 'backbeat' for h in hits),
        'hat_count': sum(h.role == 'hat' for h in hits),
        'midi_first_meter': catalog_signature,
        'midi_tempo_events': len(tempos),
        'arms': {k: {**v, 'bpm_alias': tempo_alias(v['bpm'], official_bpm),
                     'tempo_correct': matches_bpm(v['bpm'], official_bpm),
                     'meter_correct': v['meter'] == label if v['meter'] is not None else None,
                     'bar_origin_phase_correct': (min(v['phase'], label - v['phase']) <= .25
                                                  if v['phase'] is not None and v['meter'] == label
                                                  and matches_bpm(v['bpm'], official_bpm) else None)}
                 for k, v in arms.items()},
        'mismatched_external_recording_status': unsafe_title_only['status'],
        'deliberate_wrong_meter_status': conflict(raw_arm, spoof),
    }


def aggregate(results, planned):
    if len(results) != len(planned) or {r['id'] for r in results} != set(planned):
        return None
    scored = [r for r in results if r['status'] == 'scored']
    output = {'planned': len(planned), 'scored': len(scored),
              'statuses': dict(Counter(r['status'] for r in results)),
              'meter_counts': dict(Counter(r['meter'] for r in scored))}
    for arm in EXPECTED_ARMS:
        rows = [r['arms'][arm] for r in scored]
        valid = [v for v in rows if v['status'] == 'scored']
        output[arm] = {
            'scored': len(valid), 'not_scored': len(rows) - len(valid),
            'tempo_correct': sum(v['tempo_correct'] for v in valid),
            'tempo_alias_half_double': sum(v['bpm_alias'] == 'half_double' for v in valid),
            'meter_decided': sum(v['meter'] is not None for v in valid),
            'meter_correct_and_decided': sum(v['meter_correct'] is True for v in valid),
            'meter_wrong_and_decided': sum(v['meter_correct'] is False for v in valid),
            'phase_decided': sum(v['phase'] is not None for v in valid),
            'phase_correct_at_midi_origin': sum(v['bar_origin_phase_correct'] is True for v in valid),
            'phase_wrong_at_midi_origin': sum(v['bar_origin_phase_correct'] is False for v in valid),
        }
        output[arm]['by_meter'] = {}
        for meter in ('3-4', '4-4'):
            sub = [r['arms'][arm] for r in scored if r['meter'] == meter
                   and r['arms'][arm]['status'] == 'scored']
            output[arm]['by_meter'][meter] = {
                'count': len(sub), 'tempo_correct': sum(v['tempo_correct'] for v in sub),
                'meter_correct': sum(v['meter_correct'] is True for v in sub),
                'meter_wrong': sum(v['meter_correct'] is False for v in sub),
                'meter_abstain': sum(v['meter_correct'] is None for v in sub),
            }
    output['wrong_meter_conflict'] = dict(Counter(r['deliberate_wrong_meter_status']
                                                  for r in scored))
    output['title_only_rejected'] = sum(r['mismatched_external_recording_status']
                                        == 'unverified_recording' for r in scored)
    return output


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive', type=Path, required=True)
    p.add_argument('--report', type=Path, required=True)
    args = p.parse_args()
    if args.report.exists() or args.report.is_symlink():
        p.error('new output path required')
    if args.archive.is_symlink() or not args.archive.is_file() or args.archive.stat().st_size > MAX_BYTES:
        p.error('invalid source archive')
    archive_digest = sha(args.archive.read_bytes())
    if archive_digest != ARCHIVE_SHA256:
        p.error('official archive SHA mismatch')
    if os.getenv('HF_TOKEN') or os.getenv('HUGGING_FACE_HUB_TOKEN'):
        p.error('credential-free study only')
    started = time.monotonic()
    report = {
        'status': 'started', 'archive_sha256': archive_digest,
        'source_revision': os.getenv('GITHUB_SHA'), 'python': platform.python_version(),
        'scope': 'GMD human MIDI drum events, role identities GIVEN; no WAV classification',
        'data_split': SPLIT, 'max_3_4': MAX_34, 'max_4_4': MAX_44,
        'training': False, 'real_audio_extraction': False, 'api_call': False,
        'metadata_source': 'original GMD info.csv, NOT a live provider',
        'reference_midi_origin_barline': (
            'assumed beat 1 at MIDI tick zero; not separately annotated acoustic downbeat'),
        'cases': [], 'summary': None, 'quality_approved': False,
    }

    def save():
        args.report.parent.mkdir(parents=True, exist_ok=True)
        ptmp = args.report.with_suffix('.tmp')
        ptmp.write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
        ptmp.replace(args.report)

    save()
    with zipfile.ZipFile(args.archive) as z:
        prefix, rows = manifest(z)
        selection, eligible_meter_counts = candidates_from_manifest(rows)
        supplementary, supplemental_counts = supplementary_three_four(rows)
        if eligible_meter_counts.get('3-4', 0):
            supplementary = []  # official-test 3/4 already has precedence
        selection = selection + supplementary
        if len({r['id'] for r in selection}) != len(selection):
            raise ValueError('duplicated official performance identifier')
        report.update(
            planned_ids=[r['id'] for r in selection],
            official_test_meter_counts=dict(eligible_meter_counts),
            supplemental_3_4_available=dict(supplemental_counts),
            supplemental_3_4_selected=len(supplementary),
            selection_amendment='3/4 in official test absent; non-test coverage separately reported',
        )
        save()
        if not selection:
            report['status'] = 'no_supported_test_cases'
            save()
            return 1
        for r in selection:
            try:
                value = case(z, prefix, r)
            except Exception as e:
                value = {'id': r['id'], 'status': 'failed', 'error_type': type(e).__name__}
            report['cases'].append(value)
            save()
            print(r['id'], value['status'], flush=True)
    report['summary'] = aggregate(report['cases'], report['planned_ids'])
    report['summary_by_cohort'] = {}
    for cohort in ('official_test', 'supplemental_3_4'):
        group = [r for r in report['cases'] if r.get('cohort', (
            'official_test' if r.get('split', 'test') == 'test' else 'supplemental_3_4')) == cohort]
        ids = [r['id'] for r in group]
        report['summary_by_cohort'][cohort] = aggregate(group, ids) if group else None
    report['status'] = 'complete' if report['summary'] and not any(
        x['status'] == 'failed' for x in report['cases']) else 'incomplete'
    report['elapsed_seconds'] = time.monotonic() - started
    save()
    return 0 if report['status'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())

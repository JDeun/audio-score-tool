"""Frozen GMD tempo-only CPU study: human MIDI diagnostics and actual kit WAV."""
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
from scripts.tempo_pattern_probe import (
    METHODS,
    SETTINGS,
    audio_flux,
    estimate,
    event_envelope,
    fingerprint,
    score_tempo,
    select_audio,
    summarize,
)

SECONDS = 24.0
RUNTIME = {'numpy': '1.26.4', 'scipy': '1.13.1', 'librosa': '0.10.2.post1',
           'numba': '0.60.0', 'mido': '1.3.3', 'soundfile': '0.13.1'}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def infer_representation(env, count, duration):
    original = digest(env.tobytes())
    result = estimate(env, unique_hit_count=count, duration=duration)
    if digest(env.tobytes()) != original or set(result) != set(METHODS):
        raise ValueError('inference mutated observations or missed method')
    return {'envelope_sha256': original, 'envelope_frames': len(env),
            'unique_hit_count': count, 'methods': result}


def attach_reference(predictions, row):
    """Called only after ALL algorithms finish; catalog tempo cannot affect choices."""
    truth = float(row['bpm'])
    if not np.isfinite(truth) or truth <= 0:
        raise ValueError('invalid publisher nominal tempo')
    for rep in predictions.values():
        for name, result in rep['methods'].items():
            rep['methods'][name] = {'prediction': result, 'evaluation': score_tempo(result, truth)}
    return truth


def evaluate_midi(package, base, row):
    raw = safe_member(package, base + row['midi_filename'])
    hits, _signatures, tempos = parse_midi(raw)
    if len({t for _, t in tempos}) > 1:
        return {'status': 'unsupported_tempo_change'}
    length = mido.MidiFile(file=io.BytesIO(raw)).length
    if not np.isfinite(length) or length <= 0:
        return {'status': 'no_duration'}
    duration = min(SECONDS, length)
    predictions = {}
    for rep, roles in (('kick_backbeat', {'kick', 'backbeat'}),
                       ('kick_backbeat_hat', {'kick', 'backbeat', 'hat'})):
        observed = [(h.time, h.weight) for h in hits if h.role in roles and h.time < duration]
        env, count = event_envelope(observed, duration)
        predictions[rep] = infer_representation(env, count, duration)
    truth = attach_reference(predictions, row)
    return {'status': 'scored', 'nominal_bpm': truth, 'reference_in_40_240': 40 <= truth <= 240,
            'midi_sha256': digest(raw), 'excerpt_seconds': duration,
            'representations': predictions}


def evaluate_audio(package, base, row):
    raw, crc, member_bytes = guarded_wav_member(package, base + row['audio_filename'])
    samples, duration, original_sr = decode_excerpt(raw, seconds=SECONDS)
    # Source MIDI, its labels, tempo, meter and filename are NOT passed to these functions.
    detected = detect_audio_roles(samples)
    hit_env, count = event_envelope([(t, w) for t, _role, w in detected], duration)
    dense = audio_flux(samples)
    predictions = {'detected_hit_train': infer_representation(hit_env, count, duration),
                   'continuous_flux': infer_representation(dense, count, duration)}
    truth = attach_reference(predictions, row)
    return {'status': 'scored', 'nominal_bpm': truth, 'reference_in_40_240': 40 <= truth <= 240,
            'audio_sha256': digest(raw), 'audio_crc32': crc, 'audio_bytes': member_bytes,
            'original_sample_rate': original_sr, 'excerpt_seconds': duration,
            'representations': predictions}


def stamp(row, cohort):
    return {'id': row['id'], 'cohort': cohort, 'split': row['split'],
            'meter_for_reporting_only': row['time_signature'], 'beat_type': row['beat_type']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('midi', 'audio'), required=True)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists() or args.report.is_symlink():
        parser.error('new report path required')
    if (args.archive.is_symlink() or not args.archive.is_file()
            or args.archive.stat().st_size > 8_000_000
            or digest(args.archive.read_bytes()) != ARCHIVE_SHA256):
        parser.error('original checksum-bound GMD metadata archive required')
    if os.getenv('HF_TOKEN') or os.getenv('HUGGING_FACE_HUB_TOKEN'):
        parser.error('no model credentials')
    root = Path(__file__).resolve().parents[1]
    paths = ('scripts/tempo_pattern_probe.py', 'scripts/run_tempo_pattern_probe.py',
             'tests/test_tempo_pattern_probe.py', 'scripts/drum_meter_probe.py',
             'scripts/gmd_audio_range_probe.py', 'scripts/run_drum_meter_probe.py',
             'docs/research/TEMPO_PATTERN_PROTOCOL_2026-11-11.md')
    report = {'status': 'started', 'mode': args.mode, 'source_revision': os.getenv('GITHUB_SHA'),
              'python': platform.python_version(), 'runtime': {p: version(p) for p in RUNTIME},
              'source_sha256': {p: digest((root / p).read_bytes()) for p in paths},
              'settings': SETTINGS, 'settings_sha256': fingerprint(SETTINGS),
              'archive_sha256': ARCHIVE_SHA256, 'excerpt_max_seconds': SECONDS,
              'reference_bpm_used_for_inference': False, 'meter_or_phase_inferred': False,
              'real_audio': args.mode == 'audio', 'learned_model': False, 'training': False,
              'api_metadata_called': False, 'full_zip_sha_verified': False,
              'product_quality_approved': False, 'cases': [], 'summary': None}

    def save():
        args.report.parent.mkdir(parents=True, exist_ok=True)
        temp = args.report.with_suffix('.tmp')
        temp.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
        temp.replace(args.report)

    save()
    started = time.monotonic()
    if report['runtime'] != RUNTIME:
        report['status'] = 'blocked_runtime_mismatch'
        save()
        return 1
    with zipfile.ZipFile(args.archive) as local:
        base, rows = manifest(local)
        if args.mode == 'midi':
            planned = [(r, 'official_test') for r in rows if r['split'] == 'test']
            planned += [(r, 'supplemental_3_4') for r in rows
                        if r['split'] != 'test' and r['time_signature'] == '3-4']
            planned.sort(key=lambda pair: pair[0]['id'])
        else:
            old_ids = [r['id'] for r in select_audio_rows(rows)]
            planned = select_audio(rows, old_ids)
        report['planned_ids'] = [r['id'] for r, _ in planned]
        report['planned_by_cohort'] = dict(Counter(c for _, c in planned))
        report['planned_by_meter'] = dict(Counter(r['time_signature'] for r, _ in planned))
        report['planned_selection_sha256'] = fingerprint(report['planned_ids'])
        save()
        remote, package, blocked = None, None, None
        if args.mode == 'audio':
            try:
                remote = RangeZipReader()
                package = zipfile.ZipFile(remote)
                reference_csv = safe_member(local, base + 'info.csv')
                remote_csv = package.read(base + 'info.csv')
                if digest(reference_csv) != digest(remote_csv):
                    raise ValueError('publisher metadata mismatch')
                report['info_csv_sha256'] = digest(reference_csv)
                report['remote_archive_bytes'] = remote.size
                # Conservative preflight for the whole selection; never replace hard cases.
                compressed = sum(package.getinfo(base + r['audio_filename']).compress_size
                                 for r, _ in planned)
                report['selected_compressed_bytes'] = compressed
                if compressed + (2 * len(planned) + 8) * 1024 ** 2 > MAX_TOTAL_BYTES:
                    raise ValueError('selection exceeds frozen range budget')
            except Exception as exc:
                blocked = type(exc).__name__ + ': ' + str(exc)[:200]
                report['audio_access_blocked_reason'] = blocked
        try:
            for row, cohort in planned:
                result = stamp(row, cohort)
                if blocked:
                    result.update(status='blocked_audio_access', reason=blocked)
                else:
                    try:
                        result.update(evaluate_midi(local, base, row) if args.mode == 'midi'
                                      else evaluate_audio(package, base, row))
                    except Exception as exc:
                        result.update(status='failed', reason=type(exc).__name__ + ': ' + str(exc)[:200])
                report['cases'].append(result)
                save()
                print(result['id'], result['status'], flush=True)
        finally:
            if package is not None:
                package.close()
            if remote is not None:
                report['range_requests'] = remote.requests_made
                report['range_bytes_fetched'] = remote.bytes_fetched
                remote.close()
    report['summary'] = summarize(report['cases'], report['planned_ids'])
    report['status'] = ('complete' if report['summary'] and report['summary']['all_cases_evaluated']
                        else 'incomplete')
    report['elapsed_seconds'] = time.monotonic() - started
    save()
    return 0 if report['status'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())

"""Same-input CPU BPM study: immutable DSP baselines versus file-held-out Beat This."""
from __future__ import annotations

import argparse
import gc
import json
import os
import platform
import subprocess
import time
import zipfile
from importlib.metadata import version
from pathlib import Path

from scripts.gmd_audio_range_probe import (
    MAX_TOTAL_BYTES,
    RangeZipReader,
    decode_excerpt,
    detect_audio_roles,
    guarded_wav_member,
)
from scripts.run_drum_meter_probe import ARCHIVE_SHA256, manifest, safe_member
from scripts.run_tempo_consensus_probe import infer_env, plans
from scripts.tempo_beat_model_probe import (
    CHECKPOINT_ROOT,
    MODEL_BYTE_LIMIT,
    MODEL_TOTAL_LIMIT,
    PRIMARY_METHODS,
    SOURCE_REVISION,
    SPLIT_BLOB,
    SPLIT_URL,
    admitted_fold,
    annotation_key,
    bounded_download,
    bpm_from_beats,
    digest,
    parse_folds,
    summarize,
    verify_checkpoint_metadata,
)
from scripts.tempo_pattern_probe import audio_flux, event_envelope, score_tempo

RUNTIME = {'numpy': '1.26.4', 'scipy': '1.13.1', 'mido': '1.3.3',
           'torch': '2.7.1+cpu', 'torchaudio': '2.7.1+cpu',
           'einops': '0.8.1', 'rotary-embedding-torch': '0.8.6',
           'soxr': '0.5.0.post1', 'beat-this': '1.1.0'}


def unavailable(status, reason=None):
    value = {'status': status, 'bpm': None, 'candidates': []}
    if reason:
        value['reason'] = reason
    return value


def run_baselines(samples, duration):
    """Use unchanged earlier input processing and exact mean8/consensus methods."""
    hits = detect_audio_roles(samples)
    env, _count = event_envelope([(t, w) for t, _role, w in hits], duration)
    curves = {'hit': env, 'flux': audio_flux(samples)}
    result, hashes = {}, {}
    for representation, values in curves.items():
        inferred = infer_env(values)
        hashes[representation] = inferred['envelope_sha256']
        for short, method in (('mean8', 'mean8_prior120'), ('consensus', 'consensus_prior120')):
            result[f'{representation}_{short}'] = inferred['methods'][method]
    return result, hashes


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive', type=Path, required=True)
    p.add_argument('--work', type=Path, required=True)
    p.add_argument('--report', type=Path, required=True)
    p.add_argument('--upstream-source', type=Path, required=True)
    args = p.parse_args()
    if args.report.exists() or args.report.is_symlink() or args.work.exists():
        p.error('new unlinked output/work paths required')
    if (args.archive.is_symlink() or args.archive.stat().st_size > 8_000_000
            or digest(args.archive.read_bytes()) != ARCHIVE_SHA256):
        p.error('publisher MIDI ZIP checksum mismatch')
    root = Path(__file__).resolve().parents[1]
    previous = json.loads((root / 'docs/research/TEMPO_BEAT_MODEL_INPUTS_2026-11-12.json').read_text())
    expected = {x['id']: x for x in previous['inputs']}
    runtime = {name: version(name) for name in RUNTIME}
    upstream = subprocess.check_output(['git', '-C', str(args.upstream_source),
                                       'rev-parse', 'HEAD'], text=True).strip()
    if runtime != RUNTIME or upstream != SOURCE_REVISION:
        p.error('pinned runtime or upstream source mismatch')
    if os.getenv('HF_TOKEN') or os.getenv('HUGGING_FACE_HUB_TOKEN'):
        p.error('credential-free research only')
    import beat_this.inference
    import torch

    source_path = args.upstream_source / 'beat_this/inference.py'
    loaded_path = Path(beat_this.inference.__file__)
    if digest(loaded_path.read_bytes()) != digest(source_path.read_bytes()):
        p.error('installed inference source does not match pinned upstream')
    torch.set_num_threads(2)
    torch.set_num_interop_threads(2)
    torch.manual_seed(0)
    if torch.cuda.is_available():
        p.error('CPU-only runner required')
    args.work.mkdir(parents=True)
    paths = ['scripts/tempo_beat_model_probe.py', 'scripts/run_tempo_beat_model_probe.py',
             'tests/test_tempo_beat_model_probe.py', 'scripts/tempo_consensus_probe.py',
             'scripts/tempo_pattern_probe.py', 'scripts/run_tempo_consensus_probe.py',
             'scripts/gmd_audio_range_probe.py',
             'docs/research/TEMPO_BEAT_MODEL_PROTOCOL_2026-11-12.md',
             'docs/research/TEMPO_BEAT_MODEL_INPUTS_2026-11-12.json']
    report = {
        'status': 'started', 'source_revision': os.getenv('GITHUB_SHA'),
        'python': platform.python_version(), 'runtime': runtime,
        'upstream_commit': upstream, 'upstream_inference_sha256': digest(source_path.read_bytes()),
        'source_sha256': {f: digest((root / f).read_bytes()) for f in paths},
        'midi_zip_sha256': ARCHIVE_SHA256, 'audio_range_budget': MAX_TOTAL_BYTES,
        'device': 'cpu', 'float16': False, 'dbn': False,
        'bpm_rule': '60/median(diff(beats)), minimum4beats, no half/double folding',
        'training': False, 'product_quality_approved': False,
        'external_metadata_api': False, 'reference_bpm_input': False,
        'meter_or_downbeat_scored': False, 'file_level_validation_folds': True,
        'untouched_generalization_test': False, 'full_zip_sha_verified': False,
        'cases': [], 'models': {}, 'summary': None,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)

    def save():
        temp = args.report.with_suffix('.tmp')
        temp.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
        temp.replace(args.report)

    save()
    start_all = time.monotonic()
    try:
        split_path = args.work / '8-folds.split'
        split_receipt = bounded_download(SPLIT_URL, split_path, 150_000)
        mapping = parse_folds(split_path.read_bytes())
        report['fold_manifest'] = {**split_receipt, 'git_blob': SPLIT_BLOB, 'entries': len(mapping)}
    except Exception as exc:
        report.update(status='blocked_fold_manifest', reason=f'{type(exc).__name__}: {exc}')
        save()
        return 1
    samples_by_id, truths = {}, {}
    remote, package = None, None
    try:
        with zipfile.ZipFile(args.archive) as local:
            base, rows = manifest(local)
            selected = plans(rows, 'audio')
            ids = [r['id'] for r, _c in selected]
            if ids != [x['id'] for x in previous['inputs']]:
                raise ValueError('source plan differs from completed comparison')
            report['planned_ids'] = ids
            report['planned_count'] = len(ids)
            for row, cohort in selected:
                fold = admitted_fold(row['audio_filename'], mapping)
                report['cases'].append({
                    'id': row['id'], 'cohort': cohort, 'source_split': row['split'],
                    'fold': fold, 'annotation_key': annotation_key(row['audio_filename']),
                    'fold_verified': False, 'status': 'pending',
                    'methods': {m: {'prediction': unavailable('not_run')} for m in PRIMARY_METHODS},
                })
            save()
            remote = RangeZipReader()
            package = zipfile.ZipFile(remote)
            reference_csv = safe_member(local, base + 'info.csv')
            if digest(package.read(base + 'info.csv')) != digest(reference_csv):
                raise ValueError('full and MIDI archive metadata mismatch')
            report['info_csv_sha256'] = digest(reference_csv)
            report['remote_archive_bytes'] = remote.size
            compressed = sum(package.getinfo(base + r['audio_filename']).compress_size for r, _c in selected)
            if compressed + (2 * len(selected) + 8) * 1024**2 > MAX_TOTAL_BYTES:
                raise ValueError('preselected source budget exceeded')
            for (row, _cohort), receipt in zip(selected, report['cases']):
                try:
                    raw, crc, byte_count = guarded_wav_member(package, base + row['audio_filename'])
                    if digest(raw) != expected[row['id']]['source_sha256']:
                        raise ValueError('WAV differs from previous evaluation')
                    samples, duration, source_rate = decode_excerpt(raw, seconds=24.)
                    if duration != expected[row['id']]['excerpt_seconds']:
                        raise ValueError('excerpt length differs')
                    samples.setflags(write=False)
                    before = digest(samples.tobytes())
                    t0 = time.monotonic()
                    baselines, hashes = run_baselines(samples, duration)
                    for name, prediction in baselines.items():
                        receipt['methods'][name] = {'prediction': prediction}
                    receipt.update(status='baselines_complete', source_sha256=digest(raw),
                                   audio_crc32=crc, audio_bytes=byte_count, excerpt_seconds=duration,
                                   source_sample_rate=source_rate, sample_sha256=before,
                                   envelope_sha256=hashes, baseline_seconds=time.monotonic() - t0)
                    if before != digest(samples.tobytes()):
                        raise ValueError('waveform mutated')
                    samples_by_id[row['id']] = samples
                    truths[row['id']] = float(row['bpm'])
                    if receipt['fold'] is None:
                        receipt['methods']['beat_this_cv']['prediction'] = unavailable('fold_not_mapped')
                        receipt['status'] = 'model_not_admitted'
                except Exception as exc:
                    receipt.update(status='source_or_baseline_failed', reason=f'{type(exc).__name__}: {exc}')
                    truths[row['id']] = float(row['bpm'])
                save()
                print(receipt['id'], receipt['status'], 'fold', receipt['fold'], flush=True)
    except Exception as exc:
        report['preparation_error'] = f'{type(exc).__name__}: {exc}'
    finally:
        if package is not None:
            package.close()
        if remote is not None:
            report['range_requests'] = remote.requests_made
            report['range_bytes_fetched'] = remote.bytes_fetched
            remote.close()
    save()
    folds = sorted({r['fold'] for r in report['cases'] if r['fold'] is not None
                    and r['status'] == 'baselines_complete'})
    report['required_folds'] = folds
    total_weights = 0
    for fold in folds:
        chosen = [r for r in report['cases'] if r['fold'] == fold and r['status'] == 'baselines_complete']
        model_path = args.work / f'fold{fold}.ckpt'
        try:
            weights = bounded_download(f'{CHECKPOINT_ROOT}/fold{fold}.ckpt', model_path, MODEL_BYTE_LIMIT)
            total_weights += weights['bytes']
            if total_weights > MODEL_TOTAL_LIMIT:
                raise ValueError('total model download budget exceeded')
            checkpoint = torch.load(model_path, map_location='cpu', weights_only=True)
            admission = verify_checkpoint_metadata(checkpoint, fold)
            del checkpoint
            gc.collect()
            report['models'][str(fold)] = {**weights, **admission, 'status': 'verified_before_inference'}
            save()
            t0 = time.monotonic()
            model = beat_this.inference.Audio2Beats(checkpoint_path=str(model_path),
                                                    device='cpu', float16=False, dbn=False)
            report['models'][str(fold)]['load_seconds'] = time.monotonic() - t0
            for row in chosen:
                row['fold_verified'] = True
                try:
                    values = samples_by_id[row['id']]
                    before = digest(values.tobytes())
                    t0 = time.monotonic()
                    beats, _downbeats_not_used = model(values.copy(), 16000)
                    prediction = bpm_from_beats(beats, row['excerpt_seconds'])
                    prediction['inference_seconds'] = time.monotonic() - t0
                    if digest(values.tobytes()) != before:
                        raise ValueError('model input waveform mutated')
                    row['methods']['beat_this_cv']['prediction'] = prediction
                    row['status'] = 'complete'
                except Exception as exc:
                    row['methods']['beat_this_cv']['prediction'] = unavailable('model_failed', f'{type(exc).__name__}: {exc}')
                    row['status'] = 'model_failed'
                save()
                print(row['id'], row['status'], flush=True)
            del model
            gc.collect()
        except Exception as exc:
            report['models'][str(fold)] = {'status': 'blocked', 'reason': f'{type(exc).__name__}: {exc}'}
            for row in chosen:
                row['methods']['beat_this_cv']['prediction'] = unavailable('checkpoint_not_admitted')
                row['status'] = 'checkpoint_not_admitted'
            save()
    for row in report['cases']:
        truth = truths.get(row['id'])
        if truth is None:
            for value in row['methods'].values():
                value['evaluation'] = {'status': 'source_unavailable', 'alias': 'unavailable', 'within_4pct': False}
            continue
        row['nominal_bpm'] = truth
        for value in row['methods'].values():
            value['evaluation'] = score_tempo(value['prediction'], truth)
    if report['cases'] and len(report['cases']) == len(report.get('planned_ids', [])):
        report['summary'] = summarize(report['cases'], report['planned_ids'])
    report['model_download_bytes'] = total_weights
    report['elapsed_seconds'] = time.monotonic() - start_all
    report['status'] = ('complete_with_admission_limits' if report['summary'] and all(
        r['status'] in {'complete', 'model_not_admitted'} for r in report['cases']) else 'incomplete')
    save()
    return 0 if report['status'] == 'complete_with_admission_limits' else 1


if __name__ == '__main__':
    raise SystemExit(main())

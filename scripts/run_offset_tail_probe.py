"""CPU paired offset-only study; analytic meter controls remain a separate test."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import platform
import random
import resource
import time
import zipfile
from dataclasses import asdict
from importlib.metadata import distributions, version
from pathlib import Path

import numpy as np

from scripts.offset_tail_evidence import (
    ARMS,
    SETTINGS,
    aggregate,
    anchor_diagnostics,
    checked_events,
    metrical_controls,
    propose,
)


def fingerprint(notes):
    return hashlib.sha256(json.dumps([asdict(n) for n in notes], sort_keys=True,
                                    allow_nan=False).encode()).hexdigest()


def save(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    tmp.replace(path)


def bp_decoders(path, directory, original):
    from basic_pitch.constants import AUDIO_SAMPLE_RATE, FFT_HOP
    from basic_pitch.note_creation import model_output_to_notes

    from audio_score_tool.metrics import midi_notes
    from scripts.run_cpu_vocadito_candidates import digest

    before = digest(path)
    result = {}
    with np.load(path, allow_pickle=False) as arrays:
        for name, threshold in (('default', .5), ('onset065', .65)):
            copied = {key: arrays[key].copy() for key in arrays.files}
            midi, _ = model_output_to_notes(
                copied, onset_thresh=threshold, frame_thresh=.3,
                min_note_len=int(np.round(.1277 * AUDIO_SAMPLE_RATE / FFT_HOP)),
                multiple_pitch_bends=False, melodia_trick=True,
            )
            target = directory / f'{name}.mid'
            midi.write(str(target))
            result[name] = checked_events(midi_notes(target))
    if digest(path) != before or fingerprint(result['default']) != fingerprint(original):
        raise ValueError('neural-output mutation or default replay mismatch')
    return result


def run(args):
    import librosa
    from basic_pitch.note_creation import model_frames_to_time

    from scripts.run_cpu_vocadito_candidates import (
        ARCHIVE_BYTES,
        ARCHIVE_MD5,
        CASE_IDS,
        ROOT,
        digest,
        prepare,
    )
    from scripts.vocadito_reference import read_notes, score_annotations

    if (args.work.exists() or args.work.is_symlink() or args.report.exists()
            or args.report.is_symlink() or args.work.resolve().is_relative_to(ROOT)
            or args.archive.is_symlink() or args.archive.stat().st_size != ARCHIVE_BYTES
            or hashlib.md5(args.archive.read_bytes()).hexdigest() != ARCHIVE_MD5
            or os.getenv('HF_TOKEN') or os.getenv('HUGGING_FACE_HUB_TOKEN')):
        raise ValueError('fresh private paths and original credential-free corpus required')
    expected = {'librosa': '0.10.2.post1', 'numpy': '1.26.4', 'scipy': '1.13.1',
                'mir-eval': '0.8.2', 'basic-pitch': '0.4.0', 'onnxruntime': '1.20.1',
                'numba': '0.60.0', 'soundfile': '0.13.1'}
    if any(version(k) != v for k, v in expected.items()):
        raise ValueError('pinned runtime required')
    args.work.mkdir(parents=True, mode=0o700)
    random.seed(0)
    np.random.seed(0)
    bases = ('default', 'onset065') if args.model == 'basic_pitch' else ('yourmt3',)
    report = {
        'schema_version': 1, 'model': args.model, 'status': 'running', 'cases': [],
        'source_revision': os.getenv('GITHUB_SHA'), 'archive_sha256': digest(args.archive),
        'planned_case_ids': list(CASE_IDS), 'planned_bases': bases, 'planned_arms': ARMS,
        'settings': SETTINGS, 'all_cases_complete': False, 'aggregate': None,
        'python': platform.python_version(), 'platform': platform.platform(),
        'runtime': {d.metadata['Name']: d.version for d in distributions() if d.metadata['Name']},
        'script_sha256': {p: digest(ROOT / p) for p in (
            'scripts/offset_tail_evidence.py', 'scripts/run_offset_tail_probe.py',
            'scripts/vocadito_reference.py', 'scripts/run_cpu_vocadito_candidates.py')},
        'policy': {'device': 'cpu', 'threads': 2, 'training': False, 'llm': False,
                   'reference_used_for_edits': False, 'tempo_used_for_offsets': False,
                   'onsets_pitch_counts_invariant': True, 'heldout_generalization': False,
                   'training_overlap': 'unknown', 'quality_approved': False,
                   'original_hz': True, 'onset_s': .05, 'pitch_cents': 50,
                   'offset': 'max(50ms,20% reference duration)',
                   'media_predictions_weights_uploaded': False,
                   'yourmt3_corrected_arms_use_basic_pitch_auxiliary_model': args.model == 'yourmt3'},
        'metrical_controls': metrical_controls(),
    }
    save(args.report, report)
    started = time.monotonic()
    try:
        bp_dir = args.work / 'bp-model'
        bp_dir.mkdir()
        with (args.work / 'prepare.log').open('w') as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            bp, bp_identity = prepare('basic_pitch', bp_dir)
            report['basic_pitch_identity'] = bp_identity
            target = None
            if args.model == 'yourmt3':
                model_dir = args.work / 'your-model'
                model_dir.mkdir()
                target, identity = prepare('yourmt3', model_dir)
                report['yourmt3_identity'] = identity
        report['preparation_seconds'] = time.monotonic() - started
    except Exception as exc:
        report.update(status='preparation_failed', error_type=type(exc).__name__)
        save(args.report, report)
        return report
    save(args.report, report)
    with zipfile.ZipFile(args.archive) as archive:
        for case in CASE_IDS:
            directory = args.work / case
            directory.mkdir()
            audio = directory / 'source.wav'
            audio.write_bytes(archive.read(f'Audio/{case}.wav'))
            row = {'id': case, 'audio_sha256': digest(audio), 'status': 'started', 'bases': {}}
            tick = time.monotonic()
            try:
                random.seed(0)
                np.random.seed(0)
                with (directory / 'private.log').open('w') as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                    bp_notes, bp_receipt = bp(audio, directory / 'bp')
                    raw_path = directory / 'bp/raw.npz'
                    activation_hash = digest(raw_path)
                    with np.load(raw_path, allow_pickle=False) as arrays:
                        activations = arrays['note'].copy()
                    times = model_frames_to_time(len(activations))
                    if args.model == 'basic_pitch':
                        originals = bp_decoders(raw_path, directory, checked_events(bp_notes))
                    else:
                        notes, receipt = target(audio, directory / 'your')
                        row['yourmt3_receipt'] = receipt
                        originals = {'yourmt3': checked_events(notes)}
                    row['bp_receipt'] = bp_receipt
                    samples, sr = librosa.load(audio, sr=16000, mono=True)
                    duration = len(samples) / sr
                    hz, voiced, probability = librosa.pyin(
                        samples, sr=16000, fmin=55, fmax=880,
                        frame_length=2048, hop_length=160, center=True,
                        fill_na=np.nan, pad_mode='constant',
                    )
                    hz = np.where(voiced & np.isfinite(hz), hz, 0.)
                    f0_times = np.arange(len(hz), dtype=float) * .01
                    np.savez_compressed(directory / 'f0.npz', times=f0_times, hz=hz, probability=probability)
                    row['f0_sha256'] = digest(directory / 'f0.npz')
                    generated = {}
                    immutable = {b: fingerprint(n) for b, n in originals.items()}
                    for base, original in originals.items():
                        generated[base] = propose(original, times, activations, duration,
                                                   f0_times, hz, probability)
                    if ({b: fingerprint(n) for b, n in originals.items()} != immutable
                            or digest(raw_path) != activation_hash or digest(audio) != row['audio_sha256']):
                        raise ValueError('immutable input changed')
                # Truth is first read only after ALL paired predictions for this recording.
                references = {a: archive.read(f'Annotations/Notes/{case}_notes{a}.csv')
                              for a in ('A1', 'A2')}
                row['reference_sha256'] = {a: hashlib.sha256(v).hexdigest() for a, v in references.items()}
                row['activation_sha256'] = activation_hash
                row['activation_clock'] = 'upstream basic_pitch.note_creation.model_frames_to_time'
                for base, (arms, screening) in generated.items():
                    result = {'screening': screening, 'arms': {}}
                    for arm, notes in arms.items():
                        raw = originals[base]
                        entry = {'count': len(notes), 'event_sha256': fingerprint(notes),
                                 'changed_offsets': sum(x.offset != y.offset for x, y in zip(raw, notes)),
                                 'annotators': {}}
                        (directory / f'{base}-{arm}.json').write_text(json.dumps([asdict(n) for n in notes]))
                        for ann, reference in references.items():
                            score = score_annotations(notes, reference)
                            if arm != 'raw' and score['onset_f1'] != result['arms']['raw']['annotators'][ann]['onset_f1']:
                                raise ValueError('offset-only experiment changed onset F1')
                            intervals, pitches = read_notes(reference)
                            score['anchor_diagnostics'] = anchor_diagnostics(raw, notes, intervals, pitches)
                            entry['annotators'][ann] = score
                        result['arms'][arm] = entry
                    row['bases'][base] = result
                row.update(status='scored', elapsed_seconds=time.monotonic() - tick)
            except Exception as exc:
                row.update(status='failed', error_type=type(exc).__name__)
            report['cases'].append(row)
            save(args.report, report)
            print(json.dumps({'case': case, 'status': row['status']}), flush=True)
    report['aggregate'] = aggregate(report['cases'], CASE_IDS, bases)
    report['all_cases_complete'] = report['aggregate'] is not None
    report['status'] = 'complete' if report['all_cases_complete'] else 'incomplete'
    report['elapsed_seconds'] = time.monotonic() - started
    report['peak_self_rss_kib'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    report['rss_scope'] = 'parent only; subprocess model peak is NOT included'
    save(args.report, report)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model', choices=('basic_pitch', 'yourmt3'), required=True)
    for name in ('archive', 'work', 'report'):
        p.add_argument('--' + name, type=Path, required=True)
    args = p.parse_args()
    return 0 if run(args)['all_cases_complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

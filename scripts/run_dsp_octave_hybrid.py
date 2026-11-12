"""CPU paired octave-evidence ablation. No product edits, fitting or oracle choices."""
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
from collections import Counter
from dataclasses import asdict
from importlib.metadata import distributions, version
from pathlib import Path

import numpy as np

from scripts.dsp_octave_evidence import (
    ARMS,
    FRAME,
    HOP,
    SETTINGS,
    SR,
    Note,
    anchored_transitions,
    fingerprint,
    frame_gate,
    freeze_notes,
    propose,
)


def save(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    tmp.replace(path)


def f0(samples, fmax=880):
    import librosa

    hz, voiced, probability = librosa.pyin(samples, sr=SR, fmin=55, fmax=fmax,
        frame_length=FRAME, hop_length=HOP, center=True, fill_na=np.nan, pad_mode='constant')
    return np.where(voiced & np.isfinite(hz), hz, 0.), probability


def synthetic():
    t = np.arange(SR * 2) / SR
    def sine(f):
        return np.sin(2 * np.pi * f * t).astype(np.float32)
    cases = []
    # Both ranges are declared in advance; the corpus always retains55..880Hz.
    for tone in (65.406391, 110., 220., 440., 830.609395, 880., 932.327523):
        for upper in (880, 1760):
            hz, _ = f0(sine(tone), upper)
            v = hz[20:-20]
            v = v[v > 0]
            cases.append({'kind': 'range', 'tone_hz': tone, 'upper_hz': upper,
                          'voiced_frames': len(v),
                          'median_hz': float(np.median(v)) if len(v) else None,
                          'within_50_cents': float((abs(1200*np.log2(v/tone)) <= 50).mean()) if len(v) else 0.})
    controls = {
        'correct220': (sine(220), [Note(57, .2, 1.8)]),
        'octave_high220': (sine(220), [Note(69, .2, 1.8)]),
        'octave_low440': (sine(440), [Note(57, .2, 1.8)]),
        'dominant_second': (.2*sine(220)+sine(440)+.5*sine(660), [Note(69, .2, 1.8)]),
        'missing_fundamental': (sine(440)+.5*sine(660), [Note(69, .2, 1.8)]),
        'even_only_ambiguous': (sine(440)+.5*sine(880), [Note(57, .2, 1.8)]),
        'real_octave_leap': (np.where(t < 1, sine(220), sine(440)), [Note(57, .2, .8), Note(69, 1.2, 1.8)]),
        'silence': (np.zeros(len(t), dtype=np.float32), [Note(69, .2, 1.8)]),
        'seeded_noise': (np.random.default_rng(0).normal(0,.05,len(t)).astype(np.float32), [Note(69,.2,1.8)]),
    }
    for name, (samples, notes) in controls.items():
        hz, prob = f0(samples)
        arms, decisions = propose(notes, samples, hz, prob)
        cases.append({'kind': 'injected_or_clean_control', 'name': name,
                      'signal_sha256': hashlib.sha256(samples.tobytes()).hexdigest(),
                      'output_pitches': {a: [n.pitch for n in ns] for a, ns in arms.items()},
                      'decisions': decisions})
    return cases


def decode_065(raw_path, directory):
    from basic_pitch.constants import AUDIO_SAMPLE_RATE, FFT_HOP
    from basic_pitch.note_creation import model_output_to_notes

    from audio_score_tool.metrics import midi_notes

    with np.load(raw_path, allow_pickle=False) as arrays:
        values = {k: arrays[k].copy() for k in arrays.files}
    midi, _ = model_output_to_notes(values, onset_thresh=.65, frame_thresh=.3,
        min_note_len=int(np.round(.1277*AUDIO_SAMPLE_RATE/FFT_HOP)),
        multiple_pitch_bends=False, melodia_trick=True)
    target = directory / 'onset065.mid'
    midi.write(str(target))
    return freeze_notes(midi_notes(target))


def aggregate(rows, planned, bases):
    if (len(rows) != len(planned) or {r['id'] for r in rows} != set(planned)
            or any(r.get('status') != 'scored' or set(r.get('bases', {})) != set(bases) for r in rows)):
        return None
    if any(set(r['bases'][b].get('arms', {})) != set(ARMS)
           for r in rows for b in bases):
        return None
    out = {}
    for base in bases:
        out[base] = {}
        for arm in ARMS:
            records = [r['bases'][base]['arms'][arm] for r in rows]
            item = {'notes': sum(x['count'] for x in records),
                    'changed_pitches': sum(x['changed_pitches'] for x in records)}
            for metric in ('onset_f1', 'onset_offset_f1'):
                values = np.array([np.mean([x['annotators'][a][metric] for a in ('A1', 'A2')]) for x in records])
                original = np.array([np.mean([r['bases'][base]['arms']['raw']['annotators'][a][metric] for a in ('A1', 'A2')]) for r in rows])
                delta = values-original
                if not np.isfinite(values).all():
                    raise ValueError('nonfinite evaluation')
                boot = np.random.default_rng(0).choice(delta, size=(2000,len(delta)), replace=True).mean(axis=1)
                item[metric] = {'macro': float(values.mean()), 'delta': float(delta.mean()),
                    'improved': int((delta>1e-8).sum()), 'worse': int((delta < -1e-8).sum()),
                    'paired_recording_bootstrap95': np.quantile(boot,[.025,.975]).tolist()}
            item['temporal_anchor_diagnostic'] = {a: {
                k: sum(x['anchors'][a][k] for x in records)
                for k in records[0]['anchors'][a]} for a in ('A1','A2')}
            out[base][arm] = item
    return out


def run(args):
    import librosa

    from scripts.run_cpu_vocadito_candidates import (
        ARCHIVE_BYTES,
        ARCHIVE_MD5,
        CASE_IDS,
        ROOT,
        digest,
        f0_metrics,
        prepare,
    )
    from scripts.vocadito_reference import read_notes, score_annotations

    start = time.monotonic()
    if (args.work.exists() or args.work.is_symlink() or args.report.exists() or args.report.is_symlink()
            or args.work.resolve().is_relative_to(ROOT) or os.getenv('HF_TOKEN') or os.getenv('HUGGING_FACE_HUB_TOKEN')):
        raise ValueError('new private paths and no model credentials required')
    args.work.mkdir(parents=True, mode=0o700)
    report = {'status': 'started', 'task': args.task, 'source_revision': os.getenv('GITHUB_SHA'),
        'settings': SETTINGS, 'runtime': {d.metadata['Name']: d.version for d in distributions() if d.metadata['Name']},
        'python': platform.python_version(), 'platform': platform.platform(), 'cases': [],
        'source_sha256': {p: digest(ROOT/p) for p in ('scripts/dsp_octave_evidence.py',
             'scripts/run_dsp_octave_hybrid.py', 'scripts/vocadito_reference.py', 'scripts/run_cpu_vocadito_candidates.py')},
        'quality_approved': False, 'reference_used_for_edits': False, 'heldout_generalization': False,
        'training': False, 'llm': False, 'device': 'cpu', 'threads': 2, 'all_cases_complete': False}
    save(args.report, report)
    expected = {'numpy':'1.26.4','librosa':'0.10.2.post1','mir-eval':'0.8.2','scipy':'1.13.1','numba':'0.60.0'}
    try:
        if any(version(k) != v for k,v in expected.items()):
            raise ValueError('pinned CPU environment required')
        random.seed(0)
        np.random.seed(0)
        if args.task == 'signals':
            report.update(cases=synthetic(), status='complete', all_cases_complete=True)
        else:
            archive = args.archive
            if (archive is None or archive.is_symlink() or archive.stat().st_size != ARCHIVE_BYTES
                    or hashlib.md5(archive.read_bytes()).hexdigest() != ARCHIVE_MD5):
                raise ValueError('original corpus required')
            report.update(archive_sha256=digest(archive), planned_cases=list(CASE_IDS))
            bases = ('default', 'onset065') if args.task == 'basic_pitch' else ('default',)
            report['planned_bases'] = bases
            cache = args.work/'models'
            cache.mkdir()
            with (args.work/'prepare.log').open('w') as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                predictor, identity = prepare(args.task, cache)
            report['model_identity'] = identity
            with zipfile.ZipFile(archive) as package:
                for case in CASE_IDS:
                    folder = args.work/case
                    folder.mkdir()
                    audio = folder/'source.wav'
                    audio.write_bytes(package.read(f'Audio/{case}.wav'))
                    row = {'id':case, 'audio_sha256':digest(audio), 'status':'started', 'bases':{}}
                    try:
                        with (folder/'private.log').open('w') as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                            random.seed(0)
                            np.random.seed(0)
                            notes, receipt = predictor(audio, folder/'raw')
                            original = {'default':freeze_notes(notes)}
                            if args.task == 'basic_pitch':
                                original['onset065'] = decode_065(folder/'raw/raw.npz', folder)
                            y, _ = librosa.load(audio, sr=SR, mono=True)
                            hz, probability = f0(y)
                            gated = frame_gate(y, hz, probability)
                            outputs = {base:propose(ns,y,hz,probability) for base,ns in original.items()}
                        # Read all annotations ONLY after prediction/proposals have been frozen.
                        refs = {a:package.read(f'Annotations/Notes/{case}_notes{a}.csv') for a in ('A1','A2')}
                        fref = package.read(f'Annotations/F0/{case}_f0.csv')
                        row.update(reference_sha256={a:hashlib.sha256(r).hexdigest() for a,r in refs.items()},
                            f0_reference_sha256=hashlib.sha256(fref).hexdigest(), prediction_receipt=receipt)
                        times = np.arange(len(hz))*HOP/SR
                        row['f0'] = {a:f0_metrics(fref,times,track) for a,track in (('raw',hz),('gated',gated))}
                        np.savez_compressed(folder/'f0.npz', hz=hz, probability=probability, gated=gated)
                        for base, (arms, decisions) in outputs.items():
                            save(folder/f'{base}-decisions.json',decisions)
                            entry = {'reasons':dict(Counter(d['reason'] for d in decisions)),
                                'proposed':sum(d['reason']=='proposed' for d in decisions),
                                'corroborated':sum(d.get('corroborated',False) for d in decisions), 'arms':{}}
                            for arm, events in arms.items():
                                save(folder/f'{base}-{arm}.json',[asdict(n) for n in events])
                                scores, anchors = {}, {}
                                for a,r in refs.items():
                                    scores[a] = score_annotations(events,r)
                                    intervals, reference_hz = read_notes(r)
                                    anchors[a] = anchored_transitions(original[base],events,intervals,reference_hz)
                                entry['arms'][arm] = {'count':len(events), 'event_sha256':fingerprint(events),
                                    'changed_pitches':sum(a.pitch!=b.pitch for a,b in zip(original[base],events)),
                                    'annotators':scores,'anchors':anchors}
                            row['bases'][base] = entry
                        if digest(audio) != row['audio_sha256']:
                            raise ValueError('source mutated')
                        row['status'] = 'scored'
                    except Exception as exc:
                        row.update(status='failed',error_type=type(exc).__name__)
                    report['cases'].append(row)
                    save(args.report,report)
                    print(json.dumps({'case':case,'status':row['status']}),flush=True)
            report['aggregate'] = aggregate(report['cases'],CASE_IDS,bases)
            report['all_cases_complete'] = report['aggregate'] is not None
            report['status'] = 'complete' if report['all_cases_complete'] else 'incomplete'
    except Exception as exc:
        report.update(status='failed',error_type=type(exc).__name__)
    report.update(elapsed_seconds=time.monotonic()-start, peak_self_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    save(args.report,report)
    return 0 if report['all_cases_complete'] else 1


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--task',required=True,choices=('signals','basic_pitch','yourmt3'))
    p.add_argument('--archive',type=Path)
    p.add_argument('--work',type=Path,required=True)
    p.add_argument('--report',type=Path,required=True)
    return run(p.parse_args())


if __name__ == '__main__':
    raise SystemExit(main())

"""Re-infer original vocadito in private CPU storage; no product edits or promotion."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import random
import time
import zipfile
from importlib.metadata import distributions, version
from pathlib import Path

import numpy as np

from scripts.note_candidate_diagnostics import (
    candidates,
    error_partition,
    fingerprint,
    from_notes,
    metrics,
    window_oracle,
    windows,
)


def decode_threshold(raw_path, folder, threshold):
    from basic_pitch.constants import AUDIO_SAMPLE_RATE, FFT_HOP
    from basic_pitch.note_creation import model_output_to_notes

    from audio_score_tool.metrics import midi_notes

    with np.load(raw_path, allow_pickle=False) as source:
        arrays = {k: source[k].copy() for k in source.files}
    midi, _ = model_output_to_notes(arrays, onset_thresh=threshold, frame_thresh=.3,
                                    min_note_len=int(np.round(.1277*AUDIO_SAMPLE_RATE/FFT_HOP)),
                                    multiple_pitch_bends=False, melodia_trick=True)
    target = folder / f'decode-{threshold}.mid'
    midi.write(str(target))
    return from_notes(midi_notes(target))


def aggregate(rows, planned, arms):
    if (len(rows) != len(planned) or {r['id'] for r in rows} != set(planned)
            or any(r.get('status') != 'scored' or set(r.get('arms', {})) != set(arms) for r in rows)):
        return None
    result = {}
    for arm in arms:
        result[arm] = {}
        for metric in ('onset_f1', 'onset_offset_f1'):
            result[arm][metric] = float(np.mean([
                row['arms'][arm]['annotators'][a]['primary'][metric]
                for row in rows for a in ('A1', 'A2')]))
    return result


def run(args):
    import librosa
    import soundfile as sf

    from scripts.run_cpu_vocadito_candidates import (
        ARCHIVE_BYTES,
        ARCHIVE_MD5,
        CASE_IDS,
        ROOT,
        digest,
        prepare,
    )
    from scripts.vocadito_reference import read_notes, score_annotations

    if (args.work.exists() or args.work.is_symlink() or args.output.exists()
            or args.work.resolve().is_relative_to(ROOT) or args.archive.is_symlink()
            or args.archive.stat().st_size != ARCHIVE_BYTES
            or hashlib.md5(args.archive.read_bytes()).hexdigest() != ARCHIVE_MD5
            or any(os.getenv(k) for k in ('HF_TOKEN', 'HUGGING_FACE_HUB_TOKEN'))
            or version('mir-eval') != '0.8.2'):
        raise ValueError('private fresh paths, exact original corpus, scorer and no credentials required')
    args.work.mkdir(parents=True, mode=0o700)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    arms = ('raw', 'onset_065') if args.model == 'basic_pitch' else ('raw',)
    report = {'schema_version': 1, 'model': args.model, 'status': 'running', 'cases': [],
              'planned_case_ids': list(CASE_IDS), 'planned_arms': list(arms),
              'source_revision': os.getenv('GITHUB_SHA'), 'archive_sha256': digest(args.archive),
              'script_sha256': {p: digest(ROOT/p) for p in (
                  'scripts/run_note_candidate_diagnostics.py', 'scripts/note_candidate_diagnostics.py',
                  'scripts/run_cpu_vocadito_candidates.py', 'scripts/vocadito_reference.py')},
              'runtime': {d.metadata['Name']: d.version for d in distributions() if d.metadata['Name']},
              'protocol': {'device': 'cpu', 'threads': 2, 'seed': 0, 'training': False,
                  'development_corpus': True, 'independent_validation': False,
                  'training_overlap': 'unknown', 'production_policy_changed': False,
                  'oracle_is_deployable': False, 'references_used_to_generate_candidates': False,
                  'oracle_scope': 'independent local window, one edit, metric-specific maximum',
                  'window_seconds': 4, 'maximum_windows_per_recording': 3,
                  'maximum_candidates_per_window': 17, 'onset_tolerance': .05,
                  'pitch_tolerance_cents': 50, 'offset_tolerance': 'max(.05,.2*duration)',
                  'partition': 'priority-dependent heuristic, not confirmed causal error labels'},
              'aggregate': None, 'quality_approved': False}

    def save():
        temp = args.output.with_suffix('.tmp')
        temp.write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
        temp.replace(args.output)

    save()
    try:
        random.seed(0)
        np.random.seed(0)
        model_root = args.work/'models'
        model_root.mkdir()
        with (args.work/'prepare.log').open('w') as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            predict, identity = prepare(args.model, model_root)
        report['model_identity'] = identity
    except Exception as exc:
        report.update(status='preparation_failed', error_type=type(exc).__name__)
        save()
        return 1
    with zipfile.ZipFile(args.archive) as archive:
        for name in CASE_IDS:
            folder = args.work/name
            folder.mkdir()
            audio = folder/'source.wav'
            audio.write_bytes(archive.read(f'Audio/{name}.wav'))
            row = {'id': name, 'status': 'started', 'audio_sha256': digest(audio), 'arms': {}}
            begun = time.monotonic()
            try:
                random.seed(0)
                np.random.seed(0)
                with (folder/'inference.log').open('w') as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                    source, receipt = predict(audio, folder/'raw')
                    raw = from_notes(source)
                    before = fingerprint(raw)
                    predictions = {'raw': raw}
                    if args.model == 'basic_pitch':
                        asset = folder/'raw/raw.npz'
                        raw_digest = digest(asset)
                        replay = decode_threshold(asset, folder, .5)
                        if fingerprint(replay) != before:
                            raise ValueError('baseline decoder replay mismatch')
                        predictions['onset_065'] = decode_threshold(asset, folder, .65)
                        if digest(asset) != raw_digest:
                            raise ValueError('model activations mutated')
                    y, sr = librosa.load(str(audio), sr=22050, mono=True)
                    peaks = librosa.onset.onset_detect(y=y, sr=sr, hop_length=220,
                                                       backtrack=False, units='time')
                selected = windows(name, sf.info(audio).duration)
                proposals = {}
                for arm, events in predictions.items():
                    proposals[arm] = [candidates([n for n in events if lo <= n.onset < hi],
                                                 peaks, lo, hi) for lo, hi in selected]
                # FIRST access to annotation bytes. No reference is passed into candidate creation.
                refs = {a: archive.read(f'Annotations/Notes/{name}_notes{a}.csv') for a in ('A1', 'A2')}
                if before != fingerprint(raw) or digest(audio) != row['audio_sha256']:
                    raise ValueError('original mutated')
                row.update(prediction_receipt=receipt, raw_fingerprint=before,
                           reference_sha256={a: hashlib.sha256(b).hexdigest() for a, b in refs.items()})
                for arm, events in predictions.items():
                    entry = {'event_sha256': fingerprint(events), 'count': len(events),
                             'windows': [{'start': lo, 'end': hi,
                                          'candidate_kinds': [c['kind'] for c in option],
                                          'candidate_fingerprints': [fingerprint(c['notes']) for c in option]}
                                         for (lo, hi), option in zip(selected, proposals[arm])],
                             'annotators': {}}
                    for a, reference in refs.items():
                        ref_i, ref_p = read_notes(reference)
                        primary = score_annotations(events, reference)
                        independent = metrics(events, ref_i, ref_p)
                        if any(abs(primary[k]-independent[k]) > 1e-7
                               for k in ('onset_f1', 'onset_offset_f1')):
                            raise ValueError('primary scorer parity failure')
                        local = []
                        for (lo, hi), options in zip(selected, proposals[arm]):
                            keep = (ref_i[:, 0] >= lo) & (ref_i[:, 0] < hi)
                            local.append(window_oracle(options, ref_i[keep], ref_p[keep]))
                        entry['annotators'][a] = {'primary': primary,
                            'partition': error_partition(events, ref_i, ref_p), 'windows': local}
                    row['arms'][arm] = entry
                row.update(status='scored', seconds=time.monotonic()-begun)
            except Exception as exc:
                row.update(status='failed', error_type=type(exc).__name__)
                (folder/'error.txt').write_text(str(exc))
            report['cases'].append(row)
            save()
            print(json.dumps({'model': args.model, 'case': name, 'status': row['status']}), flush=True)
    report['aggregate'] = aggregate(report['cases'], CASE_IDS, arms)
    report['status'] = 'complete' if report['aggregate'] is not None else 'incomplete'
    save()
    return 0 if report['status'] == 'complete' else 1


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model', choices=['basic_pitch', 'yourmt3'], required=True)
    for name in ('archive', 'work', 'output'):
        p.add_argument('--'+name, type=Path, required=True)
    return run(p.parse_args())


if __name__ == '__main__':
    raise SystemExit(main())

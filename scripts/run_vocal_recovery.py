"""Paired CPU research: fixed neural outputs, reference-free edits, no product changes."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import platform
import random
import time
import zipfile
from dataclasses import asdict
from importlib.metadata import distributions, version
from pathlib import Path

import numpy as np

from scripts.vocal_recovery import (
    aggregate,
    event_digest,
    events_from,
    matched_transition,
    octave_proposals,
    onset_proposals,
)

ARMS = {
    'yourmt3_recovery': ('raw', 'octave_only', 'onset_only', 'octave_and_onset'),
    'basic_pitch_decode': ('raw', 'minimum_64ms', 'onset_065', 'frame_050', 'no_melodia'),
}
DECODE = {
    'raw': (0.5, 0.3, 127.7, True),
    'minimum_64ms': (0.5, 0.3, 64.0, True),
    'onset_065': (0.65, 0.3, 127.7, True),
    'frame_050': (0.5, 0.5, 127.7, True),
    'no_melodia': (0.5, 0.3, 127.7, False),
}


def score_with_diagnostics(notes, reference: bytes):
    """Relaxations are sensitivity diagnostics, NOT mutually exclusive error counts."""
    import mir_eval.transcription as mt
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import maximum_bipartite_matching

    from scripts.vocadito_reference import read_notes, score_annotations

    intervals, hz = read_notes(reference)
    positions = [i for i, n in enumerate(notes) if not n.is_drum]
    predicted = np.array([(notes[i].onset, notes[i].offset) for i in positions]).reshape(-1, 2)
    pitch = np.array([440 * 2 ** ((notes[i].pitch - 69) / 12) for i in positions])
    result = score_annotations(notes, reference)

    def matching(tolerance=.05, fold=False):
        if not positions:
            return []
        if fold:
            # Circular cents avoids false mismatches at the octave wrap boundary.
            cents = 1200 * np.log2(hz[:, None] / pitch[None, :])
            circular = np.abs((cents + 600) % 1200 - 600)
            temporal = np.abs(intervals[:, 0, None] - predicted[None, :, 0])
            edges = (circular <= 50) & (temporal <= tolerance)
            pairs = maximum_bipartite_matching(csr_matrix(edges), perm_type='column')
            return [(i, int(j)) for i, j in enumerate(pairs) if j >= 0]
        return mt.match_notes(intervals, hz, predicted, pitch, onset_tolerance=tolerance,
                              pitch_tolerance=50, offset_ratio=None)

    strict = matching()
    result.update(
        predicted_note_count=len(positions), onset_matched=len(strict),
        onset_precision=len(strict) / len(positions) if positions else 0.,
        onset_recall=len(strict) / len(intervals),
        diagnostic_onset_100ms_f1=2 * len(matching(.1)) / (len(intervals) + len(positions)),
        diagnostic_pitch_class_50ms_f1=2 * len(matching(fold=True)) / (len(intervals) + len(positions)),
        diagnostic_onset_only_50ms_f1=(mt.onset_precision_recall_f1(intervals, predicted)[2]
                                      if positions else 0.),
    )
    return result, {positions[p] for _, p in strict}


def decode_arms(raw_path: Path, output: Path, original):
    from basic_pitch.constants import AUDIO_SAMPLE_RATE, FFT_HOP
    from basic_pitch.note_creation import model_output_to_notes

    from audio_score_tool.metrics import midi_notes
    from scripts.run_cpu_vocadito_candidates import digest

    before = digest(raw_path)
    arms = {}
    with np.load(raw_path, allow_pickle=False) as arrays:
        for arm, (onset, frame, minimum, melodia) in DECODE.items():
            # The upstream decoder can mutate its arrays. Each arm gets fresh copies.
            raw = {key: arrays[key].copy() for key in arrays.files}
            midi, _ = model_output_to_notes(
                raw, onset_thresh=onset, frame_thresh=frame,
                min_note_len=int(np.round(minimum / 1000 * AUDIO_SAMPLE_RATE / FFT_HOP)),
                multiple_pitch_bends=False, melodia_trick=melodia,
            )
            target = output / f'{arm}.mid'
            midi.write(str(target))
            arms[arm] = events_from(midi_notes(target))
    if digest(raw_path) != before or event_digest(arms['raw']) != event_digest(original):
        raise ValueError('Network-output mutation or baseline decoder replay mismatch')
    return arms


def run(task: str, archive: Path, work: Path, output: Path) -> dict:
    from scripts.run_cpu_vocadito_candidates import (
        ARCHIVE_BYTES,
        ARCHIVE_MD5,
        CASE_IDS,
        ROOT,
        digest,
        prepare,
    )

    if (task not in ARMS or work.exists() or work.is_symlink() or output.exists() or output.is_symlink()
            or work.resolve().is_relative_to(ROOT) or archive.is_symlink()
            or archive.stat().st_size != ARCHIVE_BYTES
            or hashlib.md5(archive.read_bytes()).hexdigest() != ARCHIVE_MD5):
        raise ValueError('Invalid workspace or original corpus')
    if version('mir-eval') != '0.8.2' or os.getenv('HF_TOKEN') or os.getenv('HUGGING_FACE_HUB_TOKEN'):
        raise ValueError('Pinned scorer and credential-free runtime required')
    work.mkdir(parents=True, mode=0o700)
    output.parent.mkdir(parents=True, exist_ok=True)
    random.seed(0)
    np.random.seed(0)
    report = {
        'schema_version': 1, 'task': task, 'status': 'running', 'cases': [],
        'planned_case_ids': list(CASE_IDS), 'planned_arms': list(ARMS[task]),
        'archive_sha256': digest(archive), 'source_revision': os.getenv('GITHUB_SHA'),
        'python': platform.python_version(), 'platform': platform.platform(),
        'runtime': {d.metadata['Name']: d.version for d in distributions() if d.metadata['Name']},
        'source_sha256': {p: digest(ROOT / p) for p in (
            'scripts/run_vocal_recovery.py', 'scripts/vocal_recovery.py',
            'scripts/vocadito_reference.py', 'scripts/run_cpu_vocadito_candidates.py')},
        'protocol': {'device': 'cpu', 'seed': 0, 'threads': 2, 'training': False,
                     'llm': False, 'heldout_generalization': False, 'training_overlap': 'unknown',
                     'annotations_used_for_edits': False, 'original_hz': True,
                     'primary_onset_seconds': .05, 'pitch_cents': 50,
                     'offset': 'max(50ms,20% reference duration)',
                     'parameter_selection_from_results': False,
                     'bootstrap_unit': 'recording; both annotators averaged within recording',
                     'media_or_predictions_published': False},
        'decode_settings': DECODE if task == 'basic_pitch_decode' else None,
        'all_cases_complete': False, 'aggregate': None, 'quality_approved': False,
    }

    def save():
        temporary = output.with_suffix('.tmp')
        temporary.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
        temporary.replace(output)

    save()
    setup = work / 'models'
    setup.mkdir()
    try:
        with (work / 'prepare.log').open('w') as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            predictor, identity = prepare('yourmt3' if task == 'yourmt3_recovery' else 'basic_pitch', setup)
            report['model_identity'] = identity
            if task == 'yourmt3_recovery':
                tiny, tiny_identity = prepare('torchcrepe_tiny', setup)
                report['tiny_identity'] = tiny_identity
    except Exception as exc:
        report.update(status='preparation_failed', error_type=type(exc).__name__)
        save()
        return report
    save()
    with zipfile.ZipFile(archive) as package:
        for case in CASE_IDS:
            root = work / case
            root.mkdir()
            audio = root / 'source.wav'
            audio.write_bytes(package.read(f'Audio/{case}.wav'))
            row = {'id': case, 'audio_sha256': digest(audio), 'arms': {}, 'status': 'running'}
            started = time.perf_counter()
            try:
                random.seed(0)
                np.random.seed(0)
                with (root / 'inference.log').open('w') as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                    notes, receipt = predictor(audio, root / 'raw')
                    raw = events_from(notes)
                    fingerprint = event_digest(raw)
                    if task == 'basic_pitch_decode':
                        arms = decode_arms(root / 'raw/raw.npz', root, raw)
                    else:
                        import librosa
                        import torch

                        torch.manual_seed(0)
                        (times, hz), f0_receipt = tiny(audio, root / 'f0')
                        row['f0_prediction_sha256'] = f0_receipt['prediction_f0_sha256']
                        samples, sr = librosa.load(str(audio), sr=22050, mono=True)
                        peaks = librosa.onset.onset_detect(y=samples, sr=sr, hop_length=220,
                                                           backtrack=False, units='time')
                        octave = octave_proposals(raw, times, hz)
                        arms = {'raw': raw, 'octave_only': octave,
                                'onset_only': onset_proposals(raw, peaks),
                                'octave_and_onset': onset_proposals(octave, peaks)}
                if fingerprint != event_digest(raw) or digest(audio) != row['audio_sha256']:
                    raise ValueError('Immutable raw prediction or source changed')
                # Reference annotations are first accessed AFTER all candidate predictions.
                references = {a: package.read(f'Annotations/Notes/{case}_notes{a}.csv')
                              for a in ('A1', 'A2')}
                row['reference_sha256'] = {a: hashlib.sha256(v).hexdigest() for a, v in references.items()}
                row['raw_event_sha256'] = fingerprint
                row['prediction_receipt'] = receipt
                baseline_matches = {}
                for arm, events in arms.items():
                    private = root / f'{arm}.events.json'
                    private.write_text(json.dumps([asdict(n) for n in events], allow_nan=False))
                    entry = {'event_sha256': event_digest(events), 'count': len(events), 'annotators': {}}
                    if task == 'yourmt3_recovery':
                        if len(events) != len(raw):
                            raise ValueError('Correction changed event count')
                        entry['changed_pitches'] = sum(a.pitch != b.pitch for a, b in zip(raw, events))
                        entry['changed_onsets'] = sum(a.onset != b.onset for a, b in zip(raw, events))
                        if any((a.offset, a.channel, a.program, a.is_drum)
                               != (b.offset, b.channel, b.program, b.is_drum)
                               for a, b in zip(raw, events)):
                            raise ValueError('Correction changed offset or instrument identity')
                    for annotator, reference in references.items():
                        metrics, matches = score_with_diagnostics(events, reference)
                        if arm == 'raw':
                            baseline_matches[annotator] = matches
                        elif task == 'yourmt3_recovery':
                            metrics.update(matched_transition(baseline_matches[annotator], matches))
                        entry['annotators'][annotator] = metrics
                    row['arms'][arm] = entry
                row.update(status='scored', elapsed_seconds=time.perf_counter() - started)
            except Exception as exc:
                row.update(status='failed', error_type=type(exc).__name__)
            report['cases'].append(row)
            save()
            print(f"{task}: {case}: {row['status']}", flush=True)
    report['aggregate'] = aggregate(report['cases'], CASE_IDS, ARMS[task])
    report['all_cases_complete'] = report['aggregate'] is not None
    report['status'] = 'complete' if report['all_cases_complete'] else 'incomplete'
    save()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task', choices=ARMS, required=True)
    for name in ('archive', 'work', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    return 0 if run(args.task, args.archive, args.work, args.output)['all_cases_complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

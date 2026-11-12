"""Frozen vocadito waveform-gate experiment; metadata-only evidence export."""
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
from importlib.metadata import version
from pathlib import Path
from statistics import mean

import numpy as np

from scripts.audio_gate_rest import (
    ARMS,
    MODES,
    SETTINGS,
    apply_gate,
    gains_and_damage,
    gate_levels,
    mask_intervals,
    occupancy_score,
    rms_envelope,
    scored_notes,
)
from scripts.vocal_recovery import event_digest, events_from

BASELINE_ZIP_SHA = '6dc61e728c749ebfe8a51b3d4eea94026d18ca2cb6ec59c4e4ff734894cda3b0'
BASELINE_REPORT_SHA = 'dff293dc36a6642141cd235d8d958770e01d4bcd90f6f67c2ae0f82ae465309c'
BASES = {'default': 'raw', 'onset065': 'onset_065'}
EXPECTED = {'numpy': '1.26.4', 'scipy': '1.13.1', 'mir-eval': '0.8.2',
            'librosa': '0.10.2.post1', 'soundfile': '0.13.1', 'numba': '0.60.0',
            'basic-pitch': '0.4.0', 'onnxruntime': '1.20.1'}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def baseline_receipt(path):
    if path.is_symlink() or path.stat().st_size > 1_000_000:
        raise ValueError('invalid baseline path/size')
    data = path.read_bytes()
    if digest(data) != BASELINE_ZIP_SHA:
        raise ValueError('archived baseline ZIP changed')
    with zipfile.ZipFile(path) as archive:
        if archive.namelist() != ['basic_pitch_decode.json']:
            raise ValueError('unexpected baseline member')
        raw = archive.read('basic_pitch_decode.json')
    if digest(raw) != BASELINE_REPORT_SHA:
        raise ValueError('baseline report changed')
    report = json.loads(raw)
    if report['status'] != 'complete' or not report['all_cases_complete']:
        raise ValueError('incomplete baseline')
    return report


def summarize(cases, planned):
    if (len(cases) != len(planned) or {r['id'] for r in cases} != set(planned)
            or any(r['status'] != 'scored' for r in cases)):
        return None
    result = {'recordings': len(cases), 'annotators': ['A1', 'A2'], 'bases': {}}
    for base in BASES:
        result['bases'][base] = {}
        for arm in ARMS:
            values = [r['bases'][base]['arms'][arm]['annotators'][a]
                      for r in cases for a in ('A1', 'A2')]
            entry = {m: mean(v[m] for v in values) for m in ('onset_f1', 'onset_offset_f1')}
            entry['by_annotator'] = {a: {
                m: mean(r['bases'][base]['arms'][arm]['annotators'][a][m] for r in cases)
                for m in ('onset_f1', 'onset_offset_f1')} for a in ('A1', 'A2')}
            entry['occupancy_totals'] = {key: sum(v['occupancy'][key] for v in values)
                                        for key in ('reference_note_s', 'reference_gap_s',
                                                    'correct_gap_s', 'lost_note_s',
                                                    'filled_reference_gap_s')}
            for m in ('onset', 'onset_offset'):
                entry[m + '_transition'] = {
                    k: sum(v['transition'][m][k] for v in values) for k in ('gained', 'damaged')}
            deltas = [mean(r['bases'][base]['arms'][arm]['annotators'][a]['onset_offset_f1']
                           - r['bases'][base]['arms']['raw']['annotators'][a]['onset_offset_f1']
                           for a in ('A1', 'A2')) for r in cases]
            entry['paired_recordings'] = {'improved': sum(x > 1e-9 for x in deltas),
                                           'worsened': sum(x < -1e-9 for x in deltas),
                                           'equal': sum(abs(x) <= 1e-9 for x in deltas)}
            entry['changed_parents'] = sum(r['bases'][base]['arms'][arm]['edits']['changed_parents']
                                            for r in cases) if arm != 'raw' else 0
            entry['output_notes'] = sum(r['bases'][base]['arms'][arm]['count'] for r in cases)
            result['bases'][base][arm] = entry
    result['gate_evidence'] = {}
    for mode in MODES:
        result['gate_evidence'][mode] = {}
        for a in ('A1', 'A2'):
            vals = [r['gates'][mode]['annotators'][a] for r in cases]
            sums = {k: sum(v[k] for v in vals) for k in ('reference_note_s', 'reference_gap_s',
                     'correct_gap_s', 'lost_note_s', 'filled_reference_gap_s')}
            tp, fp, fn = sums['correct_gap_s'], sums['lost_note_s'], sums['filled_reference_gap_s']
            sums.update(gap_precision=tp/(tp+fp) if tp+fp else None,
                        gap_recall=tp/(tp+fn) if tp+fn else None)
            result['gate_evidence'][mode][a] = sums
    result['relative_gain_changed_frames'] = sum(
        v['relative_changed_frames'] for r in cases for v in r['gain_checks'].values())
    return result


def main():
    import soundfile as sf

    from scripts.run_cpu_vocadito_candidates import ARCHIVE_BYTES, ARCHIVE_MD5, CASE_IDS, prepare
    from scripts.run_offset_tail_probe import bp_decoders
    from scripts.vocadito_reference import read_notes

    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('archive', 'baseline', 'work', 'output'):
        parser.add_argument('--' + key, required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if (args.output.exists() or args.output.is_symlink() or args.work.exists()
            or args.work.is_symlink() or args.work.resolve().is_relative_to(root)
            or args.archive.is_symlink() or args.archive.stat().st_size != ARCHIVE_BYTES
            or hashlib.md5(args.archive.read_bytes()).hexdigest() != ARCHIVE_MD5):
        raise ValueError('fresh private paths and original corpus required')
    if os.getenv('HF_TOKEN') or os.getenv('HUGGING_FACE_HUB_TOKEN'):
        raise ValueError('no model credentials permitted')
    if any(version(k) != v for k, v in EXPECTED.items()):
        raise ValueError('pinned numeric/model runtime required')
    previous = baseline_receipt(args.baseline)
    if digest(args.archive.read_bytes()) != previous['archive_sha256']:
        raise ValueError('changed musical source corpus')
    expected_cases = {r['id']: r for r in previous['cases']}
    if set(expected_cases) != set(CASE_IDS):
        raise ValueError('baseline source coverage mismatch')
    args.work.mkdir(parents=True, mode=0o700)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = {'status': 'running', 'cases': [], 'planned_ids': list(CASE_IDS),
              'source_revision': os.getenv('GITHUB_SHA', 'local'),
              'source_head': os.getenv('EXPERIMENT_HEAD', 'local'),
              'baseline_zip_sha256': BASELINE_ZIP_SHA,
              'archive_sha256': previous['archive_sha256'], 'settings': SETTINGS,
              'runtime': {k: version(k) for k in EXPECTED}, 'python': platform.python_version(),
              'summary': None, 'quality_approved': False, 'model_inference_repeated': True,
              'explicit_notated_rest_reference': False, 'joint_bar_decoder_evaluated': False,
              'reused_development_corpus': True, 'gate_used_reference': False,
              'gain_tests_are_unclipped_float_amplitude_changes': True,
              'source_sha256': {p: digest((root / p).read_bytes()) for p in (
                  'scripts/audio_gate_rest.py', 'scripts/run_audio_gate_rest.py',
                  'tests/test_audio_gate_rest.py',
                  'docs/research/AUDIO_GATE_REST_PROTOCOL_2026-11-12.md',
                  'scripts/run_cpu_vocadito_candidates.py', 'scripts/vocadito_reference.py',
                  'scripts/run_offset_tail_probe.py', 'scripts/vocal_recovery.py')}}
    def save():
        tmp = args.output.with_suffix('.tmp')
        tmp.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
        tmp.replace(args.output)
    save()
    started = time.monotonic()
    model_dir = args.work / 'model'
    model_dir.mkdir()
    with (args.work / 'model.log').open('w') as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        predict, identity = prepare('basic_pitch', model_dir)
    report['model_identity'] = identity
    save()
    with zipfile.ZipFile(args.archive) as archive:
        for case in CASE_IDS:
            tick = time.monotonic()
            row = {'id': case, 'status': 'started'}
            folder = args.work / case
            folder.mkdir()
            try:
                raw_audio = archive.read(f'Audio/{case}.wav')
                expected = expected_cases[case]
                if digest(raw_audio) != expected['audio_sha256']:
                    raise ValueError('audio changed from baseline')
                audio = folder / 'source.wav'
                audio.write_bytes(raw_audio)
                samples, sr = sf.read(audio, dtype='float64', always_2d=True)
                if len(samples)/sr > 120 or not np.isfinite(samples).all():
                    raise ValueError('invalid or oversized audio')
                edges, levels = rms_envelope(samples, int(sr))
                gates = {mode: gate_levels(levels, mode) for mode in MODES}
                gain_checks = {}
                for db in (-12, 12):
                    scaled_edges, scaled_levels = rms_envelope(samples * 10 ** (db/20), int(sr))
                    if not np.array_equal(edges, scaled_edges):
                        raise ValueError('gain changed clock')
                    gain_checks[str(db)] = {
                        mode + '_changed_frames': int(np.sum(gate_levels(scaled_levels, mode)[0]
                                                            != gates[mode][0])) for mode in MODES}
                random.seed(0)
                np.random.seed(0)
                with (folder / 'model.log').open('w') as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                    raw_notes, receipt = predict(audio, folder / 'inference')
                    originals = bp_decoders(folder / 'inference/raw.npz', folder, events_from(raw_notes))
                predictions = {}
                for base, original in originals.items():
                    if event_digest(original) != expected['arms'][BASES[base]]['event_sha256']:
                        raise ValueError('original neural-note replay mismatch: ' + base)
                    predictions[base] = {'raw': (original, {'changed_parents': 0})}
                    for mode, (quiet, _) in gates.items():
                        for policy in ('hard', 'soft'):
                            predictions[base][mode + '_' + policy] = apply_gate(
                                original, edges, quiet, policy)
                # No note/f0 reference was read before all candidates were frozen above.
                references = {a: archive.read(f'Annotations/Notes/{case}_notes{a}.csv')
                              for a in ('A1', 'A2')}
                if {a: digest(b) for a, b in references.items()} != expected['reference_sha256']:
                    raise ValueError('annotation changed')
                row.update(audio_sha256=digest(raw_audio),
                           reference_sha256=expected['reference_sha256'],
                           duration_s=len(samples)/sr, gain_checks=gain_checks,
                           source_prediction_receipt=receipt, gates={}, bases={})
                for mode, (quiet, settings) in gates.items():
                    active = mask_intervals(edges, ~quiet)
                    row['gates'][mode] = {**settings, 'quiet_frames': int(quiet.sum()),
                        'total_frames': len(quiet),
                        'annotators': {a: occupancy_score(active, read_notes(raw)[0], edges)
                                       for a, raw in references.items()}}
                for base, variants in predictions.items():
                    entries = {}
                    for arm in ARMS:
                        notes, edits = variants[arm]
                        metrics = {a: scored_notes(notes, raw, edges) for a, raw in references.items()}
                        if arm == 'raw':
                            for a, value in metrics.items():
                                for metric in ('onset_f1', 'onset_offset_f1'):
                                    if value[metric] != expected['arms'][BASES[base]]['annotators'][a][metric]:
                                        raise ValueError('baseline score failed exact replay')
                        for a, value in metrics.items():
                            before = metrics[a] if arm == 'raw' else entries['raw']['annotators'][a]
                            value['transition'] = {m: gains_and_damage(
                                before[m + '_reference_mask'], value[m + '_reference_mask'])
                                for m in ('onset', 'onset_offset')}
                        entries[arm] = {'count': len(notes), 'event_sha256': event_digest(notes),
                                        'edits': edits, 'annotators': metrics}
                    row['bases'][base] = {'arms': entries}
                if digest(audio.read_bytes()) != row['audio_sha256']:
                    raise ValueError('source waveform changed')
                row['status'] = 'scored'
            except Exception as exc:
                row.update(status='failed', error_type=type(exc).__name__, reason=str(exc)[:300])
            row['elapsed_seconds'] = time.monotonic() - tick
            report['cases'].append(row)
            save()
            print(case, row['status'], row.get('reason', ''), flush=True)
    report['summary'] = summarize(report['cases'], CASE_IDS)
    report['status'] = 'complete' if report['summary'] is not None else 'incomplete'
    report['elapsed_seconds'] = time.monotonic() - started
    save()
    return 0 if report['status'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())

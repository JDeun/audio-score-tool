"""Replay the frozen vocal gate, then attribute its fixed choices by edit type."""
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

from scripts.audio_gate_attribution import ARMS, make_attribution_arms, rms_envelope
from scripts.audio_gate_replay import verify_gate_replay
from scripts.audio_gate_rest import SETTINGS, gains_and_damage, gate_levels, scored_notes
from scripts.audio_gate_rest import rms_envelope as legacy_envelope
from scripts.audit_waveform_gate_receipts import load_receipts
from scripts.run_audio_gate_rest import BASES, EXPECTED
from scripts.vocal_recovery import event_digest, events_from

ANNOTATORS = ('A1', 'A2')
METRICS = ('onset_f1', 'onset_offset_f1')
INCOMPLETE_ZIP = 'waveform-gate-attribution-incomplete-43178487837.zip'
INCOMPLETE_ZIP_SHA = '40df7f512ebf0680af7393ba0bf8c413dc9db716572803e162f74c9bfd4db388'
INCOMPLETE_REPORT_SHA = '3391f88dd327d0752cab62cc788d52321e5bf07c5ab28feffef695768675a088'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def comparison_counts(values):
    return {'improved': sum(x > 1e-9 for x in values),
            'worsened': sum(x < -1e-9 for x in values),
            'equal': sum(abs(x) <= 1e-9 for x in values)}


def summarize(cases, planned):
    """Only a complete paired cohort can produce the primary aggregate."""
    if (len(cases) != len(planned) or len(set(planned)) != len(planned)
            or {r.get('id') for r in cases} != set(planned)
            or any(r.get('status') != 'scored' for r in cases)):
        return None
    if any(set(r.get('bases', {})) != set(BASES) or any(
            set(r['bases'][b].get('arms', {})) != set(ARMS) or any(
                set(r['bases'][b]['arms'][arm].get('annotators', {})) != set(ANNOTATORS)
                for arm in ARMS) for b in BASES) for r in cases):
        return None
    result = {'recordings': len(cases), 'annotators': list(ANNOTATORS), 'bases': {}}
    for base in BASES:
        result['bases'][base] = {}
        for arm in ARMS:
            rows = [r['bases'][base]['arms'][arm] for r in cases]
            raw_rows = [r['bases'][base]['arms']['raw'] for r in cases]
            values = [r['annotators'][a] for r in rows for a in ANNOTATORS]
            entry = {m: mean(v[m] for v in values) for m in METRICS}
            entry['by_annotator'] = {}
            for a in ANNOTATORS:
                deltas = [r['annotators'][a]['onset_offset_f1']
                          - raw['annotators'][a]['onset_offset_f1']
                          for r, raw in zip(rows, raw_rows)]
                entry['by_annotator'][a] = {
                    **{m: mean(r['annotators'][a][m] for r in rows) for m in METRICS},
                    'paired_recordings': comparison_counts(deltas),
                }
            deltas = [mean(r['annotators'][a]['onset_offset_f1']
                           - raw['annotators'][a]['onset_offset_f1'] for a in ANNOTATORS)
                      for r, raw in zip(rows, raw_rows)]
            entry['paired_recordings'] = comparison_counts(deltas)
            for metric in ('onset', 'onset_offset'):
                entry[metric + '_transition'] = {
                    k: sum(v['transition'][metric][k] for v in values)
                    for k in ('gained', 'damaged')}
            # Average the two annotator totals, never count their timelines twice.
            entry['occupancy_seconds_annotator_average'] = {
                k: sum(v['occupancy'][k] for v in values) / len(ANNOTATORS)
                for k in ('reference_note_s', 'reference_gap_s', 'correct_gap_s',
                          'lost_note_s', 'filled_reference_gap_s')}
            entry['output_notes'] = sum(r['count'] for r in rows)
            entry['changed_parents'] = sum(r['edits']['changed_parents'] for r in rows)
            entry['operation_counts'] = {
                k: sum(r['edits']['operation_counts'].get(k, 0) for r in rows)
                for k in ('unchanged', 'tail_trim', 'onset_trim', 'delete', 'split')}
            result['bases'][base][arm] = entry
    return result


def assert_replay(entry, old):
    """Check numerical evidence, not just old rounded headline F1 values."""
    for key in ('count', 'event_sha256', 'annotators'):
        if entry[key] != old[key]:
            raise ValueError('frozen gate replay mismatch: ' + key)


def load_incomplete(root, previous):
    """Reuse only the 39 verified rows of the immutable first attempt.

    This is a fixed recovery receipt, not an arbitrary cache or a way to drop
    unfavorable cases. Only vocadito_11 may require fresh inference.
    """
    path = root / 'docs/research/receipts' / INCOMPLETE_ZIP
    if path.is_symlink() or path.stat().st_size != 50470:
        raise ValueError('invalid recovery receipt path/size')
    if digest(path.read_bytes()) != INCOMPLETE_ZIP_SHA:
        raise ValueError('recovery ZIP changed')
    with zipfile.ZipFile(path) as archive:
        if archive.namelist() != ['report.json']:
            raise ValueError('unexpected recovery member')
        raw = archive.read('report.json')
    if digest(raw) != INCOMPLETE_REPORT_SHA:
        raise ValueError('recovery report changed')
    prior = json.loads(raw)
    if (prior['status'] != 'incomplete' or prior['summary'] is not None
            or prior['source_head'] != 'f03152cef4e5e12e3beb8675b77ef005fe51d905'
            or prior['source_revision'] != '55b4fb57f29b6753e04319ab5e9d27bd80aa002d'
            or prior['archive_sha256'] != previous['archive_sha256']
            or prior['runtime'] != EXPECTED or prior['settings'] != SETTINGS
            or prior['model_identity'] != previous['model_identity']):
        raise ValueError('recovery provenance changed')
    # Selection/envelope/scoring code must be unchanged. Only this orchestration
    # runner is repaired; the historical algorithm and original protocol stay frozen.
    for path_name, expected_hash in prior['source_sha256'].items():
        if path_name == 'scripts/run_audio_gate_attribution.py':
            continue
        if digest((root / path_name).read_bytes()) != expected_hash:
            raise ValueError('recovery changed frozen component: ' + path_name)
    old = {r['id']: r for r in previous['cases']}
    rows = prior['cases']
    if len(rows) != 40 or {r['id'] for r in rows} != set(old):
        raise ValueError('recovery source population changed')
    failed = [r for r in rows if r['status'] != 'scored']
    if (len(failed) != 1 or failed[0]['id'] != 'vocadito_11'
            or failed[0]['reason'] != 'frozen relative gate changed'):
        raise ValueError('unexpected recovery failure set')
    reused = {r['id']: r for r in rows if r['status'] == 'scored'}
    for case_id, row in reused.items():
        if (row['audio_sha256'] != old[case_id]['audio_sha256']
                or row['reference_sha256'] != old[case_id]['reference_sha256']
                or not row['historical_envelope_equal']
                or not row['replayed_raw_and_relative_soft']):
            raise ValueError('reused source identity/replay changed')
        for base in BASES:
            for arm in ('raw', 'relative_soft'):
                assert_replay(row['bases'][base]['arms'][arm], old[case_id]['bases'][base]['arms'][arm])
    provenance = {
        'prior_run_id': 43178487837, 'prior_artifact_id': 13925346757,
        'prior_head': prior['source_head'], 'prior_checkout': prior['source_revision'],
        'prior_zip_sha256': INCOMPLETE_ZIP_SHA, 'prior_report_sha256': INCOMPLETE_REPORT_SHA,
        'prior_source_sha256': prior['source_sha256'],
        'reused_case_ids': list(reused), 'newly_inferred_case_ids': ['vocadito_11'],
        'failed_prior_cases': failed, 'reused_rows_value_exact': True,
    }
    return reused, provenance


def save(path, report):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    tmp.replace(path)


def main():
    import soundfile as sf

    from scripts.run_cpu_vocadito_candidates import ARCHIVE_BYTES, ARCHIVE_MD5, CASE_IDS, prepare
    from scripts.run_offset_tail_probe import bp_decoders

    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('archive', 'work', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--resume-incomplete', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if (args.work.exists() or args.work.is_symlink() or args.output.exists()
            or args.output.is_symlink() or args.work.resolve().is_relative_to(root)
            or args.archive.is_symlink() or args.archive.stat().st_size != ARCHIVE_BYTES
            or hashlib.md5(args.archive.read_bytes()).hexdigest() != ARCHIVE_MD5):
        raise ValueError('fresh private paths and original corpus required')
    if os.getenv('HF_TOKEN') or os.getenv('HUGGING_FACE_HUB_TOKEN'):
        raise ValueError('model credentials are not permitted')
    if any(version(k) != v for k, v in EXPECTED.items()):
        raise ValueError('pinned numeric and model runtime required')
    baseline, previous = load_receipts(root)
    if digest(args.archive.read_bytes()) != previous['archive_sha256']:
        raise ValueError('source corpus changed')
    old_cases = {r['id']: r for r in previous['cases']}
    if set(old_cases) != set(CASE_IDS) or baseline['archive_sha256'] != previous['archive_sha256']:
        raise ValueError('historical source coverage mismatch')
    reused, recovery = load_incomplete(root, previous) if args.resume_incomplete else ({}, None)
    # Preserve literal historical code identities; the new module only wraps it.
    for path, expected_hash in previous['source_sha256'].items():
        if digest((root / path).read_bytes()) != expected_hash:
            raise ValueError('historical source bytes changed: ' + path)
    args.work.mkdir(parents=True, mode=0o700)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    source_paths = (
        'scripts/audio_gate_attribution.py', 'scripts/run_audio_gate_attribution.py',
        'scripts/audit_waveform_gate_receipts.py', 'tests/test_audio_gate_attribution.py',
        'tests/test_waveform_gate_receipts.py', 'tests/test_run_audio_gate_attribution.py',
        'docs/research/AUDIO_GATE_ATTRIBUTION_PROTOCOL_2026-11-12.md',
        'scripts/audio_gate_replay.py', 'tests/test_audio_gate_replay.py',
        'tests/test_gate_attribution_recovery.py',
        'docs/research/AUDIO_GATE_ATTRIBUTION_RECOVERY_2026-11-12.md',
    )
    report = {
        'schema_version': 1, 'status': 'running', 'cases': [], 'planned_ids': list(CASE_IDS),
        'planned_bases': list(BASES), 'planned_arms': list(ARMS),
        'source_revision': os.getenv('GITHUB_SHA', 'local'),
        'source_head': os.getenv('EXPERIMENT_HEAD', 'local'),
        'archive_sha256': previous['archive_sha256'], 'settings': SETTINGS,
        'runtime': {k: version(k) for k in EXPECTED}, 'python': platform.python_version(),
        'summary': None, 'quality_approved': False, 'model_inference_repeated': True,
        'explicit_notated_rest_reference': False, 'reused_development_corpus': True,
        'gate_used_reference': False, 'neural_forward_passes_planned': len(CASE_IDS) - len(reused),
        'neural_forward_passes_executed': 0, 'recovery': recovery,
        'historical_source_sha256': previous['source_sha256'],
        'source_sha256': {p: digest((root / p).read_bytes()) for p in source_paths},
        'retained_receipts': {p.name: digest(p.read_bytes())
                              for p in sorted((root / 'docs/research/receipts').glob('*.zip'))},
        'population': '40 reused recordings; two correlated annotator evaluations per condition',
    }
    save(args.output, report)
    started = time.monotonic()
    model_dir = args.work / 'model'
    model_dir.mkdir()
    with (args.work / 'model.log').open('w') as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        predict, identity = prepare('basic_pitch', model_dir)
    if identity != previous['model_identity']:
        raise ValueError('model identity changed')
    report['model_identity'] = identity
    save(args.output, report)
    with zipfile.ZipFile(args.archive) as archive:
        for case in CASE_IDS:
            if case in reused:
                report['cases'].append(reused[case])
                save(args.output, report)
                print(case, 'reused_verified_receipt', flush=True)
                continue
            tick = time.monotonic()
            row = {'id': case, 'status': 'started'}
            directory = args.work / case
            directory.mkdir()
            try:
                old = old_cases[case]
                raw_audio = archive.read(f'Audio/{case}.wav')
                if digest(raw_audio) != old['audio_sha256']:
                    raise ValueError('audio hash mismatch')
                audio = directory / 'source.wav'
                audio.write_bytes(raw_audio)
                samples, sr = sf.read(audio, dtype='float64', always_2d=True)
                if len(samples) / sr > 120 or not np.isfinite(samples).all():
                    raise ValueError('invalid or oversized audio')
                edges, levels = rms_envelope(samples, int(sr))
                old_edges, old_levels = legacy_envelope(samples, int(sr))
                if not (np.array_equal(edges, old_edges) and np.array_equal(levels, old_levels)):
                    raise ValueError('historical waveform was changed by boundary repair')
                quiet, gate_settings = gate_levels(levels, 'relative')
                row['gate_replay'] = verify_gate_replay(
                    levels, quiet, gate_settings, old['gates']['relative'])
                random.seed(0)
                np.random.seed(0)
                with (directory / 'model.log').open('w') as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                    raw_notes, receipt = predict(audio, directory / 'inference')
                    report['neural_forward_passes_executed'] += 1
                    originals = bp_decoders(directory / 'inference/raw.npz', directory,
                                            events_from(raw_notes))
                if set(originals) != set(BASES):
                    raise ValueError('decoder population changed')
                if any(n.is_drum for notes in originals.values() for n in notes):
                    raise ValueError('vocal scorer requires non-drum predictions')
                predictions = {base: make_attribution_arms(notes, edges, quiet)
                               for base, notes in originals.items()}
                # All four arms for both bases are frozen before reading any note annotations.
                references = {a: archive.read(f'Annotations/Notes/{case}_notes{a}.csv')
                              for a in ANNOTATORS}
                if {a: digest(b) for a, b in references.items()} != old['reference_sha256']:
                    raise ValueError('annotation hash mismatch')
                row.update(audio_sha256=old['audio_sha256'],
                           reference_sha256=old['reference_sha256'],
                           duration_s=len(samples)/sr, historical_envelope_equal=True,
                           source_prediction_receipt=receipt, gate=gate_settings, bases={})
                for base in BASES:
                    entries = {}
                    for arm in ARMS:
                        notes, edits = predictions[base][arm]
                        metrics = {a: scored_notes(notes, raw, edges) for a, raw in references.items()}
                        for a, value in metrics.items():
                            before = value if arm == 'raw' else entries['raw']['annotators'][a]
                            value['transition'] = {m: gains_and_damage(
                                before[m + '_reference_mask'], value[m + '_reference_mask'])
                                for m in ('onset', 'onset_offset')}
                            if arm == 'tail_only' and value['onset_f1'] != before['onset_f1']:
                                raise ValueError('tail-only altered onset F1')
                        entry = {'count': len(notes), 'event_sha256': event_digest(notes),
                                 'edits': edits, 'annotators': metrics}
                        if arm in ('raw', 'relative_soft'):
                            assert_replay(entry, old['bases'][base]['arms'][arm])
                        entries[arm] = entry
                    row['bases'][base] = {'arms': entries}
                if digest(audio.read_bytes()) != row['audio_sha256']:
                    raise ValueError('source waveform mutated')
                row['replayed_raw_and_relative_soft'] = True
                row['status'] = 'scored'
            except Exception as exc:
                row.update(status='failed', error_type=type(exc).__name__, reason=str(exc)[:300])
            row['elapsed_seconds'] = time.monotonic() - tick
            report['cases'].append(row)
            save(args.output, report)
            print(case, row['status'], row.get('reason', ''), flush=True)
    report['summary'] = summarize(report['cases'], CASE_IDS)
    report['status'] = 'complete' if report['summary'] is not None else 'incomplete'
    report['elapsed_seconds'] = time.monotonic() - started
    save(args.output, report)
    return 0 if report['status'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())

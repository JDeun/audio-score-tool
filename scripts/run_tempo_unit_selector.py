"""Paired unit-selection evaluation on unchanged real pulse predictions and onsets."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import time
import zipfile
from collections import Counter
from importlib.metadata import version
from pathlib import Path

from scripts.drum_meter_probe import parse_midi
from scripts.gmd_audio_range_probe import (
    RangeZipReader,
    decode_excerpt,
    detect_audio_roles,
    guarded_wav_member,
)
from scripts.run_drum_meter_probe import ARCHIVE_SHA256, manifest, safe_member
from scripts.tempo_unit_selector import (
    METHODS,
    SETTINGS,
    evaluate,
    identifiability_control,
    infer_units,
)

INPUT_ZIP_SHA = 'd62e26589018d0690e65104858ff37cd2763e5c9cce22166cd2b854d80fff08d'
INPUT_JSON_SHA = '36f003bdff729fb63d2950930a49791fe411809551459843bb2dda961f417f82'
REPRESENTATIONS = ('audio_detected', 'midi_known_roles')
RUNTIME = {'numpy': '1.26.4', 'scipy': '1.13.1', 'mido': '1.3.3'}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def fingerprint(value):
    return sha(json.dumps(value, sort_keys=True, allow_nan=False).encode())


def read_receipt(path):
    if path.is_symlink() or path.stat().st_size > 2_000_000:
        raise ValueError('invalid receipt path')
    raw = path.read_bytes()
    if sha(raw) != INPUT_ZIP_SHA:
        raise ValueError('original artifact checksum mismatch')
    with zipfile.ZipFile(path) as z:
        if z.namelist() != ['report.json'] or z.getinfo('report.json').file_size > 2_000_000:
            raise ValueError('unexpected receipt members')
        payload = z.read('report.json')
    if sha(payload) != INPUT_JSON_SHA:
        raise ValueError('original report checksum mismatch')
    report = json.loads(payload)
    if len(report['cases']) != 16 or len({c['id'] for c in report['cases']}) != 16:
        raise ValueError('original cohort mismatch')
    return report


def process_source(source, row, local, base, remote):
    model = source['methods'].get('beat_this_cv', {}).get('prediction', {})
    if model.get('status') != 'estimated' or not source.get('fold_verified'):
        return {'status': 'model_unavailable', 'representations': {}}
    pulses = tuple(model['beat_seconds'])
    duration = source['excerpt_seconds']
    raw, crc, size = guarded_wav_member(remote, base + row['audio_filename'])
    if sha(raw) != source['source_sha256']:
        raise ValueError('original WAV checksum mismatch')
    samples, seconds, _sr = decode_excerpt(raw, seconds=duration)
    if abs(seconds - duration) > 1e-9 or sha(samples.tobytes()) != source['sample_sha256']:
        raise ValueError('decoded input differs from prior study')
    detected = detect_audio_roles(samples)
    audio_events = tuple((float(t), role) for t, role, _weight in detected if t < seconds)
    midi = safe_member(local, base + row['midi_filename'])
    hits, _signatures, _tempos = parse_midi(midi)
    midi_events = tuple((h.time, h.role) for h in hits
                        if h.time < seconds and h.role in ('kick', 'backbeat'))
    observations = {'audio_detected': audio_events, 'midi_known_roles': midi_events}
    predicted = {}
    pulse_digest = fingerprint(pulses)
    for name, events in observations.items():
        before = fingerprint(events)
        predicted[name] = infer_units(pulses, events)
        predicted[name]['onset_sha256'] = before
        if fingerprint(events) != before or fingerprint(pulses) != pulse_digest:
            raise ValueError('input mutation')
        if abs(predicted[name]['pulse_rate'] - model['bpm']) > 1e-8:
            raise ValueError('source pulse rate changed')
    # Neither row/catalog/reference nor nominal source BPM was passed to infer_units.
    reference = float(row['bpm'])
    if abs(reference - float(source['nominal_bpm'])) > 1e-9:
        raise ValueError('catalog reference identity mismatch')
    for value in predicted.values():
        value['evaluations'] = {m: evaluate(p, reference)
                                for m, p in value['methods'].items()}
    family = any(abs(model['bpm'] * unit / reference - 1) <= .04 + 1e-12
                 for unit in (.5, 1., 2.))
    return {'status': 'complete', 'source_wav_sha256': sha(raw),
            'source_midi_sha256': sha(midi), 'audio_crc32': crc, 'audio_bytes': size,
            'sample_sha256': sha(samples.tobytes()), 'pulse_sha256': pulse_digest,
            'excerpt_seconds': seconds, 'original_pulse_rate': model['bpm'],
            'reference_qpm_evaluation_only': reference, 'family_ceiling': family,
            'representations': predicted}


def summarize(cases, planned):
    if (len(cases) != len(planned) or len(set(planned)) != len(planned)
            or {c['id'] for c in cases} != set(planned)):
        return None
    done = [c for c in cases if c['status'] == 'complete']
    output = {'planned': len(planned), 'paired_sources': len(done),
              'statuses': dict(Counter(c['status'] for c in cases)),
              'family_ceiling': sum(c['family_ceiling'] for c in done),
              'groups': {}}
    for name in REPRESENTATIONS:
        groups = {}
        for method in METHODS:
            vals = [c['representations'][name]['evaluations'][method] for c in done]
            base = [c['representations'][name]['evaluations']['keep_quarter'] for c in done]
            accepted = sum(v['selected'] for v in vals)
            correct = sum(v['correct'] for v in vals)
            groups[method] = {
                'paired_denominator': len(done), 'planned_denominator': len(planned),
                'selected': accepted, 'correct': correct, 'wrong_selected': accepted - correct,
                'unselected': len(vals) - accepted,
                'conditional_precision': correct / accepted if accepted else None,
                'correct_per_planned': correct / len(planned),
                'coverage_per_planned': accepted / len(planned),
                'error_types': dict(Counter(v['error_type'] for v in vals)),
                'fixed_original_wrong': sum(not b['correct'] and v['correct']
                                             for b, v in zip(base, vals)),
                'lost_original_correct': sum(b['correct'] and not v['correct']
                                             for b, v in zip(base, vals)),
                'corrupted_original_correct': sum(b['correct'] and v['selected']
                                                  and not v['correct']
                                                  for b, v in zip(base, vals)),
                'withheld_original_correct': sum(b['correct'] and not v['selected']
                                                 for b, v in zip(base, vals)),
                'selected_units': dict(Counter(str(c['representations'][name]['methods'][method]['unit'])
                                               for c in done)),
            }
        output['groups'][name] = groups
    return output


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--receipt', type=Path, required=True)
    p.add_argument('--midi-zip', type=Path, required=True)
    p.add_argument('--report', type=Path, required=True)
    args = p.parse_args()
    if args.report.exists() or args.report.is_symlink():
        p.error('new output path required')
    if args.midi_zip.is_symlink() or sha(args.midi_zip.read_bytes()) != ARCHIVE_SHA256:
        p.error('original metadata ZIP checksum mismatch')
    runtime = {name: version(name) for name in RUNTIME}
    if runtime != RUNTIME:
        p.error('unexpected numerical runtime')
    source = read_receipt(args.receipt)
    started = time.monotonic()
    repo = Path(__file__).resolve().parents[1]
    paths = ('scripts/tempo_unit_selector.py', 'scripts/run_tempo_unit_selector.py',
             'tests/test_tempo_unit_selector.py', 'scripts/gmd_audio_range_probe.py',
             'scripts/drum_meter_probe.py',
             'docs/research/TEMPO_UNIT_SELECTION_PROTOCOL_2026-11-12.md')
    report = {'status': 'running', 'source_revision': os.getenv('GITHUB_SHA', 'local'),
              'runtime': runtime, 'python': platform.python_version(),
              'source_sha256': {f: sha((repo / f).read_bytes()) for f in paths},
              'input_receipt_zip_sha256': INPUT_ZIP_SHA, 'input_json_sha256': INPUT_JSON_SHA,
              'midi_zip_sha256': ARCHIVE_SHA256,
              'settings': SETTINGS, 'planned_ids': [c['id'] for c in source['cases']],
              'cases': [], 'summary': None, 'identifiability_control': identifiability_control(),
              'reference_provided_to_selector': False, 'meter_provided_to_selector': False,
              'learned_model_rerun': False, 'raw_dsp_audio_rerun': True,
              'full_band_music': False, 'new_independent_holdout': False,
              'product_changes': False, 'quality_approved': False,
              'note_or_rest_duration_accuracy_measured': False}

    def save():
        args.report.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.report.with_suffix('.tmp')
        temporary.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
        temporary.replace(args.report)

    save()
    reader = None
    try:
        with zipfile.ZipFile(args.midi_zip) as local:
            base, rows = manifest(local)
            by_id = {r['id']: r for r in rows}
            if len(by_id) != len(rows):
                raise ValueError('duplicate metadata IDs')
            reader = RangeZipReader()
            with zipfile.ZipFile(reader) as remote:
                metadata = safe_member(local, base + 'info.csv')
                if sha(safe_member(remote, base + 'info.csv')) != sha(metadata):
                    raise ValueError('WAV/metadata identity mismatch')
                report['info_csv_sha256'] = sha(metadata)
                for original in source['cases']:
                    try:
                        result = process_source(original, by_id[original['id']], local, base, remote)
                    except Exception as exc:
                        result = {'status': 'failed', 'reason': type(exc).__name__,
                                  'detail': str(exc)[:180], 'representations': {}}
                    report['cases'].append({'id': original['id'], 'cohort': original['cohort'],
                                            **result})
                    save()
                    print(original['id'], result['status'], flush=True)
    except Exception as exc:
        report['blocking_failure'] = {'type': type(exc).__name__, 'detail': str(exc)[:180]}
    finally:
        if reader is not None:
            report['range_bytes_fetched'] = reader.bytes_fetched
            report['range_requests'] = reader.requests_made
            reader.close()
    report['summary'] = summarize(report['cases'], report['planned_ids'])
    complete = report['summary'] is not None and all(
        c['status'] in ('complete', 'model_unavailable') for c in report['cases'])
    report['status'] = 'complete' if complete else 'incomplete'
    report['elapsed_seconds'] = time.monotonic() - started
    save()
    return 0 if complete else 1


if __name__ == '__main__':
    raise SystemExit(main())

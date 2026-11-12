"""New CPU unit/sequence/export experiment over fixed #258 learned predictions."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import time
import zipfile
from collections import Counter
from pathlib import Path

from scripts.tempo_unit_probe import (
    evaluate_rate,
    fixture_trials,
    hypotheses,
    sequence_diagnostics,
)

SOURCE_ZIP_SHA = 'd62e26589018d0690e65104858ff37cd2763e5c9cce22166cd2b854d80fff08d'
SOURCE_JSON_SHA = '36f003bdff729fb63d2950930a49791fe411809551459843bb2dda961f417f82'
METHODS = ('hit_mean8', 'hit_consensus', 'flux_mean8', 'flux_consensus', 'beat_this_cv')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_receipt(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1_000_000:
        raise ValueError('original bounded artifact required')
    if digest(path.read_bytes()) != SOURCE_ZIP_SHA:
        raise ValueError('original source ZIP SHA256 mismatch')
    with zipfile.ZipFile(path) as package:
        if package.namelist() != ['report.json'] or package.getinfo('report.json').file_size > 2_000_000:
            raise ValueError('unexpected source archive entries')
        raw = package.read('report.json')
    if digest(raw) != SOURCE_JSON_SHA:
        raise ValueError('original source report SHA256 mismatch')
    source = json.loads(raw)
    if (len(source['cases']) != 16 or len(set(source['planned_ids'])) != 16
            or {r['id'] for r in source['cases']} != set(source['planned_ids'])):
        raise ValueError('previous trial completeness changed')
    return source


def adversarial_trials():
    clean = [i * .4 for i in range(30)]
    skipped = [t for i, t in enumerate(clean) if i != 12]
    switch = [i * .4 for i in range(20)] + [7.6 + i * .8 for i in range(1, 9)]
    answer = {}
    for name, values in [('clean_double_pulse', clean), ('one_missing_pulse', skipped),
                         ('pulse_unit_switch_midstream', switch)]:
        answer[name] = sequence_diagnostics(values, 75.)
    answer['outside_frozen_family'] = evaluate_rate(100., 150.)
    return answer


def analyze(source):
    outputs = []
    for row in source['cases']:
        predictions = {}
        # ALL candidates are constructed before reference tempo reaches evaluation.
        for name in METHODS:
            prediction = row['methods'][name]['prediction']
            rate = prediction.get('bpm')
            predictions[name] = {'source_status': prediction['status'],
                                 'pulse_bpm': rate,
                                 'unit_hypotheses': hypotheses(rate) if rate is not None else [],
                                 'automatic_unit_selection': 'unresolved' if rate else 'unavailable'}
        truth = row['nominal_bpm']
        for name in METHODS:
            predictions[name]['evaluation'] = evaluate_rate(predictions[name]['pulse_bpm'], truth)
        model = row['methods']['beat_this_cv']['prediction']
        sequence, invariants = None, []
        if model.get('bpm') is not None:
            if not row['fold_verified'] or row['status'] != 'complete':
                raise ValueError('learned source lacks verified admission')
            beats = model['beat_seconds']
            sequence = sequence_diagnostics(beats, truth)
            if not math.isclose(sequence['pulse_bpm'], model['bpm'], rel_tol=1e-12):
                raise ValueError('source median BPM not reproduced')
            for h in predictions['beat_this_cv']['unit_hypotheses']:
                recovered = [((t * h['pulse_bpm'] / 60) * h['quarter_per_pulse'])
                             * 60 / h['quarter_bpm'] for t in beats]
                invariants.append({'quarter_per_pulse': h['quarter_per_pulse'],
                                   'max_time_error_seconds': max(abs(a - b)
                                                                for a, b in zip(beats, recovered)),
                                   'count_unchanged': len(beats) == len(recovered)})
        outputs.append({'id': row['id'], 'cohort': row['cohort'],
                        'model_admitted': row['fold_verified'],
                        'nominal_qpm_evaluation_only': truth,
                        'source_wav_sha256': row['source_sha256'],
                        'methods': predictions, 'sequence_diagnostic': sequence,
                        'unit_roundtrip_invariants': invariants})
    return outputs


def summarize(rows):
    result = {'all_planned': len(rows), 'model_admitted': sum(r['model_admitted'] for r in rows),
              'automatic_unit_resolved': 0, 'methods': {}}
    for name in METHODS:
        entry = {}
        for scope, group in [('all16', rows),
                             ('same_model_admitted12', [r for r in rows if r['model_admitted']])]:
            values = [r['methods'][name]['evaluation'] for r in group]
            entry[scope] = {'planned': len(group), 'available': sum(v['available'] for v in values),
                            'strict_correct': sum(v['strict'] for v in values),
                            'family_correct': sum(v['family'] for v in values),
                            'alias_only': sum(v['family'] and not v['strict'] for v in values),
                            'other': sum(v['available'] and not v['family'] for v in values),
                            'unavailable': sum(not v['available'] for v in values)}
        result['methods'][name] = entry
    seq = [r['sequence_diagnostic'] for r in rows if r['sequence_diagnostic'] is not None]
    family = [s for s in seq if s['timeline'] is not None]
    result['sequence'] = {
        'available': len(seq), 'reference_family_matched': len(family),
        'intervals': sum(s['interval_count'] for s in family),
        'intervals_within_4pct': sum(s['timeline']['intervals_within_4pct'] for s in family),
        'intervals_within_10pct': sum(s['timeline']['intervals_within_10pct'] for s in family),
        'over_1_5_expected': sum(s['timeline']['intervals_over_1_5_expected'] for s in family),
        'under_0_67_expected': sum(s['timeline']['intervals_under_0_67_expected'] for s in family),
        'reference_assisted_units': dict(Counter(str(s['timeline']['quarter_per_pulse'])
                                                for s in family)),
        'rate_match_not_equal_to_timeline_validation': True,
    }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists() or args.report.is_symlink():
        parser.error('new output path required')
    source = read_receipt(args.receipt)
    source_before = digest(json.dumps(source, sort_keys=True).encode())
    started = time.monotonic()
    rows = analyze(source)
    fixtures = fixture_trials()
    controls = adversarial_trials()
    if source_before != digest(json.dumps(source, sort_keys=True).encode()):
        raise ValueError('original predictions mutated')
    if len(rows) != 16 or len(fixtures) != 36 or not all(x['passed'] for x in fixtures):
        raise ValueError('incomplete conversion study')
    if (not controls['one_missing_pulse']['rate_evaluation']['family']
            or controls['one_missing_pulse']['timeline']['intervals_over_1_5_expected'] != 1
            or controls['pulse_unit_switch_midstream']['timeline']['intervals_over_1_5_expected'] < 1
            or controls['outside_frozen_family']['family']):
        raise ValueError('adversarial observation controls not separated')
    root = Path(__file__).resolve().parents[1]
    source_files = ('scripts/tempo_unit_probe.py', 'scripts/run_tempo_unit_probe.py',
                    'tests/test_tempo_unit_probe.py',
                    'docs/research/TEMPO_UNIT_PROTOCOL_2026-11-12.md')
    report = {'status': 'complete', 'source_revision': os.getenv('GITHUB_SHA', 'local'),
              'python': platform.python_version(),
              'source_sha256': {f: digest((root / f).read_bytes()) for f in source_files},
              'input_zip_sha256': SOURCE_ZIP_SHA, 'input_report_sha256': SOURCE_JSON_SHA,
              'original_run_id': 43122028203, 'original_artifact_id': 13900383659,
              'new_audio_or_model_inference': False, 'prediction_receipt_replay': True,
              'new_unit_sequence_xml_midi_experiment': True,
              'reference_used_for_candidate_generation': False,
              'reference_used_for_diagnostic_unit_match': True,
              'automatic_unit_resolution_tested': False,
              'product_quality_approved': False, 'cases': rows,
              'summary': summarize(rows), 'authored_score_trials': fixtures,
              'authored_score_summary': {'planned': 36, 'passed': sum(v['passed'] for v in fixtures),
                                        'naive_quarter_assumption_correct': sum(
                                            v['unit_omission_control_correct'] for v in fixtures),
                                        'independent_real_songs': False},
              'adversarial_controls': controls, 'elapsed_seconds': time.monotonic() - started}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(json.dumps(report['summary'], indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

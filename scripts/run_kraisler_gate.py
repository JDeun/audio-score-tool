"""Fixed waveform-gate transfer study on six preselected KRAISLER dry stems.

Predictions use audio only. The source note CSV, score and beat annotations are
opened for evaluation after every decoder/arm has already been constructed.
This is a new-recording transfer pilot, not a written-rest detector benchmark.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import platform
import random
import time
from importlib.metadata import version
from pathlib import Path

import numpy as np

from scripts.audio_gate_attribution import ARMS, make_attribution_arms, rms_envelope
from scripts.audio_gate_rest import SETTINGS, gate_levels
from scripts.kraisler_gate_eval import BASES, evaluate_arms, score_context_audit, summarize
from scripts.kraisler_source import acquire_sources, load_manifest
from scripts.run_audio_gate_rest import EXPECTED
from scripts.vocal_recovery import event_digest, events_from

ROOT = Path(__file__).resolve().parents[1]
PLANNED_IDS = ('02', '19', '08', '12', '05', '06')
FROZEN_SOURCE_SHA256 = {
    'scripts/audio_gate_attribution.py': '99b3c494b59fbb0725cc9dd4cd25665a777c93d1516ba6e5a13eb238ddf65cea',
    'scripts/audio_gate_rest.py': '05f239835c2bee14e40cb059b68bad35c7c5a79f247c3d616677c501161fff73',
    'scripts/run_cpu_vocadito_candidates.py': '0265be97c1f891816da30e75fa145a58a1972636a5729fcb1ccc761665c52465',
    'scripts/run_offset_tail_probe.py': '44730f903b4e8eddc1755ff0ae89793052c43abc129f15028b91b0d16562939e',
    'scripts/vocadito_reference.py': '2ee6f18518e0f4887b9f0c163fff6cfcb964a05d21da1eddd6fcf8e031259194',
    'scripts/vocal_recovery.py': '9cbc4c1e635b78263c46473d357fa928350fabdf3efcab79ec44a42e00fa246b',
    'scripts/offset_tail_evidence.py': '5adb61edca4b68deac9a0f9f6f619009d8295f006a5913b9f14c6a30f6ce0b4c',
    'src/audio_score_tool/metrics.py': '476fdb3dcebf8660a83b258263a2719193590eee5135d40f79b87ceab313df4f',
}
NEW_SOURCE_PATHS = (
    'scripts/run_kraisler_gate.py', 'scripts/kraisler_source.py',
    'scripts/kraisler_gate_eval.py', 'scripts/kraisler_gate_manifest.json',
    'tests/test_kraisler_source.py', 'tests/test_kraisler_gate_eval.py',
    'tests/test_run_kraisler_gate.py',
    'docs/research/KRAISLER_GATE_PROTOCOL_2026-11-12.md',
    '.github/workflows/cpu-kraisler-gate.yml',
)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def save(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    tmp.replace(path)


def validate_frozen_sources():
    for name, expected_hash in FROZEN_SOURCE_SHA256.items():
        if digest((ROOT / name).read_bytes()) != expected_hash:
            raise ValueError('frozen predictor/scorer changed: ' + name)


def run(work, output):
    import soundfile as sf

    from scripts.run_cpu_vocadito_candidates import prepare
    from scripts.run_offset_tail_probe import bp_decoders

    if (work.exists() or work.is_symlink() or output.exists() or output.is_symlink()
            or work.resolve().is_relative_to(ROOT)
            or output.resolve().is_relative_to(ROOT)
            or output.resolve().is_relative_to(work.resolve())):
        raise ValueError('fresh separate private work/report paths outside repository required')
    work.mkdir(parents=True, mode=0o700)
    report = {
        'schema_version': 1, 'status': 'running', 'cases': [], 'summary': None,
        'planned_ids': list(PLANNED_IDS), 'planned_bases': list(BASES),
        'planned_arms': list(ARMS), 'source_head': os.getenv('EXPERIMENT_HEAD', 'local'),
        'source_revision': os.getenv('GITHUB_SHA', 'local'),
        'source_sha256': {},
        'frozen_source_sha256': FROZEN_SOURCE_SHA256,
        'settings': SETTINGS, 'runtime': {},
        'python': platform.python_version(), 'completed_recording_inferences': 0,
        'planned_recording_inferences': len(PLANNED_IDS), 'predictor_invocations': 0,
        'policy': {
            'source': 'KRAISLER v1.0 / six fixed full VN dry recordings',
            'selection_seed': 'waveform-gate-kraisler-v1/',
            'population': 'six recordings, not 48 independent condition samples',
            'same_performers_and_collection': True,
            'new_to_gate_development': True, 'training_overlap_verified': False,
            'vocadito_repeated': False, 'inference_device': 'cpu', 'training': False,
            'new_model': False, 'reference_used_for_gate_or_edits': False,
            'score_or_beats_used_for_prediction': False,
            'all_arms_frozen_before_reference_scoring': True,
            'mono_waveform_implies_monophonic_music': False,
            'note_reference': 'author-reviewed alignment-derived violin notes',
            'reference_offset_uncertainty': 'authors warn offsets are less reliable than onsets/pitch',
            'explicit_written_rest_accuracy_measured': False,
            'score_to_audio_mapping_verified': False,
            'quality_approved': False, 'automatic_correction_enabled': False,
            'source_media_or_event_arrays_published': False,
        },
    }
    save(output, report)
    started = time.monotonic()
    try:
        if os.getenv('HF_TOKEN') or os.getenv('HUGGING_FACE_HUB_TOKEN'):
            raise ValueError('external model credentials are not permitted')
        report['runtime'] = {name: version(name) for name in EXPECTED}
        if report['runtime'] != EXPECTED:
            raise ValueError('unchanged pinned CPU research runtime required')
        validate_frozen_sources()
        load_manifest()
        report['source_sha256'] = {name: digest((ROOT / name).read_bytes()) for name in NEW_SOURCE_PATHS}
        save(output, report)
        sources = acquire_sources(work / 'sources')
        if tuple(case['id'] for case in sources['cases']) != PLANNED_IDS:
            raise ValueError('source cohort changed')
        # Retain receipts, never private local paths or raw source material.
        report['source_acquisition'] = {key: value for key, value in sources.items()
                                        if key != 'cases'}
        save(output, report)
        model_dir = work / 'model'
        model_dir.mkdir()
        tick = time.monotonic()
        with (work / 'model.log').open('w') as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            predict, identity = prepare('basic_pitch', model_dir)
        report['model_identity'] = identity
        report['preparation_seconds'] = time.monotonic() - tick
        save(output, report)
    except Exception as exc:
        report.update(status='preparation_failed', error_type=type(exc).__name__, reason=str(exc)[:400])
        save(output, report)
        return 1

    for source in sources['cases']:
        tick = time.monotonic()
        case_id = source['id']
        directory = work / case_id
        directory.mkdir()
        row = {'id': case_id, 'status': 'started', 'bases': {}}
        try:
            audio = Path(source['audio_path'])
            before = digest(audio.read_bytes())
            samples, sr = sf.read(audio, dtype='float64', always_2d=True)
            if (sr != 44100 or samples.ndim != 2 or samples.shape[1] != 1
                    or not 0 < len(samples) / sr <= 150 or not np.isfinite(samples).all()):
                raise ValueError('invalid or oversized original mono dry recording')
            edges, levels = rms_envelope(samples, int(sr))
            quiet, gate = gate_levels(levels, 'relative')
            random.seed(0)
            np.random.seed(0)
            with (directory / 'model.log').open('w') as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                inference_tick = time.monotonic()
                report['predictor_invocations'] += 1
                raw_notes, inference_receipt = predict(audio, directory / 'inference')
                report['completed_recording_inferences'] += 1
                row['model_inference_seconds'] = time.monotonic() - inference_tick
                originals = bp_decoders(directory / 'inference/raw.npz', directory, events_from(raw_notes))
            if set(originals) != set(BASES):
                raise ValueError('decoder population changed')
            original_hashes = {base: event_digest(notes) for base, notes in originals.items()}
            predictions = {base: make_attribution_arms(notes, edges, quiet)
                           for base, notes in originals.items()}
            # No source labels have entered inference or the gate. Read only now.
            raw_reference = Path(source['notes_path']).read_bytes()
            raw_score = Path(source['score_path']).read_bytes()
            raw_beats = Path(source['beats_path']).read_bytes()
            row.update(
                audio_sha256=before, reference_sha256=digest(raw_reference),
                score_sha256=digest(raw_score), beats_sha256=digest(raw_beats),
                source_member_sha256=source['member_sha256'], duration_s=len(samples) / sr,
                gate={**gate, 'frame_count': len(quiet), 'quiet_frame_count': int(quiet.sum()),
                      'mask_sha256': digest(quiet.astype(np.uint8).tobytes())},
                source_prediction_receipt=inference_receipt,
            )
            for base in BASES:
                entries = evaluate_arms(predictions[base], raw_reference, edges)
                if entries['raw']['event_sha256'] != original_hashes[base]:
                    raise ValueError('raw control changed')
                row['bases'][base] = {'arms': entries}
            try:
                row['score_context'] = score_context_audit(raw_score, raw_beats, raw_reference)
            except Exception as exc:
                row['score_context'] = {'status': 'unavailable', 'alignment_status': 'unaligned',
                                        'error_type': type(exc).__name__, 'reason': str(exc)[:300]}
            if (digest(audio.read_bytes()) != before
                    or {base: event_digest(notes) for base, notes in originals.items()} != original_hashes):
                raise ValueError('immutable source/prediction changed')
            row['status'] = 'scored'
        except Exception as exc:
            row.update(status='failed', error_type=type(exc).__name__, reason=str(exc)[:400])
        row['elapsed_seconds'] = time.monotonic() - tick
        report['cases'].append(row)
        save(output, report)
        print(case_id, row['status'], row.get('reason', ''), flush=True)

    try:
        report['summary'] = summarize(report['cases'], PLANNED_IDS)
        report['status'] = 'complete' if report['summary'] is not None else 'incomplete'
    except Exception as exc:
        report.update(status='aggregation_failed', error_type=type(exc).__name__,
                      reason=str(exc)[:400], summary=None)
    report['elapsed_seconds'] = time.monotonic() - started
    save(output, report)
    return 0 if report['status'] == 'complete' else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    return run(args.work, args.output)


if __name__ == '__main__':
    raise SystemExit(main())

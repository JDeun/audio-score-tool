"""One frozen four-arm GMD waveform experiment; no production model changes."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import wave
import zipfile
from pathlib import Path

import numpy as np

from scripts.drum_event_lanes import ARMS, detect_all_arms
from scripts.drum_event_metrics import Event, recovery_diagnostics, score_events
from scripts.drum_lane_controls import control_inventory, control_reference, synthesize_input
from scripts.drum_lane_source import (
    EXCLUSION_SHA256,
    METADATA_SHA256,
    SUPPORTED_ROLES,
    exclusion_inventory,
    midi_reference,
    read_metadata,
    select_rows,
)
from scripts.gmd_audio_range_probe import (
    BUFFER_BYTES,
    FULL_ZIP_URL,
    MAX_MEMBER_BYTES,
    MAX_TOTAL_BYTES,
    RangeNotSupported,
    RangeZipReader,
    decode_excerpt,
    guarded_wav_member,
)
from scripts.research_numeric_qualification import qualify
from scripts.run_drum_meter_probe import ARCHIVE_SHA256, safe_member

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'drum-event-lanes-v1'
SOURCE_FREEZE = ROOT / 'docs/research/DRUM_EVENT_LANES_FROZEN_SOURCES_2026-11-14.json'
CONTROL_INPUTS = ROOT / 'docs/research/DRUM_EVENT_LANES_CONTROL_INPUTS_2026-11-14.json'
COHORTS = ('new_waveform', 'development_replay', 'authored_controls')
STRATA = ('supported_50ms', 'all_kit_50ms', 'supported_10ms', 'all_kit_10ms')
COUNT_FIELDS = ('reference', 'predicted', 'matched', 'false_positives', 'false_negatives')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, indent=2, allow_nan=False) + '\n').encode()
    with path.open('xb') as output:
        output.write(raw)
    return sha(raw)


def source_contract():
    raw = SOURCE_FREEZE.read_bytes()
    contract = json.loads(raw)
    if contract['schema'] != SCHEMA or contract['base_revision'] != (
            'b60545fb2024cd37cf74a78fe68700daa8dde622'):
        raise ValueError('source_freeze_schema_or_base')
    actual = {}
    for name, expected in contract['source_sha256'].items():
        path = ROOT / name
        if path.is_symlink() or '..' in Path(name).parts or Path(name).is_absolute():
            raise ValueError('source_freeze_unsafe_path')
        actual[name] = sha(path.read_bytes())
        if actual[name] != expected:
            raise ValueError('source_freeze_mismatch/' + name)
    return {'manifest_sha256': sha(raw), 'source_sha256': actual,
            'all_equal': True, 'base_revision': contract['base_revision']}


def sample_sha(samples):
    return sha(np.asarray(samples, dtype='<f4').tobytes())


def save_input(work, index, samples, row):
    samples = np.asarray(samples, dtype='<f4')
    if samples.ndim != 1 or not np.isfinite(samples).all():
        raise ValueError('input_must_be_finite_mono')
    filename = f'inputs/{index:03d}.npy'
    path = work / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        np.save(stream, samples, allow_pickle=False)
    return {**row, 'status': 'ready', 'input_path': filename,
            'input_sha256': sample_sha(samples), 'input_dtype': '<f4',
            'input_shape': [len(samples)], 'sample_rate': 16000}


def collect_inputs(archive, work):
    """Acquire and freeze every waveform before any detector or MIDI parser."""
    base, metadata = read_metadata(archive)
    selection = select_rows(metadata)
    controls = control_inventory()
    if len(selection) != 10 or len(controls) != 100:
        raise ValueError('fixed_population_required')
    control_binding = json.loads(CONTROL_INPUTS.read_text())
    frozen_inputs = control_binding['cases']
    if [row['id'] for row in frozen_inputs] != [row['id'] for row in controls]:
        raise ValueError('fixed_authored_input_population')
    planned = [{**row, 'status': 'unavailable', 'reason': 'not_acquired'}
               for row in selection]
    expected_old = {row['id']: row['source_sha256'] for row in exclusion_inventory()}
    remote = None
    remote_info = {'full_source_zip_uri': FULL_ZIP_URL,
                   'full_source_zip_sha256_verified': False,
                   'range_bytes_fetched': 0, 'range_requests': 0}
    try:
        remote = RangeZipReader()
        with zipfile.ZipFile(remote) as wav_archive:
            original_csv = safe_member(wav_archive, base + 'info.csv')
            if sha(original_csv) != METADATA_SHA256:
                raise ValueError('ranged_audio_metadata_identity')
            remote_info['full_archive_size'] = remote.size
            members = []
            for row in selection:
                info = wav_archive.getinfo(base + row['audio_filename'])
                if not 0 < info.file_size <= MAX_MEMBER_BYTES or info.compress_size > MAX_MEMBER_BYTES or info.flag_bits & 1:
                    raise ValueError('whole_selection_member_budget')
                members.append({'id': row['id'], 'compressed_bytes': info.compress_size,
                                'uncompressed_bytes': info.file_size, 'crc32': info.CRC})
            estimate = sum(member['compressed_bytes'] for member in members) + (
                2 * len(selection) + 8) * BUFFER_BYTES
            remote_info.update(member_preflight=members, estimated_fetch_bytes=estimate,
                               enforced_range_budget_bytes=MAX_TOTAL_BYTES)
            if estimate > MAX_TOTAL_BYTES:
                raise ValueError('whole_selection_estimated_range_budget')
            for index, row in enumerate(selection):
                try:
                    raw, crc, size = guarded_wav_member(wav_archive, base + row['audio_filename'])
                    wav_sha = sha(raw)
                    if row['id'] in expected_old and wav_sha != expected_old[row['id']]:
                        raise ValueError('historical_waveform_member_identity')
                    samples, duration, original_sr = decode_excerpt(raw)
                    planned[index] = save_input(work, index, samples, {
                        **row, 'duration_seconds': duration, 'source_audio_sha256': wav_sha,
                        'source_audio_crc32': crc, 'source_audio_bytes': size,
                        'original_sample_rate': original_sr,
                    })
                except (KeyError, ValueError, OSError, EOFError, wave.Error) as exc:
                    planned[index]['reason'] = f'{type(exc).__name__}: {exc}'
    except (RangeNotSupported, KeyError, OSError, ValueError, zipfile.BadZipFile) as exc:
        remote_info['failure'] = f'{type(exc).__name__}: {exc}'
    finally:
        if remote is not None:
            remote_info.update(range_bytes_fetched=remote.bytes_fetched,
                               range_requests=remote.requests_made)
            remote.close()
    for index, case in enumerate(controls, start=10):
        samples, expected = synthesize_input(case)
        frozen = frozen_inputs[index - 10]
        if (sample_sha(samples) != expected or expected != frozen['sha256']
                or list(samples.shape) != frozen['shape'] or samples.dtype.str != frozen['dtype']):
            raise ValueError('authored_input_byte_identity')
        planned.append(save_input(work, index, samples,
                                  dict(case, cohort='authored_controls')))
    return base, selection, controls, planned, remote_info


def predict_frozen_inputs(work, planned, preflight_sha256):
    cases = []
    for row in planned:
        case = {'id': row['id'], 'cohort': row['cohort'], 'status': row['status']}
        if row['status'] != 'ready':
            case['reason'] = row['reason']
            cases.append(case)
            continue
        try:
            samples = np.load(work / row['input_path'], allow_pickle=False)
            if (samples.dtype.str != '<f4' or row['input_dtype'] != '<f4'
                    or list(samples.shape) != row['input_shape'] or samples.ndim != 1
                    or row['sample_rate'] != 16000 or not np.isfinite(samples).all()):
                raise ValueError('input_dtype_shape_or_sample_rate_before_prediction')
            if sample_sha(samples) != row['input_sha256']:
                raise ValueError('input_identity_before_prediction')
            samples.flags.writeable = False
            output = detect_all_arms(samples, sr=16000)
            if tuple(output) != tuple(ARMS) or sample_sha(samples) != row['input_sha256']:
                raise ValueError('prediction_inventory_or_input_mutation')
            case.update(status='predicted', input_sha256=row['input_sha256'], arms={})
            for arm in ARMS:
                case['arms'][arm] = [
                    {'event_id': f'{arm}:p{i:05d}', 'time': float(t), 'role': role,
                     'velocity': None, 'strength': float(strength)}
                    for i, (t, role, strength) in enumerate(output[arm])]
        except (ValueError, RuntimeError, OSError) as exc:
            case.update(status='prediction_failed', reason=f'{type(exc).__name__}: {exc}')
            case.pop('arms', None)
        cases.append(case)
    return {'schema': SCHEMA, 'arms': list(ARMS), 'preflight_sha256': preflight_sha256,
            'reference_calls_before_freeze': 0, 'cases': cases}


def freeze_references(archive, base, planned, controls, prediction_path, expected_sha):
    """The complete, on-disk prediction artifact is the reference-access gate."""
    raw = prediction_path.read_bytes()
    if sha(raw) != expected_sha:
        raise ValueError('prediction_barrier_byte_identity')
    predictions = json.loads(raw)
    if [x['id'] for x in predictions['cases']] != [x['id'] for x in planned]:
        raise ValueError('prediction_barrier_complete_population')
    for case in predictions['cases']:
        if case['status'] == 'predicted' and tuple(case['arms']) != tuple(ARMS):
            raise ValueError('prediction_barrier_all_four_arms')
    authored = {case['id']: case for case in controls}
    cases = []
    for row in planned:
        case = {'id': row['id'], 'cohort': row['cohort'], 'status': row['status']}
        if row['status'] != 'ready':
            case['reason'] = row['reason']
        else:
            try:
                if row['cohort'] == 'authored_controls':
                    events = control_reference(authored[row['id']])
                else:
                    midi = safe_member(archive, base + row['midi_filename'])
                    case['source_midi_sha256'] = sha(midi)
                    events = midi_reference(midi, row['duration_seconds'])
                case.update(status='ready', events=events)
            except (ValueError, KeyError, OSError, EOFError) as exc:
                case.update(status='reference_failed', reason=f'{type(exc).__name__}: {exc}')
        cases.append(case)
    return {'schema': SCHEMA, 'predictions_sha256': expected_sha,
            'all_predictions_frozen_before_reference_access': True, 'cases': cases}


def events(rows):
    return [Event(row['event_id'], row['time'], row['role'], row.get('velocity')) for row in rows]


def case_metrics(planned, predictions, references):
    metrics = []
    for source, prediction, reference in zip(planned, predictions['cases'],
                                            references['cases'], strict=True):
        if not source['id'] == prediction['id'] == reference['id']:
            raise ValueError('scoring_population_identity')
        result = {'id': source['id'], 'cohort': source['cohort'],
                  'category': source.get('category'), 'status': 'not_scored'}
        if prediction['status'] != 'predicted' or reference['status'] != 'ready':
            result['prediction_status'] = prediction['status']
            result['reference_status'] = reference['status']
            metrics.append(result)
            continue
        truth = events(reference['events'])
        supported = [event for event in truth if event.role in SUPPORTED_ROLES]
        result.update(status='scored', arms={})
        for arm in ARMS:
            predicted = events(prediction['arms'][arm])
            result['arms'][arm] = {
                'supported_50ms': score_events(supported, predicted, tolerance=.05),
                'all_kit_50ms': score_events(truth, predicted, tolerance=.05),
                'supported_10ms': score_events(supported, predicted, tolerance=.01),
                'all_kit_10ms': score_events(truth, predicted, tolerance=.01),
                'recovery': recovery_diagnostics(supported, predicted),
            }
        metrics.append(result)
    return metrics


def sum_counts(rows):
    counts = {key: sum(row[key] for row in rows) for key in COUNT_FIELDS}
    counts.update(precision=counts['matched'] / counts['predicted'] if counts['predicted'] else 0.0,
                  recall=counts['matched'] / counts['reference'] if counts['reference'] else 0.0,
                  f1=2 * counts['matched'] / (counts['reference'] + counts['predicted'])
                  if counts['reference'] + counts['predicted'] else 0.0)
    return counts


def aggregate(metrics):
    output = {}
    for cohort in COHORTS:
        planned = [row for row in metrics if row['cohort'] == cohort]
        scored = [row for row in planned if row['status'] == 'scored']
        summary = {'planned': len(planned), 'scored': len(scored),
                   'conditional_on_admitted_cases': len(scored) != len(planned), 'strata': {}}
        for stratum in STRATA:
            summary['strata'][stratum] = {}
            for arm in ARMS:
                rows = [row['arms'][arm][stratum] for row in scored]
                value = sum_counts(rows)
                roles = sorted({role for row in rows for role in row['per_role']})
                value['per_role'] = {role: sum_counts([row['per_role'][role] for row in rows
                                                      if role in row['per_role']])
                                     for role in roles}
                value['edit_operations'] = sum(row['edit_proxy']['cost'] for row in rows)
                value['normalized_edit_operations'] = value['edit_operations'] / max(1, value['reference'])
                summary['strata'][stratum][arm] = value
        summary['recovery'] = {
            arm: {'flam_pairs': sum(row['arms'][arm]['recovery']['flam']['pairs'] for row in scored),
                  'flam_recovered': sum(row['arms'][arm]['recovery']['flam']['recovered_pairs']
                                        for row in scored),
                  'simultaneous_groups': sum(row['arms'][arm]['recovery']['simultaneous']['groups']
                                             for row in scored),
                  'simultaneous_recovered': sum(
                      row['arms'][arm]['recovery']['simultaneous']['timing_preserved_groups']
                      for row in scored)} for arm in ARMS}
        if cohort == 'authored_controls':
            summary['pair_gap_bins_ms'] = {}
            for arm in ARMS:
                bins = {str(gap): {'pairs': 0, 'recovered_pairs': 0} for gap in (15, 30, 60, 90)}
                for row in scored:
                    if row['category'] != 'same_class_pair':
                        continue
                    for pair in row['arms'][arm]['recovery']['flam']['details']:
                        gap = pair['reference_gap_seconds'] * 1000
                        target = min((15, 30, 60, 90), key=lambda value: abs(value - gap))
                        if abs(target - gap) > 1e-8:
                            raise ValueError('authored_pair_outside_frozen_gap_bins')
                        bins[str(target)]['pairs'] += 1
                        bins[str(target)]['recovered_pairs'] += int(pair['recovered'])
                summary['pair_gap_bins_ms'][arm] = bins
        output[cohort] = summary
    return output


def decide(metrics, aggregates):
    """Fixed engineering gate, not a significance test or release approval."""
    baseline, candidate = 'global85', 'independent10'
    complete = all(row['status'] == 'scored' for row in metrics) and len(metrics) == 110
    primary = aggregates['new_waveform']['strata']['supported_50ms']
    kit = aggregates['new_waveform']['strata']['all_kit_50ms']
    a, b = primary[baseline], primary[candidate]
    singleton = [row for row in metrics if row.get('category') == 'supported_singleton'
                 and row['status'] == 'scored']
    singles = {arm: sum(row['arms'][arm]['supported_50ms']['false_positives'] for row in singleton)
               for arm in (baseline, candidate)}
    controls = aggregates['authored_controls']['recovery']
    nonworse = sum(row['arms'][candidate]['supported_50ms']['f1'] + 1e-12
                   >= row['arms'][baseline]['supported_50ms']['f1']
                   for row in metrics if row['cohort'] == 'new_waveform' and row['status'] == 'scored')
    conditions = {
        'all_110_cases_complete': complete,
        'primary_improves_at_least_3pp': b['f1'] + 1e-12 >= a['f1'] + .03,
        'no_supported_class_loses_more_than_2pp': all(
            b['per_role'].get(role, {'f1': 0.0})['f1'] + 1e-12 >=
            a['per_role'].get(role, {'f1': 0.0})['f1'] - .02 for role in SUPPORTED_ROLES),
        'all_kit_f1_not_lower': kit[candidate]['f1'] + 1e-12 >= kit[baseline]['f1'],
        'at_least_four_of_six_new_clips_nonworse': nonworse >= 4,
        'all_kit_edit_proxy_not_higher': kit[candidate]['normalized_edit_operations']
        <= kit[baseline]['normalized_edit_operations'] + 1e-12,
        'supported_singleton_extra_events_not_higher': singles[candidate] <= singles[baseline],
        'strict_authored_flam_recovery_not_lower': controls[candidate]['flam_recovered']
        >= controls[baseline]['flam_recovered'],
        'strict_authored_simultaneous_recovery_not_lower': controls[candidate]['simultaneous_recovered']
        >= controls[baseline]['simultaneous_recovered'],
    }
    return {'candidate': candidate, 'baseline': baseline, 'conditions': conditions,
            'outcome': ('inconclusive_incomplete' if not complete else
                        'advance_to_broader_research' if all(conditions.values()) else 'reject_candidate'),
            'primary_f1_delta': b['f1'] - a['f1'], 'new_clips_nonworse': nonworse,
            'supported_singleton_false_positives': singles,
            'product_default_changed': False, 'release_quality_approved': False}


def run(archive_path, work, output):
    if work.exists() or output.exists():
        raise ValueError('new_work_and_output_directories_required')
    if os.getenv('NPY_DISABLE_CPU_FEATURES'):
        raise ValueError('native_cpu_dispatch_required')
    if os.getenv('HF_TOKEN') or os.getenv('HUGGING_FACE_HUB_TOKEN'):
        raise ValueError('credential_free_study_required')
    work.mkdir(parents=True)
    output.mkdir(parents=True)
    source = source_contract()
    qualification = qualify()
    qualification_sha = write_json(output / 'qualification.json', qualification)
    if qualification['status'] != 'compatible':
        raise ValueError('input_environment_incompatible')
    if archive_path.is_symlink() or sha(archive_path.read_bytes()) != ARCHIVE_SHA256:
        raise ValueError('original_midi_archive_identity')
    with zipfile.ZipFile(archive_path) as archive:
        base, _selection, controls, planned, remote = collect_inputs(archive, work)
        preflight = {'schema': SCHEMA, 'source_revision': os.getenv('GITHUB_SHA'),
                     'protocol_head_revision': os.getenv('EXPERIMENT_HEAD_SHA'),
                     'run_id': os.getenv('GITHUB_RUN_ID'), 'run_attempt': os.getenv('GITHUB_RUN_ATTEMPT'),
                     'source_contract': source, 'qualification_sha256': qualification_sha,
                     'original_midi_zip_sha256': ARCHIVE_SHA256,
                     'metadata_sha256': METADATA_SHA256,
                     'prior_waveform_inventory_sha256': EXCLUSION_SHA256,
                     'prior_waveform_ids': [row['id'] for row in exclusion_inventory()],
                     'predictor_calls_before_preflight': 0, 'reference_calls_before_preflight': 0,
                     'planned_cases': planned, 'source_access': remote,
                     'data_license': 'Google LLC, Groove MIDI Dataset, CC BY 4.0',
                     'data_source': 'https://magenta.tensorflow.org/datasets/groove'}
        preflight_sha = write_json(output / 'preflight.json', preflight)
        prediction = predict_frozen_inputs(work, planned, preflight_sha)
        prediction_path = output / 'predictions.json'
        prediction_sha = write_json(prediction_path, prediction)
        prediction_path.chmod(0o444)
        reference = freeze_references(archive, base, planned, controls, prediction_path, prediction_sha)
        reference_sha = write_json(output / 'references.json', reference)
        if sha(prediction_path.read_bytes()) != prediction_sha:
            raise ValueError('predictions_changed_after_reference_access')
    metrics = case_metrics(planned, prediction, reference)
    aggregates = aggregate(metrics)
    report = {'schema': SCHEMA, 'status': 'complete' if all(row['status'] == 'scored' for row in metrics)
              else 'incomplete', 'source_revision': os.getenv('GITHUB_SHA'),
              'protocol_head_revision': os.getenv('EXPERIMENT_HEAD_SHA'),
              'hashes': {'preflight.json': preflight_sha, 'predictions.json': prediction_sha,
                         'references.json': reference_sha, 'qualification.json': qualification_sha},
              'arms': list(ARMS), 'candidate': 'independent10', 'case_metrics': metrics,
              'aggregates': aggregates, 'decision': decide(metrics, aggregates),
              'audio_domain': 'original_GMD_TD11_sound_module_recordings',
              'new_waveforms_are_not_unseen_dataset_or_composition_holdout': True,
              'unsupported_classes_retained_in_all_kit_denominator': True,
              'training': False, 'product_default_changed': False, 'quality_approved': False}
    write_json(output / 'report.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--midi-zip', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.work.exists() or args.output.exists():
        parser.error('new work and output directories required')
    started = time.monotonic()
    try:
        report = run(args.midi_zip, args.work, args.output)
    except Exception as exc:
        args.output.mkdir(parents=True, exist_ok=True)
        failure = {'schema': SCHEMA, 'status': 'not_completed',
                   'reason': f'{type(exc).__name__}: {exc}',
                   'source_revision': os.getenv('GITHUB_SHA'),
                   'protocol_head_revision': os.getenv('EXPERIMENT_HEAD_SHA'),
                   'elapsed_seconds': time.monotonic() - started,
                   'quality_approved': False, 'aggregate': None}
        if not (args.output / 'failure.json').exists():
            write_json(args.output / 'failure.json', failure)
        raise
    print(json.dumps({'status': report['status'], 'decision': report['decision'],
                      'elapsed_seconds': time.monotonic() - started}), flush=True)
    return 0 if report['status'] == 'complete' else 2


if __name__ == '__main__':
    raise SystemExit(main())

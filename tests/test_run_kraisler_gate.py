"""Durable failure receipts; all source transport and learned inference are stubbed."""
from __future__ import annotations

import hashlib
import json
from unittest.mock import Mock

import numpy as np
import pytest
import soundfile as sf

from scripts import run_cpu_vocadito_candidates as model_runtime
from scripts import run_kraisler_gate as runner
from scripts import run_offset_tail_probe as decoder_runtime
from scripts.vocal_recovery import Event


@pytest.fixture(autouse=True)
def no_external_model_credentials(monkeypatch):
    monkeypatch.delenv('HF_TOKEN', raising=False)
    monkeypatch.delenv('HUGGING_FACE_HUB_TOKEN', raising=False)


def test_runtime_mismatch_writes_failure_receipt_without_acquisition(tmp_path, monkeypatch):
    acquire = Mock(side_effect=AssertionError('network must not be reached'))
    prepare = Mock(side_effect=AssertionError('model must not be prepared'))
    monkeypatch.setattr(runner, 'acquire_sources', acquire)
    monkeypatch.setattr(model_runtime, 'prepare', prepare)
    monkeypatch.setattr(runner, 'version',
                        lambda name: '0.0.0' if name == 'numpy' else runner.EXPECTED[name])
    output = tmp_path / 'receipt' / 'report.json'

    assert runner.run(tmp_path / 'private', output) == 1

    report = json.loads(output.read_text())
    assert report['status'] == 'preparation_failed'
    assert report['error_type'] == 'ValueError'
    assert 'pinned CPU research runtime' in report['reason']
    assert report['runtime']['numpy'] == '0.0.0'
    assert report['summary'] is None and report['cases'] == []
    assert report['planned_ids'] == list(runner.PLANNED_IDS)
    assert report['predictor_invocations'] == report['completed_recording_inferences'] == 0
    acquire.assert_not_called()
    prepare.assert_not_called()


def test_changed_frozen_source_writes_failure_receipt_before_network(tmp_path, monkeypatch):
    frozen_root = tmp_path / 'frozen-repository'
    frozen_root.mkdir()
    (frozen_root / 'predictor.py').write_bytes(b'changed predictor bytes')
    monkeypatch.setattr(runner, 'ROOT', frozen_root)
    monkeypatch.setattr(runner, 'FROZEN_SOURCE_SHA256', {
        'predictor.py': hashlib.sha256(b'previously frozen predictor bytes').hexdigest(),
    })
    monkeypatch.setattr(runner, 'version', lambda name: runner.EXPECTED[name])
    acquire = Mock(side_effect=AssertionError('network must not be reached'))
    prepare = Mock(side_effect=AssertionError('model must not be prepared'))
    monkeypatch.setattr(runner, 'acquire_sources', acquire)
    monkeypatch.setattr(model_runtime, 'prepare', prepare)
    output = tmp_path / 'receipt' / 'report.json'

    assert runner.run(tmp_path / 'private', output) == 1

    report = json.loads(output.read_text())
    assert report['status'] == 'preparation_failed'
    assert report['error_type'] == 'ValueError'
    assert report['reason'] == 'frozen predictor/scorer changed: predictor.py'
    assert report['summary'] is None and report['cases'] == []
    assert report['planned_ids'] == list(runner.PLANNED_IDS)
    assert report['predictor_invocations'] == report['completed_recording_inferences'] == 0
    acquire.assert_not_called()
    prepare.assert_not_called()


def test_aggregation_failure_retains_all_scored_cases_and_null_summary(tmp_path, monkeypatch):
    """Exercise the runner through real gate/scorer code using tiny invented inputs."""
    monkeypatch.setattr(runner, 'version', lambda name: runner.EXPECTED[name])
    monkeypatch.setattr(runner, 'validate_frozen_sources', lambda: None)
    monkeypatch.setattr(runner, 'load_manifest', lambda: {})
    monkeypatch.setattr(runner, 'NEW_SOURCE_PATHS', ())
    calls = []

    def acquire_fixture(destination):
        cases = []
        for case_id in runner.PLANNED_IDS:
            folder = destination / case_id
            folder.mkdir(parents=True)
            contents = {
                'audio': b'invented fixture; soundfile decoding is stubbed',
                'notes': b'onset,offset,midi,velocity\n0.1,0.8,60,127\n',
                'score': b'<score-partwise/>',
                'beats': b'beat_time,beat_type,time_signature,piano,violin\n',
            }
            row = {'id': case_id, 'member_sha256': {}}
            for role, raw in contents.items():
                path = folder / role
                path.write_bytes(raw)
                row[role + '_path'] = str(path)
                row['member_sha256'][role] = hashlib.sha256(raw).hexdigest()
            cases.append(row)
        return {'status': 'verified', 'fixture': True, 'cases': cases}

    def predict_fixture(audio, _output):
        calls.append(audio.parent.name)
        return [Event(60, .1, .8)], {'fixture': True}

    def fail_after_complete_cases(cases, planned):
        assert [case['id'] for case in cases] == list(planned)
        assert all(case['status'] == 'scored' for case in cases)
        assert all(set(case['bases']) == set(runner.BASES) for case in cases)
        assert all(set(case['bases'][base]['arms']) == set(runner.ARMS)
                   for case in cases for base in runner.BASES)
        raise ValueError('controlled aggregation failure after complete scoring')

    monkeypatch.setattr(runner, 'acquire_sources', acquire_fixture)
    monkeypatch.setattr(model_runtime, 'prepare',
                        lambda _candidate, _directory: (predict_fixture, {'backend': 'fixture'}))
    monkeypatch.setattr(decoder_runtime, 'bp_decoders',
                        lambda _path, _directory, original:
                        {base: list(original) for base in runner.BASES})
    monkeypatch.setattr(sf, 'read', lambda *_args, **_kwargs: (np.zeros((44100, 1)), 44100))
    monkeypatch.setattr(runner, 'score_context_audit',
                        lambda *_args: {'status': 'unsupported', 'alignment_status': 'unaligned'})
    monkeypatch.setattr(runner, 'summarize', fail_after_complete_cases)
    output = tmp_path / 'receipt' / 'report.json'

    assert runner.run(tmp_path / 'private', output) == 1

    report = json.loads(output.read_text())
    assert report['status'] == 'aggregation_failed'
    assert report['error_type'] == 'ValueError'
    assert report['reason'] == 'controlled aggregation failure after complete scoring'
    assert report['summary'] is None
    assert calls == list(runner.PLANNED_IDS)
    assert report['predictor_invocations'] == report['completed_recording_inferences'] == 6
    assert [case['id'] for case in report['cases']] == list(runner.PLANNED_IDS)
    assert all(case['status'] == 'scored' for case in report['cases'])
    assert all(case['model_inference_seconds'] >= 0 for case in report['cases'])

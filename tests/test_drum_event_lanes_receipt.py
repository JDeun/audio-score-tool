"""Keep the original completed trial and its negative conclusion reviewable."""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from scripts.audit_drum_event_lanes import audit_directory

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / 'docs/research'
ZIP_NAME = 'drum-event-lanes-43601526575-attempt-1.zip'
ZIP_SHA256 = 'a6ab844ed5cfb6cd4ac74ddf5dc7002fc8409ba738c8f84765d9c590aba79a45'
MEMBERS = {
    'audit.json', 'preflight.json', 'predictions.json', 'references.json',
    'report.json', 'qualification.json',
}


def test_original_artifact_and_derived_summary_remain_bound(tmp_path):
    archive = RESEARCH / 'receipts' / ZIP_NAME
    raw = archive.read_bytes()
    assert len(raw) == 543266
    assert hashlib.sha256(raw).hexdigest() == ZIP_SHA256
    summary = json.loads((RESEARCH / 'DRUM_EVENT_LANES_RESULTS_2026-11-14.json').read_text())
    assert summary['artifact_sha256'] == ZIP_SHA256
    assert summary['run_id'] == 43601526575 and summary['run_attempt'] == 1
    assert summary['artifact_id'] == 14116835699
    identities = {row['filename']: row for row in summary['artifact_members']}
    assert set(identities) == MEMBERS
    with zipfile.ZipFile(archive) as source:
        assert set(source.namelist()) == MEMBERS and len(source.namelist()) == 6
        for name in sorted(MEMBERS):
            content = source.read(name)
            assert len(content) == identities[name]['size_bytes']
            assert hashlib.sha256(content).hexdigest() == identities[name]['sha256']
            (tmp_path / name).write_bytes(content)
    original_report = json.loads((tmp_path / 'report.json').read_text())
    original_preflight = json.loads((tmp_path / 'preflight.json').read_text())
    assert summary['decision'] == original_report['decision']
    assert summary['protocol_head_revision'] == original_preflight['protocol_head_revision']
    assert summary['actual_checkout_revision'] == original_preflight['source_revision']
    for cohort, values in summary['cohorts'].items():
        original = original_report['aggregates'][cohort]
        for stratum, arms in values['strata'].items():
            for arm, counts in arms.items():
                for key, value in counts.items():
                    assert original['strata'][stratum][arm][key] == value
        assert values['recovery'] == original['recovery']
    audit = audit_directory(tmp_path, root=ROOT)
    preserved = json.loads((RESEARCH / 'receipts' /
                            'drum-event-lanes-public-audit-43601526575.json').read_text())
    assert audit == preserved
    assert audit['status'] == 'audited'
    assert audit['planned_cases'] == audit['scored_cases'] == 110
    assert audit['candidate_decision']['outcome'] == 'reject_candidate'
    assert audit['input_arrays_reopened'] is False
    private = json.loads((tmp_path / 'audit.json').read_text())
    assert private['input_arrays_reopened'] is True and private['input_arrays_verified'] == 110


def test_failed_source_ci_preserves_incompatible_host_evidence():
    name = 'research-numeric-qualification-43601526551-attempt-1.zip'
    path = RESEARCH / 'receipts' / name
    assert path.stat().st_size == 73860
    assert hashlib.sha256(path.read_bytes()).hexdigest() == (
        '50d5dec4617571f57d4ddc4ccfc71290d29de24f22de211be0c6cc1500d5b631')
    with zipfile.ZipFile(path) as source:
        assert len(source.namelist()) == 1
        raw = source.read(source.namelist()[0])
    assert hashlib.sha256(raw).hexdigest() == (
        '23e639e07a694b505eb273c7ef7745357d72ab025601454a075b2363f3053665')
    qualification = json.loads(raw)
    observation = json.loads((RESEARCH / 'RESEARCH_NUMERIC_CI_V2_HOST_OBSERVATION_2026-11-14.json').read_text())
    assert qualification['status'] == observation['status'] == 'incompatible'
    assert qualification['environment']['numpy_disable_cpu_features'] is None
    assert qualification['environment']['cpu_features']['AVX512F'] is False
    assert qualification['frozen_sources']['all_equal'] is True
    mismatch_counts = {name: len(rows) for name, rows in qualification['input_differences'].items()}
    assert mismatch_counts == observation['mismatch_counts'] == {
        'legacy': 18, 'stress': 207, 'independent_stress': 207,
    }
    assert qualification['mutation_contract']['status'] == 'not_run'

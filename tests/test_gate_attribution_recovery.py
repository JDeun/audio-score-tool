"""A recovery may reuse only the exact declared historical source population."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from scripts import audit_waveform_gate_receipts
from scripts.audit_waveform_gate_receipts import load_receipts
from scripts.run_audio_gate_attribution import load_incomplete


def test_fixed_recovery_reuses_thirty_nine_rows_and_requires_only_failed_id():
    root = Path(audit_waveform_gate_receipts.__file__).resolve().parents[1]
    _, previous = load_receipts(root)
    reused, info = load_incomplete(root, previous)
    assert set(reused) == {f'vocadito_{i}' for i in range(1, 41)} - {'vocadito_11'}
    assert info['newly_inferred_case_ids'] == ['vocadito_11']
    assert info['failed_prior_cases'][0]['status'] == 'failed'
    assert info['prior_run_id'] == 43178487837


def test_recovery_rejects_a_different_corpus_before_reusing_any_rows():
    root = Path(audit_waveform_gate_receipts.__file__).resolve().parents[1]
    _, previous = load_receipts(root)
    changed = deepcopy(previous)
    changed['archive_sha256'] = '0' * 64
    with pytest.raises(ValueError, match='provenance'):
        load_incomplete(root, changed)

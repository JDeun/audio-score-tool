"""Evidence population and interpretation regressions for the attribution runner."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from scripts import audit_waveform_gate_receipts
from scripts.audit_waveform_gate_receipts import load_receipts
from scripts.run_audio_gate_attribution import ARMS, BASES, assert_replay, summarize


def receipt_cases():
    root = Path(audit_waveform_gate_receipts.__file__).resolve().parents[1]
    _, old = load_receipts(root)
    cases = deepcopy(old['cases'])
    # Aggregation-only fixtures: both partial arms equal raw; no musical claim.
    for case in cases:
        for base in BASES:
            arms = case['bases'][base]['arms']
            case['bases'][base]['arms'] = {
                arm: deepcopy(arms[arm if arm in ('raw', 'relative_soft') else 'raw'])
                for arm in ARMS}
            for entry in case['bases'][base]['arms'].values():
                entry['edits']['operation_counts'] = {}
    return cases, old


def test_complete_summary_reproduces_historical_full_control_and_exposes_annotator_damage():
    cases, old = receipt_cases()
    report = summarize(cases, old['planned_ids'])
    assert report['recordings'] == 40
    for base in BASES:
        for arm in ('raw', 'relative_soft'):
            got = report['bases'][base][arm]
            expected = old['summary']['bases'][base][arm]
            for metric in ('onset_f1', 'onset_offset_f1'):
                assert got[metric] == expected[metric]
            assert got['paired_recordings'] == expected['paired_recordings']
            assert got['output_notes'] == expected['output_notes']
            for key, value in got['occupancy_seconds_annotator_average'].items():
                # Python 3.12 changed float sum accumulation; the receipt used 3.11.
                assert value == pytest.approx(expected['occupancy_totals'][key] / 2,
                                              abs=1e-12, rel=0)
    soft = report['bases']['onset065']['relative_soft']
    assert soft['paired_recordings']['worsened'] == 0
    assert soft['by_annotator']['A1']['paired_recordings']['worsened'] >= 1


@pytest.mark.parametrize('defect', ['missing', 'duplicate', 'failed', 'base', 'arm', 'annotator'])
def test_incomplete_paired_population_has_no_summary(defect):
    cases, old = receipt_cases()
    if defect == 'missing':
        cases.pop()
    elif defect == 'duplicate':
        cases[-1] = cases[0]
    elif defect == 'failed':
        cases[-1]['status'] = 'failed'
    elif defect == 'base':
        cases[-1]['bases'].pop('default')
    elif defect == 'arm':
        cases[-1]['bases']['default']['arms'].pop('tail_only')
    else:
        cases[-1]['bases']['default']['arms']['tail_only']['annotators'].pop('A2')
    assert summarize(cases, old['planned_ids']) is None


def test_replay_rejects_changed_mask_even_when_rounded_f1_unchanged():
    cases, old = receipt_cases()
    entry = cases[0]['bases']['default']['arms']['raw']
    expected = old['cases'][0]['bases']['default']['arms']['raw']
    assert_replay(entry, expected)
    value = entry['annotators']['A1']
    mask = value['onset_reference_mask']
    value['onset_reference_mask'] = ('1' if mask[0] == '0' else '0') + mask[1:]
    with pytest.raises(ValueError, match='annotators'):
        assert_replay(entry, expected)

"""Plot complete, audit-bound #298 metadata without inference or rematching.

The original Actions ZIP is the only scientific input. Corpus F1, annotation
judgments, coverage, and authored stress populations retain separate units.
No acoustic frontend, decoder, experiment runner, or scorer is imported.
"""
from __future__ import annotations

import argparse
import json
import math
import zipfile
from pathlib import Path

from scripts.plot_note_boundary_readout_results import _count, _json, _number, _same_number, _sha256

BASE = 'gaussian_exponent_1'
SPLIT = 'gaussian_raw_hysteresis_split'
GUARD = 'gaussian_raw_hysteresis_parent_guard'
ALL_ARMS = ('pitch_runs', 'pitch_hysteresis', 'pitch_hysteresis_reattack',
            'note_state_hmm', 'note_state_hmm_rms', BASE, 'phase_balanced',
            'positive_voicing_08', 'silent_self_099', 'hop_unscaled', SPLIT, GUARD)
PLOT_ARMS = ('pitch_runs', 'note_state_hmm', BASE, SPLIT, GUARD)
FOCUS_ARMS = (BASE, SPLIT, GUARD)
CASES = tuple(f'vocadito_{index}' for index in range(1, 41))
ANNOTATORS = ('A1', 'A2')
COHORTS = ('legacy', 'single_expression', 'adjacent_semitone')
STEM = 'note-boundary-parent-guard-2026-11-13'
BLUE, AMBER, GREEN, RED, GRAY = '#376C9F', '#C48624', '#26745D', '#B74C45', '#6D7C8A'


def _load_reports(receipt):
    required = ('vocadito.json', 'synthetic.json', 'audit.json', 'legacy-vocadito.json',
                'legacy-synthetic.json', 'legacy-audit.json', 'legacy-factor-vocadito.json',
                'legacy-factor-audit.json')
    if receipt.is_symlink() or not receipt.is_file():
        raise ValueError('a regular original Actions ZIP is required')
    with zipfile.ZipFile(receipt) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != set(required):
            raise ValueError('exact eight-member original receipt required')
        if any(archive.getinfo(name).file_size > 96_000_000 for name in required):
            raise ValueError('unexpectedly large public metadata member')
        raw = {name: archive.read(name) for name in required}
    reports = {name: _json(value) for name, value in raw.items()}
    corpus, synthetic, audit = (reports[name] for name in ('vocadito.json', 'synthetic.json', 'audit.json'))
    if (corpus.get('schema') != 'note-boundary-parent-guard-v1'
            or synthetic.get('schema') != 'note-boundary-parent-guard-synthetic-v1'
            or audit.get('schema') != 'note-boundary-parent-guard-audit-v1'
            or any(reports[name].get('status') != 'complete' for name in required if 'audit' not in name)
            or any(reports[name].get('status') != 'pass' or reports[name].get('audit_completed') is not True
                   for name in required if 'audit' in name)
            or corpus.get('all_cases_complete') is not True
            or corpus.get('historical_parity', {}).get('all_equal') is not True
            or synthetic.get('historical_parity', {}).get('all_equal') is not True
            or corpus.get('all_predictions_frozen_before_references') is not True
            or synthetic.get('all_predictions_saved_before_scoring') is not True):
        raise ValueError('complete current and historical predictions with all three independent audits required')
    bindings = (
        ('audit.json', 'report_sha256', 'vocadito.json'),
        ('audit.json', 'synthetic_report_sha256', 'synthetic.json'),
        ('audit.json', 'legacy_report_sha256', 'legacy-vocadito.json'),
        ('audit.json', 'legacy_synthetic_report_sha256', 'legacy-synthetic.json'),
        ('audit.json', 'legacy_audit_sha256', 'legacy-audit.json'),
        ('legacy-audit.json', 'report_sha256', 'legacy-vocadito.json'),
        ('legacy-audit.json', 'synthetic_report_sha256', 'legacy-synthetic.json'),
        ('legacy-audit.json', 'legacy_report_sha256', 'legacy-factor-vocadito.json'),
        ('legacy-audit.json', 'legacy_audit_sha256', 'legacy-factor-audit.json'),
        ('legacy-factor-audit.json', 'report_sha256', 'legacy-factor-vocadito.json'),
        ('vocadito.json', 'legacy_report_sha256', 'legacy-vocadito.json'),
        ('vocadito.json', 'legacy_factor_report_sha256', 'legacy-factor-vocadito.json'),
        ('legacy-vocadito.json', 'legacy_report_sha256', 'legacy-factor-vocadito.json'),
    )
    for report_name, field, source in bindings:
        if reports[report_name].get(field) != _sha256(raw[source]):
            raise ValueError(f'broken report/audit binding: {report_name}/{field}')
    if (len(corpus.get('source_sha256', {})) != 66
            or corpus['source_sha256'] != synthetic.get('source_sha256')
            or corpus['source_sha256'] != audit.get('source_sha256')
            or audit.get('source_files_verified') != 66
            or audit.get('corpus_prediction_files_verified') != 480
            or audit.get('synthetic_prediction_files_verified') != 4149):
        raise ValueError('complete frozen source and prediction populations required')
    return reports, raw


def _contrast(rows, saved, baseline):
    bootstrap = saved['bootstrap']
    if (saved.get('candidate') != GUARD or saved.get('baseline') != baseline
            or saved.get('metric') != 'onset_offset_f1'
            or bootstrap.get('seed') != 298 or bootstrap.get('resamples') != 10000
            or bootstrap.get('resampling_unit') != 'recording_mean_of_A1_A2'
            or bootstrap.get('method') != 'paired_percentile_linear'
            or bootstrap.get('confidence_level') != .95
            or [item['id'] for item in saved['paired_recording_deltas']] != list(CASES)):
        raise ValueError('contrast differs from the prespecified paired design')
    deltas = [math.fsum(row['arms'][GUARD]['annotators'][ann]['onset_offset_f1']
                       - row['arms'][baseline]['annotators'][ann]['onset_offset_f1']
                       for ann in ANNOTATORS) / 2 for row in rows]
    for case, delta, item in zip(CASES, deltas, saved['paired_recording_deltas'], strict=True):
        _same_number(item['delta'], delta, f'{case}/{baseline}/paired_delta')
    _same_number(saved['mean_delta'], math.fsum(deltas) / 40, baseline + '/mean_delta')
    counts = {'improved': sum(delta > 1e-8 for delta in deltas),
              'worse': sum(delta < -1e-8 for delta in deltas),
              'tied': sum(abs(delta) <= 1e-8 for delta in deltas)}
    if any(saved['recordings_' + key] != value for key, value in counts.items()):
        raise ValueError('per-recording change count differs')
    interval = [_number(bootstrap[key], 'bootstrap/' + key, minimum=-1., maximum=1.) for key in ('low', 'high')]
    if interval[0] > interval[1]:
        raise ValueError('inverted bootstrap interval')
    return {'deltas': deltas, 'mean_delta': saved['mean_delta'], 'interval': interval, **counts}


def load_metadata(receipt):
    """Validate receipt bindings and the displayed arithmetic from saved metadata."""
    receipt = Path(receipt)
    reports, raw = _load_reports(receipt)
    corpus, synthetic = reports['vocadito.json'], reports['synthetic.json']
    rows = corpus.get('cases', [])
    if (len(rows) != 40 or {row.get('id') for row in rows} != set(CASES)
            or any(row.get('status') != 'scored' or set(row.get('arms', {})) != set(ALL_ARMS) for row in rows)):
        raise ValueError('all forty recordings and twelve scored arms required')
    by_id = {row['id']: row for row in rows}
    rows = [by_id[case] for case in CASES]
    f1, predicted = {}, {}
    for arm in ALL_ARMS:
        if any(set(row['arms'][arm]['annotators']) != set(ANNOTATORS) for row in rows):
            raise ValueError('both original annotations required')
        predicted[arm] = sum(_count(row['arms'][arm]['count'], 'predicted events') for row in rows)
        if corpus['aggregate'][arm]['predicted_notes'] != predicted[arm]:
            raise ValueError('predicted-event denominator differs')
        f1[arm] = {}
        for metric in ('onset_f1', 'onset_offset_f1'):
            values = [_number(row['arms'][arm]['annotators'][ann][metric], metric, minimum=0., maximum=1.)
                      for row in rows for ann in ANNOTATORS]
            _same_number(corpus['aggregate'][arm][metric]['macro'], math.fsum(values) / 80, arm + '/' + metric)
            f1[arm][metric] = corpus['aggregate'][arm][metric]['macro']
    contrasts = {BASE: _contrast(rows, corpus['primary_result'], BASE),
                 SPLIT: _contrast(rows, corpus['secondary_result'], SPLIT)}
    pooled = corpus['boundary_summary']['pooled_annotation_judgments']
    references = sum(_count(row['arms'][BASE]['annotators'][ann]['reference_note_count'], 'reference judgments')
                     for row in rows for ann in ANNOTATORS)
    if pooled['recording_annotations'] != 80 or pooled['reference_notes'] != references:
        raise ValueError('annotation denominator differs')
    partitions, matched = {}, {}
    for arm in FOCUS_ARMS:
        matched[arm] = _count(pooled['arms'][arm]['offset_matched'], 'offset matched judgments')
    for baseline in (BASE, SPLIT):
        value = pooled['comparisons'][baseline]['onset_offset']
        partitions[baseline] = {key: _count(value[key], key) for key in ('retained', 'gained', 'lost', 'neither')}
        part = partitions[baseline]
        if (sum(part.values()) != references or part['retained'] + part['lost'] != matched[baseline]
                or part['retained'] + part['gained'] != matched[GUARD]):
            raise ValueError('matched-reference partitions do not reconcile')
    duration = math.fsum(_number(row['duration_seconds'], 'audio seconds', minimum=0.) for row in rows)
    if duration <= 0:
        raise ValueError('positive total audio duration required')
    seconds = {
        BASE: math.fsum(row['guard']['baseline_emitted_seconds'] for row in rows),
        SPLIT: math.fsum(row['readout']['emitted_seconds'] for row in rows),
        GUARD: math.fsum(row['guard']['emitted_seconds'] for row in rows),
    }
    for row in rows:
        guard = row['guard']
        if (guard['output_interval_union_preserved'] is not True
                or guard['baseline_interval_union_sha256'] != guard['output_interval_union_sha256']
                or guard['nonemitted_parents_resurrected'] != 0
                or guard['originally_emitted_parents_all_children_pruned'] != 0):
            raise ValueError('saved interval-union preservation contract failed')
        _same_number(guard['baseline_emitted_seconds'], row['readout']['baseline_emitted_seconds'], 'shared G seconds')
        _same_number(guard['baseline_interval_union_seconds'], guard['output_interval_union_seconds'], 'union seconds')
    _same_number(seconds[GUARD], seconds[BASE], 'guard emitted interval seconds')
    cost_keys = ('parent_segment_count', 'originally_emitted_parent_count', 'originally_nonemitted_parent_count',
                 'proposed_parent_count', 'proposed_cut_count', 'proposed_child_count', 'accepted_parent_count',
                 'accepted_cut_count', 'accepted_child_count', 'rejected_parent_count', 'restored_original_event_count',
                 'unchanged_original_event_count')
    cost = {key: sum(_count(row['guard'][key], key) for row in rows) for key in cost_keys}
    cost['short_count'] = {
        BASE: sum(row['guard']['baseline']['short_segments_discarded'] for row in rows),
        SPLIT: sum(row['readout']['readout']['short_segments_discarded'] for row in rows),
        GUARD: sum(row['guard']['readout']['short_segments_discarded'] for row in rows),
        'proposed': sum(row['guard']['proposed']['short_segments_discarded'] for row in rows),
    }
    cost['short_seconds'] = {
        BASE: math.fsum(row['guard']['baseline']['short_segments_discarded_seconds'] for row in rows),
        SPLIT: math.fsum(row['readout']['readout']['short_segments_discarded_seconds'] for row in rows),
        GUARD: math.fsum(row['guard']['readout']['short_segments_discarded_seconds'] for row in rows),
        'proposed': math.fsum(row['guard']['proposed']['short_segments_discarded_seconds'] for row in rows),
    }
    synthetic_rows = synthetic.get('cases', [])
    if len(synthetic_rows) != 461 or len({row['id'] for row in synthetic_rows}) != 461:
        raise ValueError('all 461 authored cases required')
    stress = {}
    for name, expected_count, expected_eligible in (('legacy', 245, 227), ('single_expression', 108, 108),
                                                  ('adjacent_semitone', 108, 108)):
        selected = [row for row in synthetic_rows if row['cohort'] == name]
        eligible = [row for row in selected if row['accuracy_eligible']]
        if len(selected) != expected_count or len(eligible) != expected_eligible:
            raise ValueError('separate authored cohort denominator differs')
        stress[name] = {}
        for arm in FOCUS_ARMS:
            saved = synthetic['aggregate'][name][arm]
            if saved['eligible_cases'] != expected_eligible:
                raise ValueError('synthetic aggregate denominator differs')
            for metric in ('onset_f1', 'onset_offset_f1'):
                actual = math.fsum(row['arms'][arm]['metrics'][metric] for row in eligible) / expected_eligible
                _same_number(saved[metric], actual, name + '/' + arm + '/' + metric)
            stress[name][arm] = {**saved, 'perfect_cases': sum(
                all(row['arms'][arm]['metrics'][metric] == 1. for metric in ('onset_f1', 'onset_offset_f1'))
                for row in eligible)}
    return {'receipt_sha256': _sha256(receipt.read_bytes()), 'receipt_bytes': receipt.stat().st_size,
            'report_sha256': _sha256(raw['vocadito.json']), 'source_revision': corpus['source_revision'],
            'protocol_head_revision': corpus['protocol_head_revision'], 'f1': f1, 'predicted_notes': predicted,
            'contrasts': contrasts, 'reference_judgments': references, 'partitions': partitions,
            'matched': matched, 'audio_seconds': duration, 'emitted_seconds': seconds, 'cost': cost,
            'synthetic': stress, 'audit_checks': reports['audit.json']['checks_passed']}


def _style():
    import matplotlib

    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10, 'axes.titlesize': 12,
        'axes.labelsize': 10, 'axes.spines.top': False, 'axes.spines.right': False,
        'axes.labelcolor': '#25313C', 'text.color': '#25313C', 'axes.edgecolor': '#80909C',
        'xtick.color': '#475560', 'ytick.color': '#475560', 'svg.fonttype': 'none',
        'figure.facecolor': 'white', 'savefig.facecolor': 'white'})
    return plt


def _save(fig, output_dir, stem, data):
    outputs = []
    for suffix in ('.png', '.svg'):
        path = output_dir / (stem + suffix)
        metadata = {'Date': None, 'Description': 'Original receipt SHA256: ' + data['receipt_sha256']} if suffix == '.svg' else None
        fig.savefig(path, dpi=180, metadata=metadata)
        if suffix == '.svg':
            path.write_text('\n'.join(line.rstrip() for line in path.read_text().splitlines()) + '\n')
        outputs.append(path)
    return outputs


def plot_corpus(data, output_dir):
    plt = _style()
    from matplotlib.patches import Patch

    fig, axes = plt.subplots(2, 2, figsize=(18, 12))
    fig.subplots_adjust(left=.065, right=.97, bottom=.15, top=.85, hspace=.60, wspace=.25)
    fig.suptitle('Whole-parent approval on frozen Gaussian note paths', x=.065, y=.965,
                 ha='left', fontsize=20, fontweight='bold')
    fig.text(.065, .928, 'vocadito reused development corpus | 40 recordings × 2 annotators | '
             'G, unconditional split, and parent guard | 2026-11-13', fontsize=11)
    ax = axes[0, 0]
    ax.set_title('A  Note matching F1', loc='left', pad=29, fontweight='bold')
    ax.text(0., 1.04, 'Macro of 80 recording × annotator scores; n = predicted events',
            transform=ax.transAxes, fontsize=9)
    for metric, shift, color, label in (('onset_f1', -.19, BLUE, 'Pitch + onset'),
                                       ('onset_offset_f1', .19, AMBER, 'Pitch + onset + offset')):
        heights = [100 * data['f1'][arm][metric] for arm in PLOT_ARMS]
        bars = ax.bar([index + shift for index in range(5)], heights, width=.34, color=color, label=label, zorder=3)
        for bar, value in zip(bars, heights, strict=True):
            ax.text(bar.get_x() + bar.get_width() / 2, value + 1.4, f'{value:.1f}', ha='center', fontsize=9)
    labels = ('Pitch\nruns', 'Legacy\nHMM', 'Gaussian\nG', 'Unconditional\nsplit', 'Parent\nguard')
    ax.set_xticks(range(5), [f'{label}\nn={data["predicted_notes"][arm]:,}'
                           for label, arm in zip(labels, PLOT_ARMS, strict=True)])
    ax.set_ylim(0, 106)
    ax.set_yticks(range(0, 101, 20))
    ax.set_ylabel('F1 (%)')
    ax.grid(axis='y', color='#DFE5EA', linewidth=.7, zorder=0)
    ax.legend(frameon=False, loc='upper left', fontsize=9)

    ax = axes[0, 1]
    ax.set_title('B  Offset F1 change in every recording', loc='left', pad=29, fontweight='bold')
    ax.text(0., 1.04, 'Two prespecified contrasts; each point is the paired A1/A2 mean',
            transform=ax.transAxes, fontsize=9)
    limits = [0.]
    for baseline, shift, color, label in ((BASE, -.18, BLUE, 'Guard − G'),
                                        (SPLIT, .18, AMBER, 'Guard − split')):
        values = [100 * value for value in data['contrasts'][baseline]['deltas']]
        limits.extend(values)
        ax.bar([index + shift for index in range(1, 41)], values, width=.34, color=color, label=label, zorder=3)
    ax.axhline(0, color='#475560', linewidth=.9)
    spread = max(limits) - min(limits)
    margin = max(2., spread * .2)
    ax.set_ylim(min(limits) - margin, max(limits) + 2 * margin)
    ax.set_xlim(.3, 40.7)
    ax.set_xticks(range(1, 41))
    ax.tick_params(axis='x', labelsize=6.5, length=2)
    ax.set_xlabel('Recording ID (vocadito_1 through vocadito_40)')
    ax.set_ylabel('Change (percentage points)')
    ax.legend(frameon=False, loc='upper left', fontsize=9)
    ax.grid(axis='y', color='#DFE5EA', linewidth=.7, zorder=0)
    summary = []
    for baseline, label in ((BASE, 'G'), (SPLIT, 'split')):
        item = data['contrasts'][baseline]
        low, high = [100 * value for value in item['interval']]
        summary.append(f'vs {label}: {100 * item["mean_delta"]:+.2f} pp [{low:+.2f}, {high:+.2f}]; '
                       f'{item["improved"]} up / {item["worse"]} down')
    ax.text(.99, .98, '\n'.join(summary), transform=ax.transAxes, va='top', ha='right', fontsize=8,
            bbox={'facecolor': 'white', 'edgecolor': 'none', 'alpha': .94, 'pad': 4})

    ax = axes[1, 0]
    ax.set_title('C  Offset-matched reference judgments', loc='left', pad=29, fontweight='bold')
    ax.text(0., 1.04, 'A1+A2 judgments; guard repeated for two distinct comparisons',
            transform=ax.transAxes, fontsize=9)
    maximum = max(data['matched'].values())
    for baseline, y_base, y_guard in ((BASE, 3., 2.25), (SPLIT, .75, 0.)):
        parts = data['partitions'][baseline]
        for y, arm, extra, color in ((y_base, baseline, 'lost', RED), (y_guard, GUARD, 'gained', GREEN)):
            ax.barh(y, parts['retained'], height=.50, color=GRAY)
            ax.barh(y, parts[extra], left=parts['retained'], height=.50, color=color)
            for count, center in ((parts['retained'], parts['retained'] / 2),
                                  (parts[extra], parts['retained'] + parts[extra] / 2)):
                if count > .04 * max(1, maximum):
                    ax.text(center, y, f'{count:,}', color='white', ha='center', va='center', fontsize=9)
            ax.text(data['matched'][arm] + .025 * max(1, maximum), y,
                    f'{data["matched"][arm]:,} matched', va='center', fontsize=8.5)
    ax.set_yticks([3., 2.25, .75, 0.], ['G', 'Guard vs G', 'Split', 'Guard vs split'])
    ax.set_ylim(-.8, 4.1)
    ax.set_xlim(0, max(1, maximum) * 1.28)
    ax.set_xlabel('Matched annotation judgments, not unique physical notes')
    ax.legend(handles=[Patch(color=GRAY, label='Retained'), Patch(color=RED, label='Lost'),
                       Patch(color=GREEN, label='Gained')], frameon=False, ncol=3, loc='upper left', fontsize=9)
    ax.text(.01, .02, f'Reference denominator {data["reference_judgments"]:,}; neither: '
            f'vs G {data["partitions"][BASE]["neither"]:,}, vs split {data["partitions"][SPLIT]["neither"]:,}',
            transform=ax.transAxes, fontsize=8.5)
    ax.grid(axis='x', color='#DFE5EA', linewidth=.7, zorder=0)
    ax.set_axisbelow(True)

    ax = axes[1, 1]
    ax.set_title('D  Coverage and proposal versus final pruning', loc='left', pad=29, fontweight='bold')
    ax.text(0., 1.04, f'40 recordings counted once; full audio = {data["audio_seconds"]:.3f} s',
            transform=ax.transAxes, fontsize=9)
    ax.set_axis_off()
    coverage = ax.inset_axes([.13, .69, .85, .27])
    for y, arm, label, color in ((2, BASE, 'G', GRAY), (1, SPLIT, 'Split', AMBER), (0, GUARD, 'Guard', GREEN)):
        value = 100 * data['emitted_seconds'][arm] / data['audio_seconds']
        coverage.barh(y, value, height=.55, color=color)
        coverage.text(value - 1, y, f'{value:.2f}% ({data["emitted_seconds"][arm]:.3f} s)',
                      ha='right', va='center', color='white', fontsize=8)
    coverage.set_yticks([2, 1, 0], ['G', 'Split', 'Guard'])
    coverage.set_xlim(0, 100)
    coverage.set_xticks([0, 25, 50, 75, 100])
    coverage.tick_params(labelsize=8)
    coverage.grid(axis='x', color='#DFE5EA', linewidth=.6)
    coverage.set_axisbelow(True)
    cost = data['cost']
    lines = [
        ('Proposed / accepted cuts', f'{cost["proposed_cut_count"]:,} / {cost["accepted_cut_count"]:,}'),
        ('Accepted / rejected parent proposals', f'{cost["accepted_parent_count"]:,} / {cost["rejected_parent_count"]:,}'),
        ('Original events restored after rejection', f'{cost["restored_original_event_count"]:,}'),
        ('Short proposed children (not final deletions)', f'{cost["short_count"]["proposed"]:,}'),
        ('Final short pruning: G / split / guard', ' / '.join(f'{cost["short_count"][arm]:,}' for arm in FOCUS_ARMS)),
        ('Exact interval union preserved vs G', '40 / 40 recordings'),
    ]
    for index, (label, value) in enumerate(lines):
        y = .56 - index * .087
        ax.text(0., y, label, transform=ax.transAxes, fontsize=8.5, va='center')
        ax.text(.99, y, value, transform=ax.transAxes, fontsize=9, ha='right', va='center', fontweight='bold')
    fig.text(.065, .075, 'Intervals preserve emitted time, not pitch or matched-reference identity. '
             '95% intervals: recording-paired bootstrap, seed 298, 10,000 resamples.\n'
             'The forty recordings are reused development data. Synthetic stress is shown separately; no product approval is implied.',
             fontsize=9, linespacing=1.5)
    fig.text(.065, .025, 'Source: original Actions receipt SHA256 ' + data['receipt_sha256'], fontsize=8, color='#596873')
    outputs = _save(fig, output_dir, STEM, data)
    plt.close(fig)
    return outputs


def plot_stress(data, output_dir):
    plt = _style()
    fig, axes = plt.subplots(1, 2, figsize=(16, 9))
    fig.subplots_adjust(left=.07, right=.97, bottom=.42, top=.80, wspace=.23)
    fig.suptitle('Authored stress: expression and adjacent-semitone intentions', x=.07, y=.96,
                 ha='left', fontsize=19, fontweight='bold')
    fig.text(.07, .91, '108 cases per panel | fractional truth centers retain detuning | '
             'same frozen G path and readout rules | 2026-11-13', fontsize=11)
    for ax, cohort, title in zip(axes, ('single_expression', 'adjacent_semitone'),
                                ('A  Single intended note: 108 cases', 'B  Two adjacent intended notes: 108 cases'), strict=True):
        ax.set_title(title, loc='left', fontweight='bold', pad=15)
        values = data['synthetic'][cohort]
        for metric, shift, color, label in (('onset_f1', -.19, BLUE, 'Pitch + onset'),
                                           ('onset_offset_f1', .19, AMBER, 'Pitch + onset + offset')):
            heights = [100 * values[arm][metric] for arm in FOCUS_ARMS]
            bars = ax.bar([index + shift for index in range(3)], heights, width=.34, color=color, label=label, zorder=3)
            for bar, value in zip(bars, heights, strict=True):
                ax.text(bar.get_x() + bar.get_width() / 2, value + 1.5, f'{value:.1f}', ha='center', fontsize=9)
        ax.set_xticks(range(3), ['G', 'Unconditional split', 'Parent guard'])
        ax.set_ylabel('Case-macro F1 (%)')
        ax.set_ylim(0, 110)
        ax.set_yticks(range(0, 101, 20))
        ax.grid(axis='y', color='#DFE5EA', linewidth=.7, zorder=0)
        table_rows = [
            [f'{values[arm]["perfect_cases"]} / 108' for arm in FOCUS_ARMS],
            [str(values[arm]['too_many_note_cases']) for arm in FOCUS_ARMS],
            [str(values[arm]['too_few_note_cases']) for arm in FOCUS_ARMS],
            [f'{values[arm]["timing_matched_pitch_wrong_pairs"]} / {values[arm]["timing_only_matched_pairs"]}'
             for arm in FOCUS_ARMS],
        ]
        row_labels = ('Perfect onset+offset cases', 'Cases with extra notes', 'Cases with missing notes',
                      'Pitch-wrong / timing pairs')
        table = ax.table(cellText=[[label, *row] for label, row in zip(row_labels, table_rows, strict=True)],
            colLabels=['Diagnostic', 'G', 'Split', 'Guard'], colWidths=[.46, .18, .18, .18],
            cellLoc='center', bbox=[0., -.71, 1., .52])
        table.auto_set_font_size(False)
        table.set_fontsize(8.5)
        for (row, col), cell in table.get_celld().items():
            cell.set_edgecolor('#DCE3E8')
            if col == 0:
                cell.set_text_props(ha='left')
            if row == 0:
                cell.set_facecolor('#EDF2F6')
                cell.set_text_props(fontweight='bold')
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, frameon=False, ncol=2, loc='upper right', bbox_to_anchor=(.97, .865), fontsize=10)
    fig.text(.07, .085, 'Perfect means both pitch-aware onset and onset+offset F1 equal 1. '
             'Extra/missing counts compare predicted and authored note counts.\n'
             'Pitch-error pairs come from a separate pitch-agnostic onset+offset matching; they can differ from the pitch-aware pairs.\n'
             'These are authored intentions, not a general real-vocal accuracy estimate. The legacy 227 eligible cases remain a separate cohort.',
             fontsize=9, linespacing=1.5)
    fig.text(.07, .025, 'Source: original Actions receipt SHA256 ' + data['receipt_sha256'], fontsize=8, color='#596873')
    outputs = _save(fig, output_dir, STEM + '-stress', data)
    plt.close(fig)
    return outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    data = load_metadata(args.receipt)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    outputs = [*plot_corpus(data, args.output_dir), *plot_stress(data, args.output_dir)]
    print(json.dumps({'receipt_sha256': data['receipt_sha256'], 'report_sha256': data['report_sha256'],
        'figures': [{'path': str(path), 'bytes': path.stat().st_size, 'sha256': _sha256(path.read_bytes())}
                    for path in outputs]}, indent=2))


if __name__ == '__main__':
    main()

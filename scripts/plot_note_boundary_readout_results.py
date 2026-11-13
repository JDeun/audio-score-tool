"""Plot audited #296 receipt metadata without regenerating musical predictions.

Usage::

    python -m scripts.plot_note_boundary_readout_results \
        --receipt path/to/original-actions-artifact.zip \
        --output-dir docs/research/figures

Only complete, audit-bound corpus reports are accepted. The figure keeps F1
macros, annotation judgments, audio seconds and segment counts in separate
panels. It does not import the experiment, decoder, frontend or scorer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import zipfile
from pathlib import Path

BASE = 'gaussian_exponent_1'
NEW = 'gaussian_raw_hysteresis_split'
ARMS = ('pitch_runs', 'note_state_hmm', BASE, NEW)
ALL_ARMS = (
    'pitch_runs', 'pitch_hysteresis', 'pitch_hysteresis_reattack',
    'note_state_hmm', 'note_state_hmm_rms', BASE, 'phase_balanced',
    'positive_voicing_08', 'silent_self_099', 'hop_unscaled', NEW,
)
CASES = tuple(f'vocadito_{i}' for i in range(1, 41))
ANNOTATORS = ('A1', 'A2')
STEM = 'note-boundary-readout-2026-11-13'
BLUE, AMBER, GREEN, RED, GRAY = '#376C9F', '#C48624', '#26745D', '#B74C45', '#6D7C8A'


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def _json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'duplicate JSON key: {key}')
            result[key] = value
        return result

    def invalid(value):
        raise ValueError(f'nonfinite JSON value: {value}')

    return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)


def _number(value, label, *, minimum=None, maximum=None):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or (minimum is not None and value < minimum)
            or (maximum is not None and value > maximum)):
        raise ValueError(f'invalid {label}')
    return float(value)


def _count(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f'invalid {label}')
    return value


def _same_number(actual, expected, label):
    actual = _number(actual, label)
    if not math.isclose(actual, expected, rel_tol=0., abs_tol=1e-10):
        raise ValueError(f'{label} differs from saved per-recording metadata')


def load_metadata(receipt):
    """Read and cross-check saved public numbers; never reconstruct note events."""
    receipt = Path(receipt)
    if receipt.is_symlink() or not receipt.is_file():
        raise ValueError('a regular original Actions ZIP is required')
    required = ('vocadito.json', 'audit.json', 'legacy-vocadito.json', 'legacy-audit.json')
    with zipfile.ZipFile(receipt) as package:
        names = package.namelist()
        if len(names) != len(set(names)) or not set(required).issubset(names):
            raise ValueError('missing or duplicate receipt members')
        if any(package.getinfo(name).file_size > 50_000_000 for name in required):
            raise ValueError('unexpectedly large metadata member')
        raw = {name: package.read(name) for name in required}
    corpus, audit = _json(raw['vocadito.json']), _json(raw['audit.json'])
    legacy, legacy_audit = _json(raw['legacy-vocadito.json']), _json(raw['legacy-audit.json'])
    if (corpus.get('schema') != 'note-boundary-readout-v1'
            or corpus.get('status') != 'complete'
            or corpus.get('all_cases_complete') is not True
            or corpus.get('historical_parity', {}).get('all_equal') is not True
            or corpus.get('all_predictions_frozen_before_references') is not True
            or legacy.get('status') != 'complete'
            or audit.get('schema') != 'note-boundary-readout-audit-v1'
            or audit.get('status') != 'pass' or audit.get('audit_completed') is not True
            or legacy_audit.get('status') != 'pass'
            or legacy_audit.get('audit_completed') is not True):
        raise ValueError('complete historical parity and independent audit are required')
    bindings = (
        (audit.get('report_sha256'), raw['vocadito.json']),
        (audit.get('legacy_report_sha256'), raw['legacy-vocadito.json']),
        (audit.get('legacy_audit_sha256'), raw['legacy-audit.json']),
        (legacy_audit.get('report_sha256'), raw['legacy-vocadito.json']),
        (corpus.get('legacy_report_sha256'), raw['legacy-vocadito.json']),
    )
    if any(recorded != _sha256(content) for recorded, content in bindings):
        raise ValueError('audit is not bound to these exact report bytes')
    rows = corpus.get('cases', [])
    if (len(rows) != 40 or {row['id'] for row in rows} != set(CASES)
            or any(row.get('status') != 'scored' or set(row.get('arms', {})) != set(ALL_ARMS)
                   for row in rows)):
        raise ValueError('all forty recordings and eleven arms are required')
    by_id = {row['id']: row for row in rows}
    rows = [by_id[case] for case in CASES]
    f1, predicted = {}, {}
    for arm in ARMS:
        if any(set(row['arms'][arm]['annotators']) != set(ANNOTATORS) for row in rows):
            raise ValueError('both original annotations are required for each recording')
        predicted[arm] = sum(_count(row['arms'][arm]['count'], 'predicted note count') for row in rows)
        f1[arm] = {}
        for metric in ('onset_f1', 'onset_offset_f1'):
            values = [_number(row['arms'][arm]['annotators'][annotator][metric], metric,
                              minimum=0., maximum=1.)
                      for row in rows for annotator in ANNOTATORS]
            mean = math.fsum(values) / 80
            _same_number(corpus['aggregate'][arm][metric]['macro'], mean, f'{arm}/{metric}')
            f1[arm][metric] = corpus['aggregate'][arm][metric]['macro']
        if corpus['aggregate'][arm]['predicted_notes'] != predicted[arm]:
            raise ValueError('aggregate predicted-note denominator differs')
    deltas = [math.fsum(row['arms'][NEW]['annotators'][annotator]['onset_offset_f1']
                       - row['arms'][BASE]['annotators'][annotator]['onset_offset_f1']
                       for annotator in ANNOTATORS) / 2 for row in rows]
    primary = corpus['primary_result']
    bootstrap = primary['bootstrap']
    if (primary.get('candidate') != NEW or primary.get('baseline') != BASE
            or primary.get('metric') != 'onset_offset_f1'
            or bootstrap.get('seed') != 296 or bootstrap.get('resamples') != 10000
            or bootstrap.get('resampling_unit') != 'recording_mean_of_A1_A2'
            or bootstrap.get('method') != 'paired_percentile_linear'
            or bootstrap.get('confidence_level') != .95
            or [row['id'] for row in primary['paired_recording_deltas']] != list(CASES)):
        raise ValueError('primary contrast differs from the prespecified paired design')
    for case, delta, saved in zip(CASES, deltas, primary['paired_recording_deltas'], strict=True):
        _same_number(saved['delta'], delta, f'{case}/paired_delta')
    _same_number(primary['mean_delta'], math.fsum(deltas) / 40, 'paired macro delta')
    interval = [_number(bootstrap[key], f'bootstrap/{key}', minimum=-1., maximum=1.)
                for key in ('low', 'high')]
    if interval[0] > interval[1]:
        raise ValueError('inverted bootstrap interval')
    change_counts = {
        'improved': sum(delta > 1e-8 for delta in deltas),
        'worse': sum(delta < -1e-8 for delta in deltas),
        'tied': sum(abs(delta) <= 1e-8 for delta in deltas),
    }
    if any(primary['recordings_' + key] != value for key, value in change_counts.items()):
        raise ValueError('per-recording improvement counts differ')
    pooled = corpus['boundary_summary']['pooled_annotation_judgments']
    reference_count = sum(_count(row['arms'][BASE]['annotators'][annotator]['reference_note_count'],
                                 'reference judgment count')
                          for row in rows for annotator in ANNOTATORS)
    if pooled['recording_annotations'] != 80 or pooled['reference_notes'] != reference_count:
        raise ValueError('pooled annotation denominator differs')
    comparison = pooled['comparisons'][BASE]['onset_offset']
    partitions = {key: _count(comparison[key], key) for key in ('retained', 'gained', 'lost', 'neither')}
    matched = {arm: _count(pooled['arms'][arm]['offset_matched'], 'matched offset judgments')
               for arm in (BASE, NEW)}
    if (sum(partitions.values()) != reference_count
            or partitions['retained'] + partitions['lost'] != matched[BASE]
            or partitions['retained'] + partitions['gained'] != matched[NEW]):
        raise ValueError('retained/gained/lost judgment accounting differs')
    duration = math.fsum(_number(row['duration_seconds'], 'audio duration', minimum=0.) for row in rows)
    if duration <= 0:
        raise ValueError('positive full-corpus audio duration required')
    seconds = {BASE: 0., NEW: 0.}
    for arm, key in ((BASE, 'baseline_emitted_seconds'), (NEW, 'emitted_seconds')):
        values = [_number(row['readout'][key], key, minimum=0.) for row in rows]
        if any(value > row['duration_seconds'] + 1e-10 for value, row in zip(values, rows, strict=True)):
            raise ValueError('emitted duration exceeds full recording duration')
        seconds[arm] = math.fsum(values)
    if seconds[NEW] > seconds[BASE] + 1e-10:
        raise ValueError('an additional-cut readout cannot expand emitted coverage')

    def total_count(key):
        return sum(_count(row['readout'][key], key) for row in rows)

    cost = {
        'applied_cuts': total_count('applied_cut_count'),
        'affected_parents': total_count('affected_parent_count'),
        'all_children_pruned': total_count('originally_emitted_parents_all_children_pruned'),
        'lost_judgments_all_children_pruned': _count(
            pooled['pruning_harm']['onset_offset']['lost_matched_parent_all_children_pruned'],
            'lost judgments linked to all-pruned parents'),
    }
    for arm, field in ((BASE, 'baseline'), (NEW, 'readout')):
        cost[arm] = {
            'short_count': sum(_count(row['readout'][field]['short_segments_discarded'],
                                       'short segment count') for row in rows),
            'short_seconds': math.fsum(_number(
                row['readout'][field]['short_segments_discarded_seconds'],
                'short segment seconds', minimum=0.) for row in rows),
        }
    if cost['lost_judgments_all_children_pruned'] > partitions['lost']:
        raise ValueError('linked pruning judgments exceed all lost judgments')
    return {
        'receipt_sha256': _sha256(receipt.read_bytes()), 'report_sha256': _sha256(raw['vocadito.json']),
        'source_revision': corpus['source_revision'], 'protocol_head_revision': corpus['protocol_head_revision'],
        'f1': f1, 'predicted_notes': predicted, 'paired_deltas': deltas,
        'mean_delta': primary['mean_delta'], 'bootstrap_interval': interval,
        'recording_changes': change_counts, 'partitions': partitions, 'matched': matched,
        'reference_judgments': reference_count, 'audio_seconds': duration,
        'emitted_seconds': seconds, 'cost': cost,
    }


def plot_metadata(data, output_dir):
    """Render four distinct denominator views of one already-audited receipt."""
    import matplotlib

    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    plt.rcParams.update({
        'font.family': 'DejaVu Sans', 'font.size': 10, 'axes.titlesize': 12,
        'axes.labelsize': 10, 'axes.spines.top': False, 'axes.spines.right': False,
        'axes.labelcolor': '#25313C', 'text.color': '#25313C', 'axes.edgecolor': '#80909C',
        'xtick.color': '#475560', 'ytick.color': '#475560', 'svg.fonttype': 'none',
        'figure.facecolor': 'white', 'savefig.facecolor': 'white',
    })
    fig, axes = plt.subplots(2, 2, figsize=(17, 11))
    fig.subplots_adjust(left=.065, right=.97, bottom=.17, top=.845, hspace=.58, wspace=.24)
    fig.suptitle('Persistent raw-pitch splits on frozen Gaussian paths', x=.065, y=.965,
                 ha='left', fontsize=20, fontweight='bold')
    fig.text(.065, .927,
             'vocadito reused development corpus | 40 recordings × 2 annotators | '
             'same G path, added cuts only | 2026-11-13', fontsize=11)
    labels = ['Pitch\nruns', 'Legacy\nHMM', 'Gaussian\nG', 'G + raw\npitch cuts']
    ax = axes[0, 0]
    ax.set_title('A  Note matching F1', loc='left', pad=29, fontweight='bold')
    ax.text(0., 1.04, 'Macro of 80 recording × annotator scores; n = predicted events',
            transform=ax.transAxes, fontsize=9)
    for metric, shift, color, label in (
        ('onset_f1', -.19, BLUE, 'Pitch + onset'),
        ('onset_offset_f1', .19, AMBER, 'Pitch + onset + offset'),
    ):
        heights = [100 * data['f1'][arm][metric] for arm in ARMS]
        bars = ax.bar([i + shift for i in range(4)], heights, width=.34,
                      color=color, label=label, zorder=3)
        for bar, value in zip(bars, heights, strict=True):
            ax.text(bar.get_x() + bar.get_width() / 2, value + 1.4, f'{value:.1f}',
                    ha='center', va='bottom', fontsize=9)
    ax.set_xticks(range(4), [f'{label}\nn={data["predicted_notes"][arm]:,}'
                            for label, arm in zip(labels, ARMS, strict=True)])
    ax.set_ylabel('F1 (%)')
    ax.set_ylim(0, 106)
    ax.set_yticks(range(0, 101, 20))
    ax.grid(axis='y', color='#DFE5EA', linewidth=.7, zorder=0)
    ax.legend(frameon=False, loc='upper left', fontsize=9)

    ax = axes[0, 1]
    deltas = [100 * value for value in data['paired_deltas']]
    ax.set_title('B  Offset F1 change in every recording', loc='left', pad=29, fontweight='bold')
    counts = data['recording_changes']
    ax.text(0., 1.04,
            f'{counts["improved"]} improved | {counts["worse"]} worse | {counts["tied"]} tied '
            '(paired A1/A2 means)', transform=ax.transAxes, fontsize=9)
    colors = [GREEN if value > 1e-6 else RED if value < -1e-6 else GRAY for value in deltas]
    ax.bar(range(1, 41), deltas, color=colors, width=.8, zorder=3)
    ax.axhline(0., color='#475560', linewidth=.9)
    ax.axhline(100 * data['mean_delta'], color=BLUE, linestyle='--', linewidth=1.)
    low, high = [100 * value for value in data['bootstrap_interval']]
    ax.text(.02, .98,
            f'Mean {100 * data["mean_delta"]:+.2f} pp\n'
            f'95% paired bootstrap [{low:+.2f}, {high:+.2f}] pp',
            transform=ax.transAxes, va='top', fontsize=9,
            bbox={'facecolor': 'white', 'edgecolor': 'none', 'alpha': .92, 'pad': 4})
    spread = max(deltas + [0.]) - min(deltas + [0.])
    margin = max(2., spread * .18)
    ax.set_ylim(min(deltas + [0.]) - margin, max(deltas + [0.]) + 2 * margin)
    ax.set_xlim(.3, 40.7)
    ax.set_xticks(range(1, 41))
    ax.tick_params(axis='x', labelsize=6.5, length=2)
    ax.set_xlabel('Recording ID (vocadito_1 through vocadito_40)')
    ax.set_ylabel('New − G (percentage points)')
    ax.grid(axis='y', color='#DFE5EA', linewidth=.7, zorder=0)

    ax = axes[1, 0]
    ax.set_title('C  Offset-matched reference judgments', loc='left', pad=29, fontweight='bold')
    ax.text(0., 1.04, 'A1+A2 judgments; these counts are not unique physical notes',
            transform=ax.transAxes, fontsize=9)
    parts, matched = data['partitions'], data['matched']
    maximum = max(matched.values())
    for y, arm, extra, color in ((1, BASE, 'lost', RED), (0, NEW, 'gained', GREEN)):
        ax.barh(y, parts['retained'], height=.46, color=GRAY)
        ax.barh(y, parts[extra], left=parts['retained'], height=.46, color=color)
        for count, center in ((parts['retained'], parts['retained'] / 2),
                              (parts[extra], parts['retained'] + parts[extra] / 2)):
            if count > .11 * max(1, maximum):
                ax.text(center, y, f'{count:,}', color='white', ha='center', va='center',
                        fontweight='bold', fontsize=10)
        ax.text(matched[arm] + .025 * max(1, maximum), y, f'{matched[arm]:,} matched', va='center', fontsize=9)
    ax.set_yticks([1, 0], ['G', 'G + cuts'])
    ax.set_ylim(-.85, 1.8)
    ax.set_xlim(0, max(1, maximum) * 1.27)
    ax.set_xlabel('Matched annotation judgments (both annotators pooled)')
    ax.legend(handles=[Patch(color=GRAY, label=f'Retained {parts["retained"]:,}'),
                       Patch(color=RED, label=f'Lost {parts["lost"]:,}'),
                       Patch(color=GREEN, label=f'Gained {parts["gained"]:,}')],
              frameon=False, loc='upper left', ncol=3, fontsize=8.5)
    ax.text(.02, .035,
            f'Reference denominator: {data["reference_judgments"]:,} judgments\n'
            f'Net change: {parts["gained"] - parts["lost"]:+,} matched judgments',
            transform=ax.transAxes, va='bottom', fontsize=9)
    ax.grid(axis='x', color='#DFE5EA', linewidth=.7, zorder=0)
    ax.set_axisbelow(True)

    ax = axes[1, 1]
    ax.set_title('D  Emitted coverage and pruning cost', loc='left', pad=29, fontweight='bold')
    ax.text(0., 1.04, f'40 recordings counted once; full audio = {data["audio_seconds"]:.3f} s',
            transform=ax.transAxes, fontsize=9)
    ax.set_axis_off()
    coverage_ax = ax.inset_axes([.13, .70, .85, .21])
    coverage = [100 * data['emitted_seconds'][arm] / data['audio_seconds'] for arm in (BASE, NEW)]
    coverage_ax.barh([1, 0], coverage, height=.52, color=[GRAY, GREEN])
    coverage_ax.set_yticks([1, 0], ['G', 'G + cuts'])
    coverage_ax.set_xlim(0, 100)
    coverage_ax.set_xticks([0, 25, 50, 75, 100])
    coverage_ax.tick_params(labelsize=8)
    coverage_ax.grid(axis='x', color='#DFE5EA', linewidth=.6, zorder=0)
    coverage_ax.set_axisbelow(True)
    for y, arm, value in zip([1, 0], (BASE, NEW), coverage, strict=True):
        inside = value > 72
        coverage_ax.text(value - 1 if inside else value + 1, y,
                         f'{value:.2f}% ({data["emitted_seconds"][arm]:.3f} s)',
                         ha='right' if inside else 'left', va='center',
                         color='white' if inside else '#25313C', fontsize=8)
    ax.text(.13, .59, 'Emitted note duration / full audio duration (%)',
            transform=ax.transAxes, fontsize=9)
    cost = data['cost']
    lines = [
        ('Applied cuts / affected G parents', f'{cost["applied_cuts"]:,} / {cost["affected_parents"]:,}'),
        ('Short G parents → short children', f'{cost[BASE]["short_count"]:,} → {cost[NEW]["short_count"]:,}'),
        ('Discarded seconds from short segments', f'{cost[BASE]["short_seconds"]:.3f} → {cost[NEW]["short_seconds"]:.3f}'),
        ('Emitted parents with all children pruned', f'{cost["all_children_pruned"]:,}'),
        ('Lost G judgments linked to those parents',
         f'{cost["lost_judgments_all_children_pruned"]:,} of {parts["lost"]:,}'),
    ]
    for i, (label, value) in enumerate(lines):
        y = .465 - i * .083
        ax.text(0., y, label, transform=ax.transAxes, fontsize=9, va='center')
        ax.text(.98, y, value, transform=ax.transAxes, fontsize=9, va='center',
                ha='right', fontweight='bold')
    ax.text(0., .035, 'Last row is an overlap descriptor, not a causal attribution.',
            transform=ax.transAxes, fontsize=8, color='#566775')

    fig.text(.065, .088,
             'F1: pitch ≤50 cents, onset ≤50 ms; offset ≤max(50 ms, 20% reference duration). '
             'Saved per-file F1 uses 8 decimals.\n'
             'Paired interval: 10,000 recording resamples, seed 296, linear percentiles. '
             'Same G path and raw observations; each child retains the 80 ms minimum.\n'
             'The corpus is reused development data. This figure does not establish held-out generalization or product approval.',
             fontsize=8.5, linespacing=1.45)
    fig.text(.065, .035, 'Original Actions ZIP SHA-256: ' + data['receipt_sha256'],
             fontsize=7.5, color='#566775')
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {suffix: output_dir / f'{STEM}.{suffix}' for suffix in ('png', 'svg')}
    description = ('Metadata-only figure; original Actions ZIP SHA256=' + data['receipt_sha256']
                   + '; corpus report SHA256=' + data['report_sha256'])
    fig.savefig(paths['png'], dpi=200, metadata={'Description': description})
    fig.savefig(paths['svg'], metadata={'Description': description, 'Date': None})
    paths['svg'].write_text(
        '\n'.join(line.rstrip() for line in paths['svg'].read_text().splitlines()) + '\n'
    )
    plt.close(fig)
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    data = load_metadata(args.receipt)
    paths = plot_metadata(data, args.output_dir)
    print(json.dumps({'receipt_sha256': data['receipt_sha256'],
                      'png': str(paths['png'].resolve()), 'svg': str(paths['svg'].resolve()),
                      'recordings': 40, 'recording_annotations': 80,
                      'reference_judgments': data['reference_judgments'],
                      'prediction_regeneration': False}, sort_keys=True))


if __name__ == '__main__':
    main()

"""Authored score/performance experiment for #249; no real-audio accuracy claim."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import random
import time
from dataclasses import asdict
from pathlib import Path
from statistics import mean

from scripts.bar_sum_rhythm import (
    SETTINGS,
    Clock,
    Observation,
    Q,
    WrittenNote,
    rests,
    search_phases,
    solve,
    structural_check,
)

ARMS = ('independent_known_phase', 'joint_sum_known_phase', 'joint_notation_known_phase',
        'joint_unknown_phase', 'joint_unknown_phase_accent')
PROFILES = ('clean', 'jitter', 'staccato', 'weak_accent')


def fingerprint(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, allow_nan=False).encode()).hexdigest()


def authored_scores():
    """Original illustrative patterns, not songs, training data or measured performances."""
    regular = [(12, True), (6, True), (6, True), (24, True)]
    specs = [
        ('regular_44', Clock(4, 4, 120), 0, regular * 3),
        ('regular_34', Clock(3, 4, 90), 0, [(12, True), (6, True), (6, True), (12, True)] * 4),
        ('pickup_eighth', Clock(4, 4, 120), 6, [(6, True)] + regular * 3),
        ('pickup_quarter', Clock(4, 4, 100), 12, [(12, True)] + regular * 3),
        ('initial_rest', Clock(4, 4, 120), 0, [(24, False), (12, True), (12, True)] + regular * 2),
        ('syncopation', Clock(4, 4, 110), 0, [(6, True), (12, True), (6, True), (12, True), (12, True)] * 3),
        ('triplets', Clock(4, 4, 120), 0, [(4, True), (4, True), (4, True), (12, True), (24, True)] * 3),
        ('cross_bar_hold', Clock(4, 4, 120), 0,
         [(36, True), (24, True), (12, True), (24, True)] + regular),
        ('repeated_pitch', Clock(4, 4, 120), 0, [(6, True)] * 24),
        ('compound_68', Clock(6, 8, 80, 1.5), 0, [(18, True), (6, True), (6, True), (6, True)] * 4),
        ('internal_rests', Clock(4, 4, 120), 0,
         [(12, True), (6, False), (6, True), (12, True), (12, False)] * 3),
        ('full_bar_rest', Clock(4, 4, 120), 0, regular + [(48, False)] + regular * 2),
    ]
    result = []
    for name, clock, phase, pattern in specs:
        notes, tick = [], 0
        for duration, sounding in pattern:
            if sounding:
                i = len(notes)
                notes.append(WrittenNote(f'n{i}', 69 if name == 'repeated_pitch' else (60, 62, 64, 67)[i % 4],
                                         tick, duration))
            tick += duration
        result.append({'name': name, 'clock': clock, 'phase': phase, 'notes': tuple(notes),
                       'authored_length': tick})
    return result


def performance(score, profile):
    """Observation generator; hidden written durations/phase never enter the selector."""
    seed = int(hashlib.sha256((score['name'] + '/' + profile).encode()).hexdigest()[:16], 16)
    rng = random.Random(seed)
    observations = []
    for n in score['notes']:
        jitter = 0 if profile == 'clean' else rng.uniform(-.36, .36) if profile == 'staccato' else rng.uniform(-1.8, 1.8)
        onset = max(0.0, n.start + jitter)
        end_noise = 0 if profile == 'clean' else rng.uniform(-.36, .36) if profile == 'staccato' else rng.uniform(-2.2, 2.2)
        gate = .6 if profile == 'staccato' else 1.0
        offset = max(onset + .25, n.start + gate * n.duration + end_noise)
        observations.append(Observation(n.id, n.pitch, onset * score['clock'].tick_seconds,
                                        offset * score['clock'].tick_seconds))
    accents = []
    unit = score['clock'].beat_quarters * Q
    # Synthetic OTHER-PART pulse strengths, not gold downbeat flags or an audio extractor.
    for i in range(-8, 100):
        tick = score['phase'] + i * unit
        if not 0 <= tick < score['authored_length']:
            continue
        strength = 1.0 if abs((tick - score['phase']) % score['clock'].bar) < 1e-8 else .25
        if profile == 'weak_accent':
            strength = .4
        else:
            strength = min(1.0, max(0.0, strength + rng.uniform(-.025, .025)))
        accents.append((max(0.0, tick + (0 if profile == 'clean' else rng.uniform(-.15, .15))), strength))
    return tuple(observations), tuple(accents), seed


def notation_metrics(notes, truth):
    if [(n.id, n.pitch) for n in notes] != [(n.id, n.pitch) for n in truth]:
        raise ValueError('attack or pitch identity changed')
    onset = [n.start == t.start for n, t in zip(notes, truth)]
    duration = [n.duration == t.duration for n, t in zip(notes, truth)]
    pairs = [a and b for a, b in zip(onset, duration)]
    predicted_rests, true_rests = set(rests(notes)), set(rests(truth))
    rest_f1 = (2 * len(predicted_rests & true_rests) / (len(predicted_rests) + len(true_rests))
               if predicted_rests or true_rests else 1.0)
    return {'onset_exact': mean(onset), 'duration_exact': mean(duration), 'note_pair_exact': mean(pairs),
            'all_notes_exact': all(pairs), 'rest_interval_f1': rest_f1, 'correct_note_ids': [
                n.id for n, correct in zip(notes, pairs) if correct]}


def evaluate(score, profile):
    observations, accents, seed = performance(score, profile)
    before = fingerprint({'observations': [asdict(x) for x in observations], 'accents': accents})
    clock, truth = score['clock'], score['notes']
    row = {'id': score['name'] + '/' + profile, 'phrase': score['name'], 'profile': profile,
           'status': 'started', 'seed': seed, 'input_sha256': before,
           'reference_sha256': fingerprint({'notes': [asdict(n) for n in truth], 'phase': score['phase']}),
           'clock': asdict(clock), 'expected_notes': len(truth), 'true_phase_ticks': score['phase'], 'arms': {}}
    baseline_correct = set()
    for name, mode in zip(ARMS[:3], ('independent', 'joint_sum', 'joint_notation')):
        # Only these explicitly diagnostic arms receive the annotated phase.
        solution = solve(observations, clock, score['phase'], mode)
        metrics = notation_metrics(solution.notes, truth)
        correct = set(metrics['correct_note_ids'])
        if name == ARMS[0]:
            baseline_correct = correct
        row['arms'][name] = {'status': 'scored', 'known_phase_diagnostic': True,
                            'metrics': metrics, 'structure': structural_check(solution, clock, observations),
                            'correct_pairs_gained_vs_independent': len(correct - baseline_correct),
                            'correct_pairs_lost_vs_independent': len(baseline_correct - correct),
                            'solution': asdict(solution)}
    for name, evidence in ((ARMS[3], ()), (ARMS[4], accents)):
        selected = search_phases(observations, clock, evidence)
        phase = selected['selected_phase']
        row['arms'][name] = {
            'status': 'scored', 'known_phase_diagnostic': False,
            'selected_phase': phase, 'candidate_phases': selected['candidate_phases'],
            'phase_correct': phase == score['phase'] if phase is not None else None,
            'truth_in_candidate_set': score['phase'] in selected['candidate_phases'],
            'runner_up_margin': selected['runner_up_margin'], 'phase_costs': selected['phase_costs'],
            'accepted_metrics': notation_metrics(selected['best'].notes, truth) if phase is not None else None,
            'structure_of_best_diagnostic': structural_check(selected['best'], clock, observations),
            'best_diagnostic_not_deployed_when_abstained': asdict(selected['best']),
        }
    if before != fingerprint({'observations': [asdict(x) for x in observations], 'accents': accents}):
        raise ValueError('input mutation')
    row['status'] = 'scored'
    return row


def ambiguity_controls():
    clock = Clock(4, 4, 120)
    obs = tuple(Observation(str(i), 60, i * .5, (i + 1) * .5) for i in range(12))
    raw_costs = [solve(obs, clock, p, 'joint_sum').cost for p in range(clock.bar)]
    unknown = search_phases(obs, clock)
    # Both scores render exactly this SAME sounding sequence using different articulation.
    sounding_a = [(i * .5, i * .5 + .25) for i in range(8)]
    sounding_b = [(i * .5, i * .5 + .25) for i in range(8)]
    return {
        'sum_only_equal_cost_phases': sum(math.isclose(x, min(raw_costs), abs_tol=1e-10) for x in raw_costs),
        'possible_phases': clock.bar, 'notation_prior_candidate_phases': unknown['candidate_phases'],
        'notation_prior_selected_phase': unknown['selected_phase'],
        'same_sound_distinct_notation': {
            'quarter_staccato_input_sha256': fingerprint(sounding_a),
            'eighth_plus_rest_input_sha256': fingerprint(sounding_b),
            'inputs_identical': sounding_a == sounding_b,
            'quarter_written_duration_ticks': 12, 'eighth_written_duration_ticks': 6,
            'uniquely_identifiable_from_these_events': False,
        },
    }


def aggregate(rows, planned):
    if (len(rows) != len(planned) or {r['id'] for r in rows} != set(planned)
            or any(r['status'] != 'scored' or set(r['arms']) != set(ARMS) for r in rows)):
        return None
    summary = {}
    for name in ARMS[:3]:
        entries = [r['arms'][name] for r in rows]
        deltas = [r['arms'][name]['metrics']['note_pair_exact']
                  - r['arms'][ARMS[0]]['metrics']['note_pair_exact'] for r in rows]
        summary[name] = {k: mean(e['metrics'][k] for e in entries)
                         for k in ('onset_exact', 'duration_exact', 'note_pair_exact', 'rest_interval_f1')}
        summary[name].update(
            structurally_valid_cases=sum(e['structure']['bar_sums_exact'] for e in entries),
            all_notes_exact_cases=sum(e['metrics']['all_notes_exact'] for e in entries),
            improved_cases=sum(x > 1e-10 for x in deltas), worse_cases=sum(x < -1e-10 for x in deltas),
            corrected_pairs=sum(e['correct_pairs_gained_vs_independent'] for e in entries),
            damaged_pairs=sum(e['correct_pairs_lost_vs_independent'] for e in entries))
    for name in ARMS[3:]:
        entries = [r['arms'][name] for r in rows]
        decided = [e for e in entries if e['selected_phase'] is not None]
        correct = sum(e['phase_correct'] is True for e in entries)
        summary[name] = {'cases': len(entries), 'decided': len(decided), 'correct_phase': correct,
                         'wrong_phase': len(decided) - correct, 'abstained': len(entries) - len(decided),
                         'truth_in_candidate_set': sum(e['truth_in_candidate_set'] for e in entries),
                         'conditional_phase_accuracy': correct / len(decided) if decided else None,
                         'correct_and_decided_rate': correct / len(entries)}
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error('new output path required')
    root = Path(__file__).resolve().parents[1]
    started = time.monotonic()
    scores = authored_scores()
    planned = [s['name'] + '/' + p for s in scores for p in PROFILES]
    paths = ('scripts/bar_sum_rhythm.py', 'scripts/run_bar_sum_rhythm.py',
             'tests/test_bar_sum_rhythm.py', 'docs/research/BAR_SUM_RHYTHM_PROTOCOL_2026-11-11.md')
    report = {'status': 'running', 'scope': 'authored symbolic performance-to-notation only',
              'source_revision': os.getenv('GITHUB_SHA', 'local-working-files'),
              'experiment_head': os.getenv('EXPERIMENT_HEAD'), 'python': platform.python_version(),
              'source_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths},
              'settings': SETTINGS, 'settings_sha256': fingerprint(SETTINGS), 'planned_ids': planned,
              'distinct_authored_phrases': len(scores), 'profiles': PROFILES, 'cases': [],
              'real_audio': False, 'model_inference': False, 'training': False,
              'notation_reference_supplied_to_known_phase_arms': 'phase only, diagnostic',
              'product_quality_approved': False, 'all_cases_complete': False, 'aggregate': None}

    def save():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix('.tmp')
        temporary.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
        temporary.replace(args.output)

    save()
    report['ambiguity_controls'] = ambiguity_controls()
    for s in scores:
        for p in PROFILES:
            try:
                row = evaluate(s, p)
            except Exception as exc:
                row = {'id': s['name'] + '/' + p, 'status': 'failed', 'error_type': type(exc).__name__}
            report['cases'].append(row)
            save()
            print(row['id'], row['status'], flush=True)
    report['aggregate'] = aggregate(report['cases'], planned)
    report['all_cases_complete'] = report['aggregate'] is not None
    report['status'] = 'complete' if report['all_cases_complete'] else 'incomplete'
    report['elapsed_seconds'] = time.monotonic() - started
    save()
    return 0 if report['all_cases_complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

"""Research only: real aligned MIDI durations, privileged beat clocks, blind units."""
from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import io
import json
import math
import os
import statistics
import time
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

REVISION = '4097b45757bed854818cf87e77b92323ebf90615'
ROOT = 'https://raw.githubusercontent.com/CPJKU/asap-dataset/' + REVISION + '/'
METADATA_BLOB = 'f9b655ca92b3d88febab09763e7ed3b74c2c7878'
MAX_FILE = 4_000_000
MAX_TOTAL = 40_000_000
N_PIECES = 12
UNITS = (.5, 1., 2.)
GATES = ((1., 0.), (.75, .015), (.5, .030), (1.25, .020))
GRID = 48
EPS = 1e-7
DURATION_METHODS = ('literal', 'spelling', 'articulation')
SELECTORS = ('keep_unit1', 'prior120', 'duration', 'duration_voice_diagnostic')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def fingerprint(value):
    return sha(json.dumps(value, sort_keys=True, allow_nan=False).encode())


def rows(raw):
    return list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))


class Reader:
    def __init__(self):
        self.total = 0
        self.files = {}

    def get(self, path):
        if (not path or path.startswith('/') or '..' in PurePosixPath(path).parts
                or '\\' in path or '?' in path or '#' in path):
            raise ValueError('unsafe source path')
        request = urllib.request.Request(ROOT + urllib.parse.quote(path, safe='/'),
                                         headers={'User-Agent': 'audio-score-research/1.0'})
        with urllib.request.urlopen(request, timeout=40) as response:
            if response.status != 200 or not response.url.startswith(ROOT):
                raise ValueError('unapproved source redirect')
            raw = response.read(MAX_FILE + 1)
        if len(raw) > MAX_FILE or self.total + len(raw) > MAX_TOTAL:
            raise ValueError('source byte budget exceeded')
        self.total += len(raw)
        self.files[path] = {'sha256': sha(raw), 'bytes': len(raw)}
        return raw


def selection(metadata):
    """Metadata-only, before predictions; at most two compositions per composer."""
    eligible = [r for r in metadata if r.get('robust_note_alignment') in ('1', '1.0')
                and r.get('parangonada_data_folder') and r.get('performance_annotations')]
    eligible.sort(key=lambda r: sha(('nasap-duration-v1/' + r['midi_performance']).encode()))
    pieces, composers, result = set(), Counter(), []
    for r in eligible:
        key = (r['composer'], r['title'])
        if key in pieces or composers[r['composer']] >= 2:
            continue
        result.append(r)
        pieces.add(key)
        composers[r['composer']] += 1
        if len(result) == N_PIECES:
            break
    return result


@dataclass(frozen=True)
class Observation:
    id: str
    pitch: int
    onset: float
    duration: float


def validate(notes):
    if not notes or len({n.id for n in notes}) != len(notes):
        raise ValueError('nonempty unique note identities required')
    if any(not 0 <= n.pitch <= 127 or not math.isfinite(n.onset)
           or not math.isfinite(n.duration) or n.onset < 0 or n.duration <= 0
           for n in notes):
        raise ValueError('invalid note observation')


def duration_vocabulary():
    options = {}
    for base in (.0625, .125, .25, .5, 1., 2., 4., 8.):
        cost = abs(math.log2(base)) * .12
        for ratio, extra in ((1., 0.), (1.5, .18), (2/3, .30)):
            duration = base * ratio
            if duration <= 8:
                options[duration] = min(options.get(duration, math.inf), cost + extra)
    return sorted(options.items())


VOCAB = duration_vocabulary()


def fit(notes, unit=1., mode='articulation', next_voice=None):
    """No score/note labels, meter, name or reference tempo accepted here.

    next_voice is OPTIONAL privileged score-voice grouping, NOT an audio-only arm.
    Onsets snap ONCE in the supplied pulse coordinate; all units preserve that fit.
    """
    validate(notes)
    if unit not in UNITS or mode not in DURATION_METHODS:
        raise ValueError('unsupported unit or method')
    next_voice = {} if next_voice is None else next_voice
    predictions, total = {}, 0.
    for note in notes:
        observed = note.duration * unit
        onset = round(note.onset * GRID) / GRID * unit
        scores = []
        for duration, spelling in VOCAB:
            if mode == 'literal':
                cost = abs(duration - observed)
            else:
                gates = GATES if mode == 'articulation' else ((1., 0.),)
                cost = min(math.log(observed / (gate * duration)) ** 2 + penalty
                           for gate, penalty in gates) + .04 * spelling
            if note.id in next_voice:
                gap = next_voice[note.id] * unit - onset - duration
                if gap < -.125 * unit:
                    cost += .20 * min(4., (-gap / unit) ** 2)
                elif gap > .125 * unit:
                    gap_cost = min(math.log(gap / d) ** 2 + .04 * c for d, c in VOCAB)
                    cost += .15 * gap_cost
            scores.append((cost, abs(duration - observed), duration))
        cost, _, duration = min(scores)
        predictions[note.id] = (onset, duration)
        total += cost
    return predictions, total / len(notes)


def choose_units(notes, pulse_rate, next_voice=None):
    """Selections are fixed before evaluator sees true unit or score durations."""
    if not math.isfinite(pulse_rate) or pulse_rate <= 0:
        raise ValueError('invalid physical pulse rate')
    validate(notes)
    costs = {u: fit(notes, u)[1] for u in UNITS}
    context = {u: fit(notes, u, next_voice=next_voice)[1] for u in UNITS}
    def choose(values):
        ordered = sorted((v, u) for u, v in values.items())
        return None if ordered[1][0] - ordered[0][0] < 1e-9 else ordered[0][1]
    return {'keep_unit1': 1.,
            'prior120': min(UNITS, key=lambda u: abs(math.log2(pulse_rate * u / 120))),
            'duration': choose(costs),
            'duration_voice_diagnostic': choose(context)}, {
                'duration_costs': costs, 'voice_costs': context}


def interpolate(value, xs, ys):
    if not xs[0] <= value <= xs[-1]:
        raise ValueError('no extrapolation outside annotated beats')
    i = min(len(xs) - 2, max(0, bisect.bisect_right(xs, value) - 1))
    return ys[i] + (value - xs[i]) / (xs[i+1] - xs[i]) * (ys[i+1] - ys[i])


def beat_clock(performance_rows, annotation_raw):
    """Privileged annotation clock only. Ignore CSV score columns in predictor."""
    beats, signatures = [], []
    for line in annotation_raw.decode().splitlines():
        fields = line.split('\t')
        if len(fields) < 3:
            raise ValueError('malformed beat annotation')
        t = float(fields[0])
        labels = fields[2].split(',')
        if labels[0] in ('b', 'db', 'bR'):
            beats.append((t, labels[0]))
        if len(labels) > 1 and labels[1]:
            signatures.append((t, labels[1]))
    if len(beats) < 42 or not signatures:
        raise ValueError('insufficient annotated beat context')
    times = [b[0] for b in beats]
    if any(not math.isfinite(t) for t in times) or any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError('invalid beat ordering')
    start, end = times[8], times[40]
    active = [s for t, s in signatures if t <= start]
    current = active[-1] if active else signatures[0][1]
    changes = [s for t, s in signatures if start < t < end]
    if current not in ('2/4', '3/4', '4/4') or any(s != current for s in changes):
        raise ValueError('unsupported meter or change in fixed window')
    if any(tag == 'bR' for _, tag in beats[8:41]):
        raise ValueError('irregular beat annotation in fixed window')
    offsets = []
    for r in performance_rows:
        t, q = float(r['last_beat']), float(r['last_beat_ref'])
        if not start <= t <= end:
            continue
        i = min(range(8, 41), key=lambda k: abs(times[k] - t))
        if abs(times[i] - t) > 1e-4:
            raise ValueError('exported beat clock disagrees with TSV')
        offsets.append(q - i)
    if not offsets or max(offsets) - min(offsets) > 1e-4:
        raise ValueError('exported score beat coordinates are not quarter-consistent')
    shift = statistics.median(offsets)
    return times[8:41], [i + shift for i in range(8, 41)], current


def evaluate(predictions, targets):
    values = []
    for nid, target in targets.items():
        onset, duration = predictions[nid]
        oe, de = abs(onset - target[0]), abs(duration - target[1])
        values.append({'id': nid, 'onset_exact': oe <= 1/96 + EPS,
                       'duration_exact': de <= 1/96 + EPS,
                       'pair_exact': oe <= 1/96 + EPS and de <= 1/96 + EPS})
    if not values:
        raise ValueError('no aligned evaluation notes')
    return {'n': len(values),
            **{k: sum(v[k] for v in values) for k in ('onset_exact', 'duration_exact', 'pair_exact')},
            'correct_duration_ids': [v['id'] for v in values if v['duration_exact']]}


def assess(reader, row):
    folder = row['parangonada_data_folder'].rstrip('/')
    perf_raw = reader.get(folder + '/ppart.csv')
    perf = rows(perf_raw)
    clock_t, clock_q, meter = beat_clock(perf, reader.get(row['performance_annotations']))
    origin = clock_q[0]
    observations = []
    for r in perf:
        start, duration = float(r['onset_sec']), float(r['duration_sec'])
        if not (clock_t[0] <= start and start + duration <= clock_t[-1] and duration > 0):
            continue
        onset = interpolate(start, clock_t, clock_q) - origin
        end = interpolate(start + duration, clock_t, clock_q) - origin
        observations.append(Observation(r['id'], int(r['pitch']), onset, end - onset))
    observations.sort(key=lambda n: (n.onset, n.pitch, n.id))
    validate(observations)
    if len(observations) < 24:
        raise ValueError('too few performed notes in fixed window')
    before = fingerprint([n.__dict__ for n in observations])
    # No score loaded before the automatic duration-only predictions.
    duration_preds = {m: fit(observations, mode=m)[0] for m in DURATION_METHODS}
    base_rate = 60 / statistics.median(b - a for a, b in zip(clock_t, clock_t[1:]))
    auto_pre = {}
    for true_unit in UNITS:
        scaled = [Observation(n.id, n.pitch, n.onset / true_unit, n.duration / true_unit)
                  for n in observations]
        picked, costs = choose_units(scaled, base_rate / true_unit)
        auto_pre[true_unit] = (scaled, picked, costs)
    # Evaluation labels and the separate privileged voice diagnostic are loaded NOW.
    score = rows(reader.get(folder + '/part.csv'))
    align = rows(reader.get(folder + '/align.csv'))
    score_by_id = {r['id']: r for r in score}
    obs_by_id = {n.id: n for n in observations}
    targets, voices, rejected = {}, {}, Counter()
    duplicates = Counter(r['ppartid'] for r in align if r['matchtype'] == '0')
    for r in align:
        if r['matchtype'] != '0' or r['ppartid'] not in obs_by_id:
            continue
        nid = r['ppartid']
        s = score_by_id.get(r['partid'])
        if duplicates[nid] != 1 or s is None:
            rejected['ambiguous_alignment'] += 1
            continue
        onset, duration = float(s['onset_quarter']) - origin, float(s['duration_quarter'])
        if abs(float(s['onset_beat']) - float(s['onset_quarter'])) > 1e-4:
            raise ValueError('beat/quarter source convention mismatch')
        if duration <= 0 or not 0 <= onset < 32 or int(s['pitch']) != obs_by_id[nid].pitch:
            rejected['grace_outside_or_pitch_mismatch'] += 1
            continue
        targets[nid] = (onset, duration)
        voices[nid] = str(s['voice'])
    if len(targets) < 16:
        raise ValueError('insufficient unique robust aligned notes')
    next_voice = {}
    # Voice membership is supplied, but next onset is an actual performed onset.
    for nid, voice in voices.items():
        start = obs_by_id[nid].onset
        later = [obs_by_id[j].onset for j, v in voices.items()
                 if v == voice and obs_by_id[j].onset > start + .125]
        if later:
            next_voice[nid] = min(later)
    context_pred = fit(observations, next_voice=next_voice)[0]
    duration_preds['articulation_voice_diagnostic'] = context_pred
    duration_scores = {m: evaluate(p, targets) for m, p in duration_preds.items()}
    baseline_ids = set(duration_scores['literal']['correct_duration_ids'])
    for value in duration_scores.values():
        ids = set(value.pop('correct_duration_ids'))
        value['fixed_duration'] = len(ids - baseline_ids)
        value['damaged_duration'] = len(baseline_ids - ids)
    trials = []
    for true_unit in UNITS:
        scaled, original, costs = auto_pre[true_unit]
        voice_scaled = {nid: value / true_unit for nid, value in next_voice.items()}
        selected, full_costs = choose_units(scaled, base_rate / true_unit, voice_scaled)
        if any(selected[k] != original[k] for k in SELECTORS[:-1]):
            raise ValueError('evaluation labels changed blind selector')
        trials.append({'constructed_true_unit': true_unit,
                       'selected': selected, 'costs': full_costs,
                       'correct': {k: v == true_unit for k, v in selected.items()}})
    if before != fingerprint([n.__dict__ for n in observations]):
        raise ValueError('input mutation')
    ratios = [obs_by_id[n].duration / targets[n][1] for n in targets]
    return {'status': 'complete', 'meter': meter, 'observed_notes': len(observations),
            'matched_notes': len(targets), 'rejected_alignment': dict(rejected),
            'window_seconds': clock_t[-1] - clock_t[0], 'window_quarters': 32,
            'observation_sha256': before, 'duration_scores': duration_scores,
            'unit_trials': trials, 'median_performed_written_ratio': statistics.median(ratios),
            'ratio_below_075': sum(r < .75 for r in ratios),
            'ratio_above_125': sum(r > 1.25 for r in ratios),
            'explicit_rests_evaluated': False, 'waveform_transcription_evaluated': False}


def summary(cases):
    complete = [r for r in cases if r['status'] == 'complete']
    result = {'planned': len(cases), 'completed': len(complete),
              'statuses': dict(Counter(r['status'] for r in cases)),
              'matched_notes': sum(r['matched_notes'] for r in complete),
              'duration_methods': {}, 'selectors': {}}
    if not complete:
        return result
    for method in complete[0]['duration_scores']:
        group = [r['duration_scores'][method] for r in complete]
        counts = {key: sum(g[key] for g in group) for key in group[0]}
        counts['duration_macro'] = statistics.mean(g['duration_exact'] / g['n'] for g in group)
        counts['pair_macro'] = statistics.mean(g['pair_exact'] / g['n'] for g in group)
        result['duration_methods'][method] = counts
    for method in SELECTORS:
        trials = [t for r in complete for t in r['unit_trials']]
        result['selectors'][method] = {
            'trials': len(trials), 'correct': sum(t['correct'][method] for t in trials),
            'abstained': sum(t['selected'][method] is None for t in trials),
            'all_planned_trials': len(cases) * len(UNITS)}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error('new output required')
    reader = Reader()
    report = {'status': 'started', 'dataset_revision': REVISION,
              'dataset_license': 'CC BY-NC-SA 4.0; isolated research, no commercial clearance',
              'source_revision': os.getenv('GITHUB_SHA', 'local'), 'cases': [],
              'annotated_beat_clock_provided': True, 'source_is_real_performance_midi': True,
              'aliases_constructed_from_annotations': True, 'training': False,
              'audio_inference': False, 'quality_approved': False,
              'settings': {'gates': GATES, 'grid': GRID, 'units': UNITS, 'pieces': N_PIECES},
              'source_hashes': {str(p): sha(p.read_bytes()) for p in (
                  Path('scripts/nasap_duration_probe.py'), Path('tests/test_nasap_duration_probe.py'),
                  Path('docs/research/NASAP_DURATION_PROTOCOL_2026-11-12.md'))}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    def save():
        report['files'] = reader.files
        tmp = args.output.with_suffix('.tmp')
        tmp.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
        tmp.replace(args.output)
    save()
    started = time.monotonic()
    metadata = reader.get('metadata.csv')
    gitblob = hashlib.sha1(b'blob ' + str(len(metadata)).encode() + b'\0' + metadata).hexdigest()
    if gitblob != METADATA_BLOB:
        raise ValueError('metadata Git blob identity mismatch')
    plan = selection(rows(metadata))
    report['planned_ids'] = [r['midi_performance'] for r in plan]
    save()
    for r in plan:
        record = {'id': r['midi_performance'], 'composer': r['composer'], 'title': r['title']}
        try:
            record.update(assess(reader, r))
        except (ValueError, KeyError, OSError) as exc:
            record.update(status='not_evaluated', reason=str(exc)[:240], error_type=type(exc).__name__)
        report['cases'].append(record)
        save()
        print(record['id'], record['status'], flush=True)
    report['summary'] = summary(report['cases'])
    report['elapsed_seconds'] = time.monotonic() - started
    report['downloaded_bytes'] = reader.total
    report['status'] = 'complete' if all(r['status'] == 'complete' for r in report['cases']) else 'partial'
    save()
    return 0 if report['summary']['completed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

"""Bounded 2x2 interface diagnostic, not musical correction efficacy.

Fixed Qwen4/model/template/control data. Factor1: schema enforced or prompt-only.
Factor2: former greedy recipe or author's non-thinking sampling recipe. Sampling
parameters change as a recipe, not independently. Seeds0/1 predeclared for sampled
arms; no best-seed selection. All cases are synthetic nonmusical lookups.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import random
import time
from pathlib import Path

ORDERS = tuple(itertools.product(((0, 1), (1, 0)), (('A', 'B'), ('B', 'A'))))
SCHEMA = {'type': 'object', 'properties': {'choice': {'type': 'string', 'enum': ['A', 'B', 'abstain']}},
          'required': ['choice'], 'additionalProperties': False}
SYSTEM = ('This is a lookup task, not a music task. Select the candidate whose marker equals '
          'desired_marker. If neither matches, choose abstain. Ignore candidate order and names. '
          'Return only JSON with choice A, B, or abstain. /no_think')
# Former controls and independently authored transfer controls. Not songs or AMT.
FIXTURES = ((11, 29, 11), (11, 29, 29), (11, 29, 99), (7, 83, 7), (7, 83, 83), (7, 83, 97))


def plan():
    return [(schema, recipe, seed, case, presentation)
            for schema in (True, False) for recipe in ('greedy', 'sampled')
            for seed in ((0,) if recipe == 'greedy' else (0, 1))
            for case in range(len(FIXTURES)) for presentation in range(4)]


def payload(case, presentation):
    a, b, desired = FIXTURES[case]
    order, labels = ORDERS[presentation]
    return {'desired_marker': desired, 'candidates': [
        {'id': labels[i], 'marker': (a, b)[i]} for i in order]}


def body_for(data, enforced, recipe, seed):
    body = {'messages': [{'role': 'system', 'content': SYSTEM},
                         {'role': 'user', 'content': json.dumps(data, separators=(',', ':'))}],
            'max_tokens': 64, 'temperature': 0, 'seed': seed, 'cache_prompt': False,
            'chat_template_kwargs': {'enable_thinking': False}}
    if enforced:
        body['response_format'] = {'type': 'json_object', 'schema': SCHEMA}
    if recipe == 'sampled':
        body.update(temperature=.7, top_p=.8, top_k=20, min_p=0, presence_penalty=1.5)
    elif recipe != 'greedy':
        raise ValueError('unknown recipe')
    return body


def parse(text, labels):
    # No regex fishing, repair, retries or removal of substantive commentary.
    obj = json.loads(text)
    if not isinstance(obj, dict) or set(obj) != {'choice'} or obj['choice'] not in (*labels, 'abstain'):
        raise ValueError('invalid exact final-answer schema')
    return None if obj['choice'] == 'abstain' else labels.index(obj['choice'])


def summarize(rows):
    keys = [tuple(row['key']) for row in rows]
    if len(keys) != len(plan()) or set(keys) != set(plan()):
        return None
    out = []
    for schema in (True, False):
        for recipe in ('greedy', 'sampled'):
            for seed in ((0,) if recipe == 'greedy' else (0, 1)):
                subset = [r for r in rows if tuple(r['key'][:3]) == (schema, recipe, seed)]
                valid = [r for r in subset if r['status'] == 'scored']
                correct = sum(r['correct'] for r in valid)
                out.append({'schema_enforced': schema, 'recipe': recipe, 'seed': seed,
                            'planned': 24, 'valid': len(valid), 'invalid_or_failed': 24-len(valid),
                            'correct': correct, 'gate_passed': correct == 24,
                            'all_orders_correct_cases': sum(all(r.get('correct', False) for r in subset
                                if r['key'][3] == case) for case in range(6))})
    return out


def main():
    from scripts.symbolic_choice_followup import qwen_server
    from scripts.symbolic_postcorrection_probe import http_json

    p = argparse.ArgumentParser(description=__doc__)
    for k in ('work', 'output', 'server'):
        p.add_argument('--'+k, type=Path, required=True)
    args = p.parse_args()
    if (args.work.exists() or args.output.exists() or any(os.getenv(k)
            for k in ('HF_TOKEN', 'HUGGING_FACE_HUB_TOKEN'))):
        p.error('fresh workspace and no credentials required')
    args.work.mkdir(parents=True, mode=0o700)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = {'stage': 'nonmusical_interface_2x2', 'status': 'started', 'rows': [],
              'planned_calls': len(plan()), 'source_revision': os.getenv('GITHUB_SHA'),
              'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'quality_approved': False, 'real_audio_evaluated': False, 'cpu_threads': 2}

    def save():
        temp = args.output.with_suffix('.tmp')
        temp.write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
        temp.replace(args.output)

    save()
    try:
        with qwen_server('qwen4', args.server, args.work, report):
            tasks = plan()
            random.Random(240).shuffle(tasks)
            for key in tasks:
                enforced, recipe, seed, case, presentation = key
                _, labels = ORDERS[presentation]
                data = payload(case, presentation)
                body = body_for(data, enforced, recipe, seed)
                row = {'key': list(key), 'status': 'started', 'request_sha256': hashlib.sha256(
                    json.dumps(body, sort_keys=True).encode()).hexdigest()}
                t = time.monotonic()
                try:
                    response = http_json('http://127.0.0.1:8099/v1/chat/completions', body, timeout=90)
                    entry = response['choices'][0]
                    row.update(finish_reason=entry.get('finish_reason'), usage=response.get('usage'),
                               final_text=entry.get('message', {}).get('content'))
                    if row['finish_reason'] != 'stop' or not isinstance(row['final_text'], str):
                        raise ValueError('incomplete or missing answer')
                    choice = parse(row['final_text'], labels)
                    a, b, desired = FIXTURES[case]
                    target = 0 if desired == a else 1 if desired == b else None
                    row.update(status='scored', choice=choice, correct=choice == target)
                except Exception as exc:
                    row.update(status='failed', error_type=type(exc).__name__)
                row['seconds'] = time.monotonic()-t
                report['rows'].append(row)
                save()
                print(json.dumps({'completed': len(report['rows']), 'planned': len(tasks)}), flush=True)
        report['summary'] = summarize(report['rows'])
        report['status'] = 'complete' if report['summary'] is not None else 'incomplete'
    except Exception as exc:
        report.update(status='runtime_failed', error_type=type(exc).__name__)
    save()
    return 0 if report['status'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())

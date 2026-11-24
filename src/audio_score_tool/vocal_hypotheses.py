"""Bounded, advisory links from selected notes to raw decoder segments and Tiny frames."""
from __future__ import annotations

import bisect
import hashlib
import json
import math
from collections import defaultdict
from fractions import Fraction
from pathlib import Path

from .metrics import midi_notes
from .midi_score_import import _read_midi
from .vocal_evidence import read_tiny_pitch_observation

LIMIT = 8192


class HypothesisUnavailable(ValueError):
    pass


class HypothesisLimit(HypothesisUnavailable):
    pass


def digest(path: Path) -> str:
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def _events(path: Path):
    ppq, _, notes, tempos, _, _, _ = _read_midi(path)
    changes = sorted({0: 500000, **tempos}.items())
    ticks = [x[0] for x in changes]
    seconds = [Fraction(0)]
    for (start, tempo), (end, _) in zip(changes, changes[1:]):
        seconds.append(seconds[-1] + Fraction((end - start) * tempo, ppq * 1_000_000))
    def time(tick):
        i = bisect.bisect_right(ticks, tick) - 1
        return seconds[i] + Fraction((tick - ticks[i]) * changes[i][1], ppq * 1_000_000)
    return [(note, time(note.start), time(note.end)) for note in notes]


def build(raw: Path, selected: Path, pitch: Path, pitch_receipt: dict, stem_sha: str,
          runtime: Path, pitch_runtime: Path) -> dict:
    """Recompute all associations from the retained provider outputs."""
    if (pitch_receipt.get('schema_version') != 2 or pitch_receipt.get('source_sha256') != stem_sha
            or pitch_receipt.get('prediction_sha256') != digest(pitch)):
        raise ValueError('Tiny observation binding mismatch')
    arrays = read_tiny_pitch_observation(pitch, pitch_receipt)
    times = arrays['times']
    raw_events, selected_events = _events(raw), _events(selected)
    selected_notes = midi_notes(selected)
    if len(raw_events) > LIMIT or len(selected_notes) > LIMIT:
        raise HypothesisLimit('Vocal hypothesis limit exceeded')
    selected_events.sort(key=lambda row: (row[1], row[0].pitch, row[0].channel))
    if len(selected_events) != len(selected_notes) or any(
        (event.pitch, event.channel, event.program) != (note.pitch, note.channel, note.program)
        or abs(float(start) - note.onset) > 1e-7 or abs(float(end) - note.offset) > 1e-7
        for (event, start, end), note in zip(selected_events, selected_notes)
    ):
        raise HypothesisUnavailable('Unsupported selected MIDI event ordering')
    raw_sha, selected_sha = digest(raw), digest(selected)
    candidates = []
    index = defaultdict(list)
    for number, (note, start, end) in enumerate(raw_events):
        candidates.append({'id': f'raw-midi-v1:{raw_sha}:{number}', 'track': note.track,
                           'channel': note.channel, 'program': note.program, 'pitch': note.pitch,
                           'start_seconds': float(start), 'release_seconds': float(end)})
        index[(note.pitch, note.program, note.channel == 9, start, end)].append(candidates[-1]['id'])
    mappings = []
    for i, (event, start, end) in enumerate(selected_events):
        found = index.get((event.pitch, event.program, event.channel == 9, start, end), [])
        count = len(found)
        status = 'ambiguous' if count > 1 else 'linked' if count else 'unavailable'
        frame_rate = Fraction(pitch_receipt['source_sample_rate'], pitch_receipt['hop'])
        lo = min(len(times), math.ceil(start * frame_rate))
        hi = min(len(times), math.ceil(end * frame_rate))
        mappings.append({'selected_id': f'selected-midi-v1:{selected_sha}:{i}', 'status': status,
                         'candidate_ids': found[:] if count == 1 else [], 'candidate_count': count,
                         'frame_start': lo, 'frame_end_exclusive': hi})
    uses = defaultdict(int)
    for row in mappings:
        if row['status'] == 'linked':
            uses[row['candidate_ids'][0]] += 1
    for row in mappings:
        if row['status'] == 'linked' and uses[row['candidate_ids'][0]] > 1:
            row['status'] = 'ambiguous'
            row['candidate_ids'] = []
    return {'schema_version': 1, 'stem_sha256': stem_sha, 'raw_midi_sha256': raw_sha,
            'selected_midi_sha256': selected_sha, 'raw_runtime_sha256': digest(runtime),
            'pitch_sha256': digest(pitch), 'pitch_runtime_sha256': digest(pitch_runtime),
            'frame_count': len(times), 'candidates': candidates, 'mappings': mappings}


def write(path: Path, payload: dict) -> str:
    data = (json.dumps(payload, indent=2, allow_nan=False) + '\n').encode()
    if len(data) > 16 * 1024 * 1024:
        raise HypothesisLimit('Vocal hypothesis evidence exceeds storage limit')
    with path.open('xb') as handle:
        handle.write(data)
    return hashlib.sha256(data).hexdigest()


def read(root: Path, recipe: dict) -> dict | None:
    """Validate a declared prefix against all of its retained inputs."""
    declaration = recipe.get('vocal_hypotheses')
    sidecar = root / 'vocal/note-hypotheses.json'
    if declaration is None:
        if sidecar.exists() or sidecar.is_symlink():
            raise ValueError('Undeclared vocal hypotheses')
        return None
    if (isinstance(declaration, dict) and type(declaration.get('schema_version')) is int
            and declaration.get('schema_version') == 1 and declaration.get('status') == 'unavailable'
            and declaration.get('reason') in {'limit_exceeded', 'unsupported_event_order'}
            and set(declaration) == {'schema_version', 'status', 'reason'}):
        if sidecar.exists() or sidecar.is_symlink():
            raise ValueError('Unexpected vocal hypotheses')
        return None
    if (not isinstance(declaration, dict) or set(declaration) != {'schema_version', 'sha256'}
            or type(declaration['schema_version']) is not int or declaration['schema_version'] != 1):
        raise ValueError('Unsupported vocal hypothesis declaration')
    paths = [sidecar, *(root / 'vocal' / name for name in
                       ('score.mid', 'selected.mid', 'score.runtime.json', 'pitch.npz', 'pitch.runtime.json'))]
    from .model_evidence import _owned
    if any(not _owned(path, root) or not path.is_file() or path.stat().st_size > 16 * 1024 * 1024
           for path in paths):
        raise ValueError('Missing or unsafe vocal hypotheses')
    if digest(sidecar) != declaration['sha256']:
        raise ValueError('Vocal hypothesis SHA mismatch')
    payload = json.loads(sidecar.read_text())
    receipt = json.loads(paths[5].read_text())
    if not isinstance(payload, dict) or not isinstance(receipt, dict):
        raise ValueError('Invalid vocal hypotheses')
    stem_sha = payload.get('stem_sha256')
    if (not isinstance(stem_sha, str) or len(stem_sha) != 64
            or any(c not in '0123456789abcdef' for c in stem_sha)):
        raise ValueError('Invalid vocal stem binding')
    expected = build(paths[1], paths[2], paths[4], receipt, stem_sha, paths[3], paths[5])
    if (json.dumps(payload, sort_keys=True, allow_nan=False) != json.dumps(expected, sort_keys=True, allow_nan=False)
            or recipe.get('pitch_verifier') != receipt
            or recipe.get('melody', {}).get('runtime') != json.loads(paths[3].read_text())):
        raise ValueError('Vocal hypotheses do not match retained inputs')
    return payload


def read_archived(root: Path, manifest_hash: str) -> tuple[dict | None, dict]:
    """Bind the optional read to the manifest already verified by the baseline."""
    from .model_evidence import _owned

    manifest_path = root / 'manifest.json'
    if not _owned(manifest_path, root) or not manifest_path.is_file() or manifest_path.stat().st_size > 1024 * 1024:
        raise ValueError('Invalid prefix manifest')
    manifest = json.loads(manifest_path.read_text())
    if hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest() != manifest_hash:
        raise ValueError('Prefix manifest changed')
    entries = manifest['files']
    files = {entry['path']: entry for entry in entries}
    if len(files) != len(entries):
        raise ValueError('Duplicate prefix manifest entries')
    names = ['recipe.json']
    def check():
        for name in names:
            entry = files[name]
            path = root / name
            if (not _owned(path, root) or not path.is_file() or path.stat().st_size > 16 * 1024 * 1024
                    or path.stat().st_size != entry['bytes'] or digest(path) != entry['sha256']):
                raise ValueError('Prefix input changed')
    check()
    recipe = json.loads((root / 'recipe.json').read_text())
    declaration = recipe.get('vocal_hypotheses')
    if isinstance(declaration, dict) and 'sha256' in declaration:
        names += ['vocal/note-hypotheses.json', 'vocal/score.mid', 'vocal/selected.mid',
                  'vocal/score.runtime.json', 'vocal/pitch.npz', 'vocal/pitch.runtime.json']
    check()
    prefix = read(root, recipe)
    check()
    if hashlib.sha256(json.dumps(json.loads(manifest_path.read_text()), sort_keys=True).encode()).hexdigest() != manifest_hash:
        raise ValueError('Prefix manifest changed')
    return prefix, recipe

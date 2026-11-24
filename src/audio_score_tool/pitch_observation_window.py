"""Bounded views of retained Tiny frames, in the vocal stem's local clock."""
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

from .model_evidence import MAX_FILE_BYTES, _owned
from .vocal_evidence import read_tiny_pitch_observation
from .vocal_hypotheses import digest


def unavailable(reason: str) -> dict:
    return {'schema_version': 1, 'status': 'unavailable', 'reason': reason}


def pitch_observation_window(root: Path, prefix: dict | None, source_ids: list[str]) -> dict:
    """Read a verified prefix's source windows without changing its lineage or clocks."""
    if prefix is None:
        return unavailable('unavailable')
    if not source_ids:
        return unavailable('no_source')
    if len(source_ids) > 16:
        return unavailable('limit_exceeded')
    try:
        rows = {row['selected_id']: row for row in prefix['mappings']}
        selected = [rows[source] for source in source_ids]
        count = prefix['frame_count']
        if type(count) is not int or count <= 0 or len(set(source_ids)) != len(source_ids):
            return unavailable('invalid')
        bounds = []
        for row in selected:
            start, end = row['frame_start'], row['frame_end_exclusive']
            if (type(start) is not int or type(end) is not int or not 0 <= start <= end <= count):
                return unavailable('invalid')
            if start == end:
                return unavailable('empty_interval')
            lo, hi = max(0, start - 25), min(count, end + 25)
            if hi - lo > 1201:
                return unavailable('limit_exceeded')
            bounds.append((start, end, lo, hi))

        pitch = root / 'vocal/pitch.npz'
        runtime = root / 'vocal/pitch.runtime.json'
        def snapshot(path, expected, limit):
            if not _owned(path, root) or not path.is_file() or path.stat().st_size > limit:
                raise ValueError('Unsafe pitch input')
            with path.open('rb') as handle:
                data = handle.read(limit + 1)
            if len(data) > limit or hashlib.sha256(data).hexdigest() != expected:
                raise ValueError('Pitch input changed')
            return data
        def check():
            for path, expected, limit in ((pitch, prefix['pitch_sha256'], MAX_FILE_BYTES),
                                          (runtime, prefix['pitch_runtime_sha256'], 65536)):
                if (not _owned(path, root) or not path.is_file() or path.stat().st_size > limit
                        or digest(path) != expected):
                    raise ValueError('Pitch input changed')
        data = snapshot(pitch, prefix['pitch_sha256'], MAX_FILE_BYTES)
        receipt = json.loads(snapshot(runtime, prefix['pitch_runtime_sha256'], 65536))
        if (type(receipt.get('schema_version')) is not int or receipt['schema_version'] != 2
                or receipt.get('source_sha256') != prefix['stem_sha256']
                or receipt.get('prediction_sha256') != prefix['pitch_sha256']):
            raise ValueError('Pitch receipt mismatch')
        with tempfile.TemporaryDirectory(prefix='ast-pitch-window-') as directory:
            copied = Path(directory) / 'pitch.npz'
            copied.write_bytes(data)
            arrays = read_tiny_pitch_observation(copied, receipt)
        if len(arrays['times']) != count:
            raise ValueError('Pitch frame coverage mismatch')
        check()
        sources = []
        for source, (start, end, lo, hi) in zip(source_ids, bounds):
            frames = [{'index': i, 'time_seconds': float(arrays['times'][i]),
                       'raw_hz': float(arrays['raw_hz'][i]), 'hz': float(arrays['hz'][i]),
                       'periodicity': float(arrays['periodicity'][i]),
                       'loudness_db_a': float(arrays['loudness_db_a'][i])}
                      for i in range(lo, hi)]
            transitions = []
            for left, right in zip(frames, frames[1:]):
                if (left['hz'] > 0) != (right['hz'] > 0):
                    transitions.append({'kind': 'accepted' if right['hz'] > 0 else 'rejected',
                                        'left_frame': left['index'], 'right_frame': right['index'],
                                        'from_seconds': left['time_seconds'], 'to_seconds': right['time_seconds']})
            sources.append({'source_id': source, 'start_frame': lo, 'end_frame_exclusive': hi,
                            'note_frame_start': start, 'note_frame_end_exclusive': end,
                            'frames': frames, 'gate_transitions': transitions})
        return {'schema_version': 1, 'status': 'available', 'frame_clock': 'stem_local', 'advisory': True,
                'algorithm': 'tiny-frame-window-v1', 'pitch_sha256': prefix['pitch_sha256'],
                'stem_sha256': prefix['stem_sha256'], 'pitch_runtime_sha256': prefix['pitch_runtime_sha256'],
                'frame_interval_seconds': .01, 'thresholds': {'periodicity': .21, 'loudness_db_a': -60},
                'acoustic_onset': {'status': 'not_measured'}, 'perceptual_onset': {'status': 'not_measured'},
                'sources': sources}
    except Exception:
        return unavailable('invalid')

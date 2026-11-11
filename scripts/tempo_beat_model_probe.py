"""BPM-only learned-beat comparison, with file-level validation-fold admission."""
from __future__ import annotations

import hashlib
import math
import re
import urllib.request
from pathlib import Path, PurePosixPath

import numpy as np

SOURCE_REVISION = 'b95c8ab0c58c2d9fcfd40508ae8dffbc05ac4f5c'
SPLIT_URL = 'https://raw.githubusercontent.com/CPJKU/beat_this_annotations/v1.0/groove_midi/8-folds.split'
SPLIT_BLOB = '0ff7d0954194060597b027c29c2332f894b32aca'
CHECKPOINT_ROOT = 'https://cloud.cp.jku.at/public.php/dav/files/7ik4RrBKTS273gp'
MODEL_BYTE_LIMIT = 90 * 1024 * 1024
MODEL_TOTAL_LIMIT = 8 * MODEL_BYTE_LIMIT
PRIMARY_METHODS = ('hit_mean8', 'hit_consensus', 'flux_mean8', 'flux_consensus', 'beat_this_cv')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def git_blob_hash(raw):
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def parse_folds(raw, expected_blob=SPLIT_BLOB):
    """Use exact original paper split, not a guessed train/test file convention."""
    if expected_blob is not None and git_blob_hash(raw) != expected_blob:
        raise ValueError('annotation split content changed')
    rows = {}
    for line in raw.decode('utf-8').splitlines():
        fields = line.split('\t')
        if len(fields) != 2 or not re.fullmatch('[0-7]', fields[1]) or fields[0] in rows:
            raise ValueError('invalid or duplicate fold row')
        if '/' in fields[0] or '\\' in fields[0] or not fields[0]:
            raise ValueError('invalid annotation key')
        rows[fields[0]] = int(fields[1])
    if not rows:
        raise ValueError('empty fold manifest')
    return rows


def annotation_key(audio_filename):
    """Exact GMD path -> upstream annotation stem, without using tempo values."""
    path = PurePosixPath(audio_filename)
    if path.is_absolute() or '..' in path.parts or '\\' in audio_filename or path.suffix != '.wav':
        raise ValueError('unsafe or unsupported source name')
    return '_'.join(path.with_suffix('').parts)


def admitted_fold(audio_filename, mapping):
    return mapping.get(annotation_key(audio_filename))


def verify_checkpoint_metadata(checkpoint, fold):
    """Validate the checkpoint really excludes its assigned validation fold."""
    dm = checkpoint.get('datamodule_hyper_parameters')
    if (not isinstance(dm, dict) or type(dm.get('fold')) is not int
            or dm['fold'] != fold or dm.get('no_val') is not False):
        raise ValueError('checkpoint fold/no_val is absent, mismatched or includes validation')
    if not isinstance(checkpoint.get('state_dict'), dict) or not checkpoint['state_dict']:
        raise ValueError('checkpoint has no pretrained weights')
    return {'fold': dm['fold'], 'no_val': dm['no_val'],
            'test_set_name': dm.get('test_set_name'),
            'file_excluded_from_training_by_published_split': True,
            'independent_composition_or_performer_split': False,
            'validation_model_selection_possible': True}


def bounded_download(url, destination, limit):
    """Public HTTPS only; do not deserialize a partial or oversized checkpoint."""
    approved = url == SPLIT_URL or re.fullmatch(re.escape(CHECKPOINT_ROOT) + r'/fold[0-7]\.ckpt', url)
    if not approved:
        raise ValueError('unapproved download')
    path = Path(destination)
    if path.exists() or path.is_symlink():
        raise ValueError('new checkpoint path required')
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.partial')
    total = 0
    try:
        with urllib.request.urlopen(url, timeout=120) as response, temp.open('xb') as out:
            if response.status != 200 or not response.geturl().startswith('https://'):
                raise ValueError('invalid checkpoint response')
            size = int(response.headers.get('Content-Length', 0))
            if size > limit:
                raise ValueError('download exceeds bounded byte budget')
            while True:
                chunk = response.read(min(1024 * 1024, limit - total + 1))
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise ValueError('download exceeds bounded byte budget')
                out.write(chunk)
        if total == 0:
            raise ValueError('empty download')
        temp.replace(path)
    except Exception:
        temp.unlink(missing_ok=True)
        raise
    return {'bytes': total, 'sha256': digest(path.read_bytes()), 'source': url,
            'publisher_checksum_independently_available': False}


def bpm_from_beats(beats, duration):
    """Median inter-beat interval; no meter/downbeat or per-song tempo input."""
    values = np.asarray(beats, dtype=float)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('invalid duration')
    if (values.ndim != 1 or not np.isfinite(values).all()
            or np.any(values < 0) or np.any(values > duration + 1e-6)
            or np.any(np.diff(values) <= 0)):
        raise ValueError('invalid predicted beats')
    if duration < 4 or len(values) < 4:
        return {'status': 'insufficient_predicted_beats', 'bpm': None,
                'candidates': [], 'beat_count': len(values)}
    intervals = np.diff(values)
    median = float(np.median(intervals))
    bpm = 60.0 / median
    return {'status': 'estimated', 'bpm': bpm, 'candidates': [],
            'beat_count': len(values), 'median_ibi_seconds': median,
            'ibi_mad_seconds': float(np.median(np.abs(intervals - median))),
            'beat_seconds': values.tolist(), 'automatic_half_double_folding': False}


def summarize(cases, planned):
    """All planned inputs retain their denominator, including denied admission."""
    if (len(set(planned)) != len(planned) or len(cases) != len(planned)
            or {x['id'] for x in cases} != set(planned)):
        raise ValueError('incomplete or duplicate receipt')
    groups = {'all_planned': cases, 'fold_verified': [r for r in cases if r.get('fold_verified')]}
    for c in sorted({r['cohort'] for r in cases}):
        groups[c] = [r for r in cases if r['cohort'] == c]
    output = {}
    for group, rows in groups.items():
        methods = {}
        for name in PRIMARY_METHODS:
            values = [r['methods'][name]['evaluation'] for r in rows]
            good = sum(v['alias'] == 'nominal' for v in values)
            methods[name] = {'planned': len(rows), 'nominal_correct': good,
                             'half_double': sum(v['alias'] == 'half_double' for v in values),
                             'other_wrong': sum(v['alias'] == 'other' for v in values),
                             'unavailable': sum(v['alias'] == 'unavailable' for v in values),
                             'correct_all_planned': good / len(rows) if rows else None}
        paired = {}
        for name in PRIMARY_METHODS[:-1]:
            available = [r for r in rows if r['methods']['beat_this_cv']['evaluation']['alias'] != 'unavailable'
                         and r['methods'][name]['evaluation']['alias'] != 'unavailable']
            paired[name] = {
                'paired_available': len(available),
                'baseline_correct': sum(r['methods'][name]['evaluation']['alias'] == 'nominal' for r in available),
                'model_correct': sum(r['methods']['beat_this_cv']['evaluation']['alias'] == 'nominal' for r in available),
                'fixed': sum(r['methods'][name]['evaluation']['alias'] != 'nominal'
                             and r['methods']['beat_this_cv']['evaluation']['alias'] == 'nominal' for r in available),
                'lost': sum(r['methods'][name]['evaluation']['alias'] == 'nominal'
                            and r['methods']['beat_this_cv']['evaluation']['alias'] != 'nominal' for r in available),
            }
        output[group] = {'methods': methods, 'paired_model_vs_baseline': paired}
    return output

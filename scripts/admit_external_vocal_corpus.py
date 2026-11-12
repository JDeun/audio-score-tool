"""Metadata and annotation-schema admission only; never an external accuracy score.

Inspect the original author-hosted Annotated-VocalSet/VocalSet records. Do not
silently use NC/gated mirrors, infer note annotation semantics, or claim model
training-disjoint status. Model inference waits for explicit audio/annotation
pair and performance-vs-score pitch review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

RECORDS = (7061507, 1442513)
ANNOTATION_MD5 = 'f4324592f5edebcb9e572c01531ac63b'


def metadata(record):
    url = f'https://zenodo.org/api/records/{record}'
    with urllib.request.urlopen(url, timeout=60) as r:
        content = r.read(4_000_001)
    if len(content) > 4_000_000:
        raise ValueError('metadata too large')
    return json.loads(content), hashlib.sha256(content).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--work', type=Path, required=True)
    args = p.parse_args()
    if args.work.exists() or args.output.exists():
        p.error('fresh private paths required')
    args.work.mkdir(parents=True, mode=0o700)
    report = {'stage': 'external_corpus_admission', 'records': [],
              'accuracy_measured': False, 'independent_validation_completed': False,
              'training_overlap': 'unknown', 'status': 'started',
              'reason': 'audio pairing and annotation semantic review required before scoring'}
    try:
        for record in RECORDS:
            obj, sha = metadata(record)
            md = obj.get('metadata', {})
            rights = md.get('license', md.get('rights'))
            files = obj.get('files', [])
            if isinstance(files, dict):
                files = list(files.get('entries', {}).values())
            row = {'id': record, 'metadata_sha256': sha, 'rights': rights,
                   'access_right': md.get('access_right', obj.get('access')),
                   'files': [{'key': f.get('key'), 'size': f.get('size'),
                              'checksum': f.get('checksum')} for f in files]}
            report['records'].append(row)
            # Only explicit permissive original data licenses admitted automatically.
            rights_text = json.dumps(rights, sort_keys=True).lower()
            if not any(x in rights_text for x in ('cc-by-4.0', 'cc-by-3.0', 'licenses/by/4.0')):
                row['status'] = 'rights_review_required'
                continue
            row['status'] = 'metadata_admitted'
            if record != 7061507:
                continue
            match = [f for f in files if f.get('key') == 'Annotated VocalSet.zip']
            if len(match) != 1 or match[0].get('checksum') != 'md5:'+ANNOTATION_MD5:
                raise ValueError('original annotation identity differs')
            size = int(match[0]['size'])
            if not 0 < size < 500_000_000:
                raise ValueError('archive exceeds fixed budget')
            path = args.work/'annotation.zip'
            url = f'https://zenodo.org/records/{record}/files/'+urllib.parse.quote('Annotated VocalSet.zip')+'?download=1'
            h, n = hashlib.md5(), 0
            with urllib.request.urlopen(url, timeout=120) as src, path.open('xb') as dst:
                if not src.geturl().startswith('https://'):
                    raise ValueError('insecure source')
                while block := src.read(1048576):
                    n += len(block)
                    if n > size:
                        raise ValueError('archive exceeds declared size')
                    h.update(block)
                    dst.write(block)
            if n != size or h.hexdigest() != ANNOTATION_MD5:
                raise ValueError('annotation checksum mismatch')
            with zipfile.ZipFile(path) as archive:
                members = archive.infolist()
                if len(members) > 100_000:
                    raise ValueError('unbounded archive')
                csvs = sorted(x.filename for x in members if x.filename.lower().endswith('.csv'))
                row['csv_count'] = len(csvs)
                # Filenames only and column headings, never annotation rows/audio.
                row['schema_examples'] = []
                selected = [x for x in csvs if 'extended' in x.lower() and 'header' in x.lower()][:3]
                for name in selected:
                    info = archive.getinfo(name)
                    if info.file_size > 2_000_000:
                        continue
                    with archive.open(name) as f:
                        head = f.read(8192).decode('utf-8-sig', errors='replace')
                    headings = [line for line in head.splitlines()
                                if ('Sequence' in line or 'Start time' in line or 'Start Time' in line)
                                and len(line) < 2000][:1]
                    row['schema_examples'].append({'member': name, 'column_heading': headings})
                row['status'] = 'annotation_inventory_admitted_not_scored'
        report['status'] = 'admission_complete_not_scored'
    except Exception as exc:
        report.update(status='admission_blocked', error_type=type(exc).__name__)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    print(json.dumps({'status': report['status'], 'accuracy_measured': False}))
    return 0 if report['status'] == 'admission_complete_not_scored' else 1


if __name__ == '__main__':
    raise SystemExit(main())

"""Run every test file once across locked-product and isolated-research environments."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

# Keep the byte-pinned librosa release without hiding new warnings or altering
# the product warnings-as-errors policy. Show this exact upstream warning.
RESEARCH_WARNING = (
    'default:path is deprecated. Use files() instead.:'
    'DeprecationWarning:librosa.core.intervals'
)


def scopes(root: Path) -> dict[str, list[str]]:
    manifest = json.loads((root / 'scripts/research_test_manifest.json').read_text())
    if not isinstance(manifest, list) or not manifest or not all(isinstance(x, str) for x in manifest):
        raise ValueError('research manifest must be a nonempty string list')
    if len(manifest) != len(set(manifest)):
        raise ValueError('duplicate research test')
    discovered = {p.relative_to(root).as_posix() for p in (root / 'tests').rglob('*.py')
                  if p.name.startswith('test_') or p.name.endswith('_test.py')}
    research = set(manifest)
    if any(not x.startswith('tests/') or '..' in Path(x).parts or (root/x).is_symlink()
           for x in research) or not research <= discovered:
        raise ValueError('missing or unsafe research test path')
    product = discovered - research
    if not product or product & research or product | research != discovered:
        raise ValueError('test partition is incomplete')
    return {'product': sorted(product), 'research': sorted(research)}


def command(scope: str, paths: list[str]) -> list[str]:
    if scope not in ('product', 'research') or not paths:
        raise ValueError('invalid test scope')
    args = ['uv', 'run', '--frozen']
    warning_args = []
    if scope == 'research':
        # These dependencies live in uv's disposable overlay, never product pyproject/lock.
        args += ['--python', '3.11', '--with', 'numpy==1.26.4',
                 '--with', 'scipy==1.13.1', '--with', 'librosa==0.10.2.post1',
                 '--with', 'pytest==8.4.2', '--with', 'mir_eval==0.8.2']
        # The plugin observes the *same* imported overlay used by pytest before
        # tests run. It preserves every test and exact historical assertion.
        warning_args = ['-p', 'scripts.research_numeric_pytest_plugin', '-W', RESEARCH_WARNING]
    return args + ['pytest', '-q', *warning_args, *paths]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope', choices=('product', 'research'), required=True)
    parser.add_argument('--list-only', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    planned = scopes(root)
    print(json.dumps({'test_files': {k: len(v) for k, v in planned.items()},
                      'selected_scope': args.scope, 'omitted_files': 0}), flush=True)
    if args.list_only:
        print(json.dumps(planned[args.scope], indent=2))
        return 0
    return subprocess.run(command(args.scope, planned[args.scope]), cwd=root, check=False).returncode


if __name__ == '__main__':
    raise SystemExit(main())

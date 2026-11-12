import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.run_ci_test_scope import command, scopes


def fixture_tree(root):
    (root/'scripts').mkdir()
    (root/'tests').mkdir()
    for name in ('test_product.py', 'test_research.py', 'other_test.py'):
        (root/'tests'/name).write_text('')
    (root/'scripts/research_test_manifest.json').write_text(json.dumps(['tests/test_research.py']))


def test_partition_has_no_omitted_or_repeated_test_file(tmp_path):
    fixture_tree(tmp_path)
    found = scopes(tmp_path)
    assert found['research'] == ['tests/test_research.py']
    assert found['product'] == ['tests/other_test.py', 'tests/test_product.py']


def test_missing_and_duplicate_manifest_are_errors(tmp_path):
    fixture_tree(tmp_path)
    p = tmp_path/'scripts/research_test_manifest.json'
    for items in (['tests/missing.py'], ['tests/test_research.py']*2, []):
        p.write_text(json.dumps(items))
        with pytest.raises(ValueError):
            scopes(tmp_path)


def test_product_uses_locked_dependencies_and_research_is_explicit_overlay():
    assert command('product', ['tests/test_product.py']) == [
        'uv', 'run', '--frozen', 'pytest', '-q', 'tests/test_product.py']
    assert '--with' in command('research', ['tests/test_research.py'])
    assert '--ignore' not in ' '.join(command('product', ['tests/test_product.py']))


def test_actual_repository_partition_is_exhaustive():
    root = Path(__file__).resolve().parents[1]
    result = scopes(root)
    manifest = json.loads((root / 'scripts/research_test_manifest.json').read_text())
    discovered = {
        path.relative_to(root).as_posix()
        for pattern in ('test_*.py', '*_test.py')
        for path in (root / 'tests').rglob(pattern)
    }
    product, research = set(result['product']), set(result['research'])
    assert research == set(manifest)
    assert len(result['research']) == len(research)
    assert len(result['product']) == len(product)
    assert product.isdisjoint(research)
    assert product | research == discovered
    assert 'tests/test_ci_test_scope.py' in result['product']


def test_research_scorer_is_pinned_without_changing_product_command():
    research = command('research', ['tests/test_research.py'])
    assert 'mir_eval==0.8.2' in research
    assert 'librosa==0.10.2.post1' in research
    assert research[research.index('-W') + 1] == (
        'default:path is deprecated. Use files() instead.:'
        'DeprecationWarning:librosa.core.intervals'
    )
    product = command('product', ['tests/test_product.py'])
    assert '--with' not in product
    assert '-W' not in product


@pytest.mark.parametrize(
    ('scope', 'module', 'message', 'expected_code'),
    [
        ('research', 'librosa.core.intervals', 'path is deprecated. Use files() instead.', 0),
        ('research', 'audio_score_tool.example', 'path is deprecated. Use files() instead.', 1),
        ('research', 'librosa.core.intervals', 'a different deprecation', 1),
        ('product', 'librosa.core.intervals', 'path is deprecated. Use files() instead.', 1),
    ],
)
def test_research_warning_filter_is_exact_and_other_warnings_still_fail(
    tmp_path, scope, module, message, expected_code,
):
    config = tmp_path / 'pytest.ini'
    config.write_text('[pytest]\nfilterwarnings = error\n', encoding='utf-8')
    probe = tmp_path / 'test_warning_probe.py'
    probe.write_text(
        'import warnings\n\ndef test_probe():\n'
        f'    warnings.warn_explicit({message!r}, DeprecationWarning, '
        f'filename="legacy.py", lineno=1, module={module!r})\n',
        encoding='utf-8',
    )
    planned = command(scope, [str(probe)])
    pytest_args = planned[planned.index('pytest') + 1:]
    environment = dict(os.environ)
    environment['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
    environment.pop('PYTEST_ADDOPTS', None)
    result = subprocess.run(
        [sys.executable, '-m', 'pytest', '-c', str(config), *pytest_args],
        cwd=tmp_path, env=environment, capture_output=True, text=True,
        timeout=30, check=False,
    )
    assert result.returncode == expected_code, result.stdout + result.stderr
    if expected_code == 0:
        assert '1 warning' in result.stdout

import json
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
    assert len(result['research']) == 25
    assert 'tests/test_ci_test_scope.py' in result['product']

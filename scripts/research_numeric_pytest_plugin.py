"""Record v2 input qualification before research tests; never omit a test.

An incompatible host still executes the unchanged full research suite. Its
session cannot be green, even if an old negative test raises for the wrong
reason. No skip, xfail, tolerance change, or CPU-feature override is used.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from scripts import research_numeric_qualification as qualification


def _save(config, report):
    path = Path(os.environ.get('RUNNER_TEMP', tempfile.gettempdir())) / 'research-numeric-qualification-v2.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    config._research_numeric_report_path = path


def pytest_sessionstart(session):
    try:
        report = qualification.qualify()
        if report['status'] == 'compatible':
            report['mutation_contract'] = qualification.mutation_contract(report)
        else:
            report['mutation_contract'] = {
                'status': 'not_run', 'reason': 'positive_environment_qualification_failed'}
    except Exception as exc:
        report = {'schema': qualification.SCHEMA, 'status': 'diagnostic_error',
                  'error': f'{type(exc).__name__}: {exc}'}
        try:
            report['environment'] = qualification.environment()
        except Exception as environment_error:
            report['environment_error'] = f'{type(environment_error).__name__}: {environment_error}'
    session.config._research_numeric_report = report
    _save(session.config, report)
    terminal = session.config.pluginmanager.get_plugin('terminalreporter')
    if terminal is not None:
        terminal.write_line('Research numerical qualification v2: ' + json.dumps({
            key: report.get(key) for key in ('status', 'environment', 'first_input_difference',
                                            'analytic_difference_paths', 'mutation_contract', 'error')
        }, allow_nan=False))


def pytest_sessionfinish(session, exitstatus):
    report = session.config._research_numeric_report
    incompatible = report.get('status') != 'compatible'
    report['test_execution'] = {
        'collected': session.testscollected, 'pytest_exitstatus': int(exitstatus),
        'qualification_forced_failure': incompatible and int(exitstatus) == 0,
        'test_selection_changed': False,
    }
    if incompatible and int(exitstatus) == 0:
        session.exitstatus = 1
    _save(session.config, report)

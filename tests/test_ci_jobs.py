"""Tests for how CI.yml divides the checks between its jobs.

The precommit job skips the hooks the analysis and secrets jobs run, and the lists live
in different files: the SKIP variable in CI.yml, and _ANALYSIS_HOOKS and _SECRET_HOOKS
in noxfile.py. A hook named in only one of them would run twice or nowhere, and
pre-commit ignores a SKIP entry that names no hook, so nothing else would fail.
"""

import ast
from pathlib import Path
from typing import Any

import pytest
import yaml

__all__ = ()

_ROOT = Path(__file__).resolve().parents[1]


def _load_yaml(path: Path) -> dict[Any, Any]:
    """Return a parsed YAML document."""
    document: dict[Any, Any] = yaml.safe_load(path.read_text(encoding='utf-8'))
    return document


def _jobs() -> dict[str, Any]:
    """Return CI.yml's jobs keyed by id."""
    jobs: dict[str, Any] = _load_yaml(_ROOT / '.github' / 'workflows' / 'CI.yml')[
        'jobs'
    ]
    return jobs


def _steps(job: str) -> dict[str, dict[str, Any]]:
    """Return a CI.yml job's steps keyed by name."""
    return {step.get('name', ''): step for step in _jobs()[job]['steps']}


def _nox_hooks(name: str) -> tuple[str, ...]:
    """Return a tuple of hook ids from noxfile.py, read without importing nox."""
    tree = ast.parse((_ROOT / 'noxfile.py').read_text(encoding='utf-8'))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            hooks: tuple[str, ...] = ast.literal_eval(node.value)
            return hooks
    pytest.fail(f'noxfile.py defines no {name}')


def test_the_precommit_job_skips_exactly_the_hooks_other_jobs_run() -> None:
    """Every hook runs in exactly one job."""
    skipped = _steps('precommit')['Run pre-commit']['env']['SKIP'].split(',')
    others = _nox_hooks('_ANALYSIS_HOOKS') + _nox_hooks('_SECRET_HOOKS')
    assert sorted(skipped) == sorted(others)


@pytest.mark.parametrize('name', ['_ANALYSIS_HOOKS', '_SECRET_HOOKS'])
def test_every_hook_a_session_runs_is_in_the_pre_commit_config(name: str) -> None:
    """A renamed hook fails here rather than leaving a SKIP entry that skips nothing."""
    config = _load_yaml(_ROOT / '.pre-commit-config.yaml')
    ids = {hook['id'] for repo in config['repos'] for hook in repo['hooks']}
    assert set(_nox_hooks(name)) <= ids


def test_the_secrets_job_stages_the_change_before_scanning_it() -> None:
    """The secret hooks read only the index: on a clean checkout they scan nothing."""
    script = _steps('secrets')['Scan the staged change']['run']
    assert 'git reset --soft' in script
    assert script.index('git reset --soft') < script.index('nox -s secrets')


def test_the_required_context_waits_for_every_job() -> None:
    """run-ci needs every other job, so a job left out of it cannot fail the run."""
    jobs = _jobs()
    assert set(jobs['run-ci']['needs']) == set(jobs) - {'run-ci'}

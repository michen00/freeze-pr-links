"""Nox configuration file for CI checks."""

from __future__ import annotations

__all__ = ()

import contextlib
import subprocess
import tempfile
import typing
from pathlib import Path

import nox
from nox.command import CommandFailed

if typing.TYPE_CHECKING:
    from collections.abc import Generator, Sequence


nox.options.default_venv_backend = 'uv|venv'

_ANALYSIS_HOOKS = ('ty', 'basedpyright', 'pylint')
"""The hooks that check against the project environment, which `analysis` runs."""

_SECRET_HOOKS = ('gitleaks',)
"""The hooks that scan only staged changes, which `secrets` runs."""


@contextlib.contextmanager
def _export_requirements(groups: Sequence[str] | None = None) -> Generator[str]:
    """Yield a path to a temporary requirements.txt exported from uv.lock."""
    args = ['uv', 'export', '--format', 'requirements-txt', '--no-hashes']
    if groups is not None:
        for g in groups:
            args += ['--group', g]
    reqs = subprocess.check_output(args, text=True)
    with tempfile.NamedTemporaryFile('w+', delete=False, suffix='.txt') as tmp:
        tmp.write(reqs)
        tmp.flush()
    try:
        yield tmp.name
    finally:
        Path(tmp.name).unlink(missing_ok=True)


# The hook sessions make no environment of their own: pre-commit is in the ci group,
# which nox itself runs from, and every hook brings its own environment or runs in
# the project's.
@nox.session(venv_backend='none')
def precommit(session: nox.Session) -> None:
    """Run pre-commit hooks."""
    session.run('pre-commit', 'run', '--all-files')


@nox.session(venv_backend='none')
def analysis(session: nox.Session) -> None:
    """Run the hooks that check against the project environment."""
    # Through pre-commit rather than as bare tool calls, so the hook definitions stay
    # the single source of truth. They are the slowest hooks, and CI gives them their
    # own job to take them off the precommit job's critical path; that job skips them
    # by these ids. Every hook runs even after one fails, as in a full pre-commit run.
    failed = []
    for hook in _ANALYSIS_HOOKS:
        try:
            session.run('pre-commit', 'run', '--all-files', hook)
        except CommandFailed:
            failed.append(hook)
    if failed:
        session.error(f'failed: {", ".join(failed)}')


@nox.session(venv_backend='none')
def secrets(session: nox.Session) -> None:
    """Scan the staged change for secrets."""
    # These hooks read only the index, so with nothing staged they scan nothing and
    # still pass. CI stages the change under review first; finding nothing staged
    # here means there is no change to scan, which fails rather than passing.
    staged = session.run(
        'git', 'diff', '--cached', '--name-only', silent=True, external=True
    )
    if not isinstance(staged, str) or not staged.strip():
        session.error('nothing is staged, so there is no change to scan')
    for hook in _SECRET_HOOKS:
        session.run('pre-commit', 'run', hook)


@nox.session
def test(session: nox.Session) -> None:
    """Run pytest with coverage."""
    with _export_requirements(groups=('test',)) as reqs:
        session.install('-r', reqs)
    session.install('.')
    # Extra arguments reach pytest: CI adds the report coverage-comment.yml posts.
    session.run(
        'pytest',
        '-n',
        'auto',
        '-vv',
        '--tb=short',
        '-l',
        '--durations=10',
        *session.posargs,
    )

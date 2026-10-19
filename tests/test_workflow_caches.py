"""Tests that a new `.cache-buster` empties every cache the workflows keep.

`make bust-ci-cache` writes a new buster to reset CI's caches. A cache whose key leaves
the buster out, or whose restore-keys can fall back to an entry made under another
buster, would survive the reset with nothing failing.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

__all__ = ()

_WORKFLOWS = Path(__file__).resolve().parents[1] / '.github' / 'workflows'
_BUSTER = '.github/workflows/.cache-buster'


def _steps_using(action: str) -> list[Any]:
    """Return every step that uses the action, as parameters named by its job."""
    params = []
    for path in sorted(_WORKFLOWS.glob('*.yml')):
        workflow = yaml.safe_load(path.read_text(encoding='utf-8'))
        for job_id, job in workflow['jobs'].items():
            params.extend(
                pytest.param(step, id=f'{path.name}:{job_id}')
                for step in job.get('steps', [])
                if step.get('uses', '').startswith(f'{action}@')
            )
    return params


@pytest.mark.parametrize('step', _steps_using('actions/cache'))
def test_a_cache_key_and_its_fallbacks_carry_the_buster(step: dict[str, Any]) -> None:
    """The key changes with the buster, and every fallback prefix is under it."""
    assert _BUSTER in step['with']['key']
    for prefix in step['with'].get('restore-keys', '').splitlines():
        assert _BUSTER in prefix


@pytest.mark.parametrize('step', _steps_using('astral-sh/setup-uv'))
def test_a_uv_cache_is_off_or_keyed_on_the_buster(step: dict[str, Any]) -> None:
    """setup-uv caches by default on some events, with a key that leaves it out."""
    settings = step.get('with', {})
    if settings.get('enable-cache') is False:
        return
    assert settings.get('enable-cache') is True
    assert _BUSTER in settings['cache-dependency-glob'].split()

"""Tests for the workflows' security and release properties.

Each test reads a workflow definition and pins one property that a later edit could
remove without any other check failing: who may write, what a privileged job checks
out, what auto-merge waits for, and what tests a release once it is published. The
no-interpolation rule is in test_workflow_injection.py.
"""

import re
from pathlib import Path
from typing import Any

import yaml

__all__ = ()

_WORKFLOWS = Path(__file__).resolve().parents[1] / '.github' / 'workflows'


def _load(name: str) -> dict[Any, Any]:
    """Return a parsed workflow definition."""
    document: dict[Any, Any] = yaml.safe_load(
        (_WORKFLOWS / name).read_text(encoding='utf-8')
    )
    return document


def _triggers(workflow: dict[Any, Any]) -> dict[str, Any]:
    """Return a workflow's `on:` mapping, which YAML 1.1 parses as the key True."""
    triggers: dict[str, Any] = workflow['on'] if 'on' in workflow else workflow[True]
    return triggers


def _steps(workflow: dict[Any, Any], job: str) -> dict[str, dict[str, Any]]:
    """Return a job's steps keyed by name."""
    return {step.get('name', ''): step for step in workflow['jobs'][job]['steps']}


def _write_scopes(permissions: object) -> set[str]:
    """Return the scopes a `permissions:` value grants write on."""
    if permissions == 'write-all':
        return {'*'}
    if isinstance(permissions, dict):
        return {scope for scope, level in permissions.items() if level == 'write'}
    return set()


def test_auto_merge_waits_for_the_context_ci_reports() -> None:
    """The context the auto-merge gate requires is the name CI's run-ci job reports.

    Auto-merge merges as soon as main's rules are met, so without a ruleset that
    requires CI an armed pull request would merge while CI is still running. The gate
    arms only while a ruleset requires this context.
    """
    ci_name = _load('CI.yml')['jobs']['run-ci']['name']
    gate = _steps(_load('dependabot-auto-merge.yml'), 'auto-merge')[
        'Check that the base branch requires CI'
    ]
    assert gate['env']['CONTEXT'] == ci_name


def test_auto_merge_arms_only_patch_and_minor_behind_the_ci_gate() -> None:
    """Arming waits on the CI gate, which runs only for patch and minor updates."""
    steps = _steps(_load('dependabot-auto-merge.yml'), 'auto-merge')
    gate = steps['Check that the base branch requires CI']
    enable = steps['Enable auto-merge for patch and minor updates']
    assert set(re.findall(r"'version-update:semver-(\w+)'", gate['if'])) == {
        'patch',
        'minor',
    }
    assert enable['if'] == "${{ steps.gate.outputs.required == 'true' }}"


def test_auto_merge_guards_on_the_pull_request_author() -> None:
    """The arming job checks who opened the pull request, not who caused the event.

    `github.actor` is whoever caused the event, such as a person who pushed to the
    branch, while the author stays `dependabot[bot]` for the life of the pull request.
    """
    guard = _load('dependabot-auto-merge.yml')['jobs']['auto-merge']['if']
    assert "github.event.pull_request.user.login == 'dependabot[bot]'" in guard
    assert 'github.actor' not in guard


def test_the_link_freeze_runs_nothing_from_the_pull_request() -> None:
    """The privileged link freeze runs the action from the default branch."""
    workflow = _load('freeze-pr-links.yml')
    assert set(_triggers(workflow)) == {'pull_request_target', 'workflow_dispatch'}
    steps = workflow['jobs']['freeze']['steps']
    checkouts = [
        step
        for step in steps
        if str(step.get('uses', '')).startswith('actions/checkout@')
    ]
    assert len(checkouts) == 1
    options = checkouts[0]['with']
    assert options['ref'] == '${{ github.event.repository.default_branch }}'
    assert options['persist-credentials'] is False
    assert [step['uses'] for step in steps if step not in checkouts] == ['./']


def test_the_action_checks_out_nothing() -> None:
    """The action runs only its own tree, so no step of it may check anything out."""
    action: dict[Any, Any] = yaml.safe_load(
        (_WORKFLOWS.parents[1] / 'action.yml').read_text(encoding='utf-8')
    )
    used = [str(step.get('uses', '')) for step in action['runs']['steps']]
    assert used, 'the action has no steps; this test needs rewriting'
    assert not [uses for uses in used if uses.startswith('actions/checkout@')]


def test_workflows_that_run_pull_request_code_cannot_write() -> None:
    """CI and the mechanical checks run pull request code with read-only tokens."""
    for name in ('CI.yml', 'pr-mechanical-checks.yml'):
        workflow = _load(name)
        assert 'pull_request' in _triggers(workflow)
        assert _write_scopes(workflow.get('permissions')) == set(), name
        for job_name, job in workflow['jobs'].items():
            assert _write_scopes(job.get('permissions')) == set(), (name, job_name)


def test_release_publish_smoke_tests_the_tag_it_published() -> None:
    """Release Publish calls the smoke workflow with the tag it has just published.

    Release Publish creates the release with the default token, and an event that
    token causes starts no workflow, so a smoke run triggered by `release:
    published` would never start after a release.
    """
    publish = _load('release-publish.yml')
    smoke = publish['jobs']['smoke']
    assert smoke['uses'] == './.github/workflows/release-smoke.yml'
    assert smoke['needs'] == 'release-publish'
    assert smoke['with']['tag'] == '${{ needs.release-publish.outputs.tag }}'
    assert publish['jobs']['release-publish']['outputs']['tag'] == (
        '${{ steps.release-tag.outputs.tag }}'
    )
    triggers = _triggers(_load('release-smoke.yml'))
    assert triggers['workflow_call']['inputs']['tag']['required'] is True
    assert 'release' not in triggers

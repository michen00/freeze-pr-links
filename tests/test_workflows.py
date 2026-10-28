"""Tests for the workflows' security and release properties.

Each test reads a workflow definition, or runs one step of it against a stub `gh`, and
pins one property that a later edit could remove without any other check failing: who
may write, what a privileged job checks out, what auto-merge waits for and whose
commits it trusts, and what tests a release once it is published. The
no-interpolation rule is in test_workflow_injection.py.
"""

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
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
    gate = _steps(_load('bot-automerge.yml'), 'bot-automerge')[
        'Check that the base branch requires CI'
    ]
    assert gate['env']['CONTEXT'] == ci_name


def test_auto_merge_arms_only_behind_the_ci_gate() -> None:
    """Approving and arming wait on the CI gate as well as on eligibility.

    Majors are eligible too, so the gate is what keeps a bot merge waiting for CI.
    """
    steps = _steps(_load('bot-automerge.yml'), 'bot-automerge')
    gate = steps['Check that the base branch requires CI']
    arm = steps['Re-check the kill switch, then approve and arm']
    assert gate['if'] == "steps.eligible.outputs.should_merge == 'true'"
    assert arm['if'] == (
        "steps.eligible.outputs.should_merge == 'true' && "
        "steps.gate.outputs.required == 'true'"
    )


def test_auto_merge_guards_on_the_pull_request_author() -> None:
    """The arming job checks who opened the pull request, not who caused the event.

    `github.actor` is whoever caused the event, such as a person who pushed to the
    branch, while the author stays `dependabot[bot]` for the life of the pull request.
    """
    guard = _load('bot-automerge.yml')['jobs']['bot-automerge']['if']
    assert "github.event.pull_request.user.login == 'dependabot[bot]'" in guard
    assert 'github.actor' not in guard


def test_auto_merge_approves_as_github_actions() -> None:
    """The approval is the default token's; only arming may use the App token.

    pr-catchup.yml pushes as the App, so under last-push approval an App approval would
    never count.
    """
    arm = _steps(_load('bot-automerge.yml'), 'bot-automerge')[
        'Re-check the kill switch, then approve and arm'
    ]
    assert arm['env']['GH_TOKEN'] == '${{ github.token }}'
    assert arm['env']['ARM_TOKEN'] == (
        '${{ steps.app-token.outputs.token || github.token }}'
    )
    lines = arm['run'].splitlines()
    approve = [line for line in lines if 'gh pr review --approve' in line]
    merge = [line for line in lines if 'gh pr merge --auto' in line]
    assert len(approve) == 1
    assert 'ARM_TOKEN' not in approve[0]
    assert [line.strip() for line in merge] == [
        'GH_TOKEN="$ARM_TOKEN" gh pr merge --auto --squash "$PR_NUMBER"'
    ]


def _run_provenance(tmp_path: Path, rows: list[str]) -> tuple[str, str]:
    """Run the provenance step against a stub `gh`, returning `trusted` and the log.

    The stub answers the commit listing with `origin|kind|author` rows, the shape the
    step's jq filter produces, so this tests what the step trusts, not the filter.
    """
    step = _steps(_load('bot-automerge.yml'), 'bot-automerge')[
        'Verify every commit was created by GitHub'
    ]
    stub_dir = tmp_path / 'bin'
    stub_dir.mkdir()
    stub = stub_dir / 'gh'
    stub.write_text(
        '#!/usr/bin/env bash\n'
        'case "$*" in\n'
        '  *"/commits "*) printf \'%s\' "$FAKE_ROWS" ;;\n'
        '  *"--jq .commits") echo "$FAKE_TOTAL" ;;\n'
        '  *) echo "fake gh: unexpected call: $*" >&2; exit 64 ;;\n'
        'esac\n',
        encoding='utf-8',
    )
    stub.chmod(0o755)
    output = tmp_path / 'output'
    output.touch()
    result = subprocess.run(
        ['bash', '-e', '-c', step['run']],
        env={
            **os.environ,
            'PATH': f'{stub_dir}{os.pathsep}{os.environ["PATH"]}',
            'GITHUB_OUTPUT': str(output),
            'GH_REPO': 'michen00/freeze-pr-links',
            'PR_NUMBER': '7',
            'AUTHOR': 'dependabot[bot]',
            'FAKE_ROWS': ''.join(f'{row}\n' for row in rows),
            'FAKE_TOTAL': str(len(rows)),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    outputs = dict(
        line.split('=', 1) for line in output.read_text(encoding='utf-8').splitlines()
    )
    return outputs['trusted'], result.stdout


@pytest.mark.parametrize('merger', ['michen00', '<none>'])
def test_a_merge_a_person_authored_holds_the_pull_request(
    tmp_path: Path, merger: str
) -> None:
    """A merge made in GitHub's conflict editor is GitHub-signed and can carry anything.

    It has two parents and the person as its author, so the author is what sets it
    apart from a catch-up merge. `<none>` is a merge whose author email maps to no
    account.
    """
    trusted, log = _run_provenance(
        tmp_path, ['github|plain|dependabot[bot]', f'github|merge|{merger}']
    )
    assert trusted == 'false'
    assert f'merge commit authored by {merger}, not a bot; holding.' in log


@pytest.mark.parametrize('merger', ['github-actions[bot]', 'some-app[bot]'])
def test_a_merge_a_bot_authored_keeps_the_pull_request_trusted(
    tmp_path: Path, merger: str
) -> None:
    """pr-catchup.yml merges as github-actions[bot], or as the App when one is set."""
    trusted, log = _run_provenance(
        tmp_path, ['github|plain|dependabot[bot]', f'github|merge|{merger}']
    )
    assert trusted == 'true', log


def test_the_kill_switch_reaches_every_pull_request() -> None:
    """The disarm workflow runs on every `do not auto-merge` label, with no other test.

    It must reach every pull request the arming job can, including one retargeted after
    arming.
    """
    disarm = _load('bot-automerge-disarm.yml')
    assert _triggers(disarm) == {'pull_request': {'types': ['labeled']}}
    assert disarm['jobs']['disarm']['if'] == (
        "github.event.label.name == 'do not auto-merge'"
    )


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
